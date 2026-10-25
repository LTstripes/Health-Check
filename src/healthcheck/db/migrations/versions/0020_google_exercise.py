"""Admit offline Google exercise sessions; no acquisition or historical rewrite."""

import sqlalchemy as sa
from alembic import op

revision = "0020_google_exercise"
down_revision = "0019_garmin_summary_date_proofs"
branch_labels = None
depends_on = None

TABLES = (
    "google_raw_payloads",
    "google_payload_observations",
    "google_source_records",
    "google_normalization_attempts",
)
STREAMS = (
    "'sleep', 'heart_rate', 'hrv', 'daily_hrv', 'daily_resting_hr', "
    "'spo2', 'daily_spo2', 'respiratory_rate_sleep', 'daily_respiratory_rate', 'steps'"
)


def _change(include: bool) -> None:
    for table in TABLES:
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.drop_constraint(op.f(f"ck_{table}_stream_code_allowed"), type_="check")
            batch.create_check_constraint(
                "stream_code_allowed",
                f"stream_code IN ({STREAMS}{', ' + repr('exercise') if include else ''})",
            )
        if table != "google_source_records":
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER immutable_{table}_{action.lower()} "
                    f"BEFORE {action} ON {table} BEGIN "
                    f"SELECT RAISE(ABORT, '{table} are append-only'); END"
                )
    with op.batch_alter_table("google_record_intervals", recreate="always") as batch:
        batch.drop_constraint(
            op.f("ck_google_record_intervals_interval_kind_allowed"), type_="check"
        )
        batch.create_check_constraint(
            "interval_kind_allowed",
            "interval_kind IN ('roll_up', 'daily_roll_up'"
            + (", 'exercise_session'" if include else "")
            + ")",
        )


def upgrade() -> None:
    _change(True)


def downgrade() -> None:
    connection = op.get_bind()
    if any(
        connection.scalar(sa.text(f"SELECT 1 FROM {table} WHERE stream_code='exercise' LIMIT 1"))
        for table in TABLES
    ) or connection.scalar(
        sa.text(
            "SELECT 1 FROM google_record_intervals WHERE interval_kind='exercise_session' LIMIT 1"
        )
    ):
        raise RuntimeError("cannot downgrade while immutable exercise evidence exists")
    _change(False)
