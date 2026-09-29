"""Explicit SQLite snapshots for compound, session-backed Owner reads."""

from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session


def ensure_read_snapshot(session: Session) -> None:
    """Start a physical read transaction, or reuse the caller's existing one.

    SQLite's legacy driver does not BEGIN on SELECT, even when SQLAlchemy
    reports an active Session transaction. Compound readers must call this
    before their first query. Nested readers share the same snapshot; the
    caller still owns commit/rollback/close (normally ``session_scope``).

    No engine events, isolation settings, writer reservations or migration
    behavior change. A pre-existing physical transaction remains caller-owned.
    Entry requires no pending ORM changes, including when reusing a transaction;
    flushed writes remain visible in that transaction after cache expiration.
    """
    if session.new or session.dirty or session.deleted:
        raise InvalidRequestError("A read snapshot requires no pending session changes")
    connection = session.connection()
    if not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN")
    # The factory uses expire_on_commit=False. Cached ORM entities from an
    # earlier transaction or pre-BEGIN SELECT must not be combined with the
    # active snapshot, even when the caller already began the transaction.
    session.expire_all()
