"""Make canonical selection identity metric-aware within a run."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_canonical_selection_metric_identity"
down_revision = "0001_r01_core_schema"
branch_labels = None
depends_on = None


def _drop_append_only_triggers() -> None:
    op.execute("DROP TRIGGER IF EXISTS immutable_canonical_selections_delete")
    op.execute("DROP TRIGGER IF EXISTS immutable_canonical_selections_update")


def _create_append_only_triggers() -> None:
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS immutable_canonical_selections_delete
        BEFORE DELETE ON canonical_selections
        BEGIN
            SELECT RAISE(ABORT, 'canonical_selections are append-only');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS immutable_canonical_selections_update
        BEFORE UPDATE ON canonical_selections
        BEGIN
            SELECT RAISE(ABORT, 'canonical_selections are append-only');
        END
        """
    )


def _assert_downgrade_is_lossless() -> None:
    conflict = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT selection_run_id, semantic_key
            FROM canonical_selections
            GROUP BY selection_run_id, semantic_key
            HAVING COUNT(*) > 1
            LIMIT 1
            """
            )
        )
        .first()
    )
    if conflict is not None:
        raise RuntimeError(
            "cannot downgrade 0002: a run contains multiple metrics for one semantic key"
        )


def upgrade() -> None:
    """Replace the legacy run/key uniqueness with the metric-aware identity."""

    # SQLite recreates this table for constraint changes.  Explicitly restore
    # the append-only triggers because Alembic batch mode does not copy them.
    _drop_append_only_triggers()
    with op.batch_alter_table("canonical_selections", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_canonical_selections_run_key", type_="unique")
        batch_op.create_unique_constraint(
            "uq_canonical_selections_run_metric_key",
            ["selection_run_id", "metric_code", "semantic_key"],
        )
    _create_append_only_triggers()


def downgrade() -> None:
    """Restore the legacy identity only when existing rows remain compatible."""

    _assert_downgrade_is_lossless()
    _drop_append_only_triggers()
    with op.batch_alter_table("canonical_selections", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_canonical_selections_run_metric_key", type_="unique")
        batch_op.create_unique_constraint(
            "uq_canonical_selections_run_key", ["selection_run_id", "semantic_key"]
        )
    _create_append_only_triggers()
