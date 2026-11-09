"""Connection-local successful agreement validation, guarded by SQLite changes."""

from sqlite3 import Connection as SQLiteConnection

from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

_CACHE_KEY = "healthcheck_agreement_validation"
_MAX_RUNS = 128


@event.listens_for(Engine, "rollback")
def _rollback(connection):
    connection.info.pop(_CACHE_KEY, None)


@event.listens_for(Engine, "rollback_savepoint")
def _rollback_savepoint(connection, name, context):
    connection.info.pop(_CACHE_KEY, None)


def validated_runs(session: Session, run_id: str) -> set[str] | None:
    """Return the successful-run set for this exact physical SQLite snapshot."""
    connection = session.connection()
    driver = connection.connection.driver_connection
    if not isinstance(driver, SQLiteConnection) or session.new or session.dirty or session.deleted:
        return None
    if not driver.in_transaction:
        connection.exec_driver_sql("BEGIN")
    # Pin the database snapshot before reading data_version, including when the
    # ORM identity map already contains the run from an earlier transaction.
    connection.exec_driver_sql("SELECT id FROM agreement_runs WHERE id = ?", (run_id,)).all()
    fingerprint = tuple(connection.exec_driver_sql(
        "SELECT data_version, schema_version, total_changes() "
        "FROM pragma_data_version, pragma_schema_version"
    ).one())
    cached = connection.info.get(_CACHE_KEY)
    if cached is None or cached[0] != fingerprint:
        # Design A: validate once per run/unchanged pooled connection. Unlike
        # count/MAX(rowid), this fingerprint detects in-place UPDATEs too:
        # data_version covers other connections, total_changes our own writes.
        # Rollback/savepoint rollback clears the cache because total_changes
        # does not rewind. Only successful validation adds an id; no rows or
        # ORM objects survive here, and unrelated writes conservatively miss.
        cached = (fingerprint, set())
        connection.info[_CACHE_KEY] = cached
        session.expire_all()
    if len(cached[1]) >= _MAX_RUNS and run_id not in cached[1]:
        cached[1].clear()
    return cached[1]
