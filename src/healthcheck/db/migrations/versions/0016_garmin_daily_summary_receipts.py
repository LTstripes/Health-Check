"""Empty append-only receipts for future complete Garmin daily-summary fetches.

Revision ID: 0016_garmin_daily_summary_receipts
Revises: 0015_candidate_metadata_origins
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_garmin_daily_summary_receipts"
down_revision = "0015_candidate_metadata_origins"
branch_labels = None
depends_on = None

TABLE = "garmin_daily_summary_acquisition_receipts"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("observation_id", sa.String(36), primary_key=True),
        sa.Column("contract_version", sa.String(120), nullable=False),
        sa.Column("surface", sa.String(40), nullable=False),
        sa.Column("method", sa.String(40), nullable=False),
        sa.Column("requested_date", sa.Date(), nullable=False),
        sa.Column("original_calendar_date", sa.Date(), nullable=False),
        sa.CheckConstraint("length(contract_version) > 0", name="version_nonempty"),
        sa.CheckConstraint("surface = 'daily_summary'", name="surface_allowed"),
        sa.CheckConstraint("method = 'get_user_summary'", name="method_allowed"),
        sa.CheckConstraint("requested_date = original_calendar_date", name="day_identity"),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["garmin_payload_observations.id"], ondelete="RESTRICT"
        ),
    )
    for action in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER immutable_{TABLE}_{action.lower()} "
            f"BEFORE {action} ON {TABLE} BEGIN "
            f"SELECT RAISE(ABORT, '{TABLE} are append-only'); END"
        )


def downgrade() -> None:
    for action in ("update", "delete"):
        op.execute(f"DROP TRIGGER IF EXISTS immutable_{TABLE}_{action}")
    op.drop_table(TABLE)
