"""Add append-only Context Capture v0 persistence.

Revision ID: 0013_context_capture_v0
Revises: 0012_r05_agreement_successor_publication

The revision is additive. It creates an isolated owner-authored context domain
without altering provider, measurement, agreement, or other existing tables.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_context_capture_v0"
down_revision = "0012_r05_agreement_successor_publication"
branch_labels = None
depends_on = None


def _create_immutability_triggers() -> None:
    for table_name in (
        "context_events",
        "context_event_revisions",
        "context_tags",
        "context_revision_tags",
    ):
        op.execute(
            f"""
            CREATE TRIGGER immutable_{table_name}_update
            BEFORE UPDATE ON {table_name}
            BEGIN
                SELECT RAISE(ABORT, '{table_name} are append-only');
            END
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER immutable_{table_name}_delete
            BEFORE DELETE ON {table_name}
            BEGIN
                SELECT RAISE(ABORT, '{table_name} are append-only');
            END
            """
        )
    op.execute(
        """
        CREATE TRIGGER context_event_heads_no_delete
        BEFORE DELETE ON context_event_heads
        BEGIN
            SELECT RAISE(ABORT, 'context event heads cannot be deleted');
        END
        """
    )


def _drop_immutability_triggers() -> None:
    for table_name in (
        "context_events",
        "context_event_revisions",
        "context_tags",
        "context_revision_tags",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS immutable_{table_name}_update")
        op.execute(f"DROP TRIGGER IF EXISTS immutable_{table_name}_delete")
    op.execute("DROP TRIGGER IF EXISTS context_event_heads_no_delete")


def upgrade() -> None:
    """Create the bounded Context Capture v0 tables and immutable evidence guards."""

    op.create_table(
        "context_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_context_events"),
    )
    op.create_table(
        "context_event_revisions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.String(80), nullable=False),
        sa.Column("operation_kind", sa.String(10), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("capture_source", sa.String(20), nullable=False),
        sa.Column("temporal_kind", sa.String(20), nullable=False),
        sa.Column("start_precision", sa.String(20), nullable=False),
        sa.Column("end_precision", sa.String(20), nullable=True),
        sa.Column("start_local_date", sa.Date(), nullable=False),
        sa.Column("end_local_date", sa.Date(), nullable=True),
        sa.Column("start_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_source_timestamp", sa.String(64), nullable=True),
        sa.Column("end_source_timestamp", sa.String(64), nullable=True),
        sa.Column("start_utc_offset_minutes", sa.Integer(), nullable=True),
        sa.Column("end_utc_offset_minutes", sa.Integer(), nullable=True),
        sa.Column("start_timezone", sa.String(100), nullable=True),
        sa.Column("end_timezone", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("revision_number >= 1", name="revision_number_positive"),
        sa.CheckConstraint(
            "length(operation_id) BETWEEN 1 AND 80", name="operation_id_bounded"
        ),
        sa.CheckConstraint(
            "operation_kind IN ('add', 'revise')", name="operation_kind_allowed"
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64", name="request_fingerprint_sha256"
        ),
        sa.CheckConstraint(
            "length(original_text) BETWEEN 1 AND 4000", name="original_text_bounded"
        ),
        sa.CheckConstraint("instr(original_text, char(0)) = 0", name="original_text_no_nul"),
        sa.CheckConstraint(
            "capture_source IN ('cli', 'manual', 'telegram', 'dashboard')",
            name="capture_source_allowed",
        ),
        sa.CheckConstraint(
            "temporal_kind IN ('date', 'instant', 'interval')", name="temporal_kind_allowed"
        ),
        sa.CheckConstraint(
            "start_precision IN ('date', 'minute', 'second', 'microsecond')",
            name="start_precision_allowed",
        ),
        sa.CheckConstraint(
            "end_precision IS NULL OR end_precision IN ('date', 'minute', 'second', 'microsecond')",
            name="end_precision_allowed",
        ),
        sa.CheckConstraint(
            "start_utc_offset_minutes IS NULL OR "
            "start_utc_offset_minutes BETWEEN -1439 AND 1439",
            name="start_offset_bounded",
        ),
        sa.CheckConstraint(
            "end_utc_offset_minutes IS NULL OR end_utc_offset_minutes BETWEEN -1439 AND 1439",
            name="end_offset_bounded",
        ),
        sa.CheckConstraint(
            "(temporal_kind = 'date' "
            "AND start_precision = 'date' AND start_local_date IS NOT NULL "
            "AND start_at_utc IS NULL AND start_source_timestamp IS NULL "
            "AND start_utc_offset_minutes IS NULL AND start_timezone IS NULL "
            "AND end_precision IS NULL AND end_local_date IS NULL AND end_at_utc IS NULL "
            "AND end_source_timestamp IS NULL AND end_utc_offset_minutes IS NULL "
            "AND end_timezone IS NULL) "
            "OR (temporal_kind = 'instant' "
            "AND start_precision <> 'date' AND start_local_date IS NOT NULL "
            "AND start_at_utc IS NOT NULL AND start_source_timestamp IS NOT NULL "
            "AND start_utc_offset_minutes IS NOT NULL "
            "AND end_precision IS NULL AND end_local_date IS NULL AND end_at_utc IS NULL "
            "AND end_source_timestamp IS NULL AND end_utc_offset_minutes IS NULL "
            "AND end_timezone IS NULL) "
            "OR (temporal_kind = 'interval' "
            "AND start_precision = 'date' AND end_precision = 'date' "
            "AND start_local_date IS NOT NULL AND end_local_date IS NOT NULL "
            "AND start_local_date <= end_local_date "
            "AND start_at_utc IS NULL AND end_at_utc IS NULL "
            "AND start_source_timestamp IS NULL AND end_source_timestamp IS NULL "
            "AND start_utc_offset_minutes IS NULL AND end_utc_offset_minutes IS NULL "
            "AND start_timezone IS NULL AND end_timezone IS NULL) "
            "OR (temporal_kind = 'interval' "
            "AND start_precision <> 'date' AND end_precision = start_precision "
            "AND start_local_date IS NOT NULL AND end_local_date IS NOT NULL "
            "AND start_at_utc IS NOT NULL AND end_at_utc IS NOT NULL "
            "AND start_source_timestamp IS NOT NULL AND end_source_timestamp IS NOT NULL "
            "AND start_utc_offset_minutes IS NOT NULL AND end_utc_offset_minutes IS NOT NULL "
            "AND start_at_utc < end_at_utc)",
            name="temporal_shape_valid",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["context_events.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_context_event_revisions"),
        sa.UniqueConstraint(
            "event_id", "revision_number", name="uq_context_revisions_number"
        ),
        sa.UniqueConstraint("event_id", "id", name="uq_context_revisions_event_id"),
        sa.UniqueConstraint("operation_id", name="uq_context_revisions_operation_id"),
    )
    op.create_index(
        "ix_context_revisions_event",
        "context_event_revisions",
        ["event_id", "revision_number"],
    )
    op.create_index(
        "ix_context_revisions_time",
        "context_event_revisions",
        ["start_local_date", "end_local_date"],
    )
    op.create_table(
        "context_tags",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("normalized_name", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "length(normalized_name) BETWEEN 1 AND 64", name="normalized_name_bounded"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_context_tags"),
        sa.UniqueConstraint("normalized_name", name="uq_context_tags_normalized_name"),
    )
    op.create_table(
        "context_revision_tags",
        sa.Column("revision_id", sa.String(36), nullable=False),
        sa.Column("tag_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provenance_source", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('suggested', 'confirmed', 'rejected')", name="status_allowed"
        ),
        sa.CheckConstraint(
            "provenance_source IN ('cli', 'manual', 'telegram', 'dashboard', 'ai')",
            name="provenance_source_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["context_event_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["tag_id"], ["context_tags.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint(
            "revision_id", "tag_id", name="pk_context_revision_tags"
        ),
    )
    op.create_table(
        "context_event_heads",
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("revision_id", sa.String(36), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "revision_id"],
            ["context_event_revisions.event_id", "context_event_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id", name="pk_context_event_heads"),
        sa.UniqueConstraint("revision_id", name="uq_context_event_heads_revision"),
    )
    _create_immutability_triggers()


def downgrade() -> None:
    """Remove only the additive Context Capture v0 schema."""

    _drop_immutability_triggers()
    for table_name in (
        "context_event_heads",
        "context_revision_tags",
        "context_tags",
        "context_event_revisions",
        "context_events",
    ):
        op.drop_table(table_name)
