"""Loopback weight series/summary JSON routes."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.db.engine import session_scope
from healthcheck.ingestion.photo.errors import PhotoImportError
from healthcheck.ingestion.photo.store import ContentAddressedPhotoStore
from healthcheck.logging import log_event
from healthcheck.web.common import database_unavailable, request_engine
from healthcheck.web.query import WeightQueryService, empty_dashboard_payload

router = APIRouter()


def _json(payload: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(payload), status_code=status_code)


@router.get("/api/weight/series")
def weight_series(
    request: Request,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    compatibility_group: str | None = Query(default=None),
) -> JSONResponse:
    try:
        with session_scope(request_engine(request)) as session:
            service = WeightQueryService(session, request.app.state.settings)
            return _json(
                service.series(
                    start_date=start_date,
                    end_date=end_date,
                    compatibility_group=compatibility_group,
                )
            )
    except SQLAlchemyError as exc:
        if database_unavailable(exc):
            return _json(empty_dashboard_payload(reason="database_unavailable")["series"])
        log_event(
            "persistence_error",
            operation="weight_series",
            status="error",
            reason="persistence_error",
        )
        return _json({"code": "persistence_error", "message": "request failed"}, status_code=500)


@router.get("/api/weight/summary")
def weight_summary(
    request: Request,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    compatibility_group: str | None = Query(default=None),
) -> JSONResponse:
    try:
        with session_scope(request_engine(request)) as session:
            service = WeightQueryService(session, request.app.state.settings)
            return _json(
                service.summary(
                    start_date=start_date,
                    end_date=end_date,
                    compatibility_group=compatibility_group,
                )
            )
    except SQLAlchemyError as exc:
        if database_unavailable(exc):
            return _json(empty_dashboard_payload(reason="database_unavailable")["summary"])
        log_event(
            "persistence_error",
            operation="weight_summary",
            status="error",
            reason="persistence_error",
        )
        return _json({"code": "persistence_error", "message": "request failed"}, status_code=500)


@router.get("/api/artifacts/{artifact_id}", response_model=None)
def artifact_bytes(artifact_id: str, request: Request) -> Response:
    try:
        with session_scope(request_engine(request)) as session:
            service = WeightQueryService(session, request.app.state.settings)
            artifact = service.repos.raw_artifacts.get(artifact_id)
            if artifact is None:
                raise PhotoImportError("unknown_artifact", "unknown artifact", status_code=404)
            if not str(artifact.media_type).startswith("image/"):
                raise PhotoImportError("unsupported_media_type", "artifact is not an image")
            store = ContentAddressedPhotoStore(request.app.state.runtime_paths.root / "artifacts")
            payload = store.read(artifact.relative_storage_path)
            return Response(content=payload, media_type=artifact.media_type)
    except PhotoImportError as exc:
        return _json({"code": exc.code, "message": exc.message}, status_code=exc.status_code)
    except SQLAlchemyError:
        log_event(
            "persistence_error",
            operation="artifact",
            status="error",
            reason="persistence_error",
        )
        return _json({"code": "persistence_error", "message": "request failed"}, status_code=500)
