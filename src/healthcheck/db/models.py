"""R01 SQLAlchemy persistence model.

The model deliberately contains only the provider-neutral evidence, weight and
provenance concepts required by R01.  Future typed entities such as sleep,
activity and intraday series belong to later migrations.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from healthcheck.db.base import Base

ID_LENGTH = 36


def new_id() -> str:
    """Return a local stable identifier suitable for a persisted entity."""

    return str(uuid4())


def utc_now() -> datetime:
    """Return an aware UTC timestamp for application-side defaults."""

    return datetime.now(UTC)


class TemporalPrecision(StrEnum):
    INSTANT = "instant"
    MINUTE = "minute"
    DATE = "date"


class IngestStatus(StrEnum):
    RECEIVED = "received"
    PARSED = "parsed"
    PENDING_CONFIRMATION = "pending-confirmation"
    COMMITTED = "committed"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    FAILED = "failed"


class CandidateDecision(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CoverageStatus(StrEnum):
    PRESENT = "present"
    CONFIRMED_EMPTY = "confirmed_empty"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    UNKNOWN = "unknown"


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class PhysicalDevice(Base):
    __tablename__ = "physical_devices"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    manufacturer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    instance_identifier: Mapped[str | None] = mapped_column(String(200), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class AcquisitionSource(Base):
    __tablename__ = "acquisition_sources"
    __table_args__ = (
        CheckConstraint(
            "input_method IN ('photo_import', 'webhook', 'provider_api', 'manual_import')",
            name="input_method_allowed",
        ),
        Index(
            "ux_acquisition_sources_sender_instance_id",
            "source_instance_id",
            unique=True,
            sqlite_where=text("source_instance_id IS NOT NULL"),
        ),
        Index(
            "ux_acquisition_sources_natural_identity",
            "provider_id",
            "physical_device_id",
            "input_method",
            unique=True,
            sqlite_where=text("source_instance_id IS NULL AND physical_device_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    provider_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False
    )
    physical_device_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("physical_devices.id", ondelete="RESTRICT"), nullable=True
    )
    input_method: Mapped[str] = mapped_column(String(40), nullable=False)
    source_instance_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_application: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_application_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    configuration_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    configuration_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class MeasurementAlgorithm(Base):
    __tablename__ = "measurement_algorithms"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_measurement_algorithms_code_version"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(180), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_family: Mapped[str] = mapped_column(String(100), nullable=False)
    producer: Mapped[str] = mapped_column(String(100), nullable=False)
    parameters_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    compatibility_group: Mapped[str] = mapped_column(String(180), nullable=False)
    verification_state: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class RawArtifact(Base):
    __tablename__ = "raw_artifacts"
    __table_args__ = (
        CheckConstraint("byte_size >= 0", name="byte_size_nonnegative"),
        CheckConstraint("length(content_hash) >= 32", name="content_hash_min_length"),
        CheckConstraint(
            "relative_storage_path NOT LIKE '/%' "
            "AND relative_storage_path NOT LIKE '\\\\%' "
            "AND relative_storage_path NOT GLOB '[A-Za-z]:*' "
            "AND relative_storage_path NOT LIKE '%..%'",
            name="relative_storage_path_only",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    media_type: Mapped[str] = mapped_column(String(160), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    relative_storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    source_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class IngestBatch(Base):
    __tablename__ = "ingest_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('received', 'parsed', 'pending-confirmation', 'committed', 'rejected', "
            "'duplicate', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint(
            "batch_kind IN ('photo', 'webhook', 'provider_sync', 'manual')",
            name="batch_kind_allowed",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    acquisition_source_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("acquisition_sources.id", ondelete="RESTRICT"), nullable=False
    )
    batch_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    parser_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    extractor_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    extractor_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default=IngestStatus.RECEIVED.value
    )
    received_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parsed_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    committed_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diagnostic_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class IngestEvent(Base):
    __tablename__ = "ingest_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('received', 'parsed', 'pending-confirmation', 'committed', 'rejected', "
            "'duplicate', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint(
            "event_type IS NULL OR event_type IN "
            "('insert', 'update', 'delete', 'clear', 'test', 'photo')",
            name="event_type_allowed",
        ),
        Index(
            "ux_ingest_events_deduplication_key",
            "deduplication_key",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    ingest_batch_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("ingest_batches.id", ondelete="RESTRICT"), nullable=False
    )
    acquisition_source_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("acquisition_sources.id", ondelete="RESTRICT"), nullable=False
    )
    raw_artifact_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("raw_artifacts.id", ondelete="RESTRICT"), nullable=True
    )
    external_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_stream: Mapped[str | None] = mapped_column(String(160), nullable=True)
    external_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    semantic_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    deduplication_key: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    source_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default=IngestStatus.RECEIVED.value
    )
    diagnostic_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    diagnostic_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    duplicate_of_event_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("ingest_events.id", ondelete="RESTRICT"), nullable=True
    )


class ImportCandidate(Base):
    __tablename__ = "import_candidates"
    __table_args__ = (
        CheckConstraint(
            "user_decision IN ('pending', 'confirmed', 'rejected')", name="user_decision_allowed"
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"
        ),
        CheckConstraint(
            "temporal_precision IS NULL OR temporal_precision IN ('instant', 'minute', 'date')",
            name="temporal_precision_allowed",
        ),
        UniqueConstraint(
            "ingest_event_id",
            "candidate_set_key",
            "measurement_group_key",
            "metric_code",
            name="uq_import_candidates_semantic_field",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    ingest_event_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("ingest_events.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_set_key: Mapped[str] = mapped_column(String(255), nullable=False)
    measurement_group_key: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_code: Mapped[str] = mapped_column(String(120), nullable=False)
    proposed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    proposed_unit: Mapped[str | None] = mapped_column(String(60), nullable=True)
    proposed_source_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    proposed_source_local_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    temporal_precision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extractor_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    extractor_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_region_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    edited_unit: Mapped[str | None] = mapped_column(String(60), nullable=True)
    edited_source_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    edited_source_local_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    user_decision: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CandidateDecision.PENDING.value
    )
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class ImportCandidateEdit(Base):
    """Append-only audit rows for candidate edits and decisions."""

    __tablename__ = "import_candidate_edits"
    __table_args__ = (
        UniqueConstraint("candidate_id", "revision", name="uq_candidate_edits_revision"),
        CheckConstraint("revision >= 1", name="revision_positive"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    candidate_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("import_candidates.id", ondelete="RESTRICT"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    edited_fields_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(80), nullable=False, default="owner")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class MeasurementSession(Base):
    __tablename__ = "measurement_sessions"
    __table_args__ = (
        CheckConstraint(
            "temporal_precision IN ('instant', 'minute', 'date')", name="temporal_precision_allowed"
        ),
        CheckConstraint(
            "(temporal_precision = 'date' AND source_timestamp_utc IS NULL "
            "AND source_local_timestamp IS NULL) "
            "OR (temporal_precision IN ('instant', 'minute') AND source_timestamp_utc IS NOT NULL)",
            name="temporal_precision_timestamp_consistency",
        ),
        CheckConstraint(
            "source_utc_offset_minutes IS NULL OR "
            "(source_utc_offset_minutes >= -840 AND source_utc_offset_minutes <= 840)",
            name="source_utc_offset_range",
        ),
        CheckConstraint(
            "confirmation_status IN ('confirmed', 'rejected', 'pending')",
            name="confirmation_status_allowed",
        ),
        CheckConstraint("revision_number >= 1", name="revision_positive"),
        Index(
            "ix_measurement_sessions_source_identity",
            "acquisition_source_id",
            "semantic_key",
            "revision_number",
        ),
        Index(
            "ux_measurement_sessions_semantic_revision",
            "acquisition_source_id",
            "semantic_key",
            "revision_number",
            unique=True,
            sqlite_where=text("semantic_key IS NOT NULL"),
        ),
        Index(
            "ux_measurement_sessions_source_record_revision",
            "acquisition_source_id",
            "source_record_id",
            "revision_number",
            unique=True,
            sqlite_where=text("source_record_id IS NOT NULL"),
        ),
        Index(
            "ux_measurement_sessions_source_fingerprint_revision",
            "acquisition_source_id",
            "source_fingerprint",
            "revision_number",
            unique=True,
            sqlite_where=text("source_fingerprint IS NOT NULL"),
        ),
        Index(
            "ux_measurement_sessions_confirmation_candidate",
            "confirmation_candidate_id",
            unique=True,
            sqlite_where=text("confirmation_candidate_id IS NOT NULL"),
        ),
        Index(
            "ux_measurement_sessions_single_successor",
            "supersedes_session_id",
            unique=True,
            sqlite_where=text("supersedes_session_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    acquisition_source_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("acquisition_sources.id", ondelete="RESTRICT"), nullable=False
    )
    ingest_event_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("ingest_events.id", ondelete="RESTRICT"), nullable=True
    )
    raw_artifact_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("raw_artifacts.id", ondelete="RESTRICT"), nullable=True
    )
    confirmation_candidate_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("import_candidates.id", ondelete="RESTRICT"), nullable=True
    )
    semantic_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    temporal_precision: Mapped[str] = mapped_column(String(20), nullable=False)
    source_local_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_timestamp_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_local_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_utc_offset_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confirmation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="confirmed"
    )
    import_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default=IngestStatus.COMMITTED.value
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_session_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("measurement_sessions.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScalarMeasurement(Base):
    __tablename__ = "scalar_measurements"
    __table_args__ = (
        CheckConstraint("length(metric_code) > 0", name="metric_code_nonempty"),
        CheckConstraint("length(normalized_unit) > 0", name="normalized_unit_nonempty"),
        Index("ix_scalar_measurements_metric_session", "metric_code", "measurement_session_id"),
        Index(
            "ux_scalar_measurements_import_candidate_metric",
            "import_candidate_id",
            "metric_code",
            unique=True,
            sqlite_where=text("import_candidate_id IS NOT NULL"),
        ),
        Index(
            "ux_scalar_measurements_single_successor",
            "supersedes_measurement_id",
            unique=True,
            sqlite_where=text("supersedes_measurement_id IS NOT NULL"),
        ),
        UniqueConstraint(
            "measurement_session_id", "metric_code", name="uq_scalar_measurements_session_metric"
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    measurement_session_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("measurement_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    import_candidate_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("import_candidates.id", ondelete="RESTRICT"), nullable=True
    )
    metric_code: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_value: Mapped[float] = mapped_column(Float, nullable=False)
    normalized_unit: Mapped[str] = mapped_column(String(60), nullable=False)
    original_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_unit: Mapped[str | None] = mapped_column(String(60), nullable=True)
    measurement_algorithm_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("measurement_algorithms.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quality_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_measurement_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("scalar_measurements.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class DerivedMeasurement(Base):
    __tablename__ = "derived_measurements"
    __table_args__ = (
        CheckConstraint("length(metric_code) > 0", name="metric_code_nonempty"),
        CheckConstraint("length(normalized_unit) > 0", name="normalized_unit_nonempty"),
        CheckConstraint(
            "input_measurement_ids_json IS NOT NULL OR input_set_hash IS NOT NULL",
            name="input_provenance_required",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    metric_code: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_value: Mapped[float] = mapped_column(Float, nullable=False)
    normalized_unit: Mapped[str] = mapped_column(String(60), nullable=False)
    algorithm_code: Mapped[str] = mapped_column(String(180), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(100), nullable=False)
    parameters_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_measurement_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_set_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    source_session_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("measurement_sessions.id", ondelete="RESTRICT"), nullable=True
    )


class CanonicalRuleSet(Base):
    __tablename__ = "canonical_rule_sets"
    __table_args__ = (
        UniqueConstraint("rule_name", "rule_version", name="uq_canonical_rule_sets_name_version"),
        CheckConstraint(
            "effective_start_date IS NULL OR effective_end_date IS NULL "
            "OR effective_start_date <= effective_end_date",
            name="effective_period_order",
        ),
        CheckConstraint("rule_version >= 1", name="rule_version_positive"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    rule_name: Mapped[str] = mapped_column(String(160), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    rule_definition_json: Mapped[str] = mapped_column(Text, nullable=False)
    rule_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    creation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class CanonicalSelectionRun(Base):
    __tablename__ = "canonical_selection_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="status_allowed"),
        CheckConstraint(
            "selection_count IS NULL OR selection_count >= 0", name="selection_count_nonnegative"
        ),
        Index(
            "ux_canonical_successful_input",
            "scope_key",
            "rule_hash",
            "input_snapshot_hash",
            unique=True,
            sqlite_where=text("status = 'succeeded'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    scope_key: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    requested_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    rule_set_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("canonical_rule_sets.id", ondelete="RESTRICT"), nullable=False
    )
    rule_name: Mapped[str] = mapped_column(String(160), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    input_snapshot_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    software_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    build_version: Mapped[str | None] = mapped_column(String(160), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=RunStatus.RUNNING.value)
    selection_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_run_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("canonical_selection_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )


class CanonicalSelection(Base):
    __tablename__ = "canonical_selections"
    __table_args__ = (
        CheckConstraint(
            "(source_measurement_id IS NOT NULL AND derived_measurement_id IS NULL) "
            "OR (source_measurement_id IS NULL AND derived_measurement_id IS NOT NULL)",
            name="exactly_one_evidence_reference",
        ),
        UniqueConstraint(
            "selection_run_id",
            "metric_code",
            "semantic_key",
            name="uq_canonical_selections_run_metric_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    selection_run_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("canonical_selection_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    metric_code: Mapped[str] = mapped_column(String(120), nullable=False)
    semantic_key: Mapped[str] = mapped_column(String(255), nullable=False)
    period_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_measurement_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("scalar_measurements.id", ondelete="RESTRICT"), nullable=True
    )
    derived_measurement_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("derived_measurements.id", ondelete="RESTRICT"), nullable=True
    )
    selection_reason: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed')", name="status_allowed"
        ),
        CheckConstraint("item_count IS NULL OR item_count >= 0", name="item_count_nonnegative"),
        CheckConstraint(
            "received_count IS NULL OR received_count >= 0", name="received_count_nonnegative"
        ),
        CheckConstraint(
            "accepted_count IS NULL OR accepted_count >= 0", name="accepted_count_nonnegative"
        ),
        CheckConstraint(
            "failed_count IS NULL OR failed_count >= 0", name="failed_count_nonnegative"
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    provider_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False
    )
    acquisition_source_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("acquisition_sources.id", ondelete="RESTRICT"), nullable=True
    )
    stream_code: Mapped[str] = mapped_column(String(160), nullable=False)
    requested_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accepted_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    diagnostic_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncStreamState(Base):
    __tablename__ = "sync_stream_state"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "acquisition_source_id",
            "stream_code",
            name="uq_sync_stream_state_identity",
        ),
        Index(
            "ux_sync_stream_state_without_source",
            "provider_id",
            "stream_code",
            unique=True,
            sqlite_where=text("acquisition_source_id IS NULL"),
        ),
        Index(
            "ux_sync_stream_state_with_source",
            "provider_id",
            "acquisition_source_id",
            "stream_code",
            unique=True,
            sqlite_where=text("acquisition_source_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    provider_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False
    )
    acquisition_source_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("acquisition_sources.id", ondelete="RESTRICT"), nullable=True
    )
    stream_code: Mapped[str] = mapped_column(String(160), nullable=False)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    watermark: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trailing_window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diagnostic_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class CoverageInterval(Base):
    __tablename__ = "coverage_intervals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('present', 'confirmed_empty', 'unavailable', 'failed', 'unknown')",
            name="status_allowed",
        ),
        CheckConstraint(
            "observed_count IS NULL OR observed_count >= 0", name="observed_count_nonnegative"
        ),
        CheckConstraint(
            "expected_count IS NULL OR expected_count >= 0", name="expected_count_nonnegative"
        ),
        CheckConstraint("interval_end > interval_start", name="interval_order"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    provider_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False
    )
    acquisition_source_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("acquisition_sources.id", ondelete="RESTRICT"), nullable=True
    )
    stream_code: Mapped[str] = mapped_column(String(160), nullable=False)
    metric_code: Mapped[str] = mapped_column(String(120), nullable=False)
    interval_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interval_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolution: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    observed_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calculation_rule_version: Mapped[str] = mapped_column(String(100), nullable=False)
    diagnostic_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


__all__ = [
    "AcquisitionSource",
    "Base",
    "CandidateDecision",
    "CanonicalRuleSet",
    "CanonicalSelection",
    "CanonicalSelectionRun",
    "CoverageInterval",
    "CoverageStatus",
    "DerivedMeasurement",
    "ImportCandidate",
    "ImportCandidateEdit",
    "IngestBatch",
    "IngestEvent",
    "IngestStatus",
    "MeasurementAlgorithm",
    "MeasurementSession",
    "PhysicalDevice",
    "Provider",
    "RawArtifact",
    "RunStatus",
    "ScalarMeasurement",
    "SyncRun",
    "SyncStreamState",
    "TemporalPrecision",
]
