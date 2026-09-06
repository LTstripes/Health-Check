"""Separate repeated Garmin acquisition/normalization observations from raw bytes.

Revision ID: 0006_garmin_payload_observation_provenance
Revises: 0005_garmin_persistence_contract
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0006_garmin_payload_observation_provenance"
down_revision = "0005_garmin_persistence_contract"
branch_labels = None
depends_on = None


_STREAM_CHECK = "stream_code IN ('daily_health', 'sleep', 'activity', 'intraday', 'original_fit')"
_STATUS_CHECK = "parse_status IN ('ok', 'partial', 'empty', 'invalid')"
_OBSERVATION_KEY_VERSION = "garmin-observation-v1"
_WIDE_OFFSET_CHECK = (
    "source_utc_offset_minutes IS NULL OR "
    "(source_utc_offset_minutes >= -1439 AND source_utc_offset_minutes <= 1439)"
)
_LEGACY_OFFSET_CHECK = (
    "source_utc_offset_minutes IS NULL OR "
    "(source_utc_offset_minutes >= -840 AND source_utc_offset_minutes <= 840)"
)
_STAGE_WIDE_OFFSET_CHECK = (
    "(start_utc_offset_minutes IS NULL OR "
    "(start_utc_offset_minutes >= -1439 AND start_utc_offset_minutes <= 1439)) "
    "AND (end_utc_offset_minutes IS NULL OR "
    "(end_utc_offset_minutes >= -1439 AND end_utc_offset_minutes <= 1439))"
)
_STAGE_LEGACY_OFFSET_CHECK = (
    "(start_utc_offset_minutes IS NULL OR "
    "(start_utc_offset_minutes >= -840 AND start_utc_offset_minutes <= 840)) "
    "AND (end_utc_offset_minutes IS NULL OR "
    "(end_utc_offset_minutes >= -840 AND end_utc_offset_minutes <= 840))"
)


def _create_observation_immutability_triggers() -> None:
    for action in ("DELETE", "UPDATE"):
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS immutable_garmin_payload_observations_{action.lower()}
            BEFORE {action} ON garmin_payload_observations
            BEGIN
                SELECT RAISE(ABORT, 'garmin_payload_observations are append-only');
            END
            """
        )


def _drop_observation_immutability_triggers() -> None:
    op.execute("DROP TRIGGER IF EXISTS immutable_garmin_payload_observations_delete")
    op.execute("DROP TRIGGER IF EXISTS immutable_garmin_payload_observations_update")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _timestamp_key(value: object) -> str | None:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _observation_key(row: sa.RowMapping, source_filename: str | None) -> str:
    payload = {
        "version": _OBSERVATION_KEY_VERSION,
        "garmin_source_id": row["garmin_source_id"],
        "stream_code": row["stream_code"],
        "content_hash": str(row["content_hash"]).lower(),
        "payload_format": row["payload_format"],
        "source_contract_version": row["source_contract_version"],
        "normalization_contract_version": row["normalization_contract_version"],
        "fixture_id": row["fixture_id"],
        "parse_status": row["parse_status"],
        "record_count": row["record_count"],
        "diagnostics_json": row["diagnostics_json"],
        "unknown_fields_json": row["unknown_fields_json"],
        "source_window_start_utc": _timestamp_key(row["source_window_start_utc"]),
        "source_window_end_utc": _timestamp_key(row["source_window_end_utc"]),
        "sync_run_id": row["sync_run_id"],
        "source_filename": source_filename,
    }
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{_OBSERVATION_KEY_VERSION}:{digest}"


def _backfill_observations() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT p.id, p.garmin_source_id, p.raw_artifact_id, p.ingest_event_id,
                   p.sync_run_id, p.stream_code, p.content_hash, p.payload_format,
                   p.source_contract_version, p.normalization_contract_version,
                   p.fixture_id, p.parse_status, p.record_count, p.diagnostics_json,
                   p.unknown_fields_json, p.source_window_start_utc,
                   p.source_window_end_utc, p.received_at, p.created_at,
                   a.source_filename
            FROM garmin_raw_payloads AS p
            LEFT JOIN raw_artifacts AS a ON a.id = p.raw_artifact_id
            ORDER BY p.id
            """
        )
    )
    for row in rows:
        mapping = row._mapping
        source_filename = mapping["source_filename"]
        bind.execute(
            sa.text(
                """
                INSERT INTO garmin_payload_observations (
                    id, garmin_raw_payload_id, raw_artifact_id, garmin_source_id,
                    ingest_event_id, sync_run_id, observation_key, stream_code,
                    payload_format, source_contract_version,
                    normalization_contract_version, fixture_id, parse_status,
                    record_count, diagnostics_json, unknown_fields_json,
                    source_window_start_utc, source_window_end_utc, source_filename,
                    received_at, created_at
                ) VALUES (
                    :id, :garmin_raw_payload_id, :raw_artifact_id, :garmin_source_id,
                    :ingest_event_id, :sync_run_id, :observation_key, :stream_code,
                    :payload_format, :source_contract_version,
                    :normalization_contract_version, :fixture_id, :parse_status,
                    :record_count, :diagnostics_json, :unknown_fields_json,
                    :source_window_start_utc, :source_window_end_utc, :source_filename,
                    :received_at, :created_at
                )
                """
            ),
            {
                "id": mapping["id"],
                "garmin_raw_payload_id": mapping["id"],
                "raw_artifact_id": mapping["raw_artifact_id"],
                "garmin_source_id": mapping["garmin_source_id"],
                "ingest_event_id": mapping["ingest_event_id"],
                "sync_run_id": mapping["sync_run_id"],
                "observation_key": _observation_key(mapping, source_filename),
                "stream_code": mapping["stream_code"],
                "payload_format": mapping["payload_format"],
                "source_contract_version": mapping["source_contract_version"],
                "normalization_contract_version": mapping["normalization_contract_version"],
                "fixture_id": mapping["fixture_id"],
                "parse_status": mapping["parse_status"],
                "record_count": mapping["record_count"],
                "diagnostics_json": mapping["diagnostics_json"],
                "unknown_fields_json": mapping["unknown_fields_json"],
                "source_window_start_utc": mapping["source_window_start_utc"],
                "source_window_end_utc": mapping["source_window_end_utc"],
                "source_filename": source_filename,
                "received_at": mapping["received_at"],
                "created_at": mapping["created_at"],
            },
        )


def upgrade() -> None:
    """Add immutable per-observation provenance and widen Garmin offsets."""

    op.create_table(
        "garmin_payload_observations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("garmin_raw_payload_id", sa.String(36), nullable=False),
        sa.Column("raw_artifact_id", sa.String(36), nullable=False),
        sa.Column("garmin_source_id", sa.String(36), nullable=False),
        sa.Column("ingest_event_id", sa.String(36), nullable=True),
        sa.Column("sync_run_id", sa.String(36), nullable=True),
        sa.Column("observation_key", sa.String(128), nullable=False),
        sa.Column("stream_code", sa.String(40), nullable=False),
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
        sa.CheckConstraint(
            "payload_format IN ('json', 'fit', 'binary')", name="payload_format_allowed"
        ),
        sa.CheckConstraint(_STATUS_CHECK, name="parse_status_allowed"),
        sa.CheckConstraint("length(observation_key) >= 32", name="observation_key_min_length"),
        sa.CheckConstraint("record_count >= 0", name="record_count_nonnegative"),
        sa.ForeignKeyConstraint(
            ["garmin_raw_payload_id"], ["garmin_raw_payloads.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["raw_artifact_id"], ["raw_artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["garmin_source_id"], ["garmin_sources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ingest_event_id"], ["ingest_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sync_run_id"], ["sync_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_garmin_payload_observations"),
        sa.UniqueConstraint("observation_key", name="uq_garmin_payload_observations_key"),
    )
    op.create_index(
        "ix_garmin_payload_observations_source_stream_received",
        "garmin_payload_observations",
        ["garmin_source_id", "stream_code", "received_at"],
    )
    _backfill_observations()
    _create_observation_immutability_triggers()

    with op.batch_alter_table("garmin_source_records", recreate="always") as batch_op:
        batch_op.drop_constraint("source_utc_offset_range", type_="check")
        batch_op.create_check_constraint("source_utc_offset_range", _WIDE_OFFSET_CHECK)
    with op.batch_alter_table("garmin_sleep_stage_intervals", recreate="always") as batch_op:
        batch_op.create_check_constraint("stage_utc_offset_range", _STAGE_WIDE_OFFSET_CHECK)


def downgrade() -> None:
    """Remove observations without silently losing values outside the old range."""

    bind = op.get_bind()
    source_conflict = bind.execute(
        sa.text(
            """
            SELECT id
            FROM garmin_source_records
            WHERE source_utc_offset_minutes < -840
               OR source_utc_offset_minutes > 840
            LIMIT 1
            """
        )
    ).first()
    if source_conflict is not None:
        raise RuntimeError(
            "cannot downgrade 0006: Garmin source record has an offset outside +/-14:00"
        )
    stage_conflict = bind.execute(
        sa.text(
            """
            SELECT id
            FROM garmin_sleep_stage_intervals
            WHERE start_utc_offset_minutes < -840
               OR start_utc_offset_minutes > 840
               OR end_utc_offset_minutes < -840
               OR end_utc_offset_minutes > 840
            LIMIT 1
            """
        )
    ).first()
    if stage_conflict is not None:
        raise RuntimeError("cannot downgrade 0006: sleep stage has an offset outside +/-14:00")

    _drop_observation_immutability_triggers()
    op.drop_index(
        "ix_garmin_payload_observations_source_stream_received",
        table_name="garmin_payload_observations",
    )
    op.drop_table("garmin_payload_observations")

    with op.batch_alter_table("garmin_sleep_stage_intervals", recreate="always") as batch_op:
        batch_op.drop_constraint("stage_utc_offset_range", type_="check")
        batch_op.create_check_constraint("stage_utc_offset_range", _STAGE_LEGACY_OFFSET_CHECK)
    with op.batch_alter_table("garmin_source_records", recreate="always") as batch_op:
        batch_op.drop_constraint("source_utc_offset_range", type_="check")
        batch_op.create_check_constraint("source_utc_offset_range", _LEGACY_OFFSET_CHECK)
