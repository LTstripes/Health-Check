"""Add Garmin current-projection collection membership and retirement.

Revision ID: 0007_garmin_collection_reconciliation
Revises: 0006_garmin_payload_observation_provenance
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_garmin_collection_reconciliation"
down_revision = "0006_garmin_payload_observation_provenance"
branch_labels = None
depends_on = None

_PRE_RECONCILIATION_VERSION = "r02-garmin-pre-collection-reconciliation"
_PROJECTION_CHECK = "projection_status IN ('current', 'retired')"
_RETIRED_CHECK = (
    "(projection_status = 'current' AND retired_at IS NULL AND retire_reason IS NULL) "
    "OR (projection_status = 'retired' AND retired_at IS NOT NULL)"
)


def upgrade() -> None:
    """Attach collection identity and non-destructive retirement to current rows."""

    with op.batch_alter_table("garmin_source_records", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("surface_code", sa.String(40), nullable=True))
        batch_op.add_column(sa.Column("collection_key", sa.String(128), nullable=True))
        batch_op.add_column(
            sa.Column(
                "projection_status",
                sa.String(20),
                nullable=False,
                server_default="current",
            )
        )
        batch_op.add_column(
            sa.Column("projection_observed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("retire_reason", sa.String(80), nullable=True))
        batch_op.add_column(
            sa.Column(
                "reconciliation_contract_version",
                sa.String(120),
                nullable=False,
                server_default=_PRE_RECONCILIATION_VERSION,
            )
        )
        batch_op.create_check_constraint("projection_status_allowed", _PROJECTION_CHECK)
        batch_op.create_check_constraint("projection_retirement_consistency", _RETIRED_CHECK)
        batch_op.create_index(
            "ix_garmin_source_records_collection",
            ["garmin_source_id", "collection_key", "projection_status"],
        )
        batch_op.create_index(
            "ix_garmin_source_records_surface_date",
            ["garmin_source_id", "surface_code", "source_local_date"],
        )


def downgrade() -> None:
    """Drop collection-reconciliation columns only when no retired rows exist."""

    bind = op.get_bind()
    retired = bind.execute(
        sa.text(
            """
            SELECT id
            FROM garmin_source_records
            WHERE projection_status = 'retired'
            LIMIT 1
            """
        )
    ).first()
    if retired is not None:
        raise RuntimeError(
            "cannot downgrade 0007: retired Garmin current rows would lose retirement state"
        )

    with op.batch_alter_table("garmin_source_records", recreate="always") as batch_op:
        batch_op.drop_index("ix_garmin_source_records_surface_date")
        batch_op.drop_index("ix_garmin_source_records_collection")
        batch_op.drop_constraint("projection_retirement_consistency", type_="check")
        batch_op.drop_constraint("projection_status_allowed", type_="check")
        batch_op.drop_column("reconciliation_contract_version")
        batch_op.drop_column("retire_reason")
        batch_op.drop_column("retired_at")
        batch_op.drop_column("projection_observed_at")
        batch_op.drop_column("projection_status")
        batch_op.drop_column("collection_key")
        batch_op.drop_column("surface_code")
