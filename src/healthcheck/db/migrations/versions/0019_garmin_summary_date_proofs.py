"""Empty saved-byte day proofs; no legacy dates or acquisition success inferred."""

import sqlalchemy as sa
from alembic import op

revision = "0019_garmin_summary_date_proofs"
down_revision = "0018_google_offline_steps"
branch_labels = None
depends_on = None

TABLE = "garmin_daily_summary_date_proofs"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("raw_payload_id", sa.String(36), primary_key=True),
        sa.Column("contract_version", sa.String(120), nullable=False),
        sa.Column("original_calendar_date", sa.Date(), nullable=False),
        sa.CheckConstraint("length(contract_version) > 0", name="version_nonempty"),
        sa.CheckConstraint(
            "length(original_calendar_date) = 10 "
            "AND original_calendar_date >= '0001-01-01' "
            "AND original_calendar_date <= '9999-12-31' "
            "AND date(original_calendar_date, '+0 days') IS NOT NULL "
            "AND date(original_calendar_date, '+0 days') = original_calendar_date",
            name="strict_calendar_date",
        ),
        sa.ForeignKeyConstraint(
            ["raw_payload_id"], ["garmin_raw_payloads.id"], ondelete="RESTRICT"
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
