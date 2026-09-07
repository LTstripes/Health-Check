"""Record reconciliation version on immutable Garmin observations.

Revision ID: 0008_garmin_observation_reconciliation_version
Revises: 0007_garmin_collection_reconciliation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_garmin_observation_reconciliation_version"
down_revision = "0007_garmin_collection_reconciliation"
branch_labels = None
depends_on = None

_PRE_RECONCILIATION_VERSION = "r02-garmin-pre-collection-reconciliation"


def _drop_observation_immutability_triggers() -> None:
    op.execute("DROP TRIGGER IF EXISTS immutable_garmin_payload_observations_delete")
    op.execute("DROP TRIGGER IF EXISTS immutable_garmin_payload_observations_update")


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


def upgrade() -> None:
    """Stamp each observation with a reconciliation version, including empty windows."""

    op.add_column(
        "garmin_payload_observations",
        sa.Column(
            "reconciliation_contract_version",
            sa.String(120),
            nullable=False,
            server_default=_PRE_RECONCILIATION_VERSION,
        ),
    )


def downgrade() -> None:
    """Drop the observation reconciliation-version column."""

    _drop_observation_immutability_triggers()
    with op.batch_alter_table("garmin_payload_observations", recreate="always") as batch_op:
        batch_op.drop_column("reconciliation_contract_version")
    _create_observation_immutability_triggers()
