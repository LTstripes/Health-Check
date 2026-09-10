"""Alembic environment for the external Health-Check SQLite database."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

import healthcheck.db.models as models  # noqa: F401  (register mapped tables)
from healthcheck.db.base import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without opening a database connection."""

    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _sqlite_foreign_key_violations(connection) -> list[tuple]:
    """Return raw PRAGMA foreign_key_check rows (works even while FKs are off)."""

    return list(connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall())


def run_migrations_online() -> None:
    """Run migrations on a SQLite connection with R01 safety pragmas.

    SQLite rejects parent-table recreation while child RESTRICT FKs exist and
    ``PRAGMA foreign_keys`` is ON.  ``PRAGMA foreign_keys`` also cannot change
    inside an open transaction, so Alembic batch recreates must temporarily
    disable enforcement on this migration connection only.  Runtime engines
    keep ``foreign_keys=ON`` via ``create_sqlite_engine``.  After a successful
    migration transaction we re-enable FKs and refuse to accept the database
    when ``PRAGMA foreign_key_check`` reports violations.
    """

    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    with connectable.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("PRAGMA busy_timeout=5000")
        # SQLAlchemy 2.x autobegins around driver SQL.  Commit the connection
        # setup before Alembic opens its migration transaction; otherwise the
        # version stamp can be rolled back when the connection closes.
        connection.commit()

        # Disable FK enforcement for migration DDL only.  Must happen outside
        # the Alembic transaction or SQLite silently ignores the pragma.
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        try:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
                violations = _sqlite_foreign_key_violations(connection)
                if violations:
                    raise RuntimeError(
                        "refusing to accept migrated SQLite database: "
                        f"PRAGMA foreign_key_check reported {len(violations)} violation(s); "
                        "migration repair will not delete or reparent invalid rows"
                    )
        finally:
            # Restore enforcement on this connection whether upgrade succeeded
            # or failed; app engines independently enable FKs on connect.
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
