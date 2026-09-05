"""Loopback photo-import HTTP routes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from healthcheck.db.engine import session_scope
from healthcheck.ingestion.photo.errors import PhotoImportError
from healthcheck.ingestion.photo.service import PhotoImportService, PhotoUpload
from healthcheck.ingestion.photo.vision import UnconfiguredImageMeasurementExtractor
from healthcheck.logging import log_event
from healthcheck.web.common import request_engine

router = APIRouter()


class CandidateEditBody(BaseModel):
    candidate_id: str
    edited_value: float | None = None
    edited_unit: str | None = None
    edited_source_local_date: date | None = None
    edited_source_timestamp: datetime | None = None


class CandidateIdsBody(BaseModel):
    candidate_ids: list[str] = Field(min_length=1)
    reason: str | None = None
    edits: dict[str, dict[str, Any]] | None = None


class ReprocessBody(BaseModel):
    extractor_version: str | None = None


def _engine(request: Request):
    return request_engine(request)


@contextmanager
def _photo_service(request: Request, extractor: Any | None = None) -> Iterator[PhotoImportService]:
    paths = request.app.state.runtime_paths
    selected = (
        extractor
        if extractor is not None
        else getattr(request.app.state, "photo_extractor", None)
    )
    if selected is None:
        selected = UnconfiguredImageMeasurementExtractor()
    with session_scope(_engine(request)) as session:
        yield PhotoImportService(session, paths, selected)


def _error(exc: PhotoImportError) -> JSONResponse:
    log_event("photo_import_error", operation="photo_import", status="error", reason=exc.code)
    return JSONResponse(
        status_code=exc.status_code, content={"code": exc.code, "message": exc.message}
    )


def _json(payload: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(payload), status_code=status_code)


def _batch_payload(service: PhotoImportService, batch_id: str) -> dict[str, Any]:
    batch, events, candidates = service.get_batch(batch_id)
    artifacts = []
    seen: set[str] = set()
    for event in events:
        if event.raw_artifact_id and event.raw_artifact_id not in seen:
            artifact = service.repos.raw_artifacts.get(event.raw_artifact_id)
            if artifact is not None:
                artifacts.append(service.artifact_view(artifact))
                seen.add(artifact.id)
    return {
        "id": batch.id,
        "batch_kind": batch.batch_kind,
        "status": batch.status,
        "extractor_name": batch.extractor_name,
        "extractor_version": batch.extractor_version,
        "received_count": batch.received_count,
        "parsed_count": batch.parsed_count,
        "committed_count": batch.committed_count,
        "failed_count": batch.failed_count,
        "diagnostic_reason": batch.diagnostic_reason,
        "started_at": batch.started_at,
        "completed_at": batch.completed_at,
        "acquisition_source_id": batch.acquisition_source_id,
        "artifacts": artifacts,
        "events": [
            {
                "id": event.id,
                "status": event.status,
                "raw_artifact_id": event.raw_artifact_id,
                "acquisition_source_id": event.acquisition_source_id,
                "diagnostic_code": event.diagnostic_code,
                "diagnostic_reason": event.diagnostic_reason,
                "duplicate_of_event_id": event.duplicate_of_event_id,
                "original_batch_id": (
                    None
                    if event.duplicate_of_event_id is None
                    else getattr(
                        service.repos.ingest_events.get(event.duplicate_of_event_id),
                        "ingest_batch_id",
                        None,
                    )
                ),
            }
            for event in events
        ],
        "candidates": [service.candidate_view(candidate) for candidate in candidates],
    }


@router.post("/api/imports/photos")
async def import_photos(
    request: Request,
    files: list[UploadFile] = File(...),
    locale: str | None = Form(default=None),
    timezone: str | None = Form(default=None),
    schema_version: str | None = Form(default=None),
    provider_code: str | None = Form(default=None),
) -> JSONResponse:
    uploads: list[PhotoUpload] = []
    for uploaded in files:
        content = await uploaded.read()
        uploads.append(
            PhotoUpload(
                filename=uploaded.filename,
                content=content,
                declared_media_type=uploaded.content_type,
            )
        )
        await uploaded.close()
    try:
        with _photo_service(request) as service:
            result = service.import_photos(
                uploads,
                locale=locale,
                timezone=timezone,
                schema_version=schema_version or "r01-photo-v1",
                provider_code=provider_code,
            )
            payload = _batch_payload(service, result.batch.id)
            payload["items"] = [
                {
                    "filename": item.filename,
                    "artifact_id": item.artifact_id,
                    "content_hash": item.content_hash,
                    "media_type": item.media_type,
                    "relative_storage_path": item.relative_storage_path,
                    "duplicate_artifact": item.duplicate_artifact,
                    "ingest_event_id": item.ingest_event_id,
                    "ingest_batch_id": item.ingest_batch_id,
                    "status": item.status,
                    "diagnostic_code": item.diagnostic_code,
                    "diagnostic_reason": item.diagnostic_reason,
                    "candidate_ids": item.candidate_ids,
                    "warnings": item.warnings,
                }
                for item in result.items
            ]
            return _json(payload)
    except PhotoImportError as exc:
        return _error(exc)


@router.get("/api/imports")
def list_imports(request: Request) -> JSONResponse:
    try:
        with _photo_service(request) as service:
            batches = service.list_batches()
            return _json(
                {
                    "imports": [
                        {
                            "id": batch.id,
                            "batch_kind": batch.batch_kind,
                            "status": batch.status,
                            "extractor_name": batch.extractor_name,
                            "extractor_version": batch.extractor_version,
                            "received_count": batch.received_count,
                            "parsed_count": batch.parsed_count,
                            "committed_count": batch.committed_count,
                            "failed_count": batch.failed_count,
                            "started_at": batch.started_at,
                            "completed_at": batch.completed_at,
                        }
                        for batch in batches
                    ]
                }
            )
    except PhotoImportError as exc:
        return _error(exc)


@router.get("/api/imports/{batch_id}")
def import_detail(batch_id: str, request: Request) -> JSONResponse:
    try:
        with _photo_service(request) as service:
            return _json(_batch_payload(service, batch_id))
    except PhotoImportError as exc:
        return _error(exc)


@router.post("/api/import-candidates/edit")
def edit_candidate(body: CandidateEditBody, request: Request) -> JSONResponse:
    try:
        with _photo_service(request) as service:
            candidate = service.edit_pending(
                body.candidate_id,
                edited_value=body.edited_value,
                edited_unit=body.edited_unit,
                edited_source_local_date=body.edited_source_local_date,
                edited_source_timestamp=body.edited_source_timestamp,
            )
            return _json(service.candidate_view(candidate))
    except PhotoImportError as exc:
        return _error(exc)


@router.post("/api/import-candidates/confirm")
def confirm_candidates(body: CandidateIdsBody, request: Request) -> JSONResponse:
    try:
        with _photo_service(request) as service:
            confirmed = service.confirm(body.candidate_ids, edits=body.edits)
            return _json({"confirmed": confirmed})
    except PhotoImportError as exc:
        return _error(exc)


@router.post("/api/import-candidates/reject")
def reject_candidates(body: CandidateIdsBody, request: Request) -> JSONResponse:
    try:
        with _photo_service(request) as service:
            rejected = service.reject(body.candidate_ids, reason=body.reason)
            return _json(
                {"rejected": [service.candidate_view(candidate) for candidate in rejected]}
            )
    except PhotoImportError as exc:
        return _error(exc)


@router.post("/api/import-events/{event_id}/reprocess")
def reprocess_event(
    event_id: str, request: Request, body: ReprocessBody | None = None
) -> JSONResponse:
    version = None if body is None else body.extractor_version
    extractor = getattr(request.app.state, "photo_extractor", None)
    if extractor is None:
        extractor = UnconfiguredImageMeasurementExtractor()
    if version is not None:
        versioned = getattr(extractor, "with_version", None)
        if not callable(versioned):
            raise PhotoImportError(
                "extractor_version_unsupported",
                "configured extractor cannot be versioned for reprocessing",
            )
        try:
            extractor = versioned(version)
        except (TypeError, ValueError):
            raise PhotoImportError(
                "extractor_version_invalid", "extractor version is invalid"
            ) from None
    try:
        with _photo_service(request, extractor=extractor) as service:
            result = service.reprocess_event(event_id)
            payload = {
                "event_id": event_id,
                "ingest_event_id": result.ingest_event_id or event_id,
                "extractor_name": extractor.name,
                "extractor_version": extractor.version,
                "candidates": [
                    service.candidate_view(candidate) for candidate in result.candidates
                ],
                "attempt_event_id": result.attempt_event_id,
            }
            failed = result.failed
            error_code = result.error_code
            error_message = result.error_message
        if failed:
            return _error(
                PhotoImportError(
                    error_code or "reprocess_failed", error_message or "reprocess failed"
                )
            )
        return _json(payload)
    except PhotoImportError as exc:
        return _error(exc)
