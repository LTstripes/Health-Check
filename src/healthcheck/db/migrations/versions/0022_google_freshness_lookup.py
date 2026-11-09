"""Index source freshness slices without changing persisted evidence."""

from alembic import op

revision = "0022_google_freshness_lookup"
down_revision = "0021_garmin_observation_lookup"
branch_labels = None
depends_on = None

INDEX = "ix_google_source_records_freshness"


def upgrade() -> None:
    op.create_index(INDEX, "google_source_records", [
        "google_source_id", "stream_code", "query_mode", "data_source_family",
        "projection_status", "record_status", "source_local_date",
    ])
    op.create_index("ix_garmin_source_records_freshness", "garmin_source_records", [
        "stream_code", "surface_code", "projection_status", "source_local_date",
        "record_status", "garmin_source_id",
    ])


def downgrade() -> None:
    op.drop_index("ix_garmin_source_records_freshness", table_name="garmin_source_records")
    op.drop_index(INDEX, table_name="google_source_records")
