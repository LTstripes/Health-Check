"""Store extraction provider and field algorithm on import candidates.

Revision ID: 0002_photo_candidate_provenance
Revises: 0001_r01_core_schema
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_photo_candidate_provenance"
down_revision = "0001_r01_core_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Retain per-candidate provider and algorithm identity from extraction."""

    with op.batch_alter_table("import_candidates") as batch:
        batch.add_column(sa.Column("algorithm_code", sa.String(180), nullable=True))
        batch.add_column(sa.Column("algorithm_version", sa.String(100), nullable=True))
        batch.add_column(sa.Column("provider_code", sa.String(120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("import_candidates") as batch:
        batch.drop_column("provider_code")
        batch.drop_column("algorithm_version")
        batch.drop_column("algorithm_code")
