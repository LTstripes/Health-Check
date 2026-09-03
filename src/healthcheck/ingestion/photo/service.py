"""Photo upload, extraction, edit/reject/confirm and reprocess workflow."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

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
)
from healthcheck.db.repositories import repositories_for
from healthcheck.ingestion.photo.errors import PhotoImportError
from healthcheck.ingestion.photo.extractor import (
    DEFAULT_SCHEMA_VERSION,
    ExtractionFailure,
    ExtractionRequest,
    ExtractionResult,
    ImageMeasurementExtractor,
)
from healthcheck.ingestion.photo.normalize import (
    candidate_set_key as build_candidate_set_key,
)
from healthcheck.ingestion.photo.normalize import (
    field_warnings_from_candidate,
    normalize_confirmed_value,
    normalize_group,
)
from healthcheck.ingestion.photo.provenance import (
    XIAOMI_HOME_PROVIDER,
    algorithm_for_metric,
    ensure_photo_acquisition_source,
    provider_code_for_source,
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
        if not uploads:
            raise PhotoImportError("empty_upload", "at least one photo is required")
        if len(uploads) > MAX_FILES:
            raise PhotoImportError(
                "too_many_files", f"at most {MAX_FILES} photos can be imported at once"
            )

        source = ensure_photo_acquisition_source(
            self.repos, provider_code=provider_code or XIAOMI_HOME_PROVIDER
        )
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
        return batch, events, candidates

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
            return self.repos.import_candidates.edit_pending(
                candidate_id,
                edited_value=edited_value,
                edited_unit=edited_unit,
                edited_source_timestamp=edited_source_timestamp,
                edited_source_local_date=edited_source_local_date,
                actor=actor,
            )
        except KeyError as exc:
            raise PhotoImportError("unknown_candidate", str(exc), status_code=404) from exc
        except ValueError as exc:
            raise _decision_error(exc) from exc

    def reject(
        self,
        candidate_ids: Sequence[str],
        *,
        reason: str | None = None,
        actor: str = "owner",
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
                raise PhotoImportError("unknown_candidate", str(exc), status_code=404) from exc
            except ValueError as exc:
                raise _decision_error(exc) from exc
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
        if not candidate_ids:
            raise PhotoImportError("empty_selection", "at least one candidate id is required")
        selected = [self._load_candidate(candidate_id) for candidate_id in candidate_ids]
        edits = edits or {}
        confirmed: list[ImportCandidate] = []
        for candidate in selected:
            payload = _edit_payload(edits.get(candidate.id) or {})
            try:
                confirmed.append(
                    self.repos.import_candidates.decide(
                        candidate.id,
                        CandidateDecision.CONFIRMED.value,
                        edited_value=payload.get("value", payload.get("edited_value")),
                        edited_unit=payload.get("unit", payload.get("edited_unit")),
                        edited_source_timestamp=payload.get(
                            "source_timestamp", payload.get("edited_source_timestamp")
                        ),
                        edited_source_local_date=_as_date(
                            payload.get(
                                "source_local_date", payload.get("edited_source_local_date")
                            )
                        ),
                        actor=actor,
                    )
                )
            except ValueError as exc:
                raise _decision_error(exc) from exc

        results: list[dict[str, Any]] = []
        grouped: dict[tuple[str, str, str], list[ImportCandidate]] = {}
        for candidate in confirmed:
            key = (
                candidate.ingest_event_id,
                candidate.candidate_set_key,
                candidate.measurement_group_key,
            )
            grouped.setdefault(key, []).append(candidate)
        for (event_id, set_key, group_key), group in grouped.items():
            results.extend(self._confirm_group(event_id, set_key, group_key, group))
            self._refresh_event_status(event_id)
        log_event("photo_confirm", operation="photo_confirm", status="ok", count=len(confirmed))
        return results

    def reprocess_event(self, event_id: str) -> list[ImportCandidate]:
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
        except ExtractionFailure as exc:
            self.repos.ingest_events.set_status(
                event.id,
                IngestStatus.FAILED.value,
                diagnostic_code=exc.code,
                diagnostic_reason=exc.message,
            )
            raise PhotoImportError(exc.code, exc.message) from exc
        candidates = self._persist_candidates(event, artifact, extracted)
        self._refresh_event_status(event.id)
        log_event(
            "photo_reprocess", operation="photo_reprocess", status="ok", count=len(candidates)
        )
        return candidates

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
        set_key = build_candidate_set_key(
            self.extractor.name, self.extractor.version, schema_version
        )
        if existing_event is not None:
            existing_candidates = [
                candidate
                for candidate in self.repos.import_candidates.list_for_event(existing_event.id)
                if candidate.candidate_set_key == set_key
            ]
            if existing_candidates:
                return PhotoItemResult(
                    filename=filename,
                    artifact_id=artifact.id,
                    content_hash=artifact.content_hash,
                    media_type=media_type,
                    relative_storage_path=artifact.relative_storage_path,
                    duplicate_artifact=True,
                    ingest_event_id=existing_event.id,
                    ingest_batch_id=existing_event.ingest_batch_id,
                    status=existing_event.status,
                    candidate_ids=[
                        candidate.id
                        for candidate in sorted(
                            existing_candidates,
                            key=lambda item: (
                                item.measurement_group_key,
                                item.metric_code,
                                item.id,
                            ),
                        )
                    ],
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

        event_source = ensure_photo_acquisition_source(
            self.repos,
            provider_code=extracted.provider_code or provider_code or XIAOMI_HOME_PROVIDER,
            physical_device_code=extracted.physical_device_code,
            source_application=extracted.source_application,
            source_application_version=extracted.source_application_version,
        )
        event = existing_event or self.repos.ingest_events.get_or_create(
            ingest_batch_id=batch.id,
            acquisition_source_id=event_source.id,
            raw_artifact_id=artifact.id,
            semantic_fingerprint=artifact.content_hash,
            event_type="photo",
            status=IngestStatus.PENDING_CONFIRMATION.value,
        )
        try:
            candidates = self._persist_candidates(event, artifact, extracted)
        except ValueError as exc:
            return self._failed_item(
                batch,
                artifact,
                filename=filename,
                media_type=media_type,
                duplicate=duplicate,
                existing_event=event,
                code="extractor_invalid_payload",
                reason=str(exc),
            )
        self._refresh_event_status(event.id)
        refreshed = self.repos.ingest_events.get(event.id)
        warnings: list[str] = []
        for group in extracted.groups:
            for normalized in normalize_group(group):
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
            candidate_ids=[
                candidate.id
                for candidate in sorted(
                    candidates,
                    key=lambda item: (item.measurement_group_key, item.metric_code, item.id),
                )
            ],
            warnings=warnings,
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
        event = existing_event or self.repos.ingest_events.get_or_create(
            ingest_batch_id=batch.id,
            acquisition_source_id=batch.acquisition_source_id,
            raw_artifact_id=artifact.id,
            semantic_fingerprint=artifact.content_hash,
            event_type="photo",
            status=IngestStatus.FAILED.value,
            diagnostic_code=code,
            diagnostic_reason=reason,
        )
        self.repos.ingest_events.set_status(
            event.id, IngestStatus.FAILED.value, diagnostic_code=code, diagnostic_reason=reason
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
            diagnostic_reason=reason,
        )

    def _persist_candidates(
        self,
        event: IngestEvent,
        artifact: RawArtifact,
        extracted: ExtractionResult,
    ) -> list[ImportCandidate]:
        del artifact  # identity is already on the ingest event
        set_key = build_candidate_set_key(
            extracted.extractor_name, extracted.extractor_version, extracted.schema_version
        )
        created: list[ImportCandidate] = []
        for group in extracted.groups:
            for normalized in normalize_group(group):
                created.append(
                    self.repos.import_candidates.create_pending(
                        ingest_event_id=event.id,
                        measurement_group_key=group.key,
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
                    )
                )
        if event.status != IngestStatus.PENDING_CONFIRMATION.value:
            self.repos.ingest_events.set_status(event.id, IngestStatus.PENDING_CONFIRMATION.value)
        return created

    def _confirm_group(
        self,
        event_id: str,
        set_key: str,
        group_key: str,
        selected: Sequence[ImportCandidate],
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
        session_record = self._session_for_group(
            event=event,
            artifact=artifact,
            group_key=group_key,
            set_key=set_key,
            selected=selected,
            all_group=all_group,
        )
        acquisition_source = self.repos.acquisition_sources.get_by_id(event.acquisition_source_id)
        if acquisition_source is None:
            raise PhotoImportError(
                "missing_source", "confirmed photo event is missing acquisition source"
            )
        provider_code = provider_code_for_source(self.repos, acquisition_source)
        rows: list[dict[str, Any]] = []
        for candidate in selected:
            measurement = self._write_measurement(session_record, candidate, provider_code)
            rows.append(
                {
                    "candidate_id": candidate.id,
                    "measurement_session_id": session_record.id,
                    "scalar_measurement_id": measurement.id,
                    "metric_code": measurement.metric_code,
                    "normalized_value": measurement.normalized_value,
                    "normalized_unit": measurement.normalized_unit,
                    "measurement_algorithm_id": measurement.measurement_algorithm_id,
                    "idempotent": True,
                }
            )
        return rows

    def _session_for_group(
        self,
        *,
        event: IngestEvent,
        artifact: RawArtifact,
        group_key: str,
        set_key: str,
        selected: Sequence[ImportCandidate],
        all_group: Sequence[ImportCandidate],
    ) -> MeasurementSession:
        source_record_id, semantic_key, source_fingerprint = _photo_source_identity(
            artifact.content_hash, group_key
        )
        precision, local_date, timestamp = _group_time(selected)
        confirmation_candidate = _representative(selected)
        existing = self.repos.measurement_sessions.find_by_source_identity(
            acquisition_source_id=event.acquisition_source_id,
            source_record_id=source_record_id,
            source_fingerprint=source_fingerprint,
            semantic_key=semantic_key,
            confirmation_candidate_id=confirmation_candidate.id,
        )
        if existing is None:
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
            )
        existing_candidate = (
            self.repos.import_candidates.get(existing.confirmation_candidate_id)
            if existing.confirmation_candidate_id is not None
            else None
        )
        if existing_candidate is not None and existing_candidate.candidate_set_key == set_key:
            return existing
        try:
            return self.repos.measurement_sessions.create_revision(
                existing.id,
                source_local_date=local_date,
                temporal_precision=precision,
                source_timestamp_utc=timestamp,
                confirmation_candidate_id=confirmation_candidate.id,
                ingest_event_id=event.id,
                raw_artifact_id=artifact.id,
                source_record_id=source_record_id,
                source_fingerprint=source_fingerprint,
                semantic_key=semantic_key,
            )
        except ValueError as exc:
            raise _decision_error(exc) from exc

    def _write_measurement(
        self,
        session_record: MeasurementSession,
        candidate: ImportCandidate,
        provider_code: str,
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
            raise PhotoImportError(
                "missing_value", f"candidate {candidate.id} has no value to confirm"
            )
        try:
            normalized_value, normalized_unit = normalize_confirmed_value(
                candidate.metric_code, value, unit
            )
        except ValueError as exc:
            raise PhotoImportError("unnormalizable_value", str(exc)) from exc
        algorithm = algorithm_for_metric(
            self.repos,
            metric_code=candidate.metric_code,
            provider_code=provider_code,
        )
        existing = self.repos.scalar_measurements.get_by_import_candidate(
            candidate.id, candidate.metric_code
        )
        if existing is not None:
            return existing
        previous = None
        if session_record.supersedes_session_id is not None:
            previous = next(
                (
                    measurement
                    for measurement in self.repos.scalar_measurements.list_for_session(
                        session_record.supersedes_session_id
                    )
                    if measurement.metric_code == candidate.metric_code
                ),
                None,
            )
        original_value = candidate.source_text or str(value)
        try:
            if previous is not None:
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
            raise _decision_error(exc) from exc

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
            diagnostic = f"{duplicate_items} duplicate artifact(s) reused"
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


def _photo_source_identity(content_hash: str, group_key: str) -> tuple[str, str, str]:
    source_record_id = f"photo:{content_hash}:{group_key}"
    fingerprint = hashlib.sha256(source_record_id.encode("utf-8")).hexdigest()
    return source_record_id, source_record_id, fingerprint


def _representative(candidates: Sequence[ImportCandidate]) -> ImportCandidate:
    by_code = {candidate.metric_code: candidate for candidate in candidates}
    if "weight" in by_code:
        return by_code["weight"]
    return sorted(candidates, key=lambda candidate: (candidate.metric_code, candidate.id))[0]


def _group_time(candidates: Sequence[ImportCandidate]) -> tuple[str, date, datetime | None]:
    precisions = {candidate.temporal_precision or "date" for candidate in candidates}
    precision = "date" if "date" in precisions or precisions == {None} else next(iter(precisions))
    local_dates = [
        candidate.edited_source_local_date or candidate.proposed_source_local_date
        for candidate in candidates
    ]
    local_dates = [value for value in local_dates if value is not None]
    if not local_dates:
        raise PhotoImportError(
            "missing_source_date", "confirmed photo evidence is missing a source date"
        )
    timestamp = None
    if precision != "date":
        timestamps = [
            candidate.edited_source_timestamp or candidate.proposed_source_timestamp
            for candidate in candidates
        ]
        timestamps = [value for value in timestamps if value is not None]
        if not timestamps:
            raise PhotoImportError(
                "missing_timestamp", "non-date photo evidence requires a timestamp"
            )
        timestamp = timestamps[0]
    return precision, local_dates[0], timestamp


def _edit_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    timestamp = result.get("source_timestamp", result.get("edited_source_timestamp"))
    if isinstance(timestamp, str):
        result["source_timestamp"] = datetime.fromisoformat(timestamp)
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
    if "terminal" in message or "revision" in message:
        return PhotoImportError("terminal_candidate", message, status_code=409)
    return PhotoImportError("invalid_confirmation", message)
