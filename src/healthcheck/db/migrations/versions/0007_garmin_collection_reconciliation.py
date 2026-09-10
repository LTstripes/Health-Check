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
_ALEMBIC_TMP_SOURCE_RECORDS = "_alembic_tmp_garmin_source_records"
_REQUIRED_TEMP_COLUMNS = frozenset(
    {
        "id",
        "garmin_source_id",
        "raw_payload_id",
        "stream_code",
        "idempotency_key",
        "temporal_precision",
        "record_status",
        "normalization_contract_version",
    }
)


def _recover_empty_alembic_temp_source_records() -> None:
    """Drop a leftover empty Alembic batch temp from a failed prior 0007 attempt.

    Owner-observed recoverable state: revision still at 0006, business rows
    intact, plus an empty ``_alembic_tmp_garmin_source_records`` left after
    SQLite DDL auto-committed the temp create while the DROP of the live parent
    failed under ``PRAGMA foreign_keys=ON``.  Only a provably empty temp whose
    columns still look like ``garmin_source_records`` may be removed.  Non-empty
    or unexpected schema fails closed.
    """

    bind = op.get_bind()
    exists = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = :name
            LIMIT 1
            """
        ),
        {"name": _ALEMBIC_TMP_SOURCE_RECORDS},
    ).first()
    if exists is None:
        return

    columns = {
        row[1]
        for row in bind.execute(sa.text(f'PRAGMA table_info("{_ALEMBIC_TMP_SOURCE_RECORDS}")'))
    }
    if not _REQUIRED_TEMP_COLUMNS.issubset(columns):
        missing = sorted(_REQUIRED_TEMP_COLUMNS - columns)
        raise RuntimeError(
            f"refusing to clean {_ALEMBIC_TMP_SOURCE_RECORDS}: unexpected schema "
            f"(missing columns {missing}); manual recovery required"
        )

    row_count = bind.execute(
        sa.text(f'SELECT COUNT(*) FROM "{_ALEMBIC_TMP_SOURCE_RECORDS}"')
    ).scalar_one()
    if row_count:
        raise RuntimeError(
            f"refusing to clean non-empty {_ALEMBIC_TMP_SOURCE_RECORDS} "
            f"({row_count} row(s)); manual recovery required"
        )

    op.execute(sa.text(f'DROP TABLE "{_ALEMBIC_TMP_SOURCE_RECORDS}"'))


def upgrade() -> None:
    """Attach collection identity and non-destructive retirement to current rows."""

    _recover_empty_alembic_temp_source_records()

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

    _recover_empty_alembic_temp_source_records()

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
