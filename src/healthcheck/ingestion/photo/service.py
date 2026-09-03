"""Photo upload, extraction, edit/reject/confirm and reprocess workflow."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    CandidateDecision,
    ImportCandidate,
    IngestBatch,
    IngestEvent,
    IngestStatus,
    MeasurementSession,
    RawArtifact,
    ScalarMeasurement,
    new_id,
)
from healthcheck.db.repositories import repositories_for, restore_stored_utc
from healthcheck.ingestion.photo.errors import PhotoImportError
from healthcheck.ingestion.photo.extractor import (
    DEFAULT_SCHEMA_VERSION,
    ExtractionFailure,
    ExtractionRequest,
    ExtractionResult,
    ImageMeasurementExtractor,
)
from healthcheck.ingestion.photo.normalize import (
    NormalizedField,
    extraction_configuration_fingerprint,
    field_warnings_from_candidate,
    normalize_confirmed_value,
    normalize_group,
    validate_local_date_and_timestamp,
)
from healthcheck.ingestion.photo.provenance import (
    algorithm_for_metric,
    ensure_photo_acquisition_source,
    provider_code_for_source,
    resolve_provider_code,
)
from healthcheck.ingestion.photo.store import (
    ContentAddressedPhotoStore,
    detect_media_type,
    safe_filename,
)
from healthcheck.logging import log_event
from healthcheck.runtime import RuntimePaths

MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_FILES = 100
_ALLOWED_PRECISION = {"date", "instant", "minute"}


@dataclass(frozen=True, slots=True)
class PhotoUpload:
    filename: str | None
    content: bytes
    declared_media_type: str | None = None


@dataclass(slots=True)
class PhotoItemResult:
    filename: str | None
    artifact_id: str | None = None
    content_hash: str | None = None
    media_type: str | None = None
    relative_storage_path: str | None = None
    duplicate_artifact: bool = False
    ingest_event_id: str | None = None
    ingest_batch_id: str | None = None
    status: str = IngestStatus.FAILED.value
    diagnostic_code: str | None = None
    diagnostic_reason: str | None = None
    candidate_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ImportBatchResult:
    batch: IngestBatch
    items: list[PhotoItemResult]


@dataclass(slots=True)
class ReprocessResult:
    candidates: list[ImportCandidate] = field(default_factory=list)
    failed: bool = False
    error_code: str | None = None
    error_message: str | None = None
    attempt_event_id: str | None = None
    ingest_event_id: str | None = None


class PhotoImportService:
    def __init__(
        self,
        session: Session,
        paths: RuntimePaths,
        extractor: ImageMeasurementExtractor,
    ):
        self.session = session
        self.paths = paths
        self.extractor = extractor
        self.repos = repositories_for(session)
        self.store = ContentAddressedPhotoStore(paths.photos.parent)

    def import_photos(
        self,
        uploads: Sequence[PhotoUpload],
        *,
        locale: str | None = None,
        timezone: str | None = None,
        schema_version: str = DEFAULT_SCHEMA_VERSION,
        provider_code: str | None = None,
    ) -> ImportBatchResult:
        try:
            return self._import_photos_inner(
                uploads,
                locale=locale,
                timezone=timezone,
                schema_version=schema_version,
                provider_code=provider_code,
            )
        except PhotoImportError:
            raise
        except SQLAlchemyError:
            raise PhotoImportError("persistence_error", "photo persistence failed") from None

    def _import_photos_inner(
        self,
        uploads: Sequence[PhotoUpload],
        *,
        locale: str | None,
        timezone: str | None,
        schema_version: str,
        provider_code: str | None,
    ) -> ImportBatchResult:
        if not uploads:
            raise PhotoImportError("empty_upload", "at least one photo is required")
        if len(uploads) > MAX_FILES:
            raise PhotoImportError(
                "too_many_files", f"at most {MAX_FILES} photos can be imported at once"
            )

        source = ensure_photo_acquisition_source(self.repos, provider_code=provider_code)
        batch = self.repos.ingest_batches.create(
            acquisition_source_id=source.id,
            batch_kind="photo",
            extractor_name=self.extractor.name,
            extractor_version=self.extractor.version,
            status=IngestStatus.RECEIVED.value,
        )
        items = [
            self._import_one(
                batch,
                upload,
                locale=locale,
                timezone=timezone,
                schema_version=schema_version,
                provider_code=provider_code,
            )
            for upload in uploads
        ]
        self._refresh_batch(batch.id, received_count=len(uploads), items=items, completed=True)
        batch = self.repos.ingest_batches.get(batch.id)
        assert batch is not None
        log_event("photo_import", operation="photo_import", status=batch.status, count=len(uploads))
        return ImportBatchResult(batch=batch, items=items)

    def list_batches(self, *, limit: int = 100) -> list[IngestBatch]:
        return self.repos.ingest_batches.list_recent(limit=limit)

    def get_batch(
        self, batch_id: str
    ) -> tuple[IngestBatch, list[IngestEvent], list[ImportCandidate]]:
        batch = self.repos.ingest_batches.get(batch_id)
        if batch is None:
            raise PhotoImportError(
                "unknown_batch", f"unknown import batch {batch_id}", status_code=404
            )
        events = self.repos.ingest_events.list_for_batch(batch_id)
        candidates = self.repos.import_candidates.list_for_batch(batch_id)
        referenced: list[ImportCandidate] = []
        for event in events:
            if event.duplicate_of_event_id is None:
                continue
            referenced.extend(
                self.repos.import_candidates.list_for_event(event.duplicate_of_event_id)
            )
        return batch, events, candidates + referenced

    def get_event(self, event_id: str) -> tuple[IngestEvent, list[ImportCandidate]]:
        event = self.repos.ingest_events.get(event_id)
        if event is None:
            raise PhotoImportError(
                "unknown_event", f"unknown import event {event_id}", status_code=404
            )
        return event, self.repos.import_candidates.list_for_event(event_id)

    def candidate_view(self, candidate: ImportCandidate) -> dict[str, Any]:
        measurement = self.repos.scalar_measurements.get_by_import_candidate(
            candidate.id, candidate.metric_code
        )
        session_id = measurement.measurement_session_id if measurement is not None else None
        return {
            "id": candidate.id,
            "ingest_event_id": candidate.ingest_event_id,
            "candidate_set_key": candidate.candidate_set_key,
            "measurement_group_key": candidate.measurement_group_key,
            "metric_code": candidate.metric_code,
            "proposed_value": candidate.proposed_value,
            "proposed_unit": candidate.proposed_unit,
            "proposed_source_local_date": candidate.proposed_source_local_date,
            "proposed_source_timestamp": candidate.proposed_source_timestamp,
            "temporal_precision": candidate.temporal_precision,
            "source_text": candidate.source_text,
            "extractor_name": candidate.extractor_name,
            "extractor_version": candidate.extractor_version,
            "model_name": candidate.model_name,
            "model_version": candidate.model_version,
            "prompt_version": candidate.prompt_version,
            "schema_version": candidate.schema_version,
            "confidence": candidate.confidence,
            "algorithm_code": candidate.algorithm_code,
            "algorithm_version": candidate.algorithm_version,
            "provider_code": candidate.provider_code,
            "source_timezone": candidate.source_timezone,
            "source_utc_offset_minutes": candidate.source_utc_offset_minutes,
            "edited_value": candidate.edited_value,
            "edited_unit": candidate.edited_unit,
            "edited_source_local_date": candidate.edited_source_local_date,
            "edited_source_timestamp": candidate.edited_source_timestamp,
            "user_decision": candidate.user_decision,
            "decision_reason": candidate.decision_reason,
            "decision_at": candidate.decision_at,
            "warnings": field_warnings_from_candidate(
                candidate.metric_code,
                candidate.proposed_unit,
                candidate.confidence,
                candidate.temporal_precision,
                candidate.proposed_source_timestamp,
                candidate.proposed_source_local_date,
            ),
            "measurement_session_id": session_id,
            "scalar_measurement_id": measurement.id if measurement is not None else None,
        }

    def artifact_view(self, artifact: RawArtifact) -> dict[str, Any]:
        return {
            "id": artifact.id,
            "content_hash": artifact.content_hash,
            "kind": artifact.kind,
            "media_type": artifact.media_type,
            "byte_size": artifact.byte_size,
            "relative_storage_path": artifact.relative_storage_path,
            "source_filename": artifact.source_filename,
        }

    def edit_pending(
        self,
        candidate_id: str,
        *,
        edited_value: float | None = None,
        edited_unit: str | None = None,
        edited_source_timestamp: datetime | None = None,
        edited_source_local_date: date | None = None,
        actor: str = "owner",
    ) -> ImportCandidate:
        try:
            candidate = self._load_candidate(candidate_id)
            planned_date = edited_source_local_date or candidate.edited_source_local_date
            if planned_date is None:
                planned_date = candidate.proposed_source_local_date
            planned_timestamp = edited_source_timestamp
            if planned_timestamp is None:
                planned_timestamp = (
                    candidate.edited_source_timestamp or candidate.proposed_source_timestamp
                )
            try:
                validate_local_date_and_timestamp(
                    planned_date,
                    planned_timestamp,
                    timezone=candidate.source_timezone,
                    utc_offset_minutes=candidate.source_utc_offset_minutes,
                )
            except ValueError:
                raise PhotoImportError(
                    "temporal_conflict", "local date and timestamp are inconsistent"
                ) from None
            return self.repos.import_candidates.edit_pending(
                candidate_id,
                edited_value=edited_value,
                edited_unit=edited_unit,
                edited_source_timestamp=edited_source_timestamp,
                edited_source_local_date=edited_source_local_date,
                actor=actor,
            )
        except KeyError as exc:
            raise PhotoImportError("unknown_candidate", str(exc), status_code=404) from None
        except ValueError as exc:
            raise _decision_error(exc) from None
        except SQLAlchemyError:
            raise PhotoImportError("persistence_error", "photo persistence failed") from None

    def reject(
        self,
        candidate_ids: Sequence[str],
        *,
        reason: str | None = None,
        actor: str = "owner",
    ) -> list[ImportCandidate]:
        try:
            return self._reject_inner(candidate_ids, reason=reason, actor=actor)
        except PhotoImportError:
            raise
        except SQLAlchemyError:
            raise PhotoImportError("persistence_error", "photo persistence failed") from None

    def _reject_inner(
        self,
        candidate_ids: Sequence[str],
        *,
        reason: str | None,
        actor: str,
    ) -> list[ImportCandidate]:
        if not candidate_ids:
            raise PhotoImportError("empty_selection", "at least one candidate id is required")
        rejected: list[ImportCandidate] = []
        event_ids: set[str] = set()
        for candidate_id in candidate_ids:
            try:
                candidate = self.repos.import_candidates.decide(
                    candidate_id,
                    CandidateDecision.REJECTED.value,
                    decision_reason=reason,
                    actor=actor,
                )
            except KeyError as exc:
                raise PhotoImportError("unknown_candidate", str(exc), status_code=404) from None
            except ValueError as exc:
                raise _decision_error(exc) from None
            rejected.append(candidate)
            event_ids.add(candidate.ingest_event_id)
        for event_id in event_ids:
            self._refresh_event_status(event_id)
        log_event("photo_reject", operation="photo_reject", status="ok", count=len(rejected))
        return rejected

    def confirm(
        self,
        candidate_ids: Sequence[str],
        *,
        edits: Mapping[str, Mapping[str, Any]] | None = None,
        actor: str = "owner",
    ) -> list[dict[str, Any]]:
        try:
            return self._confirm_inner(candidate_ids, edits=edits, actor=actor)
        except PhotoImportError:
            raise
        except SQLAlchemyError:
            raise PhotoImportError("persistence_error", "photo persistence failed") from None

    def _confirm_inner(
        self,
        candidate_ids: Sequence[str],
        *,
        edits: Mapping[str, Mapping[str, Any]] | None,
        actor: str,
    ) -> list[dict[str, Any]]:
        if not candidate_ids:
            raise PhotoImportError("empty_selection", "at least one candidate id is required")
        selected = [self._load_candidate(candidate_id) for candidate_id in candidate_ids]
        edits = edits or {}
        grouped: dict[tuple[str, str, str], list[ImportCandidate]] = {}
        for candidate in selected:
            key = (
                candidate.ingest_event_id,
                candidate.candidate_set_key,
                candidate.measurement_group_key,
            )
            grouped.setdefault(key, []).append(candidate)
        planned_times: dict[tuple[str, str, str], tuple[str, date, datetime | None]] = {}
        for key, group in grouped.items():
            payloads = {
                candidate.id: _edit_payload(edits.get(candidate.id) or {}) for candidate in group
            }
            planned_times[key] = _validated_group_time(group, payloads)
            self._assert_session_time_if_present(key[0], key[2], group, planned_times[key])
        results: list[dict[str, Any]] = []
        for key, group in grouped.items():
            results.extend(
                self._confirm_group(
                    key[0],
                    key[1],
                    key[2],
                    group,
                    edits=edits,
                    expected_time=planned_times[key],
                    actor=actor,
                )
            )
            self._refresh_event_status(key[0])
        log_event("photo_confirm", operation="photo_confirm", status="ok", count=len(selected))
        return results

    def reprocess_event(self, event_id: str) -> ReprocessResult:
        try:
            return self._reprocess_inner(event_id)
        except PhotoImportError:
            raise
        except SQLAlchemyError:
            raise PhotoImportError("persistence_error", "photo persistence failed") from None

    def _reprocess_inner(self, event_id: str) -> ReprocessResult:
        event = self.repos.ingest_events.get(event_id)
        if event is None:
            raise PhotoImportError(
                "unknown_event", f"unknown import event {event_id}", status_code=404
            )
        if event.raw_artifact_id is None:
            raise PhotoImportError(
                "missing_artifact", "import event has no raw artifact to reprocess"
            )
        artifact = self.repos.raw_artifacts.get(event.raw_artifact_id)
        if artifact is None:
            raise PhotoImportError("unknown_artifact", "raw artifact is missing", status_code=404)
        image_bytes = self.store.read(artifact.relative_storage_path)
        request = ExtractionRequest(
            artifact_id=artifact.id,
            content_hash=artifact.content_hash,
            media_type=artifact.media_type,
            schema_version=DEFAULT_SCHEMA_VERSION,
        )
        try:
            extracted = self.extractor.extract(request, image_bytes)
            target = self._target_event_for_extraction(event, artifact, extracted, batch_id=None)
            candidates = self._persist_candidates(target, artifact, extracted)
        except ExtractionFailure as exc:
            attempt = self._record_failed_attempt(event, artifact, exc.code)
            log_event("photo_reprocess", operation="photo_reprocess", status="error", count=0)
            return ReprocessResult(
                failed=True,
                error_code=exc.code,
                error_message=exc.message,
                attempt_event_id=attempt.id,
                ingest_event_id=event.id,
            )
        except ValueError:
            attempt = self._record_failed_attempt(event, artifact, "extractor_invalid_payload")
            log_event("photo_reprocess", operation="photo_reprocess", status="error", count=0)
            return ReprocessResult(
                failed=True,
                error_code="extractor_invalid_payload",
                error_message="extraction result could not be persisted",
                attempt_event_id=attempt.id,
                ingest_event_id=event.id,
            )
        self._refresh_event_status(target.id)
        log_event(
            "photo_reprocess", operation="photo_reprocess", status="ok", count=len(candidates)
        )
        return ReprocessResult(candidates=candidates, ingest_event_id=target.id)

    def _import_one(
        self,
        batch: IngestBatch,
        upload: PhotoUpload,
        *,
        locale: str | None,
        timezone: str | None,
        schema_version: str,
        provider_code: str | None,
    ) -> PhotoItemResult:
        filename = None
        try:
            filename = safe_filename(upload.filename)
        except PhotoImportError as exc:
            return PhotoItemResult(
                filename=upload.filename,
                diagnostic_code=exc.code,
                diagnostic_reason=exc.message,
            )
        if not upload.content:
            return PhotoItemResult(
                filename=filename,
                diagnostic_code="empty_file",
                diagnostic_reason="uploaded photo is empty",
            )
        if len(upload.content) > MAX_PHOTO_BYTES:
            return PhotoItemResult(
                filename=filename,
                diagnostic_code="file_too_large",
                diagnostic_reason=f"photo exceeds {MAX_PHOTO_BYTES} bytes",
            )
        try:
            media_type = detect_media_type(upload.content)
        except PhotoImportError as exc:
            return PhotoItemResult(
                filename=filename, diagnostic_code=exc.code, diagnostic_reason=exc.message
            )

        stored = self.store.put(upload.content, media_type)
        artifact = self.repos.raw_artifacts.get_or_create(
            content_hash=stored.content_hash,
            kind="photo",
            media_type=media_type,
            byte_size=len(upload.content),
            relative_storage_path=stored.relative_storage_path,
            source_filename=filename,
        )
        existing_event = self.repos.ingest_events.find_photo_by_artifact(artifact.id)
        duplicate = existing_event is not None
        request = ExtractionRequest(
            artifact_id=artifact.id,
            content_hash=artifact.content_hash,
            media_type=media_type,
            locale=locale,
            timezone=timezone,
            schema_version=schema_version,
        )
        try:
            extracted = self.extractor.extract(request, upload.content)
        except ExtractionFailure as exc:
            return self._failed_item(
                batch,
                artifact,
                filename=filename,
                media_type=media_type,
                duplicate=duplicate,
                existing_event=existing_event,
                code=exc.code,
                reason=exc.message,
            )

        set_key = _fingerprint_for_result(extracted)
        matching = self.repos.import_candidates.find_for_artifact_set_key(artifact.id, set_key)
        if matching:
            host_event = self.repos.ingest_events.get(matching[0].ingest_event_id)
            host_id = matching[0].ingest_event_id
            host_source = (
                host_event.acquisition_source_id
                if host_event is not None
                else batch.acquisition_source_id
            )
            occurrence = self.repos.ingest_events.create_linked(
                ingest_batch_id=batch.id,
                acquisition_source_id=host_source,
                raw_artifact_id=artifact.id,
                duplicate_of_event_id=host_id,
                status=IngestStatus.DUPLICATE.value,
                semantic_fingerprint=f"duplicate-occurrence:{batch.id}:{artifact.content_hash}:{set_key}",
                diagnostic_code="duplicate_artifact",
                diagnostic_reason="duplicate_artifact",
            )
            return PhotoItemResult(
                filename=filename,
                artifact_id=artifact.id,
                content_hash=artifact.content_hash,
                media_type=media_type,
                relative_storage_path=artifact.relative_storage_path,
                duplicate_artifact=True,
                ingest_event_id=occurrence.id,
                ingest_batch_id=occurrence.ingest_batch_id,
                status=IngestStatus.DUPLICATE.value,
                diagnostic_code="duplicate_artifact",
                candidate_ids=_sorted_ids(matching),
            )

        event = self._target_event_for_extraction(
            existing_event, artifact, extracted, batch_id=batch.id, provider_code=provider_code
        )
        try:
            candidates = self._persist_candidates(event, artifact, extracted)
        except (ValueError, ExtractionFailure) as exc:
            code = getattr(exc, "code", "extractor_invalid_payload")
            reason = getattr(exc, "message", None) or "extraction result could not be persisted"
            return self._failed_item(
                batch,
                artifact,
                filename=filename,
                media_type=media_type,
                duplicate=duplicate,
                existing_event=event,
                code=code,
                reason=reason,
            )
        self._refresh_event_status(event.id)
        refreshed = self.repos.ingest_events.get(event.id)
        warnings: list[str] = []
        for group in extracted.groups:
            for normalized in normalize_group(
                group,
                source_timezone=extracted.source_timezone,
                source_utc_offset_minutes=extracted.source_utc_offset_minutes,
            ):
                warnings.extend(normalized.warnings)
        return PhotoItemResult(
            filename=filename,
            artifact_id=artifact.id,
            content_hash=artifact.content_hash,
            media_type=media_type,
            relative_storage_path=artifact.relative_storage_path,
            duplicate_artifact=duplicate,
            ingest_event_id=event.id,
            ingest_batch_id=event.ingest_batch_id,
            status=refreshed.status if refreshed is not None else event.status,
            candidate_ids=_sorted_ids(candidates),
            warnings=warnings,
        )

    def _target_event_for_extraction(
        self,
        original: IngestEvent | None,
        artifact: RawArtifact,
        extracted: ExtractionResult,
        *,
        batch_id: str | None,
        provider_code: str | None = None,
    ) -> IngestEvent:
        event_source = ensure_photo_acquisition_source(
            self.repos,
            provider_code=resolve_provider_code(extracted.provider_code or provider_code),
            physical_device_code=extracted.physical_device_code,
            source_application=extracted.source_application,
            source_application_version=extracted.source_application_version,
        )
        set_key = _fingerprint_for_result(extracted)
        if original is None:
            assert batch_id is not None
            return self.repos.ingest_events.get_or_create(
                ingest_batch_id=batch_id,
                acquisition_source_id=event_source.id,
                raw_artifact_id=artifact.id,
                semantic_fingerprint=artifact.content_hash,
                event_type="photo",
                status=IngestStatus.PENDING_CONFIRMATION.value,
            )
        if original.acquisition_source_id == event_source.id:
            return original
        return self.repos.ingest_events.create_linked(
            ingest_batch_id=batch_id or original.ingest_batch_id,
            acquisition_source_id=event_source.id,
            raw_artifact_id=artifact.id,
            duplicate_of_event_id=original.id,
            status=IngestStatus.PENDING_CONFIRMATION.value,
            semantic_fingerprint=f"reprocess:{original.id}:{set_key}",
        )

    def _failed_item(
        self,
        batch: IngestBatch,
        artifact: RawArtifact,
        *,
        filename: str | None,
        media_type: str,
        duplicate: bool,
        existing_event: IngestEvent | None,
        code: str,
        reason: str,
    ) -> PhotoItemResult:
        sanitized = code
        if existing_event is not None and existing_event.status not in {
            IngestStatus.FAILED.value,
            IngestStatus.RECEIVED.value,
        }:
            attempt = self._record_failed_attempt(existing_event, artifact, code)
            return PhotoItemResult(
                filename=filename,
                artifact_id=artifact.id,
                content_hash=artifact.content_hash,
                media_type=media_type,
                relative_storage_path=artifact.relative_storage_path,
                duplicate_artifact=duplicate,
                ingest_event_id=attempt.id,
                ingest_batch_id=attempt.ingest_batch_id,
                status=IngestStatus.FAILED.value,
                diagnostic_code=code,
                diagnostic_reason=sanitized,
            )
        event = existing_event or self.repos.ingest_events.get_or_create(
            ingest_batch_id=batch.id,
            acquisition_source_id=batch.acquisition_source_id,
            raw_artifact_id=artifact.id,
            semantic_fingerprint=artifact.content_hash,
            event_type="photo",
            status=IngestStatus.FAILED.value,
            diagnostic_code=code,
            diagnostic_reason=sanitized,
        )
        self.repos.ingest_events.set_status(
            event.id, IngestStatus.FAILED.value, diagnostic_code=code, diagnostic_reason=sanitized
        )
        return PhotoItemResult(
            filename=filename,
            artifact_id=artifact.id,
            content_hash=artifact.content_hash,
            media_type=media_type,
            relative_storage_path=artifact.relative_storage_path,
            duplicate_artifact=duplicate,
            ingest_event_id=event.id,
            ingest_batch_id=event.ingest_batch_id,
            status=IngestStatus.FAILED.value,
            diagnostic_code=code,
            diagnostic_reason=sanitized,
        )

    def _record_failed_attempt(
        self, original: IngestEvent, artifact: RawArtifact | None, code: str
    ) -> IngestEvent:
        attempt_batch = self.repos.ingest_batches.create(
            acquisition_source_id=original.acquisition_source_id,
            batch_kind="photo",
            extractor_name=getattr(self.extractor, "name", None),
            extractor_version=getattr(self.extractor, "version", None),
            status=IngestStatus.FAILED.value,
        )
        attempt = self.repos.ingest_events.create_linked(
            ingest_batch_id=attempt_batch.id,
            acquisition_source_id=original.acquisition_source_id,
            raw_artifact_id=None if artifact is None else artifact.id,
            duplicate_of_event_id=original.id,
            status=IngestStatus.FAILED.value,
            semantic_fingerprint=f"failed-reprocess:{original.id}:{new_id()}",
            diagnostic_code=code,
            diagnostic_reason=code,
        )
        self.repos.ingest_batches.update(
            attempt_batch.id,
            status=IngestStatus.FAILED.value,
            received_count=1,
            failed_count=1,
            diagnostic_reason=code,
            completed=True,
        )
        return attempt

    def _persist_candidates(
        self,
        event: IngestEvent,
        artifact: RawArtifact,
        extracted: ExtractionResult,
    ) -> list[ImportCandidate]:
        del artifact
        provider_code = resolve_provider_code(extracted.provider_code)
        set_key = _fingerprint_for_result(extracted)
        prepared: list[tuple[str, NormalizedField]] = []
        try:
            for group in extracted.groups:
                for normalized in normalize_group(
                    group,
                    source_timezone=extracted.source_timezone,
                    source_utc_offset_minutes=extracted.source_utc_offset_minutes,
                ):
                    _validate_normalized_field(normalized)
                    prepared.append((group.key, normalized))
        except ValueError:
            raise ExtractionFailure(
                "temporal_conflict", "local date and timestamp are inconsistent"
            ) from None
        if not prepared:
            raise ExtractionFailure(
                "extractor_empty_result", "extractor returned no measurement groups"
            )
        created: list[ImportCandidate] = []
        nested = self.session.begin_nested()
        try:
            for group_key, normalized in prepared:
                created.append(
                    self.repos.import_candidates.create_pending(
                        ingest_event_id=event.id,
                        measurement_group_key=group_key,
                        metric_code=normalized.metric_code,
                        candidate_set_key=set_key,
                        proposed_value=normalized.proposed_value,
                        proposed_unit=normalized.proposed_unit,
                        proposed_source_timestamp=normalized.source_timestamp,
                        proposed_source_local_date=normalized.source_local_date,
                        temporal_precision=normalized.temporal_precision,
                        source_text=normalized.source_text,
                        extractor_name=extracted.extractor_name,
                        extractor_version=extracted.extractor_version,
                        model_name=extracted.model_name,
                        model_version=extracted.model_version,
                        prompt_version=extracted.prompt_version,
                        schema_version=extracted.schema_version,
                        confidence=normalized.confidence,
                        evidence_region=normalized.evidence_region,
                        algorithm_code=normalized.algorithm_code,
                        algorithm_version=normalized.algorithm_version,
                        provider_code=provider_code,
                        source_timezone=normalized.source_timezone,
                        source_utc_offset_minutes=normalized.source_utc_offset_minutes,
                    )
                )
            nested.commit()
        except Exception:
            nested.rollback()
            raise
        if event.status != IngestStatus.PENDING_CONFIRMATION.value:
            pending_exists = any(
                candidate.user_decision == CandidateDecision.PENDING.value
                for candidate in self.repos.import_candidates.list_for_event(event.id)
            )
            if pending_exists:
                self.repos.ingest_events.set_status(
                    event.id, IngestStatus.PENDING_CONFIRMATION.value
                )
        return created

    def _confirm_group(
        self,
        event_id: str,
        set_key: str,
        group_key: str,
        selected: Sequence[ImportCandidate],
        *,
        edits: Mapping[str, Mapping[str, Any]],
        expected_time: tuple[str, date, datetime | None],
        actor: str,
    ) -> list[dict[str, Any]]:
        event = self.repos.ingest_events.get(event_id)
        if event is None:
            raise PhotoImportError(
                "unknown_event", f"unknown import event {event_id}", status_code=404
            )
        artifact = (
            self.repos.raw_artifacts.get(event.raw_artifact_id)
            if event.raw_artifact_id is not None
            else None
        )
        if artifact is None:
            raise PhotoImportError(
                "missing_artifact", "confirmed photo event is missing its artifact"
            )
        all_group = [
            candidate
            for candidate in self.repos.import_candidates.list_for_event(event_id)
            if candidate.candidate_set_key == set_key
            and candidate.measurement_group_key == group_key
        ]
        results: list[dict[str, Any]] = []
        new_candidates: list[ImportCandidate] = []
        for candidate in selected:
            payload = _edit_payload(edits.get(candidate.id) or {})
            existing_measurement = self.repos.scalar_measurements.get_by_import_candidate(
                candidate.id, candidate.metric_code
            )
            if existing_measurement is not None:
                if not _terminal_replay_matches(candidate, payload):
                    raise PhotoImportError(
                        "terminal_candidate",
                        "terminal candidate cannot change",
                        status_code=409,
                    )
                results.append(
                    _measurement_row(
                        candidate, existing_measurement, existing_measurement.measurement_session_id
                    )
                )
            else:
                new_candidates.append(candidate)
        if not new_candidates:
            return results
        for candidate in new_candidates:
            payload = _edit_payload(edits.get(candidate.id) or {})
            try:
                self.repos.import_candidates.decide(
                    candidate.id,
                    CandidateDecision.CONFIRMED.value,
                    edited_value=payload.get("value", payload.get("edited_value")),
                    edited_unit=payload.get("unit", payload.get("edited_unit")),
                    edited_source_timestamp=payload.get(
                        "source_timestamp", payload.get("edited_source_timestamp")
                    ),
                    edited_source_local_date=_as_date(
                        payload.get("source_local_date", payload.get("edited_source_local_date"))
                    ),
                    actor=actor,
                )
            except ValueError as exc:
                raise _decision_error(exc) from None
        session_record = self._session_for_group(
            event=event,
            artifact=artifact,
            group_key=group_key,
            set_key=set_key,
            selected=new_candidates,
            all_group=all_group,
            expected_time=expected_time,
        )
        for candidate in new_candidates:
            loaded = self.repos.import_candidates.get(candidate.id)
            assert loaded is not None
            measurement = self._write_measurement(session_record, loaded)
            results.append(_measurement_row(loaded, measurement, session_record.id))
        return results

    def _assert_session_time_if_present(
        self,
        event_id: str,
        group_key: str,
        group: Sequence[ImportCandidate],
        expected_time: tuple[str, date, datetime | None],
    ) -> None:
        event = self.repos.ingest_events.get(event_id)
        if event is None or not group:
            return
        set_key = group[0].candidate_set_key
        siblings = [
            candidate
            for candidate in self.repos.import_candidates.list_for_event(event_id)
            if candidate.candidate_set_key == set_key
            and candidate.measurement_group_key == group_key
        ]
        for candidate in siblings:
            existing = self.repos.measurement_sessions.find_by_source_identity(
                acquisition_source_id=event.acquisition_source_id,
                confirmation_candidate_id=candidate.id,
            )
            if existing is None:
                continue
            if not _session_time_matches(existing, expected_time):
                raise PhotoImportError(
                    "temporal_conflict",
                    "sequential confirmation must match the existing session date/time/precision",
                )

    def _session_for_group(
        self,
        *,
        event: IngestEvent,
        artifact: RawArtifact,
        group_key: str,
        set_key: str,
        selected: Sequence[ImportCandidate],
        all_group: Sequence[ImportCandidate],
        expected_time: tuple[str, date, datetime | None],
    ) -> MeasurementSession:
        source_record_id, semantic_key, source_fingerprint = _photo_source_identity(
            artifact.content_hash, group_key
        )
        precision, local_date, timestamp = expected_time
        timestamp = restore_stored_utc(timestamp)
        set_session = None
        for candidate in all_group:
            found = self.repos.measurement_sessions.find_by_source_identity(
                acquisition_source_id=event.acquisition_source_id,
                confirmation_candidate_id=candidate.id,
            )
            if found is not None:
                set_session = found
                break
        if set_session is not None:
            if not _session_time_matches(set_session, expected_time):
                raise PhotoImportError(
                    "temporal_conflict",
                    "sequential confirmation must match the existing session date/time/precision",
                )
            return set_session
        confirmation_candidate = _representative(selected)
        timezone, offset = _group_zone(selected)
        head = self.repos.measurement_sessions.find_by_source_identity(
            acquisition_source_id=event.acquisition_source_id,
            source_record_id=source_record_id,
            source_fingerprint=source_fingerprint,
            semantic_key=semantic_key,
        )
        if head is None:
            return self.repos.measurement_sessions.create_confirmed(
                acquisition_source_id=event.acquisition_source_id,
                ingest_event_id=event.id,
                raw_artifact_id=artifact.id,
                confirmation_candidate_id=confirmation_candidate.id,
                source_record_id=source_record_id,
                source_fingerprint=source_fingerprint,
                semantic_key=semantic_key,
                source_local_date=local_date,
                temporal_precision=precision,
                source_timestamp_utc=timestamp,
                source_timezone=timezone,
                source_utc_offset_minutes=offset,
            )
        existing_candidate = (
            self.repos.import_candidates.get(head.confirmation_candidate_id)
            if head.confirmation_candidate_id is not None
            else None
        )
        if existing_candidate is not None and existing_candidate.candidate_set_key == set_key:
            if not _session_time_matches(head, expected_time):
                raise PhotoImportError(
                    "temporal_conflict",
                    "sequential confirmation must match the existing session date/time/precision",
                )
            return head
        try:
            return self.repos.measurement_sessions.create_revision(
                head.id,
                source_local_date=local_date,
                temporal_precision=precision,
                source_timestamp_utc=timestamp,
                confirmation_candidate_id=confirmation_candidate.id,
                ingest_event_id=event.id,
                raw_artifact_id=artifact.id,
                source_record_id=source_record_id,
                source_fingerprint=source_fingerprint,
                semantic_key=semantic_key,
                source_timezone=timezone,
                source_utc_offset_minutes=offset,
            )
        except ValueError as exc:
            raise _decision_error(exc) from None

    def _write_measurement(
        self,
        session_record: MeasurementSession,
        candidate: ImportCandidate,
    ) -> ScalarMeasurement:
        value = (
            candidate.edited_value
            if candidate.edited_value is not None
            else candidate.proposed_value
        )
        unit = (
            candidate.edited_unit if candidate.edited_unit is not None else candidate.proposed_unit
        )
        if value is None:
            raise PhotoImportError("missing_value", "candidate has no value to confirm")
        try:
            normalized_value, normalized_unit = normalize_confirmed_value(
                candidate.metric_code, value, unit
            )
        except ValueError:
            raise PhotoImportError(
                "unnormalizable_value", "candidate unit cannot be normalized"
            ) from None
        provider_code = candidate.provider_code or XIAOMI_FALLBACK_PROVIDER
        if not candidate.provider_code:
            acquisition_source = self.repos.acquisition_sources.get_by_id(
                session_record.acquisition_source_id
            )
            if acquisition_source is not None:
                provider_code = provider_code_for_source(self.repos, acquisition_source)
        algorithm = algorithm_for_metric(
            self.repos,
            metric_code=candidate.metric_code,
            provider_code=provider_code,
            algorithm_code=candidate.algorithm_code,
            algorithm_version=candidate.algorithm_version,
        )
        existing = self.repos.scalar_measurements.get_by_import_candidate(
            candidate.id, candidate.metric_code
        )
        if existing is not None:
            return existing
        previous = self.repos.scalar_measurements.active_for_source_metric(
            acquisition_source_id=session_record.acquisition_source_id,
            metric_code=candidate.metric_code,
            semantic_key=session_record.semantic_key,
            source_record_id=session_record.source_record_id,
        )
        original_value = candidate.source_text or str(value)
        try:
            if previous is not None and previous.import_candidate_id != candidate.id:
                return self.repos.scalar_measurements.create_revision(
                    previous.id,
                    measurement_session_id=session_record.id,
                    normalized_value=normalized_value,
                    normalized_unit=normalized_unit,
                    measurement_algorithm_id=algorithm.id,
                    import_candidate_id=candidate.id,
                    original_value=original_value,
                    original_unit=unit,
                    source_text=candidate.source_text,
                )
            return self.repos.scalar_measurements.create(
                measurement_session_id=session_record.id,
                metric_code=candidate.metric_code,
                normalized_value=normalized_value,
                normalized_unit=normalized_unit,
                measurement_algorithm_id=algorithm.id,
                import_candidate_id=candidate.id,
                original_value=original_value,
                original_unit=unit,
                source_text=candidate.source_text,
            )
        except ValueError as exc:
            raise _decision_error(exc) from None

    def _load_candidate(self, candidate_id: str) -> ImportCandidate:
        candidate = self.repos.import_candidates.get(candidate_id)
        if candidate is None:
            raise PhotoImportError(
                "unknown_candidate", f"unknown import candidate {candidate_id}", status_code=404
            )
        return candidate

    def _refresh_event_status(self, event_id: str) -> IngestEvent:
        event = self.repos.ingest_events.get(event_id)
        if event is None:
            raise PhotoImportError(
                "unknown_event", f"unknown import event {event_id}", status_code=404
            )
        if event.duplicate_of_event_id is not None:
            self._refresh_batch(event.ingest_batch_id)
            return event
        candidates = self.repos.import_candidates.list_for_event(event_id)
        if not candidates:
            self._refresh_batch(event.ingest_batch_id)
            return event
        decisions = {candidate.user_decision for candidate in candidates}
        if CandidateDecision.PENDING.value in decisions:
            status = IngestStatus.PENDING_CONFIRMATION.value
        elif decisions == {CandidateDecision.REJECTED.value}:
            status = IngestStatus.REJECTED.value
        else:
            status = IngestStatus.COMMITTED.value
        if event.status != status:
            event = self.repos.ingest_events.set_status(event_id, status)
        self._refresh_batch(event.ingest_batch_id)
        return event

    def _refresh_batch(
        self,
        batch_id: str,
        *,
        received_count: int | None = None,
        items: Sequence[PhotoItemResult] | None = None,
        completed: bool = False,
    ) -> IngestBatch:
        events = self.repos.ingest_events.list_for_batch(batch_id)
        statuses = [event.status for event in events]
        parsed_count = sum(
            1
            for event in events
            if event.status
            in {
                IngestStatus.PENDING_CONFIRMATION.value,
                IngestStatus.COMMITTED.value,
                IngestStatus.REJECTED.value,
            }
        )
        failed_count = sum(1 for event in events if event.status == IngestStatus.FAILED.value)
        committed_count = sum(1 for event in events if event.status == IngestStatus.COMMITTED.value)
        duplicate_items = (
            0 if items is None else sum(1 for item in items if item.duplicate_artifact)
        )
        if not statuses:
            status = (
                IngestStatus.DUPLICATE.value if duplicate_items else IngestStatus.RECEIVED.value
            )
        elif IngestStatus.PENDING_CONFIRMATION.value in statuses:
            status = IngestStatus.PENDING_CONFIRMATION.value
        elif IngestStatus.COMMITTED.value in statuses:
            status = IngestStatus.COMMITTED.value
        elif statuses and all(value == IngestStatus.REJECTED.value for value in statuses):
            status = IngestStatus.REJECTED.value
        elif statuses and all(value == IngestStatus.FAILED.value for value in statuses):
            status = IngestStatus.FAILED.value
        elif IngestStatus.DUPLICATE.value in statuses:
            status = IngestStatus.DUPLICATE.value
        else:
            status = IngestStatus.RECEIVED.value
        diagnostic = None
        if duplicate_items:
            diagnostic = "duplicate_artifact"
        return self.repos.ingest_batches.update(
            batch_id,
            status=status,
            received_count=received_count,
            parsed_count=parsed_count,
            committed_count=committed_count,
            failed_count=failed_count,
            diagnostic_reason=diagnostic,
            completed=completed,
        )


XIAOMI_FALLBACK_PROVIDER = "xiaomi_app_unknown"


def _fingerprint_for_result(extracted: ExtractionResult) -> str:
    return extraction_configuration_fingerprint(
        extractor_name=extracted.extractor_name,
        extractor_version=extracted.extractor_version,
        schema_version=extracted.schema_version,
        model_name=extracted.model_name,
        model_version=extracted.model_version,
        prompt_version=extracted.prompt_version,
        provider_code=resolve_provider_code(extracted.provider_code),
        physical_device_code=extracted.physical_device_code,
        source_application=extracted.source_application,
        source_application_version=extracted.source_application_version,
    )


def _validate_normalized_field(normalized: NormalizedField) -> None:
    if not normalized.metric_code:
        raise ExtractionFailure(
            "extractor_invalid_payload", "candidate field is missing metric_code"
        )
    if normalized.confidence is not None and not 0 <= normalized.confidence <= 1:
        raise ExtractionFailure("extractor_invalid_payload", "confidence out of range")
    if (
        normalized.temporal_precision is not None
        and normalized.temporal_precision not in _ALLOWED_PRECISION
    ):
        raise ExtractionFailure("extractor_invalid_payload", "invalid temporal precision")


def _photo_source_identity(content_hash: str, group_key: str) -> tuple[str, str, str]:
    source_record_id = f"photo:{content_hash}:{group_key}"
    fingerprint = hashlib.sha256(source_record_id.encode("utf-8")).hexdigest()
    return source_record_id, source_record_id, fingerprint


def _representative(candidates: Sequence[ImportCandidate]) -> ImportCandidate:
    by_code = {candidate.metric_code: candidate for candidate in candidates}
    if "weight" in by_code:
        return by_code["weight"]
    return sorted(candidates, key=lambda candidate: (candidate.metric_code, candidate.id))[0]


def _sorted_ids(candidates: Sequence[ImportCandidate]) -> list[str]:
    return [
        candidate.id
        for candidate in sorted(
            candidates,
            key=lambda item: (item.measurement_group_key, item.metric_code, item.id),
        )
    ]


def _effective_time(
    candidate: ImportCandidate, payload: Mapping[str, Any]
) -> tuple[str, date, datetime | None]:
    precision = candidate.temporal_precision or "date"
    edit_timestamp = payload.get("source_timestamp", payload.get("edited_source_timestamp"))
    edit_date = _as_date(payload.get("source_local_date", payload.get("edited_source_local_date")))
    timestamp = (
        edit_timestamp
        if edit_timestamp is not None
        else candidate.edited_source_timestamp or candidate.proposed_source_timestamp
    )
    local_date = (
        edit_date
        if edit_date is not None
        else candidate.edited_source_local_date or candidate.proposed_source_local_date
    )
    timestamp = restore_stored_utc(timestamp) if timestamp is not None else None
    if precision == "date":
        if edit_timestamp is not None or candidate.edited_source_timestamp is not None:
            raise PhotoImportError(
                "date_precision_timestamp",
                "date-only evidence cannot accept a timestamp",
            )
        if local_date is None:
            raise PhotoImportError(
                "missing_source_date", "confirmed photo evidence is missing a source date"
            )
        return precision, local_date, None
    if local_date is None:
        raise PhotoImportError(
            "missing_source_date", "confirmed photo evidence is missing a source date"
        )
    if timestamp is None:
        raise PhotoImportError("missing_timestamp", "non-date photo evidence requires a timestamp")
    try:
        validate_local_date_and_timestamp(
            local_date,
            timestamp,
            timezone=candidate.source_timezone,
            utc_offset_minutes=candidate.source_utc_offset_minutes,
        )
    except ValueError:
        raise PhotoImportError(
            "temporal_conflict", "local date and timestamp are inconsistent"
        ) from None
    return precision, local_date, timestamp


def _validated_group_time(
    candidates: Sequence[ImportCandidate], payloads: Mapping[str, Mapping[str, Any]]
) -> tuple[str, date, datetime | None]:
    times = [_effective_time(candidate, payloads.get(candidate.id, {})) for candidate in candidates]
    unique = {_time_key(item) for item in times}
    if len(unique) != 1:
        raise PhotoImportError(
            "temporal_conflict",
            "candidates in one session must share one date/time/precision",
        )
    return times[0]


def _time_key(value: tuple[str, date, datetime | None]) -> tuple[str, date, datetime | None]:
    precision, local_date, timestamp = value
    if timestamp is None:
        return precision, local_date, None
    restored = restore_stored_utc(timestamp)
    assert restored is not None
    return precision, local_date, restored.astimezone(UTC).replace(tzinfo=None)


def _session_time_matches(
    session: MeasurementSession, expected: tuple[str, date, datetime | None]
) -> bool:
    precision, local_date, timestamp = expected
    if session.temporal_precision != precision or session.source_local_date != local_date:
        return False
    return _time_key(
        (precision, local_date, restore_stored_utc(session.source_timestamp_utc))
    ) == _time_key((precision, local_date, timestamp))


def _measurement_row(
    candidate: ImportCandidate, measurement: ScalarMeasurement, session_id: str
) -> dict[str, Any]:
    return {
        "candidate_id": candidate.id,
        "measurement_session_id": session_id,
        "scalar_measurement_id": measurement.id,
        "metric_code": measurement.metric_code,
        "normalized_value": measurement.normalized_value,
        "normalized_unit": measurement.normalized_unit,
        "measurement_algorithm_id": measurement.measurement_algorithm_id,
        "idempotent": True,
    }


def _group_zone(candidates: Sequence[ImportCandidate]) -> tuple[str | None, int | None]:
    timezones = {candidate.source_timezone for candidate in candidates}
    offsets = {candidate.source_utc_offset_minutes for candidate in candidates}
    timezone = next(iter(timezones)) if len(timezones) == 1 else None
    offset = next(iter(offsets)) if len(offsets) == 1 else None
    return timezone, offset


def _terminal_effective(
    candidate: ImportCandidate,
) -> tuple[float | None, str | None, tuple[str, date, datetime | None]]:
    value = (
        candidate.edited_value if candidate.edited_value is not None else candidate.proposed_value
    )
    unit = candidate.edited_unit if candidate.edited_unit is not None else candidate.proposed_unit
    return value, unit, _effective_time(candidate, {})


def _planned_effective(
    candidate: ImportCandidate, payload: Mapping[str, Any]
) -> tuple[float | None, str | None, tuple[str, date, datetime | None]]:
    if "value" in payload or "edited_value" in payload:
        value = payload.get("value", payload.get("edited_value"))
    else:
        value = (
            candidate.edited_value
            if candidate.edited_value is not None
            else candidate.proposed_value
        )
    if "unit" in payload or "edited_unit" in payload:
        unit = payload.get("unit", payload.get("edited_unit"))
    else:
        unit = (
            candidate.edited_unit if candidate.edited_unit is not None else candidate.proposed_unit
        )
    return value, unit, _effective_time(candidate, payload)


def _terminal_replay_matches(candidate: ImportCandidate, payload: Mapping[str, Any]) -> bool:
    planned_value, planned_unit, planned_time = _planned_effective(candidate, payload)
    terminal_value, terminal_unit, terminal_time = _terminal_effective(candidate)
    return (
        planned_value == terminal_value
        and planned_unit == terminal_unit
        and _time_key(planned_time) == _time_key(terminal_time)
    )


def _edit_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    timestamp = result.get("source_timestamp", result.get("edited_source_timestamp"))
    if isinstance(timestamp, str):
        parsed = datetime.fromisoformat(timestamp)
        result["source_timestamp"] = restore_stored_utc(parsed)
    elif isinstance(timestamp, datetime):
        result["source_timestamp"] = restore_stored_utc(timestamp)
    local_date = result.get("source_local_date", result.get("edited_source_local_date"))
    if isinstance(local_date, str):
        result["source_local_date"] = date.fromisoformat(local_date)
    return result


def _as_date(value: date | str | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _decision_error(exc: ValueError) -> PhotoImportError:
    message = str(exc)
    if "date-only" in message:
        return PhotoImportError(
            "date_precision_timestamp", "date-only evidence cannot accept a timestamp"
        )
    if "terminal" in message or "revision" in message:
        return PhotoImportError(
            "terminal_candidate", "terminal candidate cannot change", status_code=409
        )
    if "different evidence" in message:
        return PhotoImportError(
            "extraction_conflict", "extraction identity already has different evidence"
        )
    return PhotoImportError("invalid_confirmation", "confirmation request is invalid")
