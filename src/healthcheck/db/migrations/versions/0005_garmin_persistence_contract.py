"""Create the offline R02 Garmin persistence contract.

Revision ID: 0005_garmin_persistence_contract
Revises: 0004_naive_minute_wall_clock
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_garmin_persistence_contract"
down_revision = "0004_naive_minute_wall_clock"
branch_labels = None
depends_on = None


_STREAM_CHECK = "stream_code IN ('daily_health', 'sleep', 'activity', 'intraday', 'original_fit')"
_STATUS_CHECK = "parse_status IN ('ok', 'partial', 'empty', 'invalid')"


def _create_immutability_triggers() -> None:
    for table_name in ("garmin_sources", "garmin_raw_payloads"):
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS immutable_{table_name}_delete
            BEFORE DELETE ON {table_name}
            BEGIN
                SELECT RAISE(ABORT, '{table_name} are append-only');
            END
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS immutable_{table_name}_update
            BEFORE UPDATE ON {table_name}
            BEGIN
                SELECT RAISE(ABORT, '{table_name} are append-only');
            END
            """
        )


def _drop_immutability_triggers() -> None:
    for table_name in ("garmin_sources", "garmin_raw_payloads"):
        op.execute(f"DROP TRIGGER IF EXISTS immutable_{table_name}_delete")
        op.execute(f"DROP TRIGGER IF EXISTS immutable_{table_name}_update")


def upgrade() -> None:
    """Add raw Garmin payloads and typed current source projections."""

    op.create_table(
        "garmin_sources",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("acquisition_source_id", sa.String(36), nullable=False),
        sa.Column("physical_device_id", sa.String(36), nullable=True),
        sa.Column("source_kind", sa.String(40), nullable=False),
        sa.Column("provider_code", sa.String(120), nullable=False),
        sa.Column("source_instance_id", sa.String(255), nullable=False),
        sa.Column("device_attributed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("device_code", sa.String(160), nullable=True),
        sa.Column("device_model", sa.String(160), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("length(source_kind) > 0", name="source_kind_nonempty"),
        sa.CheckConstraint("length(provider_code) > 0", name="provider_code_nonempty"),
        sa.CheckConstraint("length(source_instance_id) > 0", name="source_instance_nonempty"),
        sa.CheckConstraint(
            "(device_attributed = 1 AND device_code IS NOT NULL AND device_model IS NOT NULL) "
            "OR (device_attributed = 0 AND device_code IS NULL AND device_model IS NULL)",
            name="device_identity_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["acquisition_source_id"], ["acquisition_sources.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["physical_device_id"], ["physical_devices.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_garmin_sources"),
        sa.UniqueConstraint(
            "provider_code", "source_instance_id", name="uq_garmin_sources_provider_instance"
        ),
    )
    op.create_index("ix_garmin_sources_acquisition", "garmin_sources", ["acquisition_source_id"])

    op.create_table(
        "garmin_raw_payloads",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("garmin_source_id", sa.String(36), nullable=False),
        sa.Column("raw_artifact_id", sa.String(36), nullable=False),
        sa.Column("ingest_event_id", sa.String(36), nullable=True),
        sa.Column("sync_run_id", sa.String(36), nullable=True),
        sa.Column("stream_code", sa.String(40), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("payload_format", sa.String(20), nullable=False),
        sa.Column("source_contract_version", sa.String(120), nullable=True),
        sa.Column("normalization_contract_version", sa.String(120), nullable=False),
        sa.Column("fixture_id", sa.String(255), nullable=True),
        sa.Column("parse_status", sa.String(20), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("diagnostics_json", sa.Text(), nullable=True),
        sa.Column("unknown_fields_json", sa.Text(), nullable=True),
        sa.Column("source_window_start_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_window_end_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(_STREAM_CHECK, name="stream_code_allowed"),
        sa.CheckConstraint(
            "payload_format IN ('json', 'fit', 'binary')", name="payload_format_allowed"
        ),
        sa.CheckConstraint(_STATUS_CHECK, name="parse_status_allowed"),
        sa.CheckConstraint("length(content_hash) >= 32", name="content_hash_min_length"),
        sa.CheckConstraint("record_count >= 0", name="record_count_nonnegative"),
        sa.ForeignKeyConstraint(["garmin_source_id"], ["garmin_sources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ingest_event_id"], ["ingest_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["raw_artifact_id"], ["raw_artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sync_run_id"], ["sync_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_garmin_raw_payloads"),
        sa.UniqueConstraint(
            "garmin_source_id",
            "stream_code",
            "content_hash",
            name="uq_garmin_raw_payloads_source_stream_hash",
        ),
    )
    op.create_index(
        "ix_garmin_raw_payloads_source_stream_received",
        "garmin_raw_payloads",
        ["garmin_source_id", "stream_code", "received_at"],
    )

    op.create_table(
        "garmin_source_records",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("garmin_source_id", sa.String(36), nullable=False),
        sa.Column("raw_payload_id", sa.String(36), nullable=False),
        sa.Column("ingest_event_id", sa.String(36), nullable=True),
        sa.Column("stream_code", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("external_record_id", sa.String(255), nullable=True),
        sa.Column("record_index", sa.Integer(), nullable=True),
        sa.Column("activity_type", sa.String(120), nullable=True),
        sa.Column("source_path", sa.String(255), nullable=True),
        sa.Column("temporal_precision", sa.String(20), nullable=False),
        sa.Column("source_local_date", sa.Date(), nullable=True),
        sa.Column("source_timestamp_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("local_wall_time", sa.String(100), nullable=True),
        sa.Column("source_local_timestamp", sa.String(100), nullable=True),
        sa.Column("source_utc_offset_minutes", sa.Integer(), nullable=True),
        sa.Column("source_timezone", sa.String(100), nullable=True),
        sa.Column("source_field", sa.String(255), nullable=True),
        sa.Column("source_local_field", sa.String(255), nullable=True),
        sa.Column("source_utc_field", sa.String(255), nullable=True),
        sa.Column("record_status", sa.String(20), nullable=False),
        sa.Column("normalization_contract_version", sa.String(120), nullable=False),
        sa.Column("diagnostics_json", sa.Text(), nullable=True),
        sa.Column("unknown_fields_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(_STREAM_CHECK, name="stream_code_allowed"),
        sa.CheckConstraint(
            "temporal_precision IN ('unknown', 'date', 'instant', 'local')",
            name="temporal_precision_allowed",
        ),
        sa.CheckConstraint(
            _STATUS_CHECK.replace("parse_status", "record_status"), name="record_status_allowed"
        ),
        sa.CheckConstraint(
            "record_index IS NULL OR record_index >= 0", name="record_index_nonnegative"
        ),
        sa.CheckConstraint(
            "source_utc_offset_minutes IS NULL OR "
            "(source_utc_offset_minutes >= -840 AND source_utc_offset_minutes <= 840)",
            name="source_utc_offset_range",
        ),
        sa.CheckConstraint(
            "(temporal_precision = 'instant' AND source_timestamp_utc IS NOT NULL) "
            "OR (temporal_precision = 'local' AND local_wall_time IS NOT NULL) "
            "OR temporal_precision IN ('unknown', 'date')",
            name="temporal_precision_consistency",
        ),
        sa.ForeignKeyConstraint(["garmin_source_id"], ["garmin_sources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ingest_event_id"], ["ingest_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["raw_payload_id"], ["garmin_raw_payloads.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_garmin_source_records"),
        sa.UniqueConstraint(
            "garmin_source_id",
            "idempotency_key",
            name="uq_garmin_source_records_source_idempotency",
        ),
    )
    op.create_index(
        "ix_garmin_source_records_stream_date",
        "garmin_source_records",
        ["garmin_source_id", "stream_code", "source_local_date"],
    )
    op.create_index(
        "ix_garmin_source_records_external_id",
        "garmin_source_records",
        ["garmin_source_id", "stream_code", "external_record_id"],
    )

    op.create_table(
        "garmin_daily_records",
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["record_id"], ["garmin_source_records.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("record_id", name="pk_garmin_daily_records"),
    )
    op.create_table(
        "garmin_sleep_records",
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("wake_date", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["record_id"], ["garmin_source_records.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("record_id", name="pk_garmin_sleep_records"),
    )
    op.create_table(
        "garmin_activity_records",
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("activity_type", sa.String(120), nullable=True),
        sa.ForeignKeyConstraint(["record_id"], ["garmin_source_records.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("record_id", name="pk_garmin_activity_records"),
    )
    op.create_table(
        "garmin_intraday_records",
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("sample_date", sa.Date(), nullable=True),
        sa.Column("sample_sequence", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["record_id"], ["garmin_source_records.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("record_id", name="pk_garmin_intraday_records"),
    )
    op.create_table(
        "garmin_fit_records",
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["record_id"], ["garmin_source_records.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("record_id", name="pk_garmin_fit_records"),
    )

    op.create_table(
        "garmin_record_metrics",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("capability_code", sa.String(120), nullable=False),
        sa.Column("metric_code", sa.String(120), nullable=False),
        sa.Column("field_path", sa.String(255), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("value_number", sa.Float(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(60), nullable=True),
        sa.Column("reason", sa.String(120), nullable=True),
        sa.Column("capability_status", sa.String(40), nullable=True),
        sa.Column(
            "source_device_attributed", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("collection_json", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "state IN ('missing', 'null', 'value', 'invalid')", name="state_allowed"
        ),
        sa.CheckConstraint(
            "state = 'value' OR "
            "(value_number IS NULL AND value_text IS NULL AND collection_json IS NULL)",
            name="non_value_has_no_value",
        ),
        sa.ForeignKeyConstraint(["record_id"], ["garmin_source_records.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_garmin_record_metrics"),
        sa.UniqueConstraint(
            "record_id", "metric_code", name="uq_garmin_record_metrics_record_metric"
        ),
    )
    op.create_index(
        "ix_garmin_record_metrics_metric_state",
        "garmin_record_metrics",
        ["metric_code", "state"],
    )

    op.create_table(
        "garmin_sleep_stage_intervals",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("sleep_record_id", sa.String(36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_precision", sa.String(20), nullable=False),
        sa.Column("end_precision", sa.String(20), nullable=False),
        sa.Column("start_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_local_date", sa.Date(), nullable=True),
        sa.Column("end_local_date", sa.Date(), nullable=True),
        sa.Column("start_local_wall_time", sa.String(100), nullable=True),
        sa.Column("end_local_wall_time", sa.String(100), nullable=True),
        sa.Column("start_source_timestamp", sa.String(100), nullable=True),
        sa.Column("end_source_timestamp", sa.String(100), nullable=True),
        sa.Column("start_source_timezone", sa.String(100), nullable=True),
        sa.Column("end_source_timezone", sa.String(100), nullable=True),
        sa.Column("start_utc_offset_minutes", sa.Integer(), nullable=True),
        sa.Column("end_utc_offset_minutes", sa.Integer(), nullable=True),
        sa.Column("start_source_field", sa.String(255), nullable=True),
        sa.Column("end_source_field", sa.String(255), nullable=True),
        sa.Column("activity_level", sa.String(80), nullable=True),
        sa.Column("start_temporal_json", sa.Text(), nullable=False),
        sa.Column("end_temporal_json", sa.Text(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        sa.CheckConstraint(
            "start_at_utc IS NULL OR end_at_utc IS NULL OR end_at_utc > start_at_utc",
            name="interval_order",
        ),
        sa.ForeignKeyConstraint(
            ["sleep_record_id"], ["garmin_sleep_records.record_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_garmin_sleep_stage_intervals"),
        sa.UniqueConstraint(
            "sleep_record_id", "ordinal", name="uq_garmin_sleep_stage_intervals_ordinal"
        ),
    )
    op.create_index(
        "ix_garmin_sleep_stage_intervals_start",
        "garmin_sleep_stage_intervals",
        ["sleep_record_id", "start_at_utc"],
    )

    _create_immutability_triggers()


def downgrade() -> None:
    """Remove R02 Garmin tables in dependency order."""

    _drop_immutability_triggers()
    for table_name in (
        "garmin_sleep_stage_intervals",
        "garmin_record_metrics",
        "garmin_fit_records",
        "garmin_intraday_records",
        "garmin_activity_records",
        "garmin_sleep_records",
        "garmin_daily_records",
        "garmin_source_records",
        "garmin_raw_payloads",
        "garmin_sources",
    ):
        op.drop_table(table_name)
