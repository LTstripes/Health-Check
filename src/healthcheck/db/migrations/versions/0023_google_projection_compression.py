"""Verified, resumable compression of immutable Google attempt bodies.

SQLite cannot drop NOT NULL in place. Copy only verified compressed rows into
a shadow table, committing bounded batches, then atomically swap and stamp.
The original remains intact until the swap; never VACUUM here. Run exclusively
with application writers stopped and an independently verified backup.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

from healthcheck.google.projection_storage import compress_projection, read_projection

revision = "0023_google_projection_compression"
down_revision = "0022_google_freshness_lookup"
branch_labels = None
depends_on = None

TABLE = "google_normalization_attempts"
COMPRESSED = ("projection_blob", "projection_codec", "projection_size", "projection_sha256")
BATCH_ROWS = 16
BATCH_BYTES = 16 * 1024 * 1024
log = logging.getLogger("alembic.runtime.migration")


def _progress(converted: int, verified: int) -> None:
    # Counts only. Also provides a deterministic synthetic interruption point.
    log.info("Google projection migration: converted=%d verified=%d", converted, verified)


def _copy(compress: bool) -> None:
    connection = op.get_bind()
    context = op.get_context()
    shadow_name = "_gproj_0023_compress" if compress else "_gproj_0023_restore"
    metadata = sa.MetaData()
    source = sa.Table(TABLE, metadata, autoload_with=connection, resolve_fks=False)
    columns = [column.name for column in source.columns if column.name not in COMPRESSED]
    # Reflection retains the historical schema rather than importing today's ORM.
    # Supply referent column names for DDL compilation without recursively
    # reflecting unrelated tables (or copying any of their data).
    target_metadata = sa.MetaData()
    for foreign_key in source.foreign_keys:
        table_name, column_name = foreign_key.target_fullname.rsplit(".", 1)
        if table_name not in target_metadata.tables:
            sa.Table(table_name, target_metadata, sa.Column(column_name, sa.String(36)))
    target_source = sa.Table(
        TABLE, target_metadata, autoload_with=connection, include_columns=columns,
        resolve_fks=False,
    )
    shadow = target_source.to_metadata(target_source.metadata, name=shadow_name)
    shadow.indexes.clear()  # Recreate the original named indexes after the swap.
    shadow.c.projection_json.nullable = compress
    if compress:
        shadow.append_column(sa.Column("projection_blob", sa.LargeBinary()))
        shadow.append_column(sa.Column("projection_codec", sa.String(20)))
        shadow.append_column(sa.Column("projection_size", sa.Integer()))
        shadow.append_column(sa.Column("projection_sha256", sa.String(64)))

    # autocommit_block commits Alembic's current transaction. Every explicit
    # BEGIN/COMMIT below is a real, bounded SQLite transaction, not a savepoint.
    with context.autocommit_block():
        shadow.create(connection, checkfirst=True)
        last_id = None
        converted = verified = 0
        while True:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                query = sa.select(source).order_by(source.c.id).limit(BATCH_ROWS)
                if last_id is not None:
                    query = query.where(source.c.id > last_id)
                batch_bytes = count = 0
                # Stream rows: memory is bounded by one body plus its compressed
                # form, even for a single body larger than the byte budget.
                result = connection.execute(query)
                for row in result.mappings():
                    original = read_projection(row)
                    expected = {name: row[name] for name in columns}
                    existing = connection.execute(
                        sa.select(shadow).where(shadow.c.id == row["id"])
                    ).mappings().one_or_none()
                    if existing is not None:
                        if (read_projection(existing) != original or any(
                            existing[name] != expected[name]
                            for name in columns if name != "projection_json"
                        ) or (compress and existing["projection_json"] is not None)):
                            raise ValueError("Google projection verification failed")
                        verified += 1
                    else:
                        if compress:
                            expected.update(compress_projection(
                                original, row["projection_fingerprint"],
                            ))
                            # Clear text only after decode -> length -> SHA ->
                            # exact UTF-8 equality has passed through the accessor.
                            expected["projection_json"] = None
                        else:
                            expected["projection_json"] = original
                        connection.execute(shadow.insert().values(**expected))
                        stored = connection.execute(
                            sa.select(shadow).where(shadow.c.id == row["id"])
                        ).mappings().one()
                        if read_projection(stored) != original:
                            raise ValueError("Google projection verification failed")
                        converted += 1
                    count += 1
                    last_id = row["id"]
                    batch_bytes += len(original.encode("utf-8"))
                    if batch_bytes >= BATCH_BYTES:
                        break
                result.close()
                connection.exec_driver_sql("COMMIT")
            except BaseException:
                connection.exec_driver_sql("ROLLBACK")
                raise
            if not count:
                break
            _progress(converted, verified)

    # Alembic's reopened transaction includes both this swap and the revision
    # stamp. Explicit BEGIN is required for transactional DDL in sqlite3 legacy
    # transaction mode. A failure rolls the swap back, leaving resumable batches.
    connection.exec_driver_sql("BEGIN IMMEDIATE")
    if (connection.scalar(sa.select(sa.func.count()).select_from(source))
            != connection.scalar(sa.select(sa.func.count()).select_from(shadow))):
        raise RuntimeError("Google projection migration row count mismatch")
    ddl = connection.execute(sa.text(
        "SELECT sql FROM sqlite_master WHERE tbl_name=:table "
        "AND type IN ('index', 'trigger') AND sql IS NOT NULL ORDER BY type, name"
    ), {"table": TABLE}).scalars().all()
    connection.exec_driver_sql(f'DROP TABLE "{TABLE}"')
    connection.exec_driver_sql(f'ALTER TABLE "{shadow_name}" RENAME TO "{TABLE}"')
    for statement in ddl:
        connection.exec_driver_sql(statement)


def upgrade() -> None:
    _copy(True)


def downgrade() -> None:
    _copy(False)
