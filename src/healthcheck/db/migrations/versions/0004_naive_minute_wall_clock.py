"""Allow minute precision with naive local wall clocks (no invented UTC).

Revision ID: 0004_naive_minute_wall_clock
Revises: 0003_photo_candidate_provenance
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_naive_minute_wall_clock"
down_revision = "0003_photo_candidate_provenance"
branch_labels = None
depends_on = None

_NEW_CONSTRAINT = (
    "(temporal_precision = 'date' AND source_timestamp_utc IS NULL "
    "AND source_local_timestamp IS NULL) "
    "OR (temporal_precision = 'minute' AND ("
    "source_timestamp_utc IS NOT NULL OR source_local_timestamp IS NOT NULL)) "
    "OR (temporal_precision = 'instant' AND source_timestamp_utc IS NOT NULL)"
)

_OLD_CONSTRAINT = (
    "(temporal_precision = 'date' AND source_timestamp_utc IS NULL "
    "AND source_local_timestamp IS NULL) "
    "OR (temporal_precision IN ('instant', 'minute') AND source_timestamp_utc IS NOT NULL)"
)


def _drop_append_only_triggers() -> None:
    op.execute("DROP TRIGGER IF EXISTS immutable_measurement_sessions_delete")
    op.execute("DROP TRIGGER IF EXISTS immutable_measurement_sessions_update")


def _create_append_only_triggers() -> None:
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS immutable_measurement_sessions_delete
        BEFORE DELETE ON measurement_sessions
        BEGIN
            SELECT RAISE(ABORT, 'measurement_sessions are append-only');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS immutable_measurement_sessions_update
        BEFORE UPDATE ON measurement_sessions
        BEGIN
            SELECT RAISE(ABORT, 'measurement_sessions are append-only');
        END
        """
    )


def upgrade() -> None:
    """Permit minute rows that keep a sender-local wall without inventing UTC."""

    # SQLite recreates the table for check-constraint changes.  Restore the
    # append-only triggers because Alembic batch mode does not copy them.
    _drop_append_only_triggers()
    with op.batch_alter_table("measurement_sessions", recreate="always") as batch_op:
        batch_op.drop_constraint("temporal_precision_timestamp_consistency", type_="check")
        batch_op.create_check_constraint(
            "temporal_precision_timestamp_consistency",
            _NEW_CONSTRAINT,
        )
    _create_append_only_triggers()


def downgrade() -> None:
    """Restore the UTC-required minute/instant constraint when still valid."""

    conflict = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT id
            FROM measurement_sessions
            WHERE temporal_precision = 'minute'
              AND source_timestamp_utc IS NULL
            LIMIT 1
            """
            )
        )
        .first()
    )
    if conflict is not None:
        raise RuntimeError("cannot downgrade 0004: minute rows without source_timestamp_utc exist")
    _drop_append_only_triggers()
    with op.batch_alter_table("measurement_sessions", recreate="always") as batch_op:
        batch_op.drop_constraint("temporal_precision_timestamp_consistency", type_="check")
        batch_op.create_check_constraint(
            "temporal_precision_timestamp_consistency",
            _OLD_CONSTRAINT,
        )
    _create_append_only_triggers()
