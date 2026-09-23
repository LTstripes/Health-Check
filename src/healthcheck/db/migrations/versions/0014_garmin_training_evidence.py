"""Typed Garmin training snapshots and requested-date acquisition provenance.

Revision ID: 0014_garmin_training_evidence
Revises: 0013_context_capture_v0
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_garmin_training_evidence"
down_revision = "0013_context_capture_v0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "garmin_training_snapshots",
        sa.Column("record_id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("provider_device_key", sa.String(255)),
        sa.Column("provider_device_id", sa.String(255)),
        sa.Column("attribution", sa.String(30), nullable=False),
        sa.CheckConstraint("kind IN ('status', 'load_balance', 'readiness')", name="kind_allowed"),
        sa.CheckConstraint(
            "attribution IN ('account', 'associated_device')", name="attribution_allowed"
        ),
        sa.ForeignKeyConstraint(["record_id"], ["garmin_source_records.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "garmin_training_acquisitions",
        sa.Column("observation_id", sa.String(36), primary_key=True),
        sa.Column("surface", sa.String(40), nullable=False),
        sa.Column("requested_date", sa.Date(), nullable=False),
        sa.Column("response_state", sa.String(20), nullable=False),
        sa.CheckConstraint(
            "surface IN ('training_status', 'training_readiness')", name="surface_allowed"
        ),
        sa.CheckConstraint(
            "response_state IN ('value', 'null', 'empty', 'shape_drift')",
            name="response_state_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["garmin_payload_observations.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_garmin_training_acquisitions_requested",
        "garmin_training_acquisitions",
        ["surface", "requested_date"],
    )
    op.create_table(
        "garmin_training_observation_records",
        sa.Column("observation_id", sa.String(36), primary_key=True),
        sa.Column("record_id", sa.String(36), primary_key=True),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["garmin_payload_observations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["record_id"], ["garmin_source_records.id"], ondelete="RESTRICT"),
    )


def downgrade() -> None:
    op.drop_table("garmin_training_observation_records")
    op.drop_index(
        "ix_garmin_training_acquisitions_requested", table_name="garmin_training_acquisitions"
    )
    op.drop_table("garmin_training_acquisitions")
    op.drop_table("garmin_training_snapshots")
