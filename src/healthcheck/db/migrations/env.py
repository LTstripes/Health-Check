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


def run_migrations_online() -> None:
    """Run migrations on a SQLite connection with R01 safety pragmas."""

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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
