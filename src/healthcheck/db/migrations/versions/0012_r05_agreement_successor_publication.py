"""Restrict the R05 successor edge to successfully published runs.

Revision ID: 0012_r05_agreement_successor_publication
Revises: 0011_r05_agreement_run_persistence

The R05 run table is append-only.  This additive index correction means a
running or failed construction attempt cannot reserve the one durable
successor edge for a predecessor.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_r05_agreement_successor_publication"
down_revision = "0011_r05_agreement_run_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Make the bounded successor uniqueness apply only to successful runs."""

    op.drop_index(
        "ux_agreement_runs_single_successor",
        table_name="agreement_runs",
    )
    op.create_index(
        "ux_agreement_runs_single_successor",
        "agreement_runs",
        ["supersedes_run_id"],
        unique=True,
        sqlite_where=sa.text(
            "status = 'succeeded' AND supersedes_run_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    """Restore the original index predicate for a reversible downgrade."""

    op.drop_index(
        "ux_agreement_runs_single_successor",
        table_name="agreement_runs",
    )
    op.create_index(
        "ux_agreement_runs_single_successor",
        "agreement_runs",
        ["supersedes_run_id"],
        unique=True,
        sqlite_where=sa.text("supersedes_run_id IS NOT NULL"),
    )
