"""Add typed Google Health interval, source, and replay-attempt projections.

Revision ID: 0010_google_typed_normalization
Revises: 0009_google_persistence_contract

This revision is forward-only and additive.  It does not alter or recreate
the populated R01-R03 tables or any accepted 0009 Google table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_google_typed_normalization"
down_revision = "0009_google_persistence_contract"
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
_STATE_CHECK = "IN ('missing', 'null', 'value', 'invalid')"


def _endpoint_columns(prefix: str) -> list[sa.Column]:
    """Return the explicit temporal/provenance columns for one endpoint."""

    return [
        sa.Column(f"{prefix}_precision", sa.String(20), nullable=False),
        sa.Column(f"{prefix}_state", sa.String(20), nullable=False),
        sa.Column(f"{prefix}_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(f"{prefix}_local_date", sa.Date(), nullable=True),
        sa.Column(f"{prefix}_local_wall_time", sa.String(100), nullable=True),
        sa.Column(f"{prefix}_source_timestamp", sa.String(100), nullable=True),
        sa.Column(f"{prefix}_utc_offset_minutes", sa.Integer(), nullable=True),
        sa.Column(f"{prefix}_source_timezone", sa.String(100), nullable=True),
        sa.Column(f"{prefix}_source_field", sa.String(255), nullable=True),
        sa.Column(f"{prefix}_source_local_field", sa.String(255), nullable=True),
        sa.Column(f"{prefix}_source_utc_field", sa.String(255), nullable=True),
        sa.Column(f"{prefix}_temporal_json", sa.Text(), nullable=False),
    ]


def _endpoint_checks(*, prefix: str, constraint_prefix: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint(
            f"{prefix}_precision IN ('unknown', 'date', 'instant', 'local')",
            name=f"{constraint_prefix}_{prefix}_precision_allowed",
        ),
        sa.CheckConstraint(
            f"{prefix}_state {_STATE_CHECK}",
            name=f"{constraint_prefix}_{prefix}_state_allowed",
        ),
        sa.CheckConstraint(
            f"{prefix}_utc_offset_minutes IS NULL OR "
            f"({prefix}_utc_offset_minutes >= -1439 AND "
            f"{prefix}_utc_offset_minutes <= 1439)",
            name=f"{constraint_prefix}_{prefix}_offset_range",
        ),
    ]


def _create_immutability_trigger() -> None:
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS immutable_google_normalization_attempts_delete
        BEFORE DELETE ON google_normalization_attempts
        BEGIN
            SELECT RAISE(ABORT, 'google_normalization_attempts are append-only');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS immutable_google_normalization_attempts_update
        BEFORE UPDATE ON google_normalization_attempts
        BEGIN
            SELECT RAISE(ABORT, 'google_normalization_attempts are append-only');
        END
        """
    )


def _drop_immutability_trigger() -> None:
    op.execute("DROP TRIGGER IF EXISTS immutable_google_normalization_attempts_delete")
    op.execute("DROP TRIGGER IF EXISTS immutable_google_normalization_attempts_update")


def upgrade() -> None:
    """Add bounded typed interval/source evidence and immutable attempts."""

    op.create_table(
        "google_record_intervals",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("interval_kind", sa.String(40), nullable=False),
        sa.Column("interval_state", sa.String(20), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        *_endpoint_columns("start"),
        *_endpoint_columns("end"),
        sa.CheckConstraint(
            "interval_kind IN ('roll_up', 'daily_roll_up')",
            name="interval_kind_allowed",
        ),
        sa.CheckConstraint(
            "interval_state IN ('missing', 'null', 'value', 'invalid')",
            name="interval_state_allowed",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        *_endpoint_checks(prefix="start", constraint_prefix="record_interval"),
        *_endpoint_checks(prefix="end", constraint_prefix="record_interval"),
        sa.CheckConstraint(
            "start_at_utc IS NULL OR end_at_utc IS NULL OR end_at_utc > start_at_utc",
            name="interval_order",
        ),
        sa.ForeignKeyConstraint(["record_id"], ["google_source_records.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_google_record_intervals"),
        sa.UniqueConstraint(
            "record_id",
            "interval_kind",
            "ordinal",
            name="uq_google_record_intervals_kind_ordinal",
        ),
    )
    op.create_index(
        "ix_google_record_intervals_start", "google_record_intervals", ["record_id", "start_at_utc"]
    )

    op.create_table(
        "google_sleep_intervals",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("sleep_record_id", sa.String(36), nullable=False),
        sa.Column("interval_kind", sa.String(40), nullable=False),
        sa.Column("interval_state", sa.String(20), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("stage_type", sa.String(60), nullable=True),
        sa.Column("create_time", sa.String(100), nullable=True),
        sa.Column("update_time", sa.String(100), nullable=True),
        *_endpoint_columns("start"),
        *_endpoint_columns("end"),
        sa.CheckConstraint(
            "interval_kind IN ('sleep_session', 'sleep_stage', 'sleep_out_of_bed')",
            name="interval_kind_allowed",
        ),
        sa.CheckConstraint(
            "interval_state IN ('missing', 'null', 'value', 'invalid')",
            name="interval_state_allowed",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        sa.CheckConstraint(
            "(interval_kind = 'sleep_stage' AND stage_type IS NOT NULL) OR "
            "(interval_kind <> 'sleep_stage' AND stage_type IS NULL)",
            name="stage_type_consistency",
        ),
        *_endpoint_checks(prefix="start", constraint_prefix="sleep_interval"),
        *_endpoint_checks(prefix="end", constraint_prefix="sleep_interval"),
        sa.CheckConstraint(
            "start_at_utc IS NULL OR end_at_utc IS NULL OR end_at_utc > start_at_utc",
            name="interval_order",
        ),
        sa.ForeignKeyConstraint(
            ["sleep_record_id"], ["google_sleep_records.record_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_google_sleep_intervals"),
        sa.UniqueConstraint(
            "sleep_record_id",
            "interval_kind",
            "ordinal",
            name="uq_google_sleep_intervals_kind_ordinal",
        ),
    )
    op.create_index(
        "ix_google_sleep_intervals_start",
        "google_sleep_intervals",
        ["sleep_record_id", "start_at_utc"],
    )

    op.create_table(
        "google_sleep_field_states",
        sa.Column("sleep_record_id", sa.String(36), nullable=False),
        sa.Column("sleep_interval_state", sa.String(20), nullable=False),
        sa.Column("sleep_stages_state", sa.String(20), nullable=False),
        sa.Column("out_of_bed_state", sa.String(20), nullable=False),
        sa.CheckConstraint(
            "sleep_interval_state IN ('missing', 'null', 'value', 'invalid')",
            name="sleep_interval_state_allowed",
        ),
        sa.CheckConstraint(
            "sleep_stages_state IN ('missing', 'null', 'value', 'invalid')",
            name="sleep_stages_state_allowed",
        ),
        sa.CheckConstraint(
            "out_of_bed_state IN ('missing', 'null', 'value', 'invalid')",
            name="out_of_bed_state_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["sleep_record_id"], ["google_sleep_records.record_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("sleep_record_id", name="pk_google_sleep_field_states"),
    )

    op.create_table(
        "google_record_source_evidence",
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("field_path", sa.String(255), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.CheckConstraint(f"state {_STATE_CHECK}", name="state_allowed"),
        sa.ForeignKeyConstraint(["record_id"], ["google_source_records.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("record_id", name="pk_google_record_source_evidence"),
    )

    op.create_table(
        "google_normalization_attempts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("google_source_id", sa.String(36), nullable=False),
        sa.Column("google_raw_payload_id", sa.String(36), nullable=False),
        sa.Column("observation_id", sa.String(36), nullable=False),
        sa.Column("attempt_key", sa.String(128), nullable=False),
        sa.Column("stream_code", sa.String(40), nullable=False),
        sa.Column("query_mode", sa.String(40), nullable=False),
        sa.Column("data_source_family", sa.String(255), nullable=True),
        sa.Column("source_contract_version", sa.String(120), nullable=True),
        sa.Column("normalization_contract_version", sa.String(120), nullable=False),
        sa.Column("parse_status", sa.String(20), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("projection_fingerprint", sa.String(128), nullable=False),
        sa.Column("projection_json", sa.Text(), nullable=False),
        sa.Column("diagnostics_json", sa.Text(), nullable=True),
        sa.Column("unknown_fields_json", sa.Text(), nullable=True),
        sa.Column(
            "attempted_at",
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
        sa.CheckConstraint(_STATUS_CHECK, name="parse_status_allowed"),
        sa.CheckConstraint("record_count >= 0", name="record_count_nonnegative"),
        sa.CheckConstraint("length(attempt_key) >= 32", name="attempt_key_min_length"),
        sa.ForeignKeyConstraint(["google_source_id"], ["google_sources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["google_raw_payload_id"], ["google_raw_payloads.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["google_payload_observations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_google_normalization_attempts"),
        sa.UniqueConstraint("attempt_key", name="uq_google_normalization_attempts_key"),
    )
    op.create_index(
        "ix_google_normalization_attempts_observation_version",
        "google_normalization_attempts",
        ["observation_id", "normalization_contract_version"],
    )
    _create_immutability_trigger()


def downgrade() -> None:
    """Remove only the additive 0010 Google tables."""

    _drop_immutability_trigger()
    for table_name in (
        "google_normalization_attempts",
        "google_record_source_evidence",
        "google_sleep_field_states",
        "google_sleep_intervals",
        "google_record_intervals",
    ):
        op.drop_table(table_name)
