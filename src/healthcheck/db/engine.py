"""Minimal SQLite engine setup for later migrations."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, event

from healthcheck.runtime import RuntimePaths


def create_sqlite_engine(paths: RuntimePaths) -> Engine:
    """Create a SQLite engine with the durable runtime safety pragmas enabled."""

    engine = create_engine(
        f"sqlite:///{paths.database}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def migrate_placeholder(paths: RuntimePaths) -> None:
    """Open the empty database so later Alembic migrations have a safe starting point."""

    engine = create_sqlite_engine(paths)
    with engine.begin():
        pass
    engine.dispose()
