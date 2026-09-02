"""SQLite engine, session and Alembic migration setup."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from healthcheck.runtime import RuntimePaths


def create_sqlite_engine(paths: RuntimePaths) -> Engine:
    """Create a SQLite engine with the durable runtime safety pragmas enabled.

    The database lives under the caller-provided external runtime directory;
    this function never chooses a repository-relative fallback.
    """

    paths.root.mkdir(parents=True, exist_ok=True)
    database_path = paths.database.resolve().as_posix()
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a non-expiring session factory for application services."""

    return sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Run one repository transaction and roll it back on every failure."""

    factory = create_session_factory(engine)
    with factory() as session:
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _alembic_config(paths: RuntimePaths) -> Config:
    """Build an Alembic config without reading any runtime config or secrets."""

    config = Config(str(_repository_root() / "alembic.ini"))
    config.set_main_option(
        "script_location", str(_repository_root() / "src" / "healthcheck" / "db" / "migrations")
    )
    database_url = f"sqlite:///{paths.database.resolve().as_posix()}"
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def migrate_database(paths: RuntimePaths) -> None:
    """Upgrade the external database to the latest checked-in migration."""

    paths.root.mkdir(parents=True, exist_ok=True)
    command.upgrade(_alembic_config(paths), "head")


def migrate_placeholder(paths: RuntimePaths) -> None:
    """Backward-compatible name for the bootstrap command.

    Existing callers used the R00 placeholder.  Keeping this alias makes the
    command safe for older scripts while now applying the real R01 migration.
    """

    migrate_database(paths)


def database_readiness(paths: RuntimePaths) -> dict[str, object]:
    """Return non-sensitive migration and SQLite pragma readiness facts."""

    engine = create_sqlite_engine(paths)
    try:
        with engine.connect() as connection:
            journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar()
            foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
            try:
                revision = connection.exec_driver_sql(
                    "SELECT version_num FROM alembic_version LIMIT 1"
                ).scalar()
            except OperationalError:
                revision = None
    finally:
        engine.dispose()
    return {
        "journal_mode": journal_mode,
        "foreign_keys": foreign_keys,
        "migration_revision": revision,
        "ready": journal_mode == "wal" and foreign_keys == 1 and revision is not None,
    }


# Stable names for application services and command adapters.
get_session_factory = create_session_factory
migrate = migrate_database
run_migrations = migrate_database
