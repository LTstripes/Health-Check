"""SQLAlchemy persistence models for the R01–R04 core, Garmin, and Google contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    Boolean,
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


class GarminSource(Base):
    """Explicit Garmin provider/device identity used by R02 evidence."""

    __tablename__ = "garmin_sources"
    __table_args__ = (
        UniqueConstraint(
            "provider_code", "source_instance_id", name="uq_garmin_sources_provider_instance"
        ),
        CheckConstraint("length(source_kind) > 0", name="source_kind_nonempty"),
        CheckConstraint("length(provider_code) > 0", name="provider_code_nonempty"),
        CheckConstraint("length(source_instance_id) > 0", name="source_instance_nonempty"),
        CheckConstraint(
            "(device_attributed = 1 AND device_code IS NOT NULL AND device_model IS NOT NULL) "
            "OR (device_attributed = 0 AND device_code IS NULL AND device_model IS NULL)",
            name="device_identity_consistency",
        ),
        Index("ix_garmin_sources_acquisition", "acquisition_source_id"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    provider_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False
    )
    acquisition_source_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("acquisition_sources.id", ondelete="RESTRICT"), nullable=False
    )
    physical_device_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("physical_devices.id", ondelete="RESTRICT"), nullable=True
    )
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(120), nullable=False)
    source_instance_id: Mapped[str] = mapped_column(String(255), nullable=False)
    device_attributed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    device_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    device_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class GarminPayloadStatus(StrEnum):
    """Normalized status retained alongside one immutable raw payload."""

    OK = "ok"
    PARTIAL = "partial"
    EMPTY = "empty"
    INVALID = "invalid"


class GarminMetricState(StrEnum):
    """Presence state for a persisted Garmin metric field."""

    MISSING = "missing"
    NULL = "null"
    VALUE = "value"
    INVALID = "invalid"


class GarminProjectionStatus(StrEnum):
    """Current-projection membership for one Garmin source-record identity."""

    CURRENT = "current"
    RETIRED = "retired"


class GarminRawPayload(Base):
    """Immutable source payload metadata linked to a content-addressed artifact."""

    __tablename__ = "garmin_raw_payloads"
    __table_args__ = (
        UniqueConstraint(
            "garmin_source_id",
            "stream_code",
            "content_hash",
            name="uq_garmin_raw_payloads_source_stream_hash",
        ),
        CheckConstraint(
            "stream_code IN ('daily_health', 'sleep', 'activity', 'intraday', 'original_fit')",
            name="stream_code_allowed",
        ),
        CheckConstraint(
            "payload_format IN ('json', 'fit', 'binary')", name="payload_format_allowed"
        ),
        CheckConstraint(
            "parse_status IN ('ok', 'partial', 'empty', 'invalid')",
            name="parse_status_allowed",
        ),
        CheckConstraint("length(content_hash) >= 32", name="content_hash_min_length"),
        CheckConstraint("record_count >= 0", name="record_count_nonnegative"),
        Index(
            "ix_garmin_raw_payloads_source_stream_received",
            "garmin_source_id",
            "stream_code",
            "received_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    garmin_source_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("garmin_sources.id", ondelete="RESTRICT"), nullable=False
    )
    raw_artifact_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("raw_artifacts.id", ondelete="RESTRICT"), nullable=False
    )
    ingest_event_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("ingest_events.id", ondelete="RESTRICT"), nullable=True
    )
    sync_run_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("sync_runs.id", ondelete="RESTRICT"), nullable=True
    )
    stream_code: Mapped[str] = mapped_column(String(40), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_format: Mapped[str] = mapped_column(String(20), nullable=False)
    source_contract_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    normalization_contract_version: Mapped[str] = mapped_column(String(120), nullable=False)
    fixture_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    diagnostics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    unknown_fields_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_window_start_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_window_end_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class GarminPayloadObservation(Base):
    """One acquisition/normalization observation of an immutable raw payload."""

    __tablename__ = "garmin_payload_observations"
    __table_args__ = (
        UniqueConstraint("observation_key", name="uq_garmin_payload_observations_key"),
        CheckConstraint(
            "stream_code IN ('daily_health', 'sleep', 'activity', 'intraday', 'original_fit')",
            name="stream_code_allowed",
        ),
        CheckConstraint(
            "payload_format IN ('json', 'fit', 'binary')", name="payload_format_allowed"
        ),
        CheckConstraint(
            "parse_status IN ('ok', 'partial', 'empty', 'invalid')",
            name="parse_status_allowed",
        ),
        CheckConstraint("length(observation_key) >= 32", name="observation_key_min_length"),
        CheckConstraint("record_count >= 0", name="record_count_nonnegative"),
        Index(
            "ix_garmin_payload_observations_source_stream_received",
            "garmin_source_id",
            "stream_code",
            "received_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    garmin_raw_payload_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("garmin_raw_payloads.id", ondelete="RESTRICT"), nullable=False
    )
    raw_artifact_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("raw_artifacts.id", ondelete="RESTRICT"), nullable=False
    )
    garmin_source_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("garmin_sources.id", ondelete="RESTRICT"), nullable=False
    )
    ingest_event_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("ingest_events.id", ondelete="RESTRICT"), nullable=True
    )
    sync_run_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("sync_runs.id", ondelete="RESTRICT"), nullable=True
    )
    observation_key: Mapped[str] = mapped_column(String(128), nullable=False)
    stream_code: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_format: Mapped[str] = mapped_column(String(20), nullable=False)
    source_contract_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    normalization_contract_version: Mapped[str] = mapped_column(String(120), nullable=False)
    reconciliation_contract_version: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="r02-garmin-pre-collection-reconciliation",
        server_default=text("'r02-garmin-pre-collection-reconciliation'"),
    )
    fixture_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    diagnostics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    unknown_fields_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_window_start_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_window_end_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class GarminSourceRecord(Base):
    """Current typed projection of one stable Garmin source-record identity."""

    __tablename__ = "garmin_source_records"
    __table_args__ = (
        UniqueConstraint(
            "garmin_source_id",
            "idempotency_key",
            name="uq_garmin_source_records_source_idempotency",
        ),
        CheckConstraint(
            "stream_code IN ('daily_health', 'sleep', 'activity', 'intraday', 'original_fit')",
            name="stream_code_allowed",
        ),
        CheckConstraint(
            "temporal_precision IN ('unknown', 'date', 'instant', 'local')",
            name="temporal_precision_allowed",
        ),
        CheckConstraint(
            "record_status IN ('ok', 'partial', 'empty', 'invalid')",
            name="record_status_allowed",
        ),
        CheckConstraint(
            "record_index IS NULL OR record_index >= 0", name="record_index_nonnegative"
        ),
        CheckConstraint(
            "source_utc_offset_minutes IS NULL OR "
            "(source_utc_offset_minutes >= -1439 AND source_utc_offset_minutes <= 1439)",
            name="source_utc_offset_range",
        ),
        CheckConstraint(
            "(temporal_precision = 'instant' AND source_timestamp_utc IS NOT NULL) "
            "OR (temporal_precision = 'local' AND local_wall_time IS NOT NULL) "
            "OR temporal_precision IN ('unknown', 'date')",
            name="temporal_precision_consistency",
        ),
        CheckConstraint(
            "projection_status IN ('current', 'retired')",
            name="projection_status_allowed",
        ),
        CheckConstraint(
            "(projection_status = 'current' AND retired_at IS NULL AND retire_reason IS NULL) "
            "OR (projection_status = 'retired' AND retired_at IS NOT NULL)",
            name="projection_retirement_consistency",
        ),
        Index(
            "ix_garmin_source_records_stream_date",
            "garmin_source_id",
            "stream_code",
            "source_local_date",
        ),
        Index(
            "ix_garmin_source_records_external_id",
            "garmin_source_id",
            "stream_code",
            "external_record_id",
        ),
        Index(
            "ix_garmin_source_records_collection",
            "garmin_source_id",
            "collection_key",
            "projection_status",
        ),
        Index(
            "ix_garmin_source_records_surface_date",
            "garmin_source_id",
            "surface_code",
            "source_local_date",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    garmin_source_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("garmin_sources.id", ondelete="RESTRICT"), nullable=False
    )
    raw_payload_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("garmin_raw_payloads.id", ondelete="RESTRICT"), nullable=False
    )
    ingest_event_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("ingest_events.id", ondelete="RESTRICT"), nullable=True
    )
    stream_code: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    external_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    record_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activity_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    temporal_precision: Mapped[str] = mapped_column(String(20), nullable=False)
    source_local_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_timestamp_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    local_wall_time: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_local_timestamp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_utc_offset_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_local_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_utc_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    record_status: Mapped[str] = mapped_column(String(20), nullable=False)
    normalization_contract_version: Mapped[str] = mapped_column(String(120), nullable=False)
    diagnostics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    unknown_fields_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    surface_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    collection_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    projection_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="current", server_default=text("'current'")
    )
    projection_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retire_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reconciliation_contract_version: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="r02-garmin-pre-collection-reconciliation",
        server_default=text("'r02-garmin-pre-collection-reconciliation'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class GarminTrainingSnapshot(Base):
    """Typed Garmin-native training record; device association is not producer proof."""

    __tablename__ = "garmin_training_snapshots"
    __table_args__ = (
        CheckConstraint("kind IN ('status', 'load_balance', 'readiness')", name="kind_allowed"),
        CheckConstraint(
            "attribution IN ('account', 'associated_device')", name="attribution_allowed"
        ),
    )

    record_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("garmin_source_records.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_device_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_device_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attribution: Mapped[str] = mapped_column(String(30), nullable=False)


class GarminTrainingAcquisition(Base):
    """One requested day for an immutable training payload observation."""

    __tablename__ = "garmin_training_acquisitions"
    __table_args__ = (
        CheckConstraint(
            "surface IN ('training_status', 'training_readiness')", name="surface_allowed"
        ),
        CheckConstraint(
            "response_state IN ('value', 'null', 'empty', 'shape_drift')",
            name="response_state_allowed",
        ),
        Index("ix_garmin_training_acquisitions_requested", "surface", "requested_date"),
    )

    observation_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("garmin_payload_observations.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    surface: Mapped[str] = mapped_column(String(40), nullable=False)
    requested_date: Mapped[date] = mapped_column(Date, nullable=False)
    response_state: Mapped[str] = mapped_column(String(20), nullable=False)


class GarminTrainingObservationRecord(Base):
    """Immutable observation-to-semantic-snapshot membership."""

    __tablename__ = "garmin_training_observation_records"

    observation_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("garmin_payload_observations.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    record_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("garmin_source_records.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class GarminDailyRecord(Base):
    """Typed daily-health record marker and local calendar identity."""

    __tablename__ = "garmin_daily_records"

    record_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("garmin_source_records.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    calendar_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class GarminSleepRecord(Base):
    """Typed sleep-session record keyed to the source/local wake date."""

    __tablename__ = "garmin_sleep_records"

    record_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("garmin_source_records.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    wake_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class GarminActivityRecord(Base):
    """Typed activity record marker."""

    __tablename__ = "garmin_activity_records"

    record_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("garmin_source_records.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    activity_type: Mapped[str | None] = mapped_column(String(120), nullable=True)


class GarminIntradayRecord(Base):
    """Typed intraday sample marker."""

    __tablename__ = "garmin_intraday_records"

    record_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("garmin_source_records.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    sample_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sample_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)


class GarminFitRecord(Base):
    """Typed ORIGINAL FIT record marker; the file remains the raw evidence."""

    __tablename__ = "garmin_fit_records"

    record_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("garmin_source_records.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class GarminRecordMetric(Base):
    """Scalar metric registry attached to a typed Garmin source record."""

    __tablename__ = "garmin_record_metrics"
    __table_args__ = (
        UniqueConstraint("record_id", "metric_code", name="uq_garmin_record_metrics_record_metric"),
        CheckConstraint("state IN ('missing', 'null', 'value', 'invalid')", name="state_allowed"),
        CheckConstraint(
            "state = 'value' OR "
            "(value_number IS NULL AND value_text IS NULL AND collection_json IS NULL)",
            name="non_value_has_no_value",
        ),
        Index("ix_garmin_record_metrics_metric_state", "metric_code", "state"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    record_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("garmin_source_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    capability_code: Mapped[str] = mapped_column(String(120), nullable=False)
    metric_code: Mapped[str] = mapped_column(String(120), nullable=False)
    field_path: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    value_number: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(60), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    capability_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_device_attributed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    collection_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class GarminSleepStageInterval(Base):
    """Typed sleep-stage interval with UTC and original local evidence."""

    __tablename__ = "garmin_sleep_stage_intervals"
    __table_args__ = (
        UniqueConstraint(
            "sleep_record_id", "ordinal", name="uq_garmin_sleep_stage_intervals_ordinal"
        ),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint(
            "start_at_utc IS NULL OR end_at_utc IS NULL OR end_at_utc > start_at_utc",
            name="interval_order",
        ),
        CheckConstraint(
            "(start_utc_offset_minutes IS NULL OR "
            "(start_utc_offset_minutes >= -1439 AND start_utc_offset_minutes <= 1439)) "
            "AND (end_utc_offset_minutes IS NULL OR "
            "(end_utc_offset_minutes >= -1439 AND end_utc_offset_minutes <= 1439))",
            name="stage_utc_offset_range",
        ),
        Index("ix_garmin_sleep_stage_intervals_start", "sleep_record_id", "start_at_utc"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    sleep_record_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("garmin_sleep_records.record_id", ondelete="RESTRICT"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    start_precision: Mapped[str] = mapped_column(String(20), nullable=False)
    end_precision: Mapped[str] = mapped_column(String(20), nullable=False)
    start_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_local_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_local_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_local_wall_time: Mapped[str | None] = mapped_column(String(100), nullable=True)
    end_local_wall_time: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_source_timestamp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    end_source_timestamp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_source_timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    end_source_timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_utc_offset_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_utc_offset_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_source_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    end_source_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    activity_level: Mapped[str | None] = mapped_column(String(80), nullable=True)
    start_temporal_json: Mapped[str] = mapped_column(Text, nullable=False)
    end_temporal_json: Mapped[str] = mapped_column(Text, nullable=False)


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
    algorithm_code: Mapped[str | None] = mapped_column(String(180), nullable=True)
    algorithm_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_utc_offset_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
            "OR (temporal_precision = 'minute' AND ("
            "source_timestamp_utc IS NOT NULL OR source_local_timestamp IS NOT NULL)) "
            "OR (temporal_precision = 'instant' AND source_timestamp_utc IS NOT NULL)",
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


class AgreementRuleSet(Base):
    """Versioned R05 agreement rule/stat contract identity."""

    __tablename__ = "agreement_rule_sets"
    __table_args__ = (
        UniqueConstraint("rule_name", "rule_version", name="uq_agreement_rule_sets_name_version"),
        CheckConstraint("length(rule_name) > 0", name="rule_name_nonempty"),
        CheckConstraint("length(rule_version) > 0", name="rule_version_nonempty"),
        CheckConstraint("length(rule_hash) >= 32", name="rule_hash_min_length"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    rule_name: Mapped[str] = mapped_column(String(160), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(120), nullable=False)
    rule_definition_json: Mapped[str] = mapped_column(Text, nullable=False)
    rule_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class AgreementRun(Base):
    """Immutable completed R05 agreement result over one frozen snapshot."""

    __tablename__ = "agreement_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="status_allowed"),
        CheckConstraint("length(scope_key) > 0", name="scope_key_nonempty"),
        CheckConstraint("length(window_key) > 0", name="window_key_nonempty"),
        CheckConstraint("length(cohort) > 0", name="cohort_nonempty"),
        CheckConstraint("length(pairing_version) > 0", name="pairing_version_nonempty"),
        CheckConstraint("length(metric_version) > 0", name="metric_version_nonempty"),
        CheckConstraint("length(statistic_version) > 0", name="statistic_version_nonempty"),
        CheckConstraint("length(rule_version) > 0", name="rule_version_nonempty"),
        CheckConstraint("length(epoch_id) > 0", name="epoch_id_nonempty"),
        CheckConstraint("length(input_snapshot_hash) >= 32", name="snapshot_hash_min_length"),
        CheckConstraint("length(identity_hash) >= 32", name="identity_hash_min_length"),
        CheckConstraint("pair_count IS NULL OR pair_count >= 0", name="pair_count_nonnegative"),
        CheckConstraint(
            "exclusion_count IS NULL OR exclusion_count >= 0",
            name="exclusion_count_nonnegative",
        ),
        CheckConstraint(
            "metric_count IS NULL OR metric_count >= 0", name="metric_count_nonnegative"
        ),
        CheckConstraint(
            "coverage_count IS NULL OR coverage_count >= 0",
            name="coverage_count_nonnegative",
        ),
        CheckConstraint(
            "(status = 'succeeded' AND completed_at IS NOT NULL AND failure_reason IS NULL) "
            "OR (status = 'failed' AND completed_at IS NOT NULL AND failure_reason IS NOT NULL) "
            "OR (status = 'running' AND completed_at IS NULL)",
            name="status_completion_consistency",
        ),
        Index("ix_agreement_runs_scope_status", "scope_lineage_key", "status", "completed_at"),
        Index("ix_agreement_runs_supersedes", "supersedes_run_id"),
        Index(
            "ux_agreement_runs_single_successor",
            "supersedes_run_id",
            unique=True,
            sqlite_where=text("status = 'succeeded' AND supersedes_run_id IS NOT NULL"),
        ),
        Index(
            "ux_agreement_runs_success_identity",
            "identity_hash",
            unique=True,
            sqlite_where=text("status = 'succeeded'"),
        ),
        Index(
            "ux_agreement_runs_running_identity",
            "identity_hash",
            unique=True,
            sqlite_where=text("status = 'running'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    scope_key: Mapped[str] = mapped_column(String(255), nullable=False)
    scope_lineage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    window_key: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    requested_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cohort: Mapped[str] = mapped_column(String(80), nullable=False)
    pairing_version: Mapped[str] = mapped_column(String(120), nullable=False)
    metric_version: Mapped[str] = mapped_column(String(120), nullable=False)
    statistic_version: Mapped[str] = mapped_column(String(120), nullable=False)
    rule_set_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("agreement_rule_sets.id", ondelete="RESTRICT"), nullable=False
    )
    rule_name: Mapped[str] = mapped_column(String(160), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(120), nullable=False)
    epoch_id: Mapped[str] = mapped_column(String(160), nullable=False)
    epoch_basis_json: Mapped[str] = mapped_column(Text, nullable=False)
    input_snapshot_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    input_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    coverage_json: Mapped[str] = mapped_column(Text, nullable=False)
    identity_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=RunStatus.RUNNING.value)
    pair_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exclusion_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metric_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coverage_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_run_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("agreement_runs.id", ondelete="RESTRICT"), nullable=True
    )

    @property
    def snapshot_json(self) -> str:
        """Compatibility name for the persisted frozen input snapshot."""

        return self.input_snapshot_json


class AgreementRunPair(Base):
    """Frozen accepted pair and eligibility basis belonging to an agreement run."""

    __tablename__ = "agreement_run_pairs"
    __table_args__ = (
        UniqueConstraint("run_id", "ordinal", name="uq_agreement_run_pairs_ordinal"),
        UniqueConstraint("run_id", "pair_key", name="uq_agreement_run_pairs_key"),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint("length(pair_key) > 0", name="pair_key_nonempty"),
        CheckConstraint("length(cohort) > 0", name="cohort_nonempty"),
        Index("ix_agreement_run_pairs_wake_date", "run_id", "wake_date"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("agreement_runs.id", ondelete="RESTRICT"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    pair_key: Mapped[str] = mapped_column(String(255), nullable=False)
    wake_date: Mapped[date] = mapped_column(Date, nullable=False)
    cohort: Mapped[str] = mapped_column(String(80), nullable=False)
    source_class: Mapped[str] = mapped_column(String(80), nullable=False)
    garmin_record_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    google_record_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    garmin_source_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    google_source_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    eligibility_json: Mapped[str] = mapped_column(Text, nullable=False)
    pair_json: Mapped[str] = mapped_column(Text, nullable=False)


class AgreementRunExclusion(Base):
    """Frozen candidate/exclusion decision belonging to an agreement run."""

    __tablename__ = "agreement_run_exclusions"
    __table_args__ = (
        UniqueConstraint("run_id", "ordinal", name="uq_agreement_run_exclusions_ordinal"),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint("length(reason) > 0", name="reason_nonempty"),
        Index("ix_agreement_run_exclusions_wake_date", "run_id", "wake_date"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("agreement_runs.id", ondelete="RESTRICT"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    wake_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cohort: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reason: Mapped[str] = mapped_column(String(160), nullable=False)
    garmin_record_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    google_record_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False)
    exclusion_json: Mapped[str] = mapped_column(Text, nullable=False)


class AgreementMetricResult(Base):
    """Frozen per-pair/per-metric projection and immutable evidence manifest."""

    __tablename__ = "agreement_metric_results"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "pair_id",
            "metric_code",
            "variant_key",
            name="uq_agreement_metric_results_identity",
        ),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint(
            "status IN ('comparable', 'unavailable', 'excluded')", name="status_allowed"
        ),
        CheckConstraint("length(metric_code) > 0", name="metric_code_nonempty"),
        CheckConstraint("length(variant_key) > 0", name="variant_key_nonempty"),
        CheckConstraint("length(manifest_hash) >= 32", name="manifest_hash_min_length"),
        Index("ix_agreement_metric_results_run_metric", "run_id", "metric_code", "variant_key"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("agreement_runs.id", ondelete="RESTRICT"), nullable=False
    )
    pair_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("agreement_run_pairs.id", ondelete="RESTRICT"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    metric_code: Mapped[str] = mapped_column(String(160), nullable=False)
    variant: Mapped[str | None] = mapped_column(String(80), nullable=True)
    variant_key: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    comparable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    difference_number: Mapped[float | None] = mapped_column(Float, nullable=True)
    difference_unit: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    exclusion_basis: Mapped[str | None] = mapped_column(String(200), nullable=True)
    garmin_json: Mapped[str] = mapped_column(Text, nullable=False)
    google_json: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(128), nullable=False)


class AgreementCoverage(Base):
    """Frozen coverage counts used to produce one agreement run."""

    __tablename__ = "agreement_coverages"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "metric_code", "variant_key", name="uq_agreement_coverages_identity"
        ),
        CheckConstraint("length(metric_code) > 0", name="metric_code_nonempty"),
        CheckConstraint("length(variant_key) > 0", name="variant_key_nonempty"),
        CheckConstraint("comparable_count >= 0", name="comparable_count_nonnegative"),
        CheckConstraint("unavailable_count >= 0", name="unavailable_count_nonnegative"),
        CheckConstraint("excluded_count >= 0", name="excluded_count_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("agreement_runs.id", ondelete="RESTRICT"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    metric_code: Mapped[str] = mapped_column(String(160), nullable=False)
    variant: Mapped[str | None] = mapped_column(String(80), nullable=True)
    variant_key: Mapped[str] = mapped_column(String(80), nullable=False)
    comparable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unavailable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_count: Mapped[int] = mapped_column(Integer, nullable=False)
    coverage_json: Mapped[str] = mapped_column(Text, nullable=False)


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


class GoogleSourceKind(StrEnum):
    """Stable Google source identity kind. Query mode is never a source kind."""

    DATA_SOURCE = "data_source"
    FAMILY_AGGREGATE = "family_aggregate"


class GoogleQueryMode(StrEnum):
    """Google Health API acquisition mode. Observation context, not source identity."""

    LIST = "list"
    RECONCILE = "reconcile"
    ROLL_UP = "rollUp"
    DAILY_ROLL_UP = "dailyRollUp"


class GooglePayloadStatus(StrEnum):
    """Normalized status retained alongside one immutable Google raw payload."""

    OK = "ok"
    PARTIAL = "partial"
    EMPTY = "empty"
    INVALID = "invalid"


class GoogleMetricState(StrEnum):
    """Presence state for a persisted Google metric field."""

    MISSING = "missing"
    NULL = "null"
    VALUE = "value"
    INVALID = "invalid"


class GoogleProjectionStatus(StrEnum):
    """Current-projection membership for one Google source-record identity."""

    CURRENT = "current"
    RETIRED = "retired"


class GoogleSource(Base):
    """Explicit Google provider/source/device identity used by R04 evidence.

    Query mode and dataSourceFamily are not part of this identity. A single
    provider dataSource observed through list/reconcile/rollup stays one row.
    Family-only aggregates use ``family_aggregate`` and stay unattributed
    unless explicit device metadata is present.
    """

    __tablename__ = "google_sources"
    __table_args__ = (
        UniqueConstraint(
            "provider_code", "source_instance_id", name="uq_google_sources_provider_instance"
        ),
        CheckConstraint(
            "source_kind IN ('data_source', 'family_aggregate')", name="source_kind_allowed"
        ),
        CheckConstraint("length(source_kind) > 0", name="source_kind_nonempty"),
        CheckConstraint("length(provider_code) > 0", name="provider_code_nonempty"),
        CheckConstraint("length(source_instance_id) > 0", name="source_instance_nonempty"),
        CheckConstraint(
            "(device_attributed = 1 AND device_code IS NOT NULL AND device_model IS NOT NULL) "
            "OR (device_attributed = 0 AND device_code IS NULL AND device_model IS NULL "
            "AND device_manufacturer IS NULL AND device_uid IS NULL)",
            name="device_identity_consistency",
        ),
        CheckConstraint(
            "source_kind <> 'family_aggregate' OR device_attributed = 0",
            name="family_aggregate_unattributed",
        ),
        Index("ix_google_sources_acquisition", "acquisition_source_id"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    provider_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False
    )
    acquisition_source_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("acquisition_sources.id", ondelete="RESTRICT"), nullable=False
    )
    physical_device_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("physical_devices.id", ondelete="RESTRICT"), nullable=True
    )
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(120), nullable=False)
    source_instance_id: Mapped[str] = mapped_column(String(512), nullable=False)
    data_source_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    data_source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(120), nullable=True)
    recording_method: Mapped[str | None] = mapped_column(String(120), nullable=True)
    device_attributed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    device_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    device_manufacturer: Mapped[str | None] = mapped_column(String(160), nullable=True)
    device_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    device_uid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_contract_version: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class GoogleRawPayload(Base):
    """Immutable source payload metadata linked to a content-addressed artifact."""

    __tablename__ = "google_raw_payloads"
    __table_args__ = (
        UniqueConstraint(
            "google_source_id",
            "stream_code",
            "content_hash",
            name="uq_google_raw_payloads_source_stream_hash",
        ),
        CheckConstraint(
            "stream_code IN ('sleep', 'heart_rate', 'hrv', 'daily_hrv', "
            "'daily_resting_hr', 'spo2', 'daily_spo2', "
            "'respiratory_rate_sleep', 'daily_respiratory_rate')",
            name="stream_code_allowed",
        ),
        CheckConstraint("payload_format IN ('json', 'binary')", name="payload_format_allowed"),
        CheckConstraint(
            "parse_status IN ('ok', 'partial', 'empty', 'invalid')",
            name="parse_status_allowed",
        ),
        CheckConstraint("length(content_hash) >= 32", name="content_hash_min_length"),
        CheckConstraint("record_count >= 0", name="record_count_nonnegative"),
        Index(
            "ix_google_raw_payloads_source_stream_received",
            "google_source_id",
            "stream_code",
            "received_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    google_source_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("google_sources.id", ondelete="RESTRICT"), nullable=False
    )
    raw_artifact_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("raw_artifacts.id", ondelete="RESTRICT"), nullable=False
    )
    ingest_event_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("ingest_events.id", ondelete="RESTRICT"), nullable=True
    )
    sync_run_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("sync_runs.id", ondelete="RESTRICT"), nullable=True
    )
    stream_code: Mapped[str] = mapped_column(String(40), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_format: Mapped[str] = mapped_column(String(20), nullable=False)
    source_contract_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    normalization_contract_version: Mapped[str] = mapped_column(String(120), nullable=False)
    fixture_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    diagnostics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    unknown_fields_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_window_start_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_window_end_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class GooglePayloadObservation(Base):
    """One acquisition/normalization observation of an immutable raw payload.

    Query mode, dataSourceFamily, fetch window, and sync run live here so they
    cannot inflate ``google_sources`` identity.
    """

    __tablename__ = "google_payload_observations"
    __table_args__ = (
        UniqueConstraint("observation_key", name="uq_google_payload_observations_key"),
        CheckConstraint(
            "stream_code IN ('sleep', 'heart_rate', 'hrv', 'daily_hrv', "
            "'daily_resting_hr', 'spo2', 'daily_spo2', "
            "'respiratory_rate_sleep', 'daily_respiratory_rate')",
            name="stream_code_allowed",
        ),
        CheckConstraint(
            "query_mode IN ('list', 'reconcile', 'rollUp', 'dailyRollUp')",
            name="query_mode_allowed",
        ),
        CheckConstraint(
            "data_source_family IS NULL OR ("
            "length(data_source_family) > 0 AND "
            "data_source_family LIKE 'users/%/dataSourceFamilies/%')",
            name="data_source_family_resource",
        ),
        CheckConstraint("payload_format IN ('json', 'binary')", name="payload_format_allowed"),
        CheckConstraint(
            "parse_status IN ('ok', 'partial', 'empty', 'invalid')",
            name="parse_status_allowed",
        ),
        CheckConstraint("length(observation_key) >= 32", name="observation_key_min_length"),
        CheckConstraint("record_count >= 0", name="record_count_nonnegative"),
        Index(
            "ix_google_payload_observations_source_stream_received",
            "google_source_id",
            "stream_code",
            "received_at",
        ),
        Index(
            "ix_google_payload_observations_query_context",
            "google_source_id",
            "query_mode",
            "data_source_family",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    google_raw_payload_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("google_raw_payloads.id", ondelete="RESTRICT"), nullable=False
    )
    raw_artifact_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("raw_artifacts.id", ondelete="RESTRICT"), nullable=False
    )
    google_source_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("google_sources.id", ondelete="RESTRICT"), nullable=False
    )
    ingest_event_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("ingest_events.id", ondelete="RESTRICT"), nullable=True
    )
    sync_run_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("sync_runs.id", ondelete="RESTRICT"), nullable=True
    )
    observation_key: Mapped[str] = mapped_column(String(128), nullable=False)
    stream_code: Mapped[str] = mapped_column(String(40), nullable=False)
    query_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    data_source_family: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_format: Mapped[str] = mapped_column(String(20), nullable=False)
    source_contract_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    normalization_contract_version: Mapped[str] = mapped_column(String(120), nullable=False)
    fixture_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    diagnostics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    unknown_fields_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_window_start_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_window_end_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class GoogleSourceRecord(Base):
    """Current typed projection of one Google source-record identity.

    Query mode and dataSourceFamily are preserved so list evidence cannot
    collapse into a family rollup of the same health fact.
    """

    __tablename__ = "google_source_records"
    __table_args__ = (
        UniqueConstraint(
            "google_source_id",
            "record_identity_key",
            name="uq_google_source_records_source_identity",
        ),
        CheckConstraint(
            "stream_code IN ('sleep', 'heart_rate', 'hrv', 'daily_hrv', "
            "'daily_resting_hr', 'spo2', 'daily_spo2', "
            "'respiratory_rate_sleep', 'daily_respiratory_rate')",
            name="stream_code_allowed",
        ),
        CheckConstraint(
            "query_mode IN ('list', 'reconcile', 'rollUp', 'dailyRollUp')",
            name="query_mode_allowed",
        ),
        CheckConstraint(
            "data_source_family IS NULL OR ("
            "length(data_source_family) > 0 AND "
            "data_source_family LIKE 'users/%/dataSourceFamilies/%')",
            name="data_source_family_resource",
        ),
        CheckConstraint(
            "temporal_precision IN ('unknown', 'date', 'instant', 'local')",
            name="temporal_precision_allowed",
        ),
        CheckConstraint(
            "record_status IN ('ok', 'partial', 'empty', 'invalid')",
            name="record_status_allowed",
        ),
        CheckConstraint(
            "record_index IS NULL OR record_index >= 0", name="record_index_nonnegative"
        ),
        CheckConstraint(
            "source_utc_offset_minutes IS NULL OR "
            "(source_utc_offset_minutes >= -1439 AND source_utc_offset_minutes <= 1439)",
            name="source_utc_offset_range",
        ),
        CheckConstraint(
            "(temporal_precision = 'instant' AND source_timestamp_utc IS NOT NULL) "
            "OR (temporal_precision = 'local' AND local_wall_time IS NOT NULL) "
            "OR temporal_precision IN ('unknown', 'date')",
            name="temporal_precision_consistency",
        ),
        CheckConstraint(
            "projection_status IN ('current', 'retired')",
            name="projection_status_allowed",
        ),
        CheckConstraint(
            "(projection_status = 'current' AND retired_at IS NULL AND retire_reason IS NULL) "
            "OR (projection_status = 'retired' AND retired_at IS NOT NULL)",
            name="projection_retirement_consistency",
        ),
        Index(
            "ix_google_source_records_stream_date",
            "google_source_id",
            "stream_code",
            "source_local_date",
        ),
        Index(
            "ix_google_source_records_query_context",
            "google_source_id",
            "stream_code",
            "query_mode",
            "data_source_family",
        ),
        Index(
            "ix_google_source_records_external_id",
            "google_source_id",
            "stream_code",
            "external_record_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    google_source_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("google_sources.id", ondelete="RESTRICT"), nullable=False
    )
    raw_payload_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("google_raw_payloads.id", ondelete="RESTRICT"), nullable=False
    )
    observation_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("google_payload_observations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    ingest_event_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("ingest_events.id", ondelete="RESTRICT"), nullable=True
    )
    stream_code: Mapped[str] = mapped_column(String(40), nullable=False)
    query_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    data_source_family: Mapped[str | None] = mapped_column(String(255), nullable=True)
    record_identity_key: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    external_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    record_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temporal_precision: Mapped[str] = mapped_column(String(20), nullable=False)
    source_local_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_timestamp_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    local_wall_time: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_local_timestamp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_utc_offset_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_local_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_utc_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    record_status: Mapped[str] = mapped_column(String(20), nullable=False)
    source_contract_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    normalization_contract_version: Mapped[str] = mapped_column(String(120), nullable=False)
    diagnostics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    unknown_fields_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    projection_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="current", server_default=text("'current'")
    )
    projection_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retire_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class GoogleSleepRecord(Base):
    """Thin typed sleep-session marker keyed to the source/local wake date."""

    __tablename__ = "google_sleep_records"

    record_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("google_source_records.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    wake_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class GoogleSleepFieldState(Base):
    """Presence state for typed sleep interval collections."""

    __tablename__ = "google_sleep_field_states"
    __table_args__ = (
        CheckConstraint(
            "sleep_interval_state IN ('missing', 'null', 'value', 'invalid')",
            name="sleep_interval_state_allowed",
        ),
        CheckConstraint(
            "sleep_stages_state IN ('missing', 'null', 'value', 'invalid')",
            name="sleep_stages_state_allowed",
        ),
        CheckConstraint(
            "out_of_bed_state IN ('missing', 'null', 'value', 'invalid')",
            name="out_of_bed_state_allowed",
        ),
    )

    sleep_record_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("google_sleep_records.record_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    sleep_interval_state: Mapped[str] = mapped_column(String(20), nullable=False)
    sleep_stages_state: Mapped[str] = mapped_column(String(20), nullable=False)
    out_of_bed_state: Mapped[str] = mapped_column(String(20), nullable=False)


class GoogleRecordInterval(Base):
    """Typed interval for the accepted heart-rate rollup projections."""

    __tablename__ = "google_record_intervals"
    __table_args__ = (
        UniqueConstraint(
            "record_id",
            "interval_kind",
            "ordinal",
            name="uq_google_record_intervals_kind_ordinal",
        ),
        CheckConstraint(
            "interval_kind IN ('roll_up', 'daily_roll_up')",
            name="interval_kind_allowed",
        ),
        CheckConstraint(
            "interval_state IN ('missing', 'null', 'value', 'invalid')",
            name="interval_state_allowed",
        ),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint(
            "start_precision IN ('unknown', 'date', 'instant', 'local')",
            name="record_interval_start_precision_allowed",
        ),
        CheckConstraint(
            "start_state IN ('missing', 'null', 'value', 'invalid')",
            name="record_interval_start_state_allowed",
        ),
        CheckConstraint(
            "start_utc_offset_minutes IS NULL OR "
            "(start_utc_offset_minutes >= -1439 AND start_utc_offset_minutes <= 1439)",
            name="record_interval_start_offset_range",
        ),
        CheckConstraint(
            "end_precision IN ('unknown', 'date', 'instant', 'local')",
            name="record_interval_end_precision_allowed",
        ),
        CheckConstraint(
            "end_state IN ('missing', 'null', 'value', 'invalid')",
            name="record_interval_end_state_allowed",
        ),
        CheckConstraint(
            "end_utc_offset_minutes IS NULL OR "
            "(end_utc_offset_minutes >= -1439 AND end_utc_offset_minutes <= 1439)",
            name="record_interval_end_offset_range",
        ),
        CheckConstraint(
            "start_at_utc IS NULL OR end_at_utc IS NULL OR end_at_utc > start_at_utc",
            name="interval_order",
        ),
        Index("ix_google_record_intervals_start", "record_id", "start_at_utc"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    record_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("google_source_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    interval_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    interval_state: Mapped[str] = mapped_column(String(20), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    start_precision: Mapped[str] = mapped_column(String(20), nullable=False)
    end_precision: Mapped[str] = mapped_column(String(20), nullable=False)
    start_state: Mapped[str] = mapped_column(String(20), nullable=False)
    end_state: Mapped[str] = mapped_column(String(20), nullable=False)
    start_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_local_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_local_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_local_wall_time: Mapped[str | None] = mapped_column(String(100), nullable=True)
    end_local_wall_time: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_source_timestamp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    end_source_timestamp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_utc_offset_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_utc_offset_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_source_timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    end_source_timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_source_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    end_source_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_source_local_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    end_source_local_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_source_utc_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    end_source_utc_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_temporal_json: Mapped[str] = mapped_column(Text, nullable=False)
    end_temporal_json: Mapped[str] = mapped_column(Text, nullable=False)


class GoogleSleepInterval(Base):
    """Typed Google sleep-session, stage, and out-of-bed interval evidence."""

    __tablename__ = "google_sleep_intervals"
    __table_args__ = (
        UniqueConstraint(
            "sleep_record_id",
            "interval_kind",
            "ordinal",
            name="uq_google_sleep_intervals_kind_ordinal",
        ),
        CheckConstraint(
            "interval_kind IN ('sleep_session', 'sleep_stage', 'sleep_out_of_bed')",
            name="interval_kind_allowed",
        ),
        CheckConstraint(
            "interval_state IN ('missing', 'null', 'value', 'invalid')",
            name="interval_state_allowed",
        ),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint(
            "(interval_kind = 'sleep_stage' AND stage_type IS NOT NULL) OR "
            "(interval_kind <> 'sleep_stage' AND stage_type IS NULL)",
            name="stage_type_consistency",
        ),
        CheckConstraint(
            "start_precision IN ('unknown', 'date', 'instant', 'local')",
            name="sleep_interval_start_precision_allowed",
        ),
        CheckConstraint(
            "start_state IN ('missing', 'null', 'value', 'invalid')",
            name="sleep_interval_start_state_allowed",
        ),
        CheckConstraint(
            "start_utc_offset_minutes IS NULL OR "
            "(start_utc_offset_minutes >= -1439 AND start_utc_offset_minutes <= 1439)",
            name="sleep_interval_start_offset_range",
        ),
        CheckConstraint(
            "end_precision IN ('unknown', 'date', 'instant', 'local')",
            name="sleep_interval_end_precision_allowed",
        ),
        CheckConstraint(
            "end_state IN ('missing', 'null', 'value', 'invalid')",
            name="sleep_interval_end_state_allowed",
        ),
        CheckConstraint(
            "end_utc_offset_minutes IS NULL OR "
            "(end_utc_offset_minutes >= -1439 AND end_utc_offset_minutes <= 1439)",
            name="sleep_interval_end_offset_range",
        ),
        CheckConstraint(
            "start_at_utc IS NULL OR end_at_utc IS NULL OR end_at_utc > start_at_utc",
            name="interval_order",
        ),
        Index("ix_google_sleep_intervals_start", "sleep_record_id", "start_at_utc"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    sleep_record_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("google_sleep_records.record_id", ondelete="RESTRICT"),
        nullable=False,
    )
    interval_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    interval_state: Mapped[str] = mapped_column(String(20), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    stage_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    create_time: Mapped[str | None] = mapped_column(String(100), nullable=True)
    update_time: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_precision: Mapped[str] = mapped_column(String(20), nullable=False)
    end_precision: Mapped[str] = mapped_column(String(20), nullable=False)
    start_state: Mapped[str] = mapped_column(String(20), nullable=False)
    end_state: Mapped[str] = mapped_column(String(20), nullable=False)
    start_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_local_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_local_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_local_wall_time: Mapped[str | None] = mapped_column(String(100), nullable=True)
    end_local_wall_time: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_source_timestamp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    end_source_timestamp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_utc_offset_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_utc_offset_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_source_timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    end_source_timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_source_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    end_source_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_source_local_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    end_source_local_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_source_utc_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    end_source_utc_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_temporal_json: Mapped[str] = mapped_column(Text, nullable=False)
    end_temporal_json: Mapped[str] = mapped_column(Text, nullable=False)


class GoogleRecordSourceEvidence(Base):
    """Bounded dataSource evidence embedded in a Google source record."""

    __tablename__ = "google_record_source_evidence"
    __table_args__ = (
        CheckConstraint(
            "state IN ('missing', 'null', 'value', 'invalid')",
            name="state_allowed",
        ),
    )

    record_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("google_source_records.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    field_path: Mapped[str] = mapped_column(String(255), nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)


class GoogleNormalizationAttempt(Base):
    """Immutable bounded normalization attempt for offline v1/v2 replay."""

    __tablename__ = "google_normalization_attempts"
    __table_args__ = (
        UniqueConstraint("attempt_key", name="uq_google_normalization_attempts_key"),
        CheckConstraint(
            "stream_code IN ('sleep', 'heart_rate', 'hrv', 'daily_hrv', "
            "'daily_resting_hr', 'spo2', 'daily_spo2', "
            "'respiratory_rate_sleep', 'daily_respiratory_rate')",
            name="stream_code_allowed",
        ),
        CheckConstraint(
            "query_mode IN ('list', 'reconcile', 'rollUp', 'dailyRollUp')",
            name="query_mode_allowed",
        ),
        CheckConstraint(
            "data_source_family IS NULL OR ("
            "length(data_source_family) > 0 AND "
            "data_source_family LIKE 'users/%/dataSourceFamilies/%')",
            name="data_source_family_resource",
        ),
        CheckConstraint(
            "parse_status IN ('ok', 'partial', 'empty', 'invalid')",
            name="parse_status_allowed",
        ),
        CheckConstraint("record_count >= 0", name="record_count_nonnegative"),
        CheckConstraint("length(attempt_key) >= 32", name="attempt_key_min_length"),
        Index(
            "ix_google_normalization_attempts_observation_version",
            "observation_id",
            "normalization_contract_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    google_source_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("google_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    google_raw_payload_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("google_raw_payloads.id", ondelete="RESTRICT"),
        nullable=False,
    )
    observation_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("google_payload_observations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    attempt_key: Mapped[str] = mapped_column(String(128), nullable=False)
    stream_code: Mapped[str] = mapped_column(String(40), nullable=False)
    query_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    data_source_family: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_contract_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    normalization_contract_version: Mapped[str] = mapped_column(String(120), nullable=False)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    projection_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    projection_json: Mapped[str] = mapped_column(Text, nullable=False)
    diagnostics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    unknown_fields_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class GoogleRecordMetric(Base):
    """Scalar metric registry attached to a typed Google source record."""

    __tablename__ = "google_record_metrics"
    __table_args__ = (
        UniqueConstraint("record_id", "metric_code", name="uq_google_record_metrics_record_metric"),
        CheckConstraint("state IN ('missing', 'null', 'value', 'invalid')", name="state_allowed"),
        CheckConstraint(
            "state = 'value' OR "
            "(value_number IS NULL AND value_text IS NULL AND collection_json IS NULL)",
            name="non_value_has_no_value",
        ),
        Index("ix_google_record_metrics_metric_state", "metric_code", "state"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    record_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("google_source_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    metric_code: Mapped[str] = mapped_column(String(120), nullable=False)
    field_path: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    value_number: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(60), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    collection_json: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = [
    "AcquisitionSource",
    "AgreementCoverage",
    "AgreementMetricResult",
    "AgreementRuleSet",
    "AgreementRun",
    "AgreementRunExclusion",
    "AgreementRunPair",
    "Base",
    "CandidateDecision",
    "CanonicalRuleSet",
    "CanonicalSelection",
    "CanonicalSelectionRun",
    "CoverageInterval",
    "CoverageStatus",
    "DerivedMeasurement",
    "GarminActivityRecord",
    "GarminDailyRecord",
    "GarminFitRecord",
    "GarminIntradayRecord",
    "GarminMetricState",
    "GarminPayloadStatus",
    "GarminPayloadObservation",
    "GarminRawPayload",
    "GarminRecordMetric",
    "GarminSleepRecord",
    "GarminSleepStageInterval",
    "GarminSource",
    "GarminSourceRecord",
    "GoogleMetricState",
    "GooglePayloadObservation",
    "GooglePayloadStatus",
    "GoogleNormalizationAttempt",
    "GoogleProjectionStatus",
    "GoogleQueryMode",
    "GoogleRawPayload",
    "GoogleRecordInterval",
    "GoogleRecordMetric",
    "GoogleRecordSourceEvidence",
    "GoogleSleepRecord",
    "GoogleSleepFieldState",
    "GoogleSleepInterval",
    "GoogleSource",
    "GoogleSourceKind",
    "GoogleSourceRecord",
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
