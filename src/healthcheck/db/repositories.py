"""Small transaction-friendly repositories for R01 provenance records.

Repositories flush but do not commit.  The caller owns the transaction through
``session_scope`` (or an explicitly managed SQLAlchemy ``Session``), which lets
photo confirmation, webhook ingestion and canonical selection compose several
repositories atomically.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path, PureWindowsPath
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    AcquisitionSource,
    CandidateDecision,
    CanonicalRuleSet,
    CanonicalSelection,
    CanonicalSelectionRun,
    CoverageInterval,
    DerivedMeasurement,
    ImportCandidate,
    ImportCandidateEdit,
    IngestBatch,
    IngestEvent,
    IngestStatus,
    MeasurementAlgorithm,
    MeasurementSession,
    PhysicalDevice,
    Provider,
    RawArtifact,
    RunStatus,
    ScalarMeasurement,
    SyncRun,
    SyncStreamState,
    TemporalPrecision,
    utc_now,
)


def canonical_json(value: Any) -> str:
    """Serialize a rule/configuration value deterministically."""

    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def hash_canonical_rule(rule: Any) -> str:
    """Hash the canonical JSON representation of a deterministic rule."""

    return hashlib.sha256(canonical_json(rule).encode("utf-8")).hexdigest()


def build_input_snapshot_hash(
    records: Mapping[str, str] | Iterable[tuple[str, str]],
) -> str:
    """Hash sorted evidence IDs and revision/content hashes.

    ``records`` maps a stable source/derived evidence ID to its revision or
    content hash.  Sorting before hashing makes the snapshot independent of
    transport/query order.
    """

    pairs = records.items() if isinstance(records, Mapping) else records
    normalized = sorted((str(entity_id), str(content_hash)) for entity_id, content_hash in pairs)
    payload = json.dumps(normalized, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_or_none(value: Any) -> str | None:
    return None if value is None else canonical_json(value)


def _uuid_text(value: str | UUID | None) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(str(value)))
    except ValueError as exc:
        raise ValueError(f"expected UUID value, got {value!r}") from exc


def _required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _as_utc(value: datetime | None) -> datetime | None:
    """Validate and normalize a timestamp that is persisted as a UTC instant."""

    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("UTC timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _validate_relative_storage_path(value: str | Path) -> str:
    raw = str(value).strip()
    if not raw:
        raise ValueError("relative_storage_path must not be empty")
    posix_path = Path(raw)
    windows_path = PureWindowsPath(raw)
    if posix_path.is_absolute() or windows_path.is_absolute() or raw.startswith(("/", "\\")):
        raise ValueError("raw artifact storage path must be repository-independent and relative")
    if ".." in posix_path.parts or ".." in windows_path.parts:
        raise ValueError("raw artifact storage path must not escape its artifact directory")
    return raw.replace("\\", "/")


def _validate_temporal_precision(
    precision: str | TemporalPrecision,
    source_local_date: date,
    source_timestamp_utc: datetime | None,
    source_local_timestamp: datetime | None,
) -> str:
    try:
        value = TemporalPrecision(str(precision))
    except ValueError as exc:
        raise ValueError("temporal precision must be instant, minute, or date") from exc
    if not isinstance(source_local_date, date):
        raise TypeError("source_local_date must be a date")
    if value is TemporalPrecision.DATE:
        if source_timestamp_utc is not None or source_local_timestamp is not None:
            raise ValueError("date-only evidence must not receive an invented timestamp")
        return value.value
    if source_timestamp_utc is None:
        raise ValueError(f"{value.value} evidence requires source_timestamp_utc")
    if source_timestamp_utc.tzinfo is None or source_timestamp_utc.utcoffset() is None:
        raise ValueError("source_timestamp_utc must be timezone-aware")
    if value is TemporalPrecision.MINUTE and (
        source_timestamp_utc.second != 0 or source_timestamp_utc.microsecond != 0
    ):
        raise ValueError("minute evidence must not contain seconds or microseconds")
    return value.value


class ProviderRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_code(self, code: str) -> Provider | None:
        return self.session.scalar(select(Provider).where(Provider.code == code))

    def get_or_create(self, code: str, display_name: str, provider_kind: str) -> Provider:
        code = _required_text(code, "provider code")
        existing = self.get_by_code(code)
        if existing is not None:
            return existing
        provider = Provider(
            code=code,
            display_name=_required_text(display_name, "provider display name"),
            provider_kind=_required_text(provider_kind, "provider kind"),
        )
        self.session.add(provider)
        self.session.flush()
        return provider


class PhysicalDeviceRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_code(self, code: str) -> PhysicalDevice | None:
        return self.session.scalar(select(PhysicalDevice).where(PhysicalDevice.code == code))

    def get_or_create(
        self,
        code: str,
        *,
        manufacturer: str | None = None,
        model: str | None = None,
        instance_identifier: str | None = None,
        display_name: str | None = None,
    ) -> PhysicalDevice:
        code = _required_text(code, "physical device code")
        existing = self.get_by_code(code)
        if existing is not None:
            return existing
        device = PhysicalDevice(
            code=code,
            manufacturer=manufacturer,
            model=model,
            instance_identifier=instance_identifier,
            display_name=display_name,
        )
        self.session.add(device)
        self.session.flush()
        return device


class AcquisitionSourceRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, source_id: str) -> AcquisitionSource | None:
        return self.session.get(AcquisitionSource, source_id)

    def get_by_sender_instance_id(self, source_instance_id: str | UUID) -> AcquisitionSource | None:
        normalized = _uuid_text(source_instance_id)
        return self.session.scalar(
            select(AcquisitionSource).where(AcquisitionSource.source_instance_id == normalized)
        )

    def get_or_create(
        self,
        *,
        provider_id: str,
        input_method: str,
        physical_device_id: str | None = None,
        source_instance_id: str | UUID | None = None,
        source_application: str | None = None,
        source_application_version: str | None = None,
        configuration_snapshot: Any = None,
        configuration_fingerprint: str | None = None,
    ) -> AcquisitionSource:
        allowed_methods = {"photo_import", "webhook", "provider_api", "manual_import"}
        if input_method not in allowed_methods:
            raise ValueError(f"unsupported acquisition input method: {input_method}")
        normalized_instance_id = _uuid_text(source_instance_id)
        existing = (
            self.get_by_sender_instance_id(normalized_instance_id)
            if normalized_instance_id is not None
            else self.session.scalar(
                select(AcquisitionSource).where(
                    AcquisitionSource.provider_id == provider_id,
                    AcquisitionSource.physical_device_id == physical_device_id,
                    AcquisitionSource.input_method == input_method,
                )
            )
        )
        if existing is not None:
            return existing
        source = AcquisitionSource(
            provider_id=provider_id,
            physical_device_id=physical_device_id,
            input_method=input_method,
            source_instance_id=normalized_instance_id,
            source_application=source_application,
            source_application_version=source_application_version,
            configuration_snapshot_json=_json_or_none(configuration_snapshot),
            configuration_fingerprint=configuration_fingerprint,
        )
        self.session.add(source)
        self.session.flush()
        return source


class MeasurementAlgorithmRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_code_version(self, code: str, version: str) -> MeasurementAlgorithm | None:
        return self.session.scalar(
            select(MeasurementAlgorithm).where(
                MeasurementAlgorithm.code == code,
                MeasurementAlgorithm.version == version,
            )
        )

    def get_or_create(
        self,
        *,
        code: str,
        version: str,
        metric_family: str,
        producer: str,
        compatibility_group: str,
        parameters: Any = None,
        verification_state: str = "unknown",
    ) -> MeasurementAlgorithm:
        existing = self.get_by_code_version(code, version)
        if existing is not None:
            return existing
        algorithm = MeasurementAlgorithm(
            code=_required_text(code, "algorithm code"),
            version=_required_text(version, "algorithm version"),
            metric_family=_required_text(metric_family, "algorithm metric family"),
            producer=_required_text(producer, "algorithm producer"),
            compatibility_group=_required_text(
                compatibility_group, "algorithm compatibility group"
            ),
            parameters_json=_json_or_none(parameters),
            verification_state=_required_text(verification_state, "algorithm verification state"),
        )
        self.session.add(algorithm)
        self.session.flush()
        return algorithm


class RawArtifactRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_content_hash(self, content_hash: str) -> RawArtifact | None:
        return self.session.scalar(
            select(RawArtifact).where(RawArtifact.content_hash == content_hash.lower())
        )

    def get_or_create(
        self,
        *,
        content_hash: str,
        kind: str,
        media_type: str,
        byte_size: int,
        relative_storage_path: str | Path,
        source_filename: str | None = None,
        source_timestamp: datetime | None = None,
    ) -> RawArtifact:
        normalized_hash = _required_text(content_hash, "content hash").lower()
        existing = self.get_by_content_hash(normalized_hash)
        if existing is not None:
            return existing
        if byte_size < 0:
            raise ValueError("raw artifact byte_size must be nonnegative")
        if source_filename is not None:
            filename_path = Path(source_filename)
            windows_filename_path = PureWindowsPath(source_filename)
            if filename_path.is_absolute() or windows_filename_path.is_absolute():
                raise ValueError("source_filename must be a filename, not an absolute machine path")
        artifact = RawArtifact(
            content_hash=normalized_hash,
            kind=_required_text(kind, "artifact kind"),
            media_type=_required_text(media_type, "artifact media type"),
            byte_size=byte_size,
            relative_storage_path=_validate_relative_storage_path(relative_storage_path),
            source_filename=source_filename,
            source_timestamp=_as_utc(source_timestamp),
        )
        self.session.add(artifact)
        self.session.flush()
        return artifact


class IngestBatchRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        acquisition_source_id: str,
        batch_kind: str,
        parser_name: str | None = None,
        parser_version: str | None = None,
        extractor_name: str | None = None,
        extractor_version: str | None = None,
        status: str = IngestStatus.RECEIVED.value,
    ) -> IngestBatch:
        batch = IngestBatch(
            acquisition_source_id=acquisition_source_id,
            batch_kind=_required_text(batch_kind, "batch kind"),
            parser_name=parser_name,
            parser_version=parser_version,
            extractor_name=extractor_name,
            extractor_version=extractor_version,
            status=status,
        )
        self.session.add(batch)
        self.session.flush()
        return batch


class IngestEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def find_existing(
        self,
        *,
        acquisition_source_id: str,
        external_user_id: str | None = None,
        provider_stream: str | None = None,
        external_record_id: str | None = None,
        semantic_fingerprint: str | None = None,
    ) -> IngestEvent | None:
        if external_record_id is not None:
            event = self.session.scalar(
                select(IngestEvent).where(
                    IngestEvent.acquisition_source_id == acquisition_source_id,
                    IngestEvent.external_user_id == external_user_id,
                    IngestEvent.provider_stream == provider_stream,
                    IngestEvent.external_record_id == external_record_id,
                )
            )
            if event is not None:
                return event
        if semantic_fingerprint is not None:
            return self.session.scalar(
                select(IngestEvent).where(
                    IngestEvent.acquisition_source_id == acquisition_source_id,
                    IngestEvent.semantic_fingerprint == semantic_fingerprint.lower(),
                )
            )
        return None

    def get_or_create(
        self,
        *,
        ingest_batch_id: str,
        acquisition_source_id: str,
        raw_artifact_id: str | None = None,
        external_user_id: str | None = None,
        provider_stream: str | None = None,
        external_record_id: str | None = None,
        semantic_fingerprint: str | None = None,
        event_type: str | None = None,
        source_timestamp: datetime | None = None,
        status: str = IngestStatus.RECEIVED.value,
        diagnostic_code: str | None = None,
        diagnostic_reason: str | None = None,
    ) -> IngestEvent:
        normalized_fingerprint = semantic_fingerprint.lower() if semantic_fingerprint else None
        existing = self.find_existing(
            acquisition_source_id=acquisition_source_id,
            external_user_id=external_user_id,
            provider_stream=provider_stream,
            external_record_id=external_record_id,
            semantic_fingerprint=normalized_fingerprint,
        )
        if existing is not None:
            return existing
        event = IngestEvent(
            ingest_batch_id=ingest_batch_id,
            acquisition_source_id=acquisition_source_id,
            raw_artifact_id=raw_artifact_id,
            external_user_id=external_user_id,
            provider_stream=provider_stream,
            external_record_id=external_record_id,
            semantic_fingerprint=normalized_fingerprint,
            event_type=event_type,
            source_timestamp=_as_utc(source_timestamp),
            status=status,
            diagnostic_code=diagnostic_code,
            diagnostic_reason=diagnostic_reason,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def set_status(
        self,
        event_id: str,
        status: str,
        *,
        diagnostic_code: str | None = None,
        diagnostic_reason: str | None = None,
    ) -> IngestEvent:
        event = self.session.get(IngestEvent, event_id)
        if event is None:
            raise KeyError(f"unknown ingest event {event_id}")
        event.status = status
        event.diagnostic_code = diagnostic_code
        event.diagnostic_reason = diagnostic_reason
        self.session.flush()
        return event


class ImportCandidateRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_pending(
        self,
        *,
        ingest_event_id: str,
        measurement_group_key: str,
        metric_code: str,
        candidate_set_key: str,
        proposed_value: float | None = None,
        proposed_unit: str | None = None,
        proposed_source_timestamp: datetime | None = None,
        proposed_source_local_date: date | None = None,
        temporal_precision: str | TemporalPrecision | None = None,
        source_text: str | None = None,
        extractor_name: str | None = None,
        extractor_version: str | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
        prompt_version: str | None = None,
        schema_version: str | None = None,
        confidence: float | None = None,
        evidence_region: Any = None,
    ) -> ImportCandidate:
        if confidence is not None and not 0 <= confidence <= 1:
            raise ValueError("candidate confidence must be between 0 and 1")
        normalized_precision = None if temporal_precision is None else str(temporal_precision)
        existing = self.session.scalar(
            select(ImportCandidate).where(
                ImportCandidate.ingest_event_id == ingest_event_id,
                ImportCandidate.candidate_set_key == candidate_set_key,
                ImportCandidate.measurement_group_key == measurement_group_key,
                ImportCandidate.metric_code == metric_code,
            )
        )
        if existing is not None:
            return existing
        candidate = ImportCandidate(
            ingest_event_id=ingest_event_id,
            candidate_set_key=_required_text(candidate_set_key, "candidate set key"),
            measurement_group_key=_required_text(measurement_group_key, "measurement group key"),
            metric_code=_required_text(metric_code, "metric code"),
            proposed_value=proposed_value,
            proposed_unit=proposed_unit,
            proposed_source_timestamp=_as_utc(proposed_source_timestamp),
            proposed_source_local_date=proposed_source_local_date,
            temporal_precision=normalized_precision,
            source_text=source_text,
            extractor_name=extractor_name,
            extractor_version=extractor_version,
            model_name=model_name,
            model_version=model_version,
            prompt_version=prompt_version,
            schema_version=schema_version,
            confidence=confidence,
            evidence_region_json=_json_or_none(evidence_region),
        )
        self.session.add(candidate)
        self.session.flush()
        return candidate

    def _record_edit(
        self, candidate: ImportCandidate, fields: Mapping[str, Any], actor: str
    ) -> None:
        latest_revision = self.session.scalar(
            select(func.max(ImportCandidateEdit.revision)).where(
                ImportCandidateEdit.candidate_id == candidate.id
            )
        )
        edit = ImportCandidateEdit(
            candidate_id=candidate.id,
            revision=(latest_revision or 0) + 1,
            edited_fields_json=canonical_json(fields),
            actor=actor,
        )
        self.session.add(edit)

    def decide(
        self,
        candidate_id: str,
        decision: str | CandidateDecision,
        *,
        edited_value: float | None = None,
        edited_unit: str | None = None,
        edited_source_timestamp: datetime | None = None,
        edited_source_local_date: date | None = None,
        decision_reason: str | None = None,
        actor: str = "owner",
    ) -> ImportCandidate:
        candidate = self.session.get(ImportCandidate, candidate_id)
        if candidate is None:
            raise KeyError(f"unknown import candidate {candidate_id}")
        try:
            normalized_decision = CandidateDecision(str(decision)).value
        except ValueError as exc:
            raise ValueError("candidate decision must be pending, confirmed, or rejected") from exc
        changed_fields: dict[str, Any] = {"user_decision": normalized_decision}
        if edited_value is not None:
            candidate.edited_value = edited_value
            changed_fields["edited_value"] = edited_value
        if edited_unit is not None:
            candidate.edited_unit = edited_unit
            changed_fields["edited_unit"] = edited_unit
        if edited_source_timestamp is not None:
            candidate.edited_source_timestamp = _as_utc(edited_source_timestamp)
            changed_fields["edited_source_timestamp"] = edited_source_timestamp.isoformat()
        if edited_source_local_date is not None:
            candidate.edited_source_local_date = edited_source_local_date
            changed_fields["edited_source_local_date"] = edited_source_local_date.isoformat()
        candidate.user_decision = normalized_decision
        candidate.decision_reason = decision_reason
        candidate.decision_at = utc_now()
        self._record_edit(candidate, changed_fields, actor)
        self.session.flush()
        return candidate


class MeasurementSessionRepository:
    def __init__(self, session: Session):
        self.session = session

    def find_by_source_identity(
        self,
        *,
        acquisition_source_id: str,
        source_record_id: str | None = None,
        source_fingerprint: str | None = None,
        semantic_key: str | None = None,
        confirmation_candidate_id: str | None = None,
    ) -> MeasurementSession | None:
        conditions = [MeasurementSession.acquisition_source_id == acquisition_source_id]
        if confirmation_candidate_id is not None:
            conditions.append(
                MeasurementSession.confirmation_candidate_id == confirmation_candidate_id
            )
        elif source_record_id is not None:
            conditions.append(MeasurementSession.source_record_id == source_record_id)
        elif source_fingerprint is not None:
            conditions.append(MeasurementSession.source_fingerprint == source_fingerprint.lower())
        elif semantic_key is not None:
            conditions.append(MeasurementSession.semantic_key == semantic_key)
        else:
            return None
        return self.session.scalar(
            select(MeasurementSession)
            .where(*conditions)
            .order_by(MeasurementSession.revision_number.desc())
        )

    def create_confirmed(
        self,
        *,
        acquisition_source_id: str,
        source_local_date: date,
        temporal_precision: str | TemporalPrecision,
        source_timestamp_utc: datetime | None = None,
        source_local_timestamp: datetime | None = None,
        source_utc_offset_minutes: int | None = None,
        source_timezone: str | None = None,
        ingest_event_id: str | None = None,
        raw_artifact_id: str | None = None,
        confirmation_candidate_id: str | None = None,
        source_record_id: str | None = None,
        source_fingerprint: str | None = None,
        semantic_key: str | None = None,
        revision_number: int | None = None,
        supersedes_session_id: str | None = None,
        idempotent: bool = True,
    ) -> MeasurementSession:
        normalized_precision = _validate_temporal_precision(
            temporal_precision,
            source_local_date,
            source_timestamp_utc,
            source_local_timestamp,
        )
        normalized_source_timestamp = _as_utc(source_timestamp_utc)
        normalized_fingerprint = source_fingerprint.lower() if source_fingerprint else None
        if idempotent and supersedes_session_id is None:
            existing = self.find_by_source_identity(
                acquisition_source_id=acquisition_source_id,
                source_record_id=source_record_id,
                source_fingerprint=normalized_fingerprint,
                semantic_key=semantic_key,
                confirmation_candidate_id=confirmation_candidate_id,
            )
            if existing is not None:
                return existing
        if revision_number is None:
            if supersedes_session_id is not None:
                previous = self.session.get(MeasurementSession, supersedes_session_id)
                if previous is None:
                    raise KeyError(f"unknown superseded session {supersedes_session_id}")
                latest_revision = self.session.scalar(
                    select(func.max(MeasurementSession.revision_number)).where(
                        MeasurementSession.acquisition_source_id == previous.acquisition_source_id,
                        MeasurementSession.semantic_key == previous.semantic_key,
                    )
                )
                revision_number = (latest_revision or previous.revision_number) + 1
            else:
                revision_number = 1
        session = MeasurementSession(
            acquisition_source_id=acquisition_source_id,
            ingest_event_id=ingest_event_id,
            raw_artifact_id=raw_artifact_id,
            confirmation_candidate_id=confirmation_candidate_id,
            semantic_key=semantic_key or source_record_id or normalized_fingerprint,
            source_record_id=source_record_id,
            source_fingerprint=normalized_fingerprint,
            temporal_precision=normalized_precision,
            source_local_date=source_local_date,
            source_timestamp_utc=normalized_source_timestamp,
            source_local_timestamp=source_local_timestamp,
            source_utc_offset_minutes=source_utc_offset_minutes,
            source_timezone=source_timezone,
            confirmation_status="confirmed",
            import_status=IngestStatus.COMMITTED.value,
            revision_number=revision_number,
            supersedes_session_id=supersedes_session_id,
            confirmed_at=utc_now(),
        )
        self.session.add(session)
        self.session.flush()
        return session

    def create_revision(
        self,
        previous_session_id: str,
        *,
        source_local_date: date,
        temporal_precision: str | TemporalPrecision,
        source_timestamp_utc: datetime | None = None,
        source_local_timestamp: datetime | None = None,
        source_utc_offset_minutes: int | None = None,
        source_timezone: str | None = None,
        confirmation_candidate_id: str | None = None,
    ) -> MeasurementSession:
        previous = self.session.get(MeasurementSession, previous_session_id)
        if previous is None:
            raise KeyError(f"unknown measurement session {previous_session_id}")
        return self.create_confirmed(
            acquisition_source_id=previous.acquisition_source_id,
            source_local_date=source_local_date,
            temporal_precision=temporal_precision,
            source_timestamp_utc=source_timestamp_utc,
            source_local_timestamp=source_local_timestamp,
            source_utc_offset_minutes=source_utc_offset_minutes,
            source_timezone=source_timezone,
            ingest_event_id=previous.ingest_event_id,
            raw_artifact_id=previous.raw_artifact_id,
            confirmation_candidate_id=confirmation_candidate_id,
            source_record_id=previous.source_record_id,
            source_fingerprint=previous.source_fingerprint,
            semantic_key=previous.semantic_key,
            supersedes_session_id=previous.id,
            idempotent=False,
        )


class ScalarMeasurementRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        measurement_session_id: str,
        metric_code: str,
        normalized_value: float,
        normalized_unit: str,
        measurement_algorithm_id: str,
        import_candidate_id: str | None = None,
        original_value: str | None = None,
        original_unit: str | None = None,
        quality_status: str | None = None,
        source_text: str | None = None,
        supersedes_measurement_id: str | None = None,
        idempotent: bool = True,
    ) -> ScalarMeasurement:
        if import_candidate_id is not None and idempotent and supersedes_measurement_id is None:
            existing = self.session.scalar(
                select(ScalarMeasurement).where(
                    ScalarMeasurement.import_candidate_id == import_candidate_id,
                    ScalarMeasurement.metric_code == metric_code,
                )
            )
            if existing is not None:
                return existing
        measurement = ScalarMeasurement(
            measurement_session_id=measurement_session_id,
            import_candidate_id=import_candidate_id,
            metric_code=_required_text(metric_code, "metric code"),
            normalized_value=normalized_value,
            normalized_unit=_required_text(normalized_unit, "normalized unit"),
            original_value=original_value,
            original_unit=original_unit,
            measurement_algorithm_id=measurement_algorithm_id,
            quality_status=quality_status,
            source_text=source_text,
            supersedes_measurement_id=supersedes_measurement_id,
        )
        self.session.add(measurement)
        self.session.flush()
        return measurement

    def create_revision(
        self,
        previous_measurement_id: str,
        *,
        measurement_session_id: str,
        normalized_value: float,
        normalized_unit: str,
        measurement_algorithm_id: str,
        original_value: str | None = None,
        original_unit: str | None = None,
        quality_status: str | None = None,
        source_text: str | None = None,
    ) -> ScalarMeasurement:
        previous = self.session.get(ScalarMeasurement, previous_measurement_id)
        if previous is None:
            raise KeyError(f"unknown scalar measurement {previous_measurement_id}")
        return self.create(
            measurement_session_id=measurement_session_id,
            metric_code=previous.metric_code,
            normalized_value=normalized_value,
            normalized_unit=normalized_unit,
            measurement_algorithm_id=measurement_algorithm_id,
            original_value=original_value,
            original_unit=original_unit,
            quality_status=quality_status,
            source_text=source_text,
            supersedes_measurement_id=previous.id,
            idempotent=False,
        )

    def active_for_metric(self, metric_code: str) -> list[ScalarMeasurement]:
        superseded_ids = select(ScalarMeasurement.supersedes_measurement_id).where(
            ScalarMeasurement.supersedes_measurement_id.is_not(None)
        )
        statement = (
            select(ScalarMeasurement)
            .where(
                ScalarMeasurement.metric_code == metric_code,
                ~ScalarMeasurement.id.in_(superseded_ids),
            )
            .order_by(ScalarMeasurement.created_at, ScalarMeasurement.id)
        )
        return list(self.session.scalars(statement))


class DerivedMeasurementRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        metric_code: str,
        normalized_value: float,
        normalized_unit: str,
        algorithm_code: str,
        algorithm_version: str,
        parameters: Any = None,
        input_measurement_ids: Sequence[str] | None = None,
        input_set_hash: str | None = None,
        source_session_id: str | None = None,
    ) -> DerivedMeasurement:
        normalized_ids = None
        if input_measurement_ids is not None:
            normalized_ids = sorted(str(value) for value in input_measurement_ids)
            if input_set_hash is None:
                input_set_hash = build_input_snapshot_hash(
                    (value, value) for value in normalized_ids
                )
        if normalized_ids is None and input_set_hash is None:
            raise ValueError("a derived measurement needs input IDs or an input-set hash")
        derived = DerivedMeasurement(
            metric_code=_required_text(metric_code, "metric code"),
            normalized_value=normalized_value,
            normalized_unit=_required_text(normalized_unit, "normalized unit"),
            algorithm_code=_required_text(algorithm_code, "derived algorithm code"),
            algorithm_version=_required_text(algorithm_version, "derived algorithm version"),
            parameters_json=_json_or_none(parameters),
            input_measurement_ids_json=(
                None
                if normalized_ids is None
                else json.dumps(normalized_ids, separators=(",", ":"))
            ),
            input_set_hash=input_set_hash,
            source_session_id=source_session_id,
        )
        self.session.add(derived)
        self.session.flush()
        return derived


class CanonicalRuleSetRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, rule_name: str, rule_version: int) -> CanonicalRuleSet | None:
        return self.session.scalar(
            select(CanonicalRuleSet).where(
                CanonicalRuleSet.rule_name == rule_name,
                CanonicalRuleSet.rule_version == rule_version,
            )
        )

    def get_or_create(
        self,
        *,
        rule_name: str,
        rule_version: int,
        rule_definition: Any,
        creation_reason: str,
        effective_start_date: date | None = None,
        effective_end_date: date | None = None,
    ) -> CanonicalRuleSet:
        serialized = canonical_json(rule_definition)
        rule_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        existing = self.get(rule_name, rule_version)
        if existing is not None:
            if existing.rule_hash != rule_hash:
                raise ValueError("canonical rule name/version already has a different definition")
            return existing
        rule_set = CanonicalRuleSet(
            rule_name=_required_text(rule_name, "rule name"),
            rule_version=rule_version,
            effective_start_date=effective_start_date,
            effective_end_date=effective_end_date,
            rule_definition_json=serialized,
            rule_hash=rule_hash,
            creation_reason=_required_text(creation_reason, "rule creation reason"),
        )
        self.session.add(rule_set)
        self.session.flush()
        return rule_set


class CanonicalSelectionRunRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_successful(
        self, *, scope_key: str, rule_hash: str, input_snapshot_hash: str
    ) -> CanonicalSelectionRun | None:
        return self.session.scalar(
            select(CanonicalSelectionRun).where(
                CanonicalSelectionRun.scope_key == scope_key,
                CanonicalSelectionRun.rule_hash == rule_hash,
                CanonicalSelectionRun.input_snapshot_hash == input_snapshot_hash,
                CanonicalSelectionRun.status == RunStatus.SUCCEEDED.value,
            )
        )

    def start_or_get(
        self,
        *,
        scope_key: str,
        rule_set: CanonicalRuleSet,
        input_snapshot_hash: str,
        requested_start_date: date | None = None,
        requested_end_date: date | None = None,
        scope: Any = None,
        software_version: str | None = None,
        build_version: str | None = None,
        supersedes_run_id: str | None = None,
    ) -> tuple[CanonicalSelectionRun, bool]:
        if rule_set.rule_hash is None:
            raise ValueError("canonical rule must have a hash")
        existing = self.get_successful(
            scope_key=scope_key,
            rule_hash=rule_set.rule_hash,
            input_snapshot_hash=input_snapshot_hash,
        )
        if existing is not None:
            return existing, False
        running = self.session.scalar(
            select(CanonicalSelectionRun).where(
                CanonicalSelectionRun.scope_key == scope_key,
                CanonicalSelectionRun.rule_hash == rule_set.rule_hash,
                CanonicalSelectionRun.input_snapshot_hash == input_snapshot_hash,
                CanonicalSelectionRun.status == RunStatus.RUNNING.value,
            )
        )
        if running is not None:
            return running, False
        run = CanonicalSelectionRun(
            scope_key=_required_text(scope_key, "canonical scope key"),
            requested_start_date=requested_start_date,
            requested_end_date=requested_end_date,
            rule_set_id=rule_set.id,
            rule_name=rule_set.rule_name,
            rule_version=rule_set.rule_version,
            rule_hash=rule_set.rule_hash,
            input_snapshot_hash=_required_text(input_snapshot_hash, "input snapshot hash"),
            scope_json=_json_or_none(scope),
            software_version=software_version,
            build_version=build_version,
            supersedes_run_id=supersedes_run_id,
        )
        self.session.add(run)
        self.session.flush()
        return run, True

    def finish(
        self,
        run_id: str,
        *,
        status: str | RunStatus,
        selection_count: int | None = None,
        failure_reason: str | None = None,
    ) -> CanonicalSelectionRun:
        run = self.session.get(CanonicalSelectionRun, run_id)
        if run is None:
            raise KeyError(f"unknown canonical selection run {run_id}")
        try:
            normalized_status = RunStatus(str(status)).value
        except ValueError as exc:
            raise ValueError("canonical run status must be running, succeeded, or failed") from exc
        if selection_count is not None and selection_count < 0:
            raise ValueError("selection_count must be nonnegative")
        if run.status != RunStatus.RUNNING.value and run.status != normalized_status:
            raise ValueError("a terminal canonical run cannot change status")
        run.status = normalized_status
        run.selection_count = selection_count
        run.failure_reason = failure_reason
        run.completed_at = utc_now() if normalized_status != RunStatus.RUNNING.value else None
        self.session.flush()
        return run


class CanonicalSelectionRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_key(self, selection_run_id: str, semantic_key: str) -> CanonicalSelection | None:
        return self.session.scalar(
            select(CanonicalSelection).where(
                CanonicalSelection.selection_run_id == selection_run_id,
                CanonicalSelection.semantic_key == semantic_key,
            )
        )

    def add(
        self,
        *,
        selection_run_id: str,
        metric_code: str,
        semantic_key: str,
        selection_reason: str,
        source_measurement_id: str | None = None,
        derived_measurement_id: str | None = None,
        period_start_date: date | None = None,
        period_end_date: date | None = None,
    ) -> CanonicalSelection:
        if (source_measurement_id is None) == (derived_measurement_id is None):
            raise ValueError(
                "canonical selection must reference exactly one source or derived measurement"
            )
        run = self.session.get(CanonicalSelectionRun, selection_run_id)
        if run is None:
            raise KeyError(f"unknown canonical selection run {selection_run_id}")
        if run.status != RunStatus.RUNNING.value:
            raise ValueError("only running canonical runs can receive selections")
        if source_measurement_id is not None:
            source_measurement = self.session.get(ScalarMeasurement, source_measurement_id)
            if source_measurement is None:
                raise KeyError(f"unknown source measurement {source_measurement_id}")
            if source_measurement.metric_code != metric_code:
                raise ValueError("canonical metric does not match source measurement metric")
            if source_measurement.measurement_session_id is not None:
                source_session = self.session.get(
                    MeasurementSession, source_measurement.measurement_session_id
                )
                if source_session is None or source_session.confirmation_status != "confirmed":
                    raise ValueError("only confirmed source measurements are canonical-eligible")
            superseded = self.session.scalar(
                select(ScalarMeasurement.id).where(
                    ScalarMeasurement.supersedes_measurement_id == source_measurement_id
                )
            )
            if superseded is not None:
                raise ValueError("superseded source measurements are not canonical-eligible")
        else:
            derived_measurement = self.session.get(DerivedMeasurement, derived_measurement_id)
            if derived_measurement is None:
                raise KeyError(f"unknown derived measurement {derived_measurement_id}")
            if derived_measurement.metric_code != metric_code:
                raise ValueError("canonical metric does not match derived measurement metric")
        normalized_key = _required_text(semantic_key, "canonical semantic key")
        existing = self.get_by_key(selection_run_id, normalized_key)
        if existing is not None:
            if (
                existing.metric_code == metric_code
                and existing.source_measurement_id == source_measurement_id
                and existing.derived_measurement_id == derived_measurement_id
            ):
                return existing
            raise ValueError("canonical semantic key already points to different evidence")
        selection = CanonicalSelection(
            selection_run_id=selection_run_id,
            metric_code=_required_text(metric_code, "canonical metric code"),
            semantic_key=normalized_key,
            period_start_date=period_start_date,
            period_end_date=period_end_date,
            source_measurement_id=source_measurement_id,
            derived_measurement_id=derived_measurement_id,
            selection_reason=_required_text(selection_reason, "canonical selection reason"),
        )
        self.session.add(selection)
        self.session.flush()
        return selection

    def for_run(self, selection_run_id: str) -> list[CanonicalSelection]:
        statement = select(CanonicalSelection).where(
            CanonicalSelection.selection_run_id == selection_run_id
        )
        return list(self.session.scalars(statement.order_by(CanonicalSelection.semantic_key)))


class SyncRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_run(
        self,
        *,
        provider_id: str,
        stream_code: str,
        acquisition_source_id: str | None = None,
        requested_start: datetime | None = None,
        requested_end: datetime | None = None,
    ) -> SyncRun:
        run = SyncRun(
            provider_id=provider_id,
            acquisition_source_id=acquisition_source_id,
            stream_code=_required_text(stream_code, "sync stream code"),
            requested_start=_as_utc(requested_start),
            requested_end=_as_utc(requested_end),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        item_count: int | None = None,
        received_count: int | None = None,
        accepted_count: int | None = None,
        failed_count: int | None = None,
        error_category: str | None = None,
        diagnostic_reason: str | None = None,
        actual_start: datetime | None = None,
        actual_end: datetime | None = None,
    ) -> SyncRun:
        if status not in {"running", "succeeded", "partial", "failed"}:
            raise ValueError("sync run status must be running, succeeded, partial, or failed")
        if item_count is not None and item_count < 0:
            raise ValueError("sync item_count must be nonnegative")
        for value, name in (
            (received_count, "received_count"),
            (accepted_count, "accepted_count"),
            (failed_count, "failed_count"),
        ):
            if value is not None and value < 0:
                raise ValueError(f"sync {name} must be nonnegative")
        run = self.session.get(SyncRun, run_id)
        if run is None:
            raise KeyError(f"unknown sync run {run_id}")
        run.status = status
        run.item_count = item_count
        run.received_count = received_count
        run.accepted_count = accepted_count
        run.failed_count = failed_count
        run.error_category = error_category
        run.diagnostic_reason = diagnostic_reason
        run.actual_start = _as_utc(actual_start)
        run.actual_end = _as_utc(actual_end)
        run.completed_at = utc_now() if status != "running" else None
        self.session.flush()
        return run

    def get_or_create_state(
        self,
        *,
        provider_id: str,
        stream_code: str,
        acquisition_source_id: str | None = None,
        cursor: str | None = None,
        watermark: datetime | None = None,
        trailing_window_days: int | None = None,
        diagnostic_status: str | None = None,
        last_success_at: datetime | None = None,
        last_attempt_at: datetime | None = None,
    ) -> SyncStreamState:
        state = self.session.scalar(
            select(SyncStreamState).where(
                SyncStreamState.provider_id == provider_id,
                SyncStreamState.acquisition_source_id == acquisition_source_id,
                SyncStreamState.stream_code == stream_code,
            )
        )
        if state is not None:
            if cursor is not None:
                state.cursor = cursor
            if watermark is not None:
                state.watermark = _as_utc(watermark)
            if trailing_window_days is not None:
                if trailing_window_days < 0:
                    raise ValueError("trailing_window_days must be nonnegative")
                state.trailing_window_days = trailing_window_days
            if diagnostic_status is not None:
                state.diagnostic_status = diagnostic_status
            if last_success_at is not None:
                state.last_success_at = _as_utc(last_success_at)
            if last_attempt_at is not None:
                state.last_attempt_at = _as_utc(last_attempt_at)
            state.updated_at = utc_now()
            self.session.flush()
            return state
        if trailing_window_days is not None and trailing_window_days < 0:
            raise ValueError("trailing_window_days must be nonnegative")
        state = SyncStreamState(
            provider_id=provider_id,
            acquisition_source_id=acquisition_source_id,
            stream_code=_required_text(stream_code, "sync stream code"),
            cursor=cursor,
            watermark=_as_utc(watermark),
            last_success_at=_as_utc(last_success_at),
            last_attempt_at=_as_utc(last_attempt_at),
            trailing_window_days=trailing_window_days,
            diagnostic_status=diagnostic_status,
        )
        self.session.add(state)
        self.session.flush()
        return state


class CoverageRepository:
    def __init__(self, session: Session):
        self.session = session

    def record(
        self,
        *,
        provider_id: str,
        stream_code: str,
        metric_code: str,
        interval_start: datetime,
        interval_end: datetime,
        resolution: str,
        status: str,
        calculation_rule_version: str,
        acquisition_source_id: str | None = None,
        observed_count: int | None = None,
        expected_count: int | None = None,
        diagnostic_reason: str | None = None,
    ) -> CoverageInterval:
        if status not in {"present", "confirmed_empty", "unavailable", "failed", "unknown"}:
            raise ValueError(
                "coverage status must be present, confirmed_empty, unavailable, failed, or unknown"
            )
        if interval_end <= interval_start:
            raise ValueError("coverage interval_end must be after interval_start")
        if observed_count is not None and observed_count < 0:
            raise ValueError("observed_count must be nonnegative")
        if expected_count is not None and expected_count < 0:
            raise ValueError("expected_count must be nonnegative")
        interval = CoverageInterval(
            provider_id=provider_id,
            acquisition_source_id=acquisition_source_id,
            stream_code=_required_text(stream_code, "coverage stream code"),
            metric_code=_required_text(metric_code, "coverage metric code"),
            interval_start=_as_utc(interval_start),
            interval_end=_as_utc(interval_end),
            resolution=_required_text(resolution, "coverage resolution"),
            status=status,
            observed_count=observed_count,
            expected_count=expected_count,
            calculation_rule_version=_required_text(
                calculation_rule_version, "coverage calculation rule version"
            ),
            diagnostic_reason=diagnostic_reason,
        )
        self.session.add(interval)
        self.session.flush()
        return interval


class ProvenanceRepositories:
    """Convenience bundle sharing one transaction-owned session."""

    def __init__(self, session: Session):
        self.providers = ProviderRepository(session)
        self.physical_devices = PhysicalDeviceRepository(session)
        self.acquisition_sources = AcquisitionSourceRepository(session)
        self.measurement_algorithms = MeasurementAlgorithmRepository(session)
        self.raw_artifacts = RawArtifactRepository(session)
        self.ingest_batches = IngestBatchRepository(session)
        self.ingest_events = IngestEventRepository(session)
        self.import_candidates = ImportCandidateRepository(session)
        self.measurement_sessions = MeasurementSessionRepository(session)
        self.scalar_measurements = ScalarMeasurementRepository(session)
        self.derived_measurements = DerivedMeasurementRepository(session)
        self.canonical_rule_sets = CanonicalRuleSetRepository(session)
        self.canonical_selection_runs = CanonicalSelectionRunRepository(session)
        self.canonical_selections = CanonicalSelectionRepository(session)
        self.sync = SyncRepository(session)
        self.sync_runs = self.sync
        self.sync_stream_state = self.sync
        self.coverage = CoverageRepository(session)


def repositories_for(session: Session) -> ProvenanceRepositories:
    """Build all R01 repositories on an existing SQLAlchemy session."""

    return ProvenanceRepositories(session)


# Explicit aliases keep the public surface discoverable for services that want
# one repository per table while the sync state/run operations remain grouped.
SyncRunRepository = SyncRepository
SyncStreamStateRepository = SyncRepository
CoverageIntervalRepository = CoverageRepository


__all__ = [
    "AcquisitionSourceRepository",
    "CanonicalSelectionRepository",
    "CanonicalSelectionRunRepository",
    "CanonicalRuleSetRepository",
    "CoverageRepository",
    "CoverageIntervalRepository",
    "DerivedMeasurementRepository",
    "ImportCandidateRepository",
    "IngestBatchRepository",
    "IngestEventRepository",
    "MeasurementAlgorithmRepository",
    "MeasurementSessionRepository",
    "PhysicalDeviceRepository",
    "ProviderRepository",
    "ProvenanceRepositories",
    "RawArtifactRepository",
    "ScalarMeasurementRepository",
    "SyncRepository",
    "SyncRunRepository",
    "SyncStreamStateRepository",
    "build_input_snapshot_hash",
    "canonical_json",
    "hash_canonical_rule",
    "repositories_for",
]
