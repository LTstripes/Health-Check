"""Create the offline R04 Google Health persistence contract.

Revision ID: 0009_google_persistence_contract
Revises: 0008_garmin_observation_reconciliation_version

Forward-only additive tables.  This revision does not ALTER or recreate any
R01–R03 parent table, so a populated owner database cannot hit the #76
batch-recreate failure class.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_google_persistence_contract"
down_revision = "0008_garmin_observation_reconciliation_version"
branch_labels = None
depends_on = None


_STREAM_CHECK = (
    "stream_code IN ('sleep', 'heart_rate', 'hrv', 'daily_hrv', "
    "'daily_resting_hr', 'spo2', 'daily_spo2', "
    "'respiratory_rate_sleep', 'daily_respiratory_rate')"
)
_STATUS_CHECK = "parse_status IN ('ok', 'partial', 'empty', 'invalid')"
_QUERY_MODE_CHECK = "query_mode IN ('list', 'reconcile', 'rollUp', 'dailyRollUp')"
_FAMILY_CHECK = (
    "data_source_family IS NULL OR ("
    "length(data_source_family) > 0 AND "
    "data_source_family LIKE 'users/%/dataSourceFamilies/%')"
)


def _create_immutability_triggers() -> None:
    for table_name in ("google_sources", "google_raw_payloads", "google_payload_observations"):
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
    for table_name in ("google_sources", "google_raw_payloads", "google_payload_observations"):
        op.execute(f"DROP TRIGGER IF EXISTS immutable_{table_name}_delete")
        op.execute(f"DROP TRIGGER IF EXISTS immutable_{table_name}_update")


def upgrade() -> None:
    """Add explicit Google source, raw, observation, and typed-record shell tables."""

    op.create_table(
        "google_sources",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("acquisition_source_id", sa.String(36), nullable=False),
        sa.Column("physical_device_id", sa.String(36), nullable=True),
        sa.Column("source_kind", sa.String(40), nullable=False),
        sa.Column("provider_code", sa.String(120), nullable=False),
        sa.Column("source_instance_id", sa.String(512), nullable=False),
        sa.Column("data_source_name", sa.String(512), nullable=True),
        sa.Column("data_source_id", sa.String(255), nullable=True),
        sa.Column("platform", sa.String(120), nullable=True),
        sa.Column("recording_method", sa.String(120), nullable=True),
        sa.Column("device_attributed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("device_code", sa.String(160), nullable=True),
        sa.Column("device_manufacturer", sa.String(160), nullable=True),
        sa.Column("device_model", sa.String(160), nullable=True),
        sa.Column("device_uid", sa.String(255), nullable=True),
        sa.Column("source_contract_version", sa.String(120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "source_kind IN ('data_source', 'family_aggregate')", name="source_kind_allowed"
        ),
        sa.CheckConstraint("length(source_kind) > 0", name="source_kind_nonempty"),
        sa.CheckConstraint("length(provider_code) > 0", name="provider_code_nonempty"),
        sa.CheckConstraint("length(source_instance_id) > 0", name="source_instance_nonempty"),
        sa.CheckConstraint(
            "(device_attributed = 1 AND device_code IS NOT NULL AND device_model IS NOT NULL) "
            "OR (device_attributed = 0 AND device_code IS NULL AND device_model IS NULL "
            "AND device_manufacturer IS NULL AND device_uid IS NULL)",
            name="device_identity_consistency",
        ),
        sa.CheckConstraint(
            "source_kind <> 'family_aggregate' OR device_attributed = 0",
            name="family_aggregate_unattributed",
        ),
        sa.ForeignKeyConstraint(
            ["acquisition_source_id"], ["acquisition_sources.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["physical_device_id"], ["physical_devices.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_google_sources"),
        sa.UniqueConstraint(
            "provider_code", "source_instance_id", name="uq_google_sources_provider_instance"
        ),
    )
    op.create_index("ix_google_sources_acquisition", "google_sources", ["acquisition_source_id"])

    op.create_table(
        "google_raw_payloads",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("google_source_id", sa.String(36), nullable=False),
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
        sa.CheckConstraint("payload_format IN ('json', 'binary')", name="payload_format_allowed"),
        sa.CheckConstraint(_STATUS_CHECK, name="parse_status_allowed"),
        sa.CheckConstraint("length(content_hash) >= 32", name="content_hash_min_length"),
        sa.CheckConstraint("record_count >= 0", name="record_count_nonnegative"),
        sa.ForeignKeyConstraint(["google_source_id"], ["google_sources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ingest_event_id"], ["ingest_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["raw_artifact_id"], ["raw_artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sync_run_id"], ["sync_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_google_raw_payloads"),
        sa.UniqueConstraint(
            "google_source_id",
            "stream_code",
            "content_hash",
            name="uq_google_raw_payloads_source_stream_hash",
        ),
    )
    op.create_index(
        "ix_google_raw_payloads_source_stream_received",
        "google_raw_payloads",
        ["google_source_id", "stream_code", "received_at"],
    )

    op.create_table(
        "google_payload_observations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("google_raw_payload_id", sa.String(36), nullable=False),
        sa.Column("raw_artifact_id", sa.String(36), nullable=False),
        sa.Column("google_source_id", sa.String(36), nullable=False),
        sa.Column("ingest_event_id", sa.String(36), nullable=True),
        sa.Column("sync_run_id", sa.String(36), nullable=True),
        sa.Column("observation_key", sa.String(128), nullable=False),
        sa.Column("stream_code", sa.String(40), nullable=False),
        sa.Column("query_mode", sa.String(40), nullable=False),
        sa.Column("data_source_family", sa.String(255), nullable=True),
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
        sa.Column("source_filename", sa.String(255), nullable=True),
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
        sa.CheckConstraint(_QUERY_MODE_CHECK, name="query_mode_allowed"),
        sa.CheckConstraint(_FAMILY_CHECK, name="data_source_family_resource"),
        sa.CheckConstraint("payload_format IN ('json', 'binary')", name="payload_format_allowed"),
        sa.CheckConstraint(_STATUS_CHECK, name="parse_status_allowed"),
        sa.CheckConstraint("length(observation_key) >= 32", name="observation_key_min_length"),
        sa.CheckConstraint("record_count >= 0", name="record_count_nonnegative"),
        sa.ForeignKeyConstraint(
            ["google_raw_payload_id"], ["google_raw_payloads.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["raw_artifact_id"], ["raw_artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["google_source_id"], ["google_sources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ingest_event_id"], ["ingest_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sync_run_id"], ["sync_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_google_payload_observations"),
        sa.UniqueConstraint("observation_key", name="uq_google_payload_observations_key"),
    )
    op.create_index(
        "ix_google_payload_observations_source_stream_received",
        "google_payload_observations",
        ["google_source_id", "stream_code", "received_at"],
    )
    op.create_index(
        "ix_google_payload_observations_query_context",
        "google_payload_observations",
        ["google_source_id", "query_mode", "data_source_family"],
    )

    op.create_table(
        "google_source_records",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("google_source_id", sa.String(36), nullable=False),
        sa.Column("raw_payload_id", sa.String(36), nullable=False),
        sa.Column("observation_id", sa.String(36), nullable=True),
        sa.Column("ingest_event_id", sa.String(36), nullable=True),
        sa.Column("stream_code", sa.String(40), nullable=False),
        sa.Column("query_mode", sa.String(40), nullable=False),
        sa.Column("data_source_family", sa.String(255), nullable=True),
        sa.Column("record_identity_key", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("external_record_id", sa.String(255), nullable=True),
        sa.Column("record_index", sa.Integer(), nullable=True),
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
        sa.Column("source_contract_version", sa.String(120), nullable=True),
        sa.Column("normalization_contract_version", sa.String(120), nullable=False),
        sa.Column("diagnostics_json", sa.Text(), nullable=True),
        sa.Column("unknown_fields_json", sa.Text(), nullable=True),
        sa.Column(
            "projection_status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'current'"),
        ),
        sa.Column("projection_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retire_reason", sa.String(80), nullable=True),
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
        sa.CheckConstraint(_QUERY_MODE_CHECK, name="query_mode_allowed"),
        sa.CheckConstraint(_FAMILY_CHECK, name="data_source_family_resource"),
        sa.CheckConstraint(
            "temporal_precision IN ('unknown', 'date', 'instant', 'local')",
            name="temporal_precision_allowed",
        ),
        sa.CheckConstraint(
            "record_status IN ('ok', 'partial', 'empty', 'invalid')",
            name="record_status_allowed",
        ),
        sa.CheckConstraint(
            "record_index IS NULL OR record_index >= 0", name="record_index_nonnegative"
        ),
        sa.CheckConstraint(
            "source_utc_offset_minutes IS NULL OR "
            "(source_utc_offset_minutes >= -1439 AND source_utc_offset_minutes <= 1439)",
            name="source_utc_offset_range",
        ),
        sa.CheckConstraint(
            "(temporal_precision = 'instant' AND source_timestamp_utc IS NOT NULL) "
            "OR (temporal_precision = 'local' AND local_wall_time IS NOT NULL) "
            "OR temporal_precision IN ('unknown', 'date')",
            name="temporal_precision_consistency",
        ),
        sa.CheckConstraint(
            "projection_status IN ('current', 'retired')",
            name="projection_status_allowed",
        ),
        sa.CheckConstraint(
            "(projection_status = 'current' AND retired_at IS NULL AND retire_reason IS NULL) "
            "OR (projection_status = 'retired' AND retired_at IS NOT NULL)",
            name="projection_retirement_consistency",
        ),
        sa.ForeignKeyConstraint(["google_source_id"], ["google_sources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["raw_payload_id"], ["google_raw_payloads.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["google_payload_observations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["ingest_event_id"], ["ingest_events.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_google_source_records"),
        sa.UniqueConstraint(
            "google_source_id",
            "record_identity_key",
            name="uq_google_source_records_source_identity",
        ),
    )
    op.create_index(
        "ix_google_source_records_stream_date",
        "google_source_records",
        ["google_source_id", "stream_code", "source_local_date"],
    )
    op.create_index(
        "ix_google_source_records_query_context",
        "google_source_records",
        ["google_source_id", "stream_code", "query_mode", "data_source_family"],
    )
    op.create_index(
        "ix_google_source_records_external_id",
        "google_source_records",
        ["google_source_id", "stream_code", "external_record_id"],
    )

    op.create_table(
        "google_sleep_records",
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("wake_date", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["record_id"], ["google_source_records.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("record_id", name="pk_google_sleep_records"),
    )

    op.create_table(
        "google_record_metrics",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("metric_code", sa.String(120), nullable=False),
        sa.Column("field_path", sa.String(255), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("value_number", sa.Float(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(60), nullable=True),
        sa.Column("reason", sa.String(120), nullable=True),
        sa.Column("collection_json", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "state IN ('missing', 'null', 'value', 'invalid')", name="state_allowed"
        ),
        sa.CheckConstraint(
            "state = 'value' OR "
            "(value_number IS NULL AND value_text IS NULL AND collection_json IS NULL)",
            name="non_value_has_no_value",
        ),
        sa.ForeignKeyConstraint(["record_id"], ["google_source_records.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_google_record_metrics"),
        sa.UniqueConstraint(
            "record_id", "metric_code", name="uq_google_record_metrics_record_metric"
        ),
    )
    op.create_index(
        "ix_google_record_metrics_metric_state",
        "google_record_metrics",
        ["metric_code", "state"],
    )

    _create_immutability_triggers()


def downgrade() -> None:
    """Remove R04 Google tables in dependency order. Does not touch R01–R03 tables."""

    _drop_immutability_triggers()
    for table_name in (
        "google_record_metrics",
        "google_sleep_records",
        "google_source_records",
        "google_payload_observations",
        "google_raw_payloads",
        "google_sources",
    ):
        op.drop_table(table_name)
