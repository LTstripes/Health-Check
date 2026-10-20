"""Admit offline Steps evidence without enabling provider acquisition."""

import sqlalchemy as sa
from alembic import op

revision = "0018_google_offline_steps"
down_revision = "0017_lab_intake_v1"
branch_labels = None
depends_on = None

_TABLES = (
    "google_raw_payloads",
    "google_payload_observations",
    "google_source_records",
    "google_normalization_attempts",
)
_STREAMS = (
    "'sleep', 'heart_rate', 'hrv', 'daily_hrv', 'daily_resting_hr', "
    "'spo2', 'daily_spo2', 'respiratory_rate_sleep', 'daily_respiratory_rate'"
)


def _change_stream_checks(include_steps: bool) -> None:
    for table in _TABLES:
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.drop_constraint(op.f(f"ck_{table}_stream_code_allowed"), type_="check")
            batch.create_check_constraint(
                "stream_code_allowed",
                f"stream_code IN ({_STREAMS}{', ' + repr('steps') if include_steps else ''})",
            )
        if table != "google_source_records":
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER immutable_{table}_{action.lower()} "
                    f"BEFORE {action} ON {table} BEGIN "
                    f"SELECT RAISE(ABORT, '{table} are append-only'); END"
                )


def upgrade() -> None:
    _change_stream_checks(True)


def downgrade() -> None:
    # Never discard or relabel Steps history to make an older CHECK fit.
    connection = op.get_bind()
    if any(
        connection.scalar(sa.text(f"SELECT 1 FROM {table} WHERE stream_code='steps' LIMIT 1"))
        for table in _TABLES
    ):
        raise RuntimeError("cannot downgrade while immutable Steps evidence exists")
    _change_stream_checks(False)
