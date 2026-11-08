"""Index Garmin observation provenance lookups without changing stored evidence."""

from alembic import op

revision = "0021_garmin_observation_lookup"
down_revision = "0020_google_exercise"
branch_labels = None
depends_on = None

INDEX = "ix_garmin_payload_observations_raw_received"


def upgrade() -> None:
    op.create_index(
        INDEX, "garmin_payload_observations", ["garmin_raw_payload_id", "received_at", "id"]
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="garmin_payload_observations")
