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

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    AcquisitionSource,
    AgreementCoverage,
    AgreementMetricResult,
    AgreementRuleSet,
    AgreementRun,
    AgreementRunExclusion,
    AgreementRunPair,
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
    new_id,
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
    by_entity: dict[str, str] = {}
    for entity_id, content_hash in pairs:
        normalized_id = str(entity_id)
        normalized_hash = str(content_hash)
        previous_hash = by_entity.get(normalized_id)
        if previous_hash is not None and previous_hash != normalized_hash:
            raise ValueError(
                "an input snapshot cannot assign multiple content hashes to one evidence ID"
            )
        by_entity[normalized_id] = normalized_hash
    normalized = sorted(by_entity.items())
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


def _date_or_none(value: date | str | None, field_name: str) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _as_utc(value: datetime | None) -> datetime | None:
    """Validate and normalize a timestamp that is persisted as a UTC instant."""

    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("UTC timestamps must be timezone-aware")
    return value.astimezone(UTC)


def restore_stored_utc(value: datetime | None) -> datetime | None:
    """Return aware UTC, treating naive SQLite-reloaded values as UTC."""

    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _datetime_key(value: datetime | None) -> datetime | None:
    """Compare SQLite-reloaded UTC timestamps without losing exactness."""

    if value is None:
        return None
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    # SQLite's built-in DateTime loader returns naive values even when the
    # mapped column advertises timezone=True.  Persisted UTC values are still
    # unambiguous, so treat a reloaded naive value as UTC for comparisons.
    return value


def _same_datetime(left: datetime | None, right: datetime | None) -> bool:
    return _datetime_key(left) == _datetime_key(right)


def _ingest_deduplication_key(
    *,
    acquisition_source_id: str,
    external_user_id: str | None,
    external_record_id: str | None,
    event_type: str | None,
    semantic_fingerprint: str | None,
    raw_artifact_id: str | None,
    source_timestamp: datetime | None,
) -> str | None:
    """Build a stable retry key without making logical source IDs unique.

    ``provider_stream`` is deliberately absent: it is transport metadata, not
    the openScale logical identity.  Event type and evidence fingerprint are
    included so an ``update`` or reprocessed payload can coexist with the
    original insert while its exact retry still converges.
    """

    if (
        external_user_id is None
        and external_record_id is None
        and semantic_fingerprint is None
        and raw_artifact_id is None
        and source_timestamp is None
    ):
        # Without any stable source identity or evidence there is no honest
        # basis for deduplicating two transport events.
        return None
    evidence = semantic_fingerprint
    if evidence is None:
        evidence = canonical_json(
            {
                "raw_artifact_id": raw_artifact_id,
                "source_timestamp": (
                    _as_utc(source_timestamp).isoformat() if source_timestamp is not None else None
                ),
            }
        )
    payload = {
        "acquisition_source_id": acquisition_source_id,
        "external_user_id": external_user_id,
        "external_record_id": external_record_id,
        "event_type": event_type,
        "evidence": evidence.lower() if isinstance(evidence, str) else evidence,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


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
        # Naive sender wall clocks preserve local minute evidence without an
        # invented UTC instant (accepted #19 / openScale contract semantics).
        if value is TemporalPrecision.MINUTE and source_local_timestamp is not None:
            return value.value
        raise ValueError(f"{value.value} evidence requires source_timestamp_utc")
    if source_timestamp_utc.tzinfo is None or source_timestamp_utc.utcoffset() is None:
        raise ValueError("source_timestamp_utc must be timezone-aware")
    if value is TemporalPrecision.MINUTE and (
        source_timestamp_utc.second != 0 or source_timestamp_utc.microsecond != 0
    ):
        raise ValueError("minute evidence must not contain seconds or microseconds")
    return value.value


def _effective_semantic_key(
    semantic_key: str | None,
    source_record_id: str | None,
    source_fingerprint: str | None,
) -> str | None:
    return semantic_key or source_record_id or source_fingerprint


def _session_matches_evidence(
    existing: MeasurementSession,
    *,
    acquisition_source_id: str,
    ingest_event_id: str | None,
    raw_artifact_id: str | None,
    confirmation_candidate_id: str | None,
    semantic_key: str | None,
    source_record_id: str | None,
    source_fingerprint: str | None,
    temporal_precision: str,
    source_local_date: date,
    source_timestamp_utc: datetime | None,
    source_local_timestamp: datetime | None,
    source_utc_offset_minutes: int | None,
    source_timezone: str | None,
) -> bool:
    """Return whether an incoming session is an exact evidence replay."""

    return (
        existing.acquisition_source_id == acquisition_source_id
        and existing.ingest_event_id == ingest_event_id
        and existing.raw_artifact_id == raw_artifact_id
        and existing.confirmation_candidate_id == confirmation_candidate_id
        and existing.semantic_key == semantic_key
        and existing.source_record_id == source_record_id
        and existing.source_fingerprint == source_fingerprint
        and existing.temporal_precision == temporal_precision
        and existing.source_local_date == source_local_date
        and _same_datetime(existing.source_timestamp_utc, source_timestamp_utc)
        and _same_datetime(existing.source_local_timestamp, source_local_timestamp)
        and existing.source_utc_offset_minutes == source_utc_offset_minutes
        and existing.source_timezone == source_timezone
    )


def _scalar_matches_evidence(
    existing: ScalarMeasurement,
    *,
    measurement_session_id: str,
    import_candidate_id: str | None,
    metric_code: str,
    normalized_value: float,
    normalized_unit: str,
    measurement_algorithm_id: str,
    original_value: str | None,
    original_unit: str | None,
    quality_status: str | None,
    source_text: str | None,
    supersedes_measurement_id: str | None,
) -> bool:
    return (
        existing.measurement_session_id == measurement_session_id
        and existing.import_candidate_id == import_candidate_id
        and existing.metric_code == metric_code
        and existing.normalized_value == normalized_value
        and existing.normalized_unit == normalized_unit
        and existing.measurement_algorithm_id == measurement_algorithm_id
        and existing.original_value == original_value
        and existing.original_unit == original_unit
        and existing.quality_status == quality_status
        and existing.source_text == source_text
        and existing.supersedes_measurement_id == supersedes_measurement_id
    )


class ProviderRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, provider_id: str) -> Provider | None:
        return self.session.get(Provider, provider_id)

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

    def get(self, device_id: str) -> PhysicalDevice | None:
        return self.session.get(PhysicalDevice, device_id)

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

    def get(self, algorithm_id: str) -> MeasurementAlgorithm | None:
        return self.session.get(MeasurementAlgorithm, algorithm_id)

    def get_by_id(self, algorithm_id: str) -> MeasurementAlgorithm | None:
        return self.get(algorithm_id)

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
        normalized_code = _required_text(code, "algorithm code")
        normalized_version = _required_text(version, "algorithm version")
        normalized_metric_family = _required_text(metric_family, "algorithm metric family")
        normalized_producer = _required_text(producer, "algorithm producer")
        normalized_compatibility_group = _required_text(
            compatibility_group, "algorithm compatibility group"
        )
        normalized_parameters = _json_or_none(parameters)
        existing = self.get_by_code_version(normalized_code, normalized_version)
        if existing is not None:
            immutable_metadata = {
                "metric_family": normalized_metric_family,
                "producer": normalized_producer,
                "compatibility_group": normalized_compatibility_group,
                "parameters_json": normalized_parameters,
            }
            existing_metadata = {
                field_name: getattr(existing, field_name) for field_name in immutable_metadata
            }
            if existing_metadata != immutable_metadata:
                raise ValueError(
                    "measurement algorithm immutable metadata conflicts with existing "
                    f"{normalized_code}@{normalized_version}"
                )
            return existing
        algorithm = MeasurementAlgorithm(
            code=normalized_code,
            version=normalized_version,
            metric_family=normalized_metric_family,
            producer=normalized_producer,
            compatibility_group=normalized_compatibility_group,
            parameters_json=normalized_parameters,
            verification_state=_required_text(verification_state, "algorithm verification state"),
        )
        self.session.add(algorithm)
        self.session.flush()
        return algorithm


class RawArtifactRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, artifact_id: str) -> RawArtifact | None:
        return self.session.get(RawArtifact, artifact_id)

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

    def get(self, batch_id: str) -> IngestBatch | None:
        return self.session.get(IngestBatch, batch_id)

    def list_recent(self, *, limit: int = 100) -> list[IngestBatch]:
        statement = select(IngestBatch).order_by(
            IngestBatch.started_at.desc(), IngestBatch.id.desc()
        )
        if limit is not None:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def update(
        self,
        batch_id: str,
        *,
        status: str | None = None,
        received_count: int | None = None,
        parsed_count: int | None = None,
        committed_count: int | None = None,
        failed_count: int | None = None,
        diagnostic_reason: str | None = None,
        completed: bool = False,
    ) -> IngestBatch:
        batch = self.session.get(IngestBatch, batch_id)
        if batch is None:
            raise KeyError(f"unknown ingest batch {batch_id}")
        if status is not None:
            batch.status = status
        if received_count is not None:
            batch.received_count = received_count
        if parsed_count is not None:
            batch.parsed_count = parsed_count
        if committed_count is not None:
            batch.committed_count = committed_count
        if failed_count is not None:
            batch.failed_count = failed_count
        if diagnostic_reason is not None:
            batch.diagnostic_reason = diagnostic_reason
        if completed and batch.completed_at is None:
            batch.completed_at = utc_now()
        self.session.flush()
        return batch


class IngestEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, event_id: str) -> IngestEvent | None:
        return self.session.get(IngestEvent, event_id)

    def list_for_batch(self, ingest_batch_id: str) -> list[IngestEvent]:
        return list(
            self.session.scalars(
                select(IngestEvent)
                .where(IngestEvent.ingest_batch_id == ingest_batch_id)
                .order_by(IngestEvent.received_at, IngestEvent.id)
            )
        )

    def find_photo_by_artifact(self, raw_artifact_id: str) -> IngestEvent | None:
        """Return the durable photo event for an artifact, if one exists.

        Photo artifacts deduplicate by content hash.  The webhook identity
        path stays on ``find_existing`` / ``get_or_create`` and is not used
        here, because a later batch may carry a different acquisition-source
        row while still referring to the same immutable image.
        """

        return self.session.scalar(
            select(IngestEvent)
            .where(
                IngestEvent.raw_artifact_id == raw_artifact_id,
                IngestEvent.event_type == "photo",
                IngestEvent.duplicate_of_event_id.is_(None),
            )
            .order_by(IngestEvent.received_at, IngestEvent.id)
        )

    def create_linked(
        self,
        *,
        ingest_batch_id: str,
        acquisition_source_id: str,
        duplicate_of_event_id: str,
        status: str,
        semantic_fingerprint: str,
        raw_artifact_id: str | None = None,
        event_type: str = "photo",
        diagnostic_code: str | None = None,
        diagnostic_reason: str | None = None,
    ) -> IngestEvent:
        """Insert a batch-local occurrence or failed attempt linked to an original event."""

        fingerprint = _required_text(semantic_fingerprint, "semantic fingerprint").lower()
        deduplication_key = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
        existing = self.session.scalar(
            select(IngestEvent).where(IngestEvent.deduplication_key == deduplication_key)
        )
        if existing is not None:
            return existing
        event = IngestEvent(
            ingest_batch_id=ingest_batch_id,
            acquisition_source_id=acquisition_source_id,
            raw_artifact_id=raw_artifact_id,
            semantic_fingerprint=fingerprint,
            deduplication_key=deduplication_key,
            event_type=event_type.strip().lower() if event_type is not None else None,
            status=status,
            diagnostic_code=diagnostic_code,
            diagnostic_reason=diagnostic_reason,
            duplicate_of_event_id=duplicate_of_event_id,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def find_existing(
        self,
        *,
        acquisition_source_id: str,
        external_user_id: str | None = None,
        provider_stream: str | None = None,
        external_record_id: str | None = None,
        semantic_fingerprint: str | None = None,
        raw_artifact_id: str | None = None,
        event_type: str | None = None,
        source_timestamp: datetime | None = None,
    ) -> IngestEvent | None:
        del provider_stream  # Transport metadata is not part of logical identity.
        normalized_fingerprint = semantic_fingerprint.lower() if semantic_fingerprint else None
        normalized_event_type = event_type.strip().lower() if event_type is not None else None
        deduplication_key = _ingest_deduplication_key(
            acquisition_source_id=acquisition_source_id,
            external_user_id=external_user_id,
            external_record_id=external_record_id,
            event_type=normalized_event_type,
            semantic_fingerprint=normalized_fingerprint,
            raw_artifact_id=raw_artifact_id,
            source_timestamp=source_timestamp,
        )
        if deduplication_key is None:
            existing = None
        else:
            existing = self.session.scalar(
                select(IngestEvent).where(IngestEvent.deduplication_key == deduplication_key)
            )
        if existing is not None:
            return existing

        # Some existing callers only have the logical external ID on a retry
        # and omit transport/evidence fields.  Accept that as an exact retry
        # only when the logical identity has one unambiguous event; once there
        # are multiple updates, callers must provide an evidence fingerprint.
        if (
            external_record_id is not None
            and normalized_fingerprint is None
            and raw_artifact_id is None
            and source_timestamp is None
        ):
            conditions = [
                IngestEvent.acquisition_source_id == acquisition_source_id,
                IngestEvent.external_user_id == external_user_id,
                IngestEvent.external_record_id == external_record_id,
            ]
            if normalized_event_type is not None:
                conditions.append(IngestEvent.event_type == normalized_event_type)
            candidates = list(
                self.session.scalars(
                    select(IngestEvent).where(*conditions).order_by(IngestEvent.id)
                )
            )
            if len(candidates) == 1:
                return candidates[0]
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
        normalized_event_type = event_type.strip().lower() if event_type is not None else None
        normalized_source_timestamp = _as_utc(source_timestamp)
        deduplication_key = (
            _ingest_deduplication_key(
                acquisition_source_id=acquisition_source_id,
                external_user_id=external_user_id,
                external_record_id=external_record_id,
                event_type=normalized_event_type,
                semantic_fingerprint=normalized_fingerprint,
                raw_artifact_id=raw_artifact_id,
                source_timestamp=normalized_source_timestamp,
            )
            or new_id()
        )
        existing = self.find_existing(
            acquisition_source_id=acquisition_source_id,
            external_user_id=external_user_id,
            provider_stream=provider_stream,
            external_record_id=external_record_id,
            semantic_fingerprint=normalized_fingerprint,
            raw_artifact_id=raw_artifact_id,
            event_type=normalized_event_type,
            source_timestamp=normalized_source_timestamp,
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
            deduplication_key=deduplication_key,
            event_type=normalized_event_type,
            source_timestamp=normalized_source_timestamp,
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

    def get(self, candidate_id: str) -> ImportCandidate | None:
        return self.session.get(ImportCandidate, candidate_id)

    def list_for_event(self, ingest_event_id: str) -> list[ImportCandidate]:
        return list(
            self.session.scalars(
                select(ImportCandidate)
                .where(ImportCandidate.ingest_event_id == ingest_event_id)
                .order_by(
                    ImportCandidate.candidate_set_key,
                    ImportCandidate.measurement_group_key,
                    ImportCandidate.metric_code,
                    ImportCandidate.id,
                )
            )
        )

    def find_for_artifact_set_key(
        self, raw_artifact_id: str, candidate_set_key: str
    ) -> list[ImportCandidate]:
        return list(
            self.session.scalars(
                select(ImportCandidate)
                .join(IngestEvent, ImportCandidate.ingest_event_id == IngestEvent.id)
                .where(
                    IngestEvent.raw_artifact_id == raw_artifact_id,
                    IngestEvent.event_type == "photo",
                    ImportCandidate.candidate_set_key == candidate_set_key,
                )
                .order_by(
                    ImportCandidate.measurement_group_key,
                    ImportCandidate.metric_code,
                    ImportCandidate.id,
                )
            )
        )

    def list_for_batch(self, ingest_batch_id: str) -> list[ImportCandidate]:
        return list(
            self.session.scalars(
                select(ImportCandidate)
                .join(IngestEvent, ImportCandidate.ingest_event_id == IngestEvent.id)
                .where(IngestEvent.ingest_batch_id == ingest_batch_id)
                .order_by(
                    ImportCandidate.candidate_set_key,
                    ImportCandidate.measurement_group_key,
                    ImportCandidate.metric_code,
                    ImportCandidate.id,
                )
            )
        )

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
        algorithm_code: str | None = None,
        algorithm_version: str | None = None,
        provider_code: str | None = None,
        source_timezone: str | None = None,
        source_utc_offset_minutes: int | None = None,
    ) -> ImportCandidate:
        if confidence is not None and not 0 <= confidence <= 1:
            raise ValueError("candidate confidence must be between 0 and 1")
        if temporal_precision is not None:
            allowed = {item.value for item in TemporalPrecision}
            if str(temporal_precision) not in allowed:
                raise ValueError("candidate temporal precision must be instant, minute, or date")
        normalized_precision = None if temporal_precision is None else str(temporal_precision)
        normalized_timestamp = (
            None
            if proposed_source_timestamp is None
            else restore_stored_utc(proposed_source_timestamp)
        )
        existing = self.session.scalar(
            select(ImportCandidate).where(
                ImportCandidate.ingest_event_id == ingest_event_id,
                ImportCandidate.candidate_set_key == candidate_set_key,
                ImportCandidate.measurement_group_key == measurement_group_key,
                ImportCandidate.metric_code == metric_code,
            )
        )
        incoming = {
            "proposed_value": proposed_value,
            "proposed_unit": proposed_unit,
            "proposed_source_local_date": proposed_source_local_date,
            "temporal_precision": normalized_precision,
            "source_text": source_text,
            "extractor_name": extractor_name,
            "extractor_version": extractor_version,
            "model_name": model_name,
            "model_version": model_version,
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "confidence": confidence,
            "algorithm_code": algorithm_code,
            "algorithm_version": algorithm_version,
            "provider_code": provider_code,
            "source_timezone": source_timezone,
            "source_utc_offset_minutes": source_utc_offset_minutes,
        }
        if existing is not None:
            stored = {field_name: getattr(existing, field_name) for field_name in incoming}
            if stored != incoming or not _same_datetime(
                existing.proposed_source_timestamp, normalized_timestamp
            ):
                raise ValueError("extraction identity already has different evidence")
            return existing
        candidate = ImportCandidate(
            ingest_event_id=ingest_event_id,
            candidate_set_key=_required_text(candidate_set_key, "candidate set key"),
            measurement_group_key=_required_text(measurement_group_key, "measurement group key"),
            metric_code=_required_text(metric_code, "metric code"),
            proposed_value=proposed_value,
            proposed_unit=proposed_unit,
            proposed_source_timestamp=normalized_timestamp,
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
            algorithm_code=algorithm_code,
            algorithm_version=algorithm_version,
            provider_code=provider_code,
            source_timezone=source_timezone,
            source_utc_offset_minutes=source_utc_offset_minutes,
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
        """Record a pending-field edit without confirming or rejecting."""

        candidate = self.session.get(ImportCandidate, candidate_id)
        if candidate is None:
            raise KeyError(f"unknown import candidate {candidate_id}")
        if candidate.user_decision != CandidateDecision.PENDING.value:
            raise ValueError(
                "a terminal candidate decision cannot be edited; create a measurement revision"
            )
        if (
            edited_source_timestamp is not None
            and candidate.temporal_precision == TemporalPrecision.DATE.value
        ):
            raise ValueError("date-only evidence cannot accept a timestamp")
        changed_fields: dict[str, Any] = {}
        if edited_value is not None and edited_value != candidate.edited_value:
            candidate.edited_value = edited_value
            changed_fields["edited_value"] = edited_value
        if edited_unit is not None and edited_unit != candidate.edited_unit:
            candidate.edited_unit = edited_unit
            changed_fields["edited_unit"] = edited_unit
        if edited_source_timestamp is not None:
            normalized_source_timestamp = _as_utc(edited_source_timestamp)
            if not _same_datetime(normalized_source_timestamp, candidate.edited_source_timestamp):
                candidate.edited_source_timestamp = normalized_source_timestamp
                changed_fields["edited_source_timestamp"] = edited_source_timestamp.isoformat()
        if (
            edited_source_local_date is not None
            and edited_source_local_date != candidate.edited_source_local_date
        ):
            candidate.edited_source_local_date = edited_source_local_date
            changed_fields["edited_source_local_date"] = edited_source_local_date.isoformat()
        if not changed_fields:
            return candidate
        self._record_edit(candidate, changed_fields, actor)
        self.session.flush()
        return candidate

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
        if (
            edited_source_timestamp is not None
            and candidate.temporal_precision == TemporalPrecision.DATE.value
        ):
            raise ValueError("date-only evidence cannot accept a timestamp")

        if candidate.user_decision != CandidateDecision.PENDING.value:
            if normalized_decision != candidate.user_decision:
                raise ValueError(
                    "a terminal candidate decision cannot change; create a measurement revision"
                )
            normalized_source_timestamp = _as_utc(edited_source_timestamp)
            if edited_value is not None and edited_value != candidate.edited_value:
                raise ValueError(
                    "a terminal candidate decision cannot be edited; create a measurement revision"
                )
            if edited_unit is not None and edited_unit != candidate.edited_unit:
                raise ValueError(
                    "a terminal candidate decision cannot be edited; create a measurement revision"
                )
            if edited_source_timestamp is not None and not _same_datetime(
                normalized_source_timestamp, candidate.edited_source_timestamp
            ):
                raise ValueError(
                    "a terminal candidate decision cannot be edited; create a measurement revision"
                )
            if (
                edited_source_local_date is not None
                and edited_source_local_date != candidate.edited_source_local_date
            ):
                raise ValueError(
                    "a terminal candidate decision cannot be edited; create a measurement revision"
                )
            if decision_reason is not None and decision_reason != candidate.decision_reason:
                raise ValueError(
                    "a terminal candidate decision cannot be edited; create a measurement revision"
                )
            # An exact terminal replay is a no-op and must not append another
            # audit row or rewrite the decision timestamp.
            return candidate

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

    def get(self, session_id: str) -> MeasurementSession | None:
        return self.session.get(MeasurementSession, session_id)

    def get_by_id(self, session_id: str) -> MeasurementSession | None:
        return self.get(session_id)

    def current_heads(
        self,
        *,
        acquisition_source_id: str | None = None,
        semantic_key: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[MeasurementSession]:
        """Return confirmed session heads, never an older superseded revision.

        Revision order is represented by the supersession edge, not by receive
        time.  The query therefore remains correct when a backfill arrives out
        of order or when a correction is confirmed after the original import.
        """

        successor_ids = select(MeasurementSession.supersedes_session_id).where(
            MeasurementSession.supersedes_session_id.is_not(None)
        )
        conditions = [
            MeasurementSession.confirmation_status == "confirmed",
            ~MeasurementSession.id.in_(successor_ids),
        ]
        if acquisition_source_id is not None:
            conditions.append(MeasurementSession.acquisition_source_id == acquisition_source_id)
        if semantic_key is not None:
            conditions.append(MeasurementSession.semantic_key == semantic_key)
        if start_date is not None:
            conditions.append(MeasurementSession.source_local_date >= start_date)
        if end_date is not None:
            conditions.append(MeasurementSession.source_local_date <= end_date)
        statement = (
            select(MeasurementSession)
            .where(*conditions)
            .order_by(
                MeasurementSession.source_local_date,
                MeasurementSession.source_timestamp_utc,
                MeasurementSession.id,
            )
        )
        return list(self.session.scalars(statement))

    def is_current_head(self, session_id: str) -> bool:
        session = self.get_by_id(session_id)
        if session is None or session.confirmation_status != "confirmed":
            return False
        successor = self.session.scalar(
            select(MeasurementSession.id).where(
                MeasurementSession.supersedes_session_id == session_id
            )
        )
        return successor is None

    def find_by_source_identity(
        self,
        *,
        acquisition_source_id: str,
        source_record_id: str | None = None,
        source_fingerprint: str | None = None,
        semantic_key: str | None = None,
        confirmation_candidate_id: str | None = None,
    ) -> MeasurementSession | None:
        if confirmation_candidate_id is not None:
            exact_candidate = self.session.scalar(
                select(MeasurementSession).where(
                    MeasurementSession.acquisition_source_id == acquisition_source_id,
                    MeasurementSession.confirmation_candidate_id == confirmation_candidate_id,
                )
            )
            if exact_candidate is not None:
                return exact_candidate

        identity_conditions = []
        if source_record_id is not None:
            identity_conditions.append(MeasurementSession.source_record_id == source_record_id)
        if source_fingerprint is not None:
            identity_conditions.append(
                MeasurementSession.source_fingerprint == source_fingerprint.lower()
            )
        if semantic_key is not None:
            identity_conditions.append(MeasurementSession.semantic_key == semantic_key)
        if not identity_conditions:
            return None
        return self.session.scalar(
            select(MeasurementSession)
            .where(
                MeasurementSession.acquisition_source_id == acquisition_source_id,
                or_(*identity_conditions),
            )
            .order_by(
                MeasurementSession.revision_number.desc(),
                MeasurementSession.created_at.desc(),
            )
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
        normalized_semantic_key = _effective_semantic_key(
            semantic_key, source_record_id, normalized_fingerprint
        )
        if idempotent and supersedes_session_id is None:
            existing = self.find_by_source_identity(
                acquisition_source_id=acquisition_source_id,
                source_record_id=source_record_id,
                source_fingerprint=normalized_fingerprint,
                semantic_key=normalized_semantic_key,
                confirmation_candidate_id=confirmation_candidate_id,
            )
            if existing is not None:
                if _session_matches_evidence(
                    existing,
                    acquisition_source_id=acquisition_source_id,
                    ingest_event_id=ingest_event_id,
                    raw_artifact_id=raw_artifact_id,
                    confirmation_candidate_id=confirmation_candidate_id,
                    semantic_key=normalized_semantic_key,
                    source_record_id=source_record_id,
                    source_fingerprint=normalized_fingerprint,
                    temporal_precision=normalized_precision,
                    source_local_date=source_local_date,
                    source_timestamp_utc=normalized_source_timestamp,
                    source_local_timestamp=source_local_timestamp,
                    source_utc_offset_minutes=source_utc_offset_minutes,
                    source_timezone=source_timezone,
                ):
                    return existing
                if (
                    confirmation_candidate_id is not None
                    and existing.confirmation_candidate_id == confirmation_candidate_id
                    and _session_matches_evidence(
                        existing,
                        acquisition_source_id=acquisition_source_id,
                        ingest_event_id=ingest_event_id,
                        raw_artifact_id=raw_artifact_id,
                        confirmation_candidate_id=confirmation_candidate_id,
                        semantic_key=existing.semantic_key,
                        source_record_id=existing.source_record_id,
                        source_fingerprint=existing.source_fingerprint,
                        temporal_precision=normalized_precision,
                        source_local_date=source_local_date,
                        source_timestamp_utc=normalized_source_timestamp,
                        source_local_timestamp=source_local_timestamp,
                        source_utc_offset_minutes=source_utc_offset_minutes,
                        source_timezone=source_timezone,
                    )
                ):
                    # The confirmation candidate is the durable evidence
                    # identity.  A transport-specific source ID may differ
                    # between exact confirmation retries.
                    return existing
                raise ValueError(
                    "source identity already has different evidence; call create_revision"
                )
        if supersedes_session_id is not None:
            previous = self.session.get(MeasurementSession, supersedes_session_id)
            if previous is None:
                raise KeyError(f"unknown superseded session {supersedes_session_id}")
            if previous.acquisition_source_id != acquisition_source_id:
                raise ValueError("a session revision must keep its acquisition source")
            if (
                previous.semantic_key != normalized_semantic_key
                or previous.source_record_id != source_record_id
                or previous.source_fingerprint != normalized_fingerprint
            ):
                raise ValueError("a session revision must preserve its source identity")
            expected_revision = previous.revision_number + 1
            if revision_number is None:
                revision_number = expected_revision
            elif revision_number != expected_revision:
                raise ValueError(
                    f"session revision must be exactly {expected_revision} after the current head"
                )
            successor = self.session.scalar(
                select(MeasurementSession).where(
                    MeasurementSession.supersedes_session_id == previous.id
                )
            )
            if successor is not None:
                if _session_matches_evidence(
                    successor,
                    acquisition_source_id=acquisition_source_id,
                    ingest_event_id=ingest_event_id,
                    raw_artifact_id=raw_artifact_id,
                    confirmation_candidate_id=confirmation_candidate_id,
                    semantic_key=normalized_semantic_key,
                    source_record_id=source_record_id,
                    source_fingerprint=normalized_fingerprint,
                    temporal_precision=normalized_precision,
                    source_local_date=source_local_date,
                    source_timestamp_utc=normalized_source_timestamp,
                    source_local_timestamp=source_local_timestamp,
                    source_utc_offset_minutes=source_utc_offset_minutes,
                    source_timezone=source_timezone,
                ):
                    return successor
                raise ValueError("superseded session already has a different successor")
        else:
            if revision_number is None:
                revision_number = 1
            elif revision_number != 1:
                raise ValueError("an initial measurement session must have revision 1")
        session = MeasurementSession(
            acquisition_source_id=acquisition_source_id,
            ingest_event_id=ingest_event_id,
            raw_artifact_id=raw_artifact_id,
            confirmation_candidate_id=confirmation_candidate_id,
            semantic_key=normalized_semantic_key,
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

    def find_by_ingest_event(self, ingest_event_id: str) -> MeasurementSession | None:
        return self.session.scalar(
            select(MeasurementSession)
            .where(MeasurementSession.ingest_event_id == ingest_event_id)
            .order_by(MeasurementSession.revision_number.desc(), MeasurementSession.id.desc())
        )

    def create_tombstone(
        self,
        previous_session_id: str,
        *,
        ingest_event_id: str | None = None,
        raw_artifact_id: str | None = None,
    ) -> MeasurementSession:
        """Supersede a confirmed head with a recoverable rejected tombstone.

        Raw history stays immutable.  Because measurement_sessions are
        append-only at the SQL layer, the tombstone must be inserted already
        rejected — never updated in place after a confirmed insert.
        """

        previous = self.session.get(MeasurementSession, previous_session_id)
        if previous is None:
            raise KeyError(f"unknown measurement session {previous_session_id}")
        if previous.confirmation_status != "confirmed":
            raise ValueError("only a confirmed session head can be tombstoned")
        successor = self.session.scalar(
            select(MeasurementSession).where(
                MeasurementSession.supersedes_session_id == previous.id
            )
        )
        if successor is not None:
            if successor.confirmation_status == "rejected":
                return successor
            raise ValueError("session already has a non-tombstone successor")
        tombstone = MeasurementSession(
            acquisition_source_id=previous.acquisition_source_id,
            ingest_event_id=ingest_event_id or previous.ingest_event_id,
            raw_artifact_id=raw_artifact_id or previous.raw_artifact_id,
            confirmation_candidate_id=None,
            semantic_key=previous.semantic_key,
            source_record_id=previous.source_record_id,
            source_fingerprint=previous.source_fingerprint,
            temporal_precision=previous.temporal_precision,
            source_local_date=previous.source_local_date,
            source_timestamp_utc=previous.source_timestamp_utc,
            source_local_timestamp=previous.source_local_timestamp,
            source_utc_offset_minutes=previous.source_utc_offset_minutes,
            source_timezone=previous.source_timezone,
            confirmation_status="rejected",
            import_status=IngestStatus.REJECTED.value,
            revision_number=previous.revision_number + 1,
            supersedes_session_id=previous.id,
            confirmed_at=None,
        )
        self.session.add(tombstone)
        self.session.flush()
        return tombstone

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
        ingest_event_id: str | None = None,
        raw_artifact_id: str | None = None,
        source_record_id: str | None = None,
        source_fingerprint: str | None = None,
        semantic_key: str | None = None,
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
            ingest_event_id=ingest_event_id or previous.ingest_event_id,
            raw_artifact_id=raw_artifact_id or previous.raw_artifact_id,
            confirmation_candidate_id=confirmation_candidate_id
            or previous.confirmation_candidate_id,
            source_record_id=source_record_id or previous.source_record_id,
            source_fingerprint=source_fingerprint or previous.source_fingerprint,
            semantic_key=semantic_key or previous.semantic_key,
            supersedes_session_id=previous.id,
            idempotent=True,
        )


class ScalarMeasurementRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, measurement_id: str) -> ScalarMeasurement | None:
        return self.session.get(ScalarMeasurement, measurement_id)

    def get_by_id(self, measurement_id: str) -> ScalarMeasurement | None:
        return self.get(measurement_id)

    def get_by_import_candidate(
        self, import_candidate_id: str, metric_code: str | None = None
    ) -> ScalarMeasurement | None:
        conditions = [ScalarMeasurement.import_candidate_id == import_candidate_id]
        if metric_code is not None:
            conditions.append(ScalarMeasurement.metric_code == metric_code)
        return self.session.scalar(select(ScalarMeasurement).where(*conditions))

    def list_for_session(self, measurement_session_id: str) -> list[ScalarMeasurement]:
        return list(
            self.session.scalars(
                select(ScalarMeasurement)
                .where(ScalarMeasurement.measurement_session_id == measurement_session_id)
                .order_by(ScalarMeasurement.metric_code, ScalarMeasurement.id)
            )
        )

    def active_for_source_metric(
        self,
        *,
        acquisition_source_id: str,
        metric_code: str,
        semantic_key: str | None = None,
        source_record_id: str | None = None,
    ) -> ScalarMeasurement | None:
        """Return the single active head for a metric on one source-identity chain."""

        identity_conditions = []
        if semantic_key is not None:
            identity_conditions.append(MeasurementSession.semantic_key == semantic_key)
        if source_record_id is not None:
            identity_conditions.append(MeasurementSession.source_record_id == source_record_id)
        if not identity_conditions:
            return None
        session_ids = select(MeasurementSession.id).where(
            MeasurementSession.acquisition_source_id == acquisition_source_id,
            or_(*identity_conditions),
        )
        measurements = list(
            self.session.scalars(
                select(ScalarMeasurement).where(
                    ScalarMeasurement.measurement_session_id.in_(session_ids),
                    ScalarMeasurement.metric_code == metric_code,
                )
            )
        )
        superseded = {
            measurement.supersedes_measurement_id
            for measurement in measurements
            if measurement.supersedes_measurement_id is not None
        }
        active = [measurement for measurement in measurements if measurement.id not in superseded]
        if not active:
            return None
        active.sort(key=lambda measurement: (measurement.created_at, measurement.id))
        return active[-1]

    def current_heads(
        self,
        metric_code: str | None = None,
        *,
        acquisition_source_id: str | None = None,
        provider_id: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[ScalarMeasurement]:
        """Return source measurements whose measurement and session are heads.

        A scalar row can be current at the measurement level while its session
        has since been revised.  Canonical selection must exclude both kinds
        of stale evidence, so this method resolves the two append-only chains
        together.
        """

        measurement_successor_ids = select(ScalarMeasurement.supersedes_measurement_id).where(
            ScalarMeasurement.supersedes_measurement_id.is_not(None)
        )
        session_successor_ids = select(MeasurementSession.supersedes_session_id).where(
            MeasurementSession.supersedes_session_id.is_not(None)
        )
        conditions = [
            ~ScalarMeasurement.id.in_(measurement_successor_ids),
            MeasurementSession.confirmation_status == "confirmed",
            ~MeasurementSession.id.in_(session_successor_ids),
        ]
        if metric_code is not None:
            conditions.append(
                ScalarMeasurement.metric_code == _required_text(metric_code, "metric code")
            )
        if acquisition_source_id is not None:
            conditions.append(MeasurementSession.acquisition_source_id == acquisition_source_id)
        if provider_id is not None:
            conditions.append(
                AcquisitionSource.provider_id == _required_text(provider_id, "provider id")
            )
        if start_date is not None:
            conditions.append(MeasurementSession.source_local_date >= start_date)
        if end_date is not None:
            conditions.append(MeasurementSession.source_local_date <= end_date)
        statement = select(ScalarMeasurement).join(
            MeasurementSession,
            MeasurementSession.id == ScalarMeasurement.measurement_session_id,
        )
        if provider_id is not None:
            statement = statement.join(
                AcquisitionSource,
                AcquisitionSource.id == MeasurementSession.acquisition_source_id,
            )
        statement = statement.where(*conditions).order_by(
            MeasurementSession.source_local_date,
            MeasurementSession.source_timestamp_utc,
            ScalarMeasurement.metric_code,
            ScalarMeasurement.id,
        )
        return list(self.session.scalars(statement))

    def is_current_head(self, measurement_id: str) -> bool:
        measurement = self.get_by_id(measurement_id)
        if measurement is None:
            return False
        successor = self.session.scalar(
            select(ScalarMeasurement.id).where(
                ScalarMeasurement.supersedes_measurement_id == measurement_id
            )
        )
        if successor is not None:
            return False
        return MeasurementSessionRepository(self.session).is_current_head(
            measurement.measurement_session_id
        )

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
        normalized_metric_code = _required_text(metric_code, "metric code")
        normalized_unit = _required_text(normalized_unit, "normalized unit")
        if supersedes_measurement_id is not None:
            previous = self.session.get(ScalarMeasurement, supersedes_measurement_id)
            if previous is None:
                raise KeyError(f"unknown superseded measurement {supersedes_measurement_id}")
            if previous.metric_code != normalized_metric_code:
                raise ValueError("a measurement revision must keep its metric code")
            successor = self.session.scalar(
                select(ScalarMeasurement).where(
                    ScalarMeasurement.supersedes_measurement_id == previous.id
                )
            )
            if successor is not None:
                if _scalar_matches_evidence(
                    successor,
                    measurement_session_id=measurement_session_id,
                    import_candidate_id=import_candidate_id,
                    metric_code=normalized_metric_code,
                    normalized_value=normalized_value,
                    normalized_unit=normalized_unit,
                    measurement_algorithm_id=measurement_algorithm_id,
                    original_value=original_value,
                    original_unit=original_unit,
                    quality_status=quality_status,
                    source_text=source_text,
                    supersedes_measurement_id=previous.id,
                ):
                    return successor
                raise ValueError("superseded measurement already has a different successor")
        elif idempotent:
            existing = None
            if import_candidate_id is not None:
                existing = self.session.scalar(
                    select(ScalarMeasurement).where(
                        ScalarMeasurement.import_candidate_id == import_candidate_id,
                        ScalarMeasurement.metric_code == normalized_metric_code,
                    )
                )
            if existing is None:
                existing = self.session.scalar(
                    select(ScalarMeasurement).where(
                        ScalarMeasurement.measurement_session_id == measurement_session_id,
                        ScalarMeasurement.metric_code == normalized_metric_code,
                    )
                )
            if existing is not None:
                if _scalar_matches_evidence(
                    existing,
                    measurement_session_id=measurement_session_id,
                    import_candidate_id=import_candidate_id,
                    metric_code=normalized_metric_code,
                    normalized_value=normalized_value,
                    normalized_unit=normalized_unit,
                    measurement_algorithm_id=measurement_algorithm_id,
                    original_value=original_value,
                    original_unit=original_unit,
                    quality_status=quality_status,
                    source_text=source_text,
                    supersedes_measurement_id=None,
                ):
                    return existing
                raise ValueError(
                    "measurement identity already has different evidence; "
                    "create a measurement revision"
                )
        measurement = ScalarMeasurement(
            measurement_session_id=measurement_session_id,
            import_candidate_id=import_candidate_id,
            metric_code=normalized_metric_code,
            normalized_value=normalized_value,
            normalized_unit=normalized_unit,
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
        import_candidate_id: str | None = None,
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
            import_candidate_id=import_candidate_id,
            original_value=original_value,
            original_unit=original_unit,
            quality_status=quality_status,
            source_text=source_text,
            supersedes_measurement_id=previous.id,
            idempotent=True,
        )

    def active_for_metric(self, metric_code: str) -> list[ScalarMeasurement]:
        return self.current_heads(metric_code)


class DerivedMeasurementRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, derived_measurement_id: str) -> DerivedMeasurement | None:
        return self.session.get(DerivedMeasurement, derived_measurement_id)

    def all(self, metric_code: str | None = None) -> list[DerivedMeasurement]:
        statement = select(DerivedMeasurement)
        if metric_code is not None:
            statement = statement.where(
                DerivedMeasurement.metric_code == _required_text(metric_code, "metric code")
            )
        return list(
            self.session.scalars(
                statement.order_by(DerivedMeasurement.computed_at, DerivedMeasurement.id)
            )
        )

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

    def latest_successful(self, scope_key: str) -> CanonicalSelectionRun | None:
        """Return the latest active result for a semantic scope.

        Only successful runs are active.  Failed and still-running attempts
        remain auditable but must never become a predecessor for a new
        canonical result.
        """

        return self.session.scalar(
            select(CanonicalSelectionRun)
            .where(
                CanonicalSelectionRun.scope_key == _required_text(scope_key, "canonical scope key"),
                CanonicalSelectionRun.status == RunStatus.SUCCEEDED.value,
            )
            .order_by(
                CanonicalSelectionRun.completed_at.desc(),
                CanonicalSelectionRun.id.desc(),
            )
        )

    def latest_for_scope(self, scope_key: str) -> CanonicalSelectionRun | None:
        """Return the newest attempt for a scope regardless of status.

        Used by read paths to detect a failed/stale recompute that is newer
        than the last successful canonical set without activating failures.
        """

        return self.session.scalar(
            select(CanonicalSelectionRun)
            .where(
                CanonicalSelectionRun.scope_key == _required_text(scope_key, "canonical scope key"),
            )
            .order_by(
                CanonicalSelectionRun.started_at.desc(),
                CanonicalSelectionRun.id.desc(),
            )
        )

    def successful_scope_keys(self, *, prefix: str) -> list[str]:
        """Return distinct successful scope keys that start with ``prefix``."""

        normalized = _required_text(prefix, "canonical scope key prefix")
        return list(
            self.session.scalars(
                select(CanonicalSelectionRun.scope_key)
                .where(
                    CanonicalSelectionRun.scope_key.startswith(normalized),
                    CanonicalSelectionRun.status == RunStatus.SUCCEEDED.value,
                )
                .distinct()
                .order_by(CanonicalSelectionRun.scope_key)
            )
        )

    def scope_keys_with_prefix(self, *, prefix: str) -> list[str]:
        """Return distinct scope keys that start with ``prefix`` (any status)."""

        normalized = _required_text(prefix, "canonical scope key prefix")
        return list(
            self.session.scalars(
                select(CanonicalSelectionRun.scope_key)
                .where(CanonicalSelectionRun.scope_key.startswith(normalized))
                .distinct()
                .order_by(CanonicalSelectionRun.scope_key)
            )
        )

    def get_by_id(self, run_id: str) -> CanonicalSelectionRun | None:
        return self.session.get(CanonicalSelectionRun, run_id)

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
        normalized_scope_key = _required_text(scope_key, "canonical scope key")
        existing = self.get_successful(
            scope_key=normalized_scope_key,
            rule_hash=rule_set.rule_hash,
            input_snapshot_hash=input_snapshot_hash,
        )
        if existing is not None:
            return existing, False
        running = self.session.scalar(
            select(CanonicalSelectionRun).where(
                CanonicalSelectionRun.scope_key == normalized_scope_key,
                CanonicalSelectionRun.rule_hash == rule_set.rule_hash,
                CanonicalSelectionRun.input_snapshot_hash == input_snapshot_hash,
                CanonicalSelectionRun.status == RunStatus.RUNNING.value,
            )
        )
        if running is not None:
            return running, False
        if supersedes_run_id is not None:
            predecessor = self.get_by_id(supersedes_run_id)
            if predecessor is None:
                raise KeyError(f"unknown canonical predecessor run {supersedes_run_id}")
            if predecessor.status != RunStatus.SUCCEEDED.value:
                raise ValueError("only a successful canonical run can be superseded")
            if predecessor.scope_key != normalized_scope_key:
                raise ValueError("a canonical run can supersede only the same scope")
        run = CanonicalSelectionRun(
            scope_key=normalized_scope_key,
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
        if run.status != RunStatus.RUNNING.value:
            if run.status != normalized_status:
                raise ValueError("a terminal canonical run cannot change status")
            if run.selection_count != selection_count or run.failure_reason != failure_reason:
                raise ValueError("a terminal canonical run is immutable")
            # Replaying the same terminal completion is an idempotent no-op;
            # in particular, do not rewrite completed_at.
            return run
        run.status = normalized_status
        run.selection_count = selection_count
        run.failure_reason = failure_reason
        run.completed_at = utc_now() if normalized_status != RunStatus.RUNNING.value else None
        self.session.flush()
        return run


class CanonicalSelectionRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_key(
        self, selection_run_id: str, metric_code: str, semantic_key: str
    ) -> CanonicalSelection | None:
        normalized_metric_code = _required_text(metric_code, "canonical metric code")
        normalized_key = _required_text(semantic_key, "canonical semantic key")
        return self.session.scalar(
            select(CanonicalSelection).where(
                CanonicalSelection.selection_run_id == selection_run_id,
                CanonicalSelection.metric_code == normalized_metric_code,
                CanonicalSelection.semantic_key == normalized_key,
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
        normalized_metric_code = _required_text(metric_code, "canonical metric code")
        normalized_key = _required_text(semantic_key, "canonical semantic key")
        if (
            period_start_date is not None
            and period_end_date is not None
            and period_end_date < period_start_date
        ):
            raise ValueError("canonical selection period_end_date must not precede start date")
        run = self.session.get(CanonicalSelectionRun, selection_run_id)
        if run is None:
            raise KeyError(f"unknown canonical selection run {selection_run_id}")
        if run.status != RunStatus.RUNNING.value:
            raise ValueError("only running canonical runs can receive selections")
        if source_measurement_id is not None:
            source_measurement = self.session.get(ScalarMeasurement, source_measurement_id)
            if source_measurement is None:
                raise KeyError(f"unknown source measurement {source_measurement_id}")
            if source_measurement.metric_code != normalized_metric_code:
                raise ValueError("canonical metric does not match source measurement metric")
            if source_measurement.measurement_session_id is not None:
                source_session = self.session.get(
                    MeasurementSession, source_measurement.measurement_session_id
                )
                if source_session is None or not MeasurementSessionRepository(
                    self.session
                ).is_current_head(source_session.id):
                    raise ValueError(
                        "only current confirmed source measurements are canonical-eligible"
                    )
                if source_session.semantic_key != normalized_key:
                    raise ValueError(
                        "canonical semantic key must match source measurement evidence"
                    )
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
            if derived_measurement.metric_code != normalized_metric_code:
                raise ValueError("canonical metric does not match derived measurement metric")
            session_repository = MeasurementSessionRepository(self.session)
            source_session_id = derived_measurement.source_session_id
            source_session = None
            if source_session_id is not None:
                source_session = session_repository.get_by_id(source_session_id)
                if source_session is None or not session_repository.is_current_head(
                    source_session_id
                ):
                    raise ValueError("derived measurement source session is not canonical-eligible")
                if source_session.semantic_key != normalized_key:
                    raise ValueError("canonical semantic key must match derived source session")
            if not derived_measurement.input_measurement_ids_json:
                raise ValueError(
                    "derived canonical selections require explicit input measurement IDs"
                )
            try:
                input_measurement_ids = json.loads(derived_measurement.input_measurement_ids_json)
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("derived measurement input IDs are malformed") from exc
            if not isinstance(input_measurement_ids, list) or not input_measurement_ids:
                raise ValueError(
                    "derived canonical selections require explicit input measurement IDs"
                )
            scalar_repository = ScalarMeasurementRepository(self.session)
            if not all(
                scalar_repository.is_current_head(str(input_id))
                for input_id in input_measurement_ids
            ):
                raise ValueError("derived measurement has ineligible input evidence")
        existing = self.get_by_key(selection_run_id, normalized_metric_code, normalized_key)
        if existing is not None:
            if (
                existing.metric_code == normalized_metric_code
                and existing.source_measurement_id == source_measurement_id
                and existing.derived_measurement_id == derived_measurement_id
            ):
                return existing
            raise ValueError("canonical semantic key already points to different evidence")
        selection = CanonicalSelection(
            selection_run_id=selection_run_id,
            metric_code=normalized_metric_code,
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
        return list(
            self.session.scalars(
                statement.order_by(
                    CanonicalSelection.metric_code,
                    CanonicalSelection.semantic_key,
                    CanonicalSelection.period_start_date,
                    CanonicalSelection.period_end_date,
                    CanonicalSelection.id,
                )
            )
        )


class AgreementRunRepository:
    """Append-only persistence adapter for bounded R05 agreement runs."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, run_id: str) -> AgreementRun | None:
        return self.session.get(AgreementRun, run_id)

    def get_successful(self, identity_hash: str) -> AgreementRun | None:
        return self.session.scalar(
            select(AgreementRun).where(
                AgreementRun.identity_hash
                == _required_text(identity_hash, "agreement identity hash"),
                AgreementRun.status == RunStatus.SUCCEEDED.value,
            )
        )

    def get_running(self, identity_hash: str) -> AgreementRun | None:
        return self.session.scalar(
            select(AgreementRun).where(
                AgreementRun.identity_hash
                == _required_text(identity_hash, "agreement identity hash"),
                AgreementRun.status == RunStatus.RUNNING.value,
            )
        )

    def latest_successful(self, scope_lineage_key: str) -> AgreementRun | None:
        """Return only the latest successful run in one bounded lineage."""

        normalized_lineage = _required_text(
            scope_lineage_key, "agreement scope lineage key"
        )
        superseded_in_lineage = select(AgreementRun.supersedes_run_id).where(
            AgreementRun.scope_lineage_key == normalized_lineage,
            AgreementRun.supersedes_run_id.is_not(None),
        )
        return self.session.scalar(
            select(AgreementRun)
            .where(
                AgreementRun.scope_lineage_key == normalized_lineage,
                AgreementRun.status == RunStatus.SUCCEEDED.value,
                ~AgreementRun.id.in_(superseded_in_lineage),
            )
            .order_by(AgreementRun.completed_at.desc(), AgreementRun.id.desc())
        )

    def get_or_create_rule_set(
        self,
        *,
        rule_name: str,
        rule_version: str,
        definition: Any,
    ) -> AgreementRuleSet:
        normalized_name = _required_text(rule_name, "agreement rule name")
        normalized_version = _required_text(rule_version, "agreement rule version")
        definition_json = canonical_json(definition)
        rule_hash = hash_canonical_rule(definition)
        existing = self.session.scalar(
            select(AgreementRuleSet).where(
                AgreementRuleSet.rule_name == normalized_name,
                AgreementRuleSet.rule_version == normalized_version,
            )
        )
        if existing is not None:
            if existing.rule_hash != rule_hash or existing.rule_definition_json != definition_json:
                raise ValueError("agreement rule name/version already has a different definition")
            return existing
        rule_set = AgreementRuleSet(
            rule_name=normalized_name,
            rule_version=normalized_version,
            rule_definition_json=definition_json,
            rule_hash=rule_hash,
        )
        self.session.add(rule_set)
        self.session.flush()
        return rule_set

    def start_or_get(
        self,
        *,
        scope_key: str,
        scope_lineage_key: str,
        window_key: str,
        requested_start_date: date | None,
        requested_end_date: date | None,
        cohort: str,
        pairing_version: str,
        metric_version: str,
        statistic_version: str,
        rule_set: AgreementRuleSet,
        rule_version: str,
        epoch_id: str,
        epoch_basis_json: str,
        input_snapshot_hash: str,
        input_snapshot_json: str,
        coverage_json: str,
        identity_hash: str,
        supersedes_run_id: str | None = None,
    ) -> tuple[AgreementRun, bool]:
        normalized_identity = _required_text(identity_hash, "agreement identity hash")
        existing = self.get_successful(normalized_identity)
        if existing is not None:
            return existing, False
        running = self.get_running(normalized_identity)
        if running is not None:
            return running, False
        normalized_scope_lineage = _required_text(
            scope_lineage_key, "agreement scope lineage key"
        )
        if supersedes_run_id is not None:
            predecessor = self.get_by_id(supersedes_run_id)
            if predecessor is None:
                raise KeyError(f"unknown agreement predecessor run {supersedes_run_id}")
            if predecessor.status != RunStatus.SUCCEEDED.value:
                raise ValueError("only a successful agreement run can be superseded")
            if predecessor.scope_lineage_key != normalized_scope_lineage:
                raise ValueError(
                    "an agreement run can supersede only the same "
                    "scope/window/cohort/version lineage"
                )
        run = AgreementRun(
            scope_key=_required_text(scope_key, "agreement scope key"),
            scope_lineage_key=normalized_scope_lineage,
            window_key=_required_text(window_key, "agreement window key"),
            requested_start_date=requested_start_date,
            requested_end_date=requested_end_date,
            cohort=_required_text(cohort, "agreement cohort"),
            pairing_version=_required_text(pairing_version, "agreement pairing version"),
            metric_version=_required_text(metric_version, "agreement metric version"),
            statistic_version=_required_text(statistic_version, "agreement statistic version"),
            rule_set_id=rule_set.id,
            rule_name=rule_set.rule_name,
            rule_version=_required_text(rule_version, "agreement rule version"),
            epoch_id=_required_text(epoch_id, "agreement epoch id"),
            epoch_basis_json=_required_text(epoch_basis_json, "agreement epoch basis"),
            input_snapshot_hash=_required_text(input_snapshot_hash, "agreement snapshot hash"),
            input_snapshot_json=_required_text(input_snapshot_json, "agreement snapshot"),
            coverage_json=_required_text(coverage_json, "agreement coverage"),
            identity_hash=normalized_identity,
            supersedes_run_id=supersedes_run_id,
        )
        self.session.add(run)
        self.session.flush()
        return run, True

    def _running(self, run_id: str) -> AgreementRun:
        run = self.get_by_id(run_id)
        if run is None:
            raise KeyError(f"unknown agreement run {run_id}")
        if run.status != RunStatus.RUNNING.value:
            raise ValueError("only running agreement runs can receive snapshot rows")
        return run

    def add_pair(self, *, run_id: str, values: Mapping[str, Any]) -> AgreementRunPair:
        self._running(run_id)
        pair_key = _required_text(str(values["pair_key"]), "agreement pair key")
        existing = self.session.scalar(
            select(AgreementRunPair).where(
                AgreementRunPair.run_id == run_id,
                AgreementRunPair.pair_key == pair_key,
            )
        )
        pair_json = canonical_json(values.get("pair", values))
        eligibility_json = canonical_json(values.get("eligibility", {}))
        if existing is not None:
            if existing.pair_json == pair_json and existing.eligibility_json == eligibility_json:
                return existing
            raise ValueError("agreement pair key already has a different frozen value")
        pair = AgreementRunPair(
            run_id=run_id,
            ordinal=int(values["ordinal"]),
            pair_key=pair_key,
            wake_date=_date_or_none(values["wake_date"], "agreement pair wake date"),
            cohort=_required_text(str(values["cohort"]), "agreement pair cohort"),
            source_class=_required_text(str(values["source_class"]), "agreement source class"),
            garmin_record_id=_required_text(str(values["garmin_record_id"]), "Garmin record ID"),
            google_record_id=_required_text(str(values["google_record_id"]), "Google record ID"),
            garmin_source_id=_required_text(str(values["garmin_source_id"]), "Garmin source ID"),
            google_source_id=_required_text(str(values["google_source_id"]), "Google source ID"),
            eligibility_json=eligibility_json,
            pair_json=pair_json,
        )
        self.session.add(pair)
        self.session.flush()
        return pair

    def add_exclusion(self, *, run_id: str, values: Mapping[str, Any]) -> AgreementRunExclusion:
        self._running(run_id)
        exclusion_json = canonical_json(values.get("exclusion", values))
        exclusion = AgreementRunExclusion(
            run_id=run_id,
            ordinal=int(values["ordinal"]),
            wake_date=_date_or_none(values.get("wake_date"), "agreement exclusion wake date"),
            cohort=values.get("cohort"),
            reason=_required_text(str(values["reason"]), "agreement exclusion reason"),
            garmin_record_ids_json=canonical_json(values.get("garmin_record_ids", [])),
            google_record_ids_json=canonical_json(values.get("google_record_ids", [])),
            details_json=canonical_json(values.get("details", {})),
            exclusion_json=exclusion_json,
        )
        self.session.add(exclusion)
        self.session.flush()
        return exclusion

    def add_metric_result(
        self, *, run_id: str, pair_id: str, values: Mapping[str, Any]
    ) -> AgreementMetricResult:
        self._running(run_id)
        variant = values.get("variant")
        variant_key = (
            "__none__" if variant is None else _required_text(str(variant), "metric variant")
        )
        manifest = values["manifest"]
        result = AgreementMetricResult(
            run_id=run_id,
            pair_id=pair_id,
            ordinal=int(values["ordinal"]),
            metric_code=_required_text(str(values["metric_code"]), "agreement metric code"),
            variant=variant,
            variant_key=variant_key,
            status=_required_text(str(values["status"]), "agreement metric status"),
            comparable=bool(values["comparable"]),
            difference_number=values.get("difference"),
            difference_unit=_required_text(
                str(values["difference_unit"]), "agreement difference unit"
            ),
            reason=values.get("reason"),
            exclusion_basis=values.get("exclusion_basis"),
            garmin_json=canonical_json(values["garmin"]),
            google_json=canonical_json(values["google"]),
            manifest_json=canonical_json(manifest),
            manifest_hash=_required_text(str(values["manifest_hash"]), "agreement manifest hash"),
        )
        self.session.add(result)
        self.session.flush()
        return result

    def add_coverage(self, *, run_id: str, values: Mapping[str, Any]) -> AgreementCoverage:
        self._running(run_id)
        variant = values.get("variant")
        variant_key = (
            "__none__" if variant is None else _required_text(str(variant), "coverage variant")
        )
        coverage = AgreementCoverage(
            run_id=run_id,
            ordinal=int(values["ordinal"]),
            metric_code=_required_text(str(values["metric_code"]), "coverage metric code"),
            variant=variant,
            variant_key=variant_key,
            comparable_count=int(values["comparable_count"]),
            unavailable_count=int(values["unavailable_count"]),
            excluded_count=int(values["excluded_count"]),
            coverage_json=canonical_json(values),
        )
        self.session.add(coverage)
        self.session.flush()
        return coverage

    def finish(
        self,
        run_id: str,
        *,
        status: str | RunStatus,
        pair_count: int | None = None,
        exclusion_count: int | None = None,
        metric_count: int | None = None,
        coverage_count: int | None = None,
        failure_reason: str | None = None,
    ) -> AgreementRun:
        run = self.get_by_id(run_id)
        if run is None:
            raise KeyError(f"unknown agreement run {run_id}")
        try:
            normalized_status = RunStatus(str(status)).value
        except ValueError as exc:
            raise ValueError("agreement run status must be running, succeeded, or failed") from exc
        if normalized_status == RunStatus.RUNNING.value:
            raise ValueError("agreement run finish status must be succeeded or failed")
        counts = {
            "pair_count": pair_count,
            "exclusion_count": exclusion_count,
            "metric_count": metric_count,
            "coverage_count": coverage_count,
        }
        for name, value in counts.items():
            if value is not None and value < 0:
                raise ValueError(f"{name} must be nonnegative")
        if normalized_status == RunStatus.SUCCEEDED.value and failure_reason is not None:
            raise ValueError("a successful agreement run cannot have a failure reason")
        if normalized_status == RunStatus.FAILED.value and not failure_reason:
            raise ValueError("a failed agreement run requires a failure reason")
        if run.status != RunStatus.RUNNING.value:
            if run.status != normalized_status:
                raise ValueError("a terminal agreement run cannot change status")
            if any(getattr(run, name) != value for name, value in counts.items()):
                raise ValueError("a terminal agreement run is immutable")
            if run.failure_reason != failure_reason:
                raise ValueError("a terminal agreement run is immutable")
            return run
        run.status = normalized_status
        run.pair_count = pair_count
        run.exclusion_count = exclusion_count
        run.metric_count = metric_count
        run.coverage_count = coverage_count
        run.failure_reason = failure_reason
        run.completed_at = utc_now()
        self.session.flush()
        return run

    def pairs_for_run(self, run_id: str) -> list[AgreementRunPair]:
        return list(
            self.session.scalars(
                select(AgreementRunPair)
                .where(AgreementRunPair.run_id == run_id)
                .order_by(AgreementRunPair.ordinal, AgreementRunPair.id)
            )
        )

    def exclusions_for_run(self, run_id: str) -> list[AgreementRunExclusion]:
        return list(
            self.session.scalars(
                select(AgreementRunExclusion)
                .where(AgreementRunExclusion.run_id == run_id)
                .order_by(AgreementRunExclusion.ordinal, AgreementRunExclusion.id)
            )
        )

    def metrics_for_run(self, run_id: str) -> list[AgreementMetricResult]:
        return list(
            self.session.scalars(
                select(AgreementMetricResult)
                .where(AgreementMetricResult.run_id == run_id)
                .order_by(AgreementMetricResult.ordinal, AgreementMetricResult.id)
            )
        )

    def coverage_for_run(self, run_id: str) -> list[AgreementCoverage]:
        return list(
            self.session.scalars(
                select(AgreementCoverage)
                .where(AgreementCoverage.run_id == run_id)
                .order_by(AgreementCoverage.ordinal, AgreementCoverage.id)
            )
        )


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

    def list(
        self,
        *,
        provider_id: str | None = None,
        acquisition_source_id: str | None = None,
        stream_code: str | None = None,
        metric_code: str | None = None,
        interval_start: datetime | None = None,
        interval_end: datetime | None = None,
    ) -> list[CoverageInterval]:
        """List interval evidence, optionally clipped by an overlapping range."""

        conditions = []
        if provider_id is not None:
            conditions.append(CoverageInterval.provider_id == provider_id)
        if acquisition_source_id is not None:
            conditions.append(CoverageInterval.acquisition_source_id == acquisition_source_id)
        if stream_code is not None:
            conditions.append(
                CoverageInterval.stream_code == _required_text(stream_code, "stream code")
            )
        if metric_code is not None:
            conditions.append(
                CoverageInterval.metric_code == _required_text(metric_code, "metric code")
            )
        normalized_start = _as_utc(interval_start)
        normalized_end = _as_utc(interval_end)
        if normalized_start is not None:
            conditions.append(CoverageInterval.interval_end > normalized_start)
        if normalized_end is not None:
            conditions.append(CoverageInterval.interval_start < normalized_end)
        statement = (
            select(CoverageInterval)
            .where(*conditions)
            .order_by(
                CoverageInterval.interval_start,
                CoverageInterval.interval_end,
                CoverageInterval.computed_at,
                CoverageInterval.id,
            )
        )
        return list(self.session.scalars(statement))

    def get_by_id(self, interval_id: str) -> CoverageInterval | None:
        return self.session.get(CoverageInterval, interval_id)

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
        idempotent: bool = True,
    ) -> CoverageInterval:
        normalized_status = getattr(status, "value", status)
        if normalized_status not in {
            "present",
            "confirmed_empty",
            "unavailable",
            "failed",
            "unknown",
        }:
            raise ValueError(
                "coverage status must be present, confirmed_empty, unavailable, failed, or unknown"
            )
        normalized_start = _as_utc(interval_start)
        normalized_end = _as_utc(interval_end)
        if normalized_start is None or normalized_end is None:
            raise ValueError("coverage interval boundaries are required")
        if normalized_end <= normalized_start:
            raise ValueError("coverage interval_end must be after interval_start")
        if observed_count is not None and observed_count < 0:
            raise ValueError("observed_count must be nonnegative")
        if expected_count is not None and expected_count < 0:
            raise ValueError("expected_count must be nonnegative")
        normalized_stream_code = _required_text(stream_code, "coverage stream code")
        normalized_metric_code = _required_text(metric_code, "coverage metric code")
        normalized_rule_version = _required_text(
            calculation_rule_version, "coverage calculation rule version"
        )
        if idempotent:
            existing = self.session.scalar(
                select(CoverageInterval).where(
                    CoverageInterval.provider_id == provider_id,
                    CoverageInterval.acquisition_source_id == acquisition_source_id,
                    CoverageInterval.stream_code == normalized_stream_code,
                    CoverageInterval.metric_code == normalized_metric_code,
                    CoverageInterval.interval_start == normalized_start,
                    CoverageInterval.interval_end == normalized_end,
                    CoverageInterval.resolution
                    == _required_text(resolution, "coverage resolution"),
                    CoverageInterval.status == normalized_status,
                    CoverageInterval.calculation_rule_version == normalized_rule_version,
                    CoverageInterval.observed_count == observed_count,
                    CoverageInterval.expected_count == expected_count,
                    CoverageInterval.diagnostic_reason == diagnostic_reason,
                )
            )
            if existing is not None:
                return existing
        interval = CoverageInterval(
            provider_id=provider_id,
            acquisition_source_id=acquisition_source_id,
            stream_code=normalized_stream_code,
            metric_code=normalized_metric_code,
            interval_start=normalized_start,
            interval_end=normalized_end,
            resolution=_required_text(resolution, "coverage resolution"),
            status=normalized_status,
            observed_count=observed_count,
            expected_count=expected_count,
            calculation_rule_version=normalized_rule_version,
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
        self.agreement_runs = AgreementRunRepository(session)
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
    "AgreementRunRepository",
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
    "restore_stored_utc",
]
