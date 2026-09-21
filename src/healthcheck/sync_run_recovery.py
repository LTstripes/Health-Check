"""Explicit fail-closed maintenance for orphaned running SyncRun rows."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError

from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, database_readiness
from healthcheck.db.repositories import repositories_for, restore_stored_utc
from healthcheck.external_runtime_lock import ExternalRuntimeOperationLock
from healthcheck.runtime import RuntimePaths, resolve_runtime_paths

SYNC_RUN_RECOVERY_CONTRACT_VERSION = "healthcheck-sync-run-recovery-v1"


class SyncRunRecoveryRuntimeError(ValueError):
    """The requested runtime cannot be safely inspected for recovery."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class SyncRunRecoveryReport:
    """Aggregate-only result with no run IDs, timestamps, or health values."""

    contract_version: str
    operation: str
    mode: str
    status: str
    running_count: int
    eligible_stale_count: int
    recovered_count: int
    remaining_running_count: int
    privacy: dict[str, bool]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=True, sort_keys=True) + "\n"


def parse_recovery_cutoff(value: str | datetime | None) -> datetime:
    """Require one explicit timezone-aware ISO cutoff and normalize it to UTC."""

    if isinstance(value, datetime):
        cutoff = value
    elif isinstance(value, str) and value.strip():
        token = value.strip()
        if token.endswith(("Z", "z")):
            token = f"{token[:-1]}+00:00"
        try:
            cutoff = datetime.fromisoformat(token)
        except ValueError as exc:
            raise ValueError("cutoff must be a timezone-aware ISO timestamp") from exc
    else:
        raise ValueError("cutoff is required")
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("cutoff must include an explicit timezone offset")
    return cutoff.astimezone(UTC)


def _require_established_runtime(settings: Settings) -> RuntimePaths:
    paths = resolve_runtime_paths(settings)
    if not paths.root.is_dir():
        raise SyncRunRecoveryRuntimeError("runtime_missing")
    if not paths.config.is_file() or not paths.database.is_file():
        raise SyncRunRecoveryRuntimeError("runtime_not_established")
    try:
        readiness = database_readiness(paths)
    except (OSError, SQLAlchemyError) as exc:
        raise SyncRunRecoveryRuntimeError("runtime_not_established") from exc
    if not readiness["ready"]:
        raise SyncRunRecoveryRuntimeError("runtime_not_established")
    return paths


def _is_stale(started_at: datetime | None, cutoff: datetime) -> bool:
    normalized = restore_stored_utc(started_at)
    return normalized is not None and normalized < cutoff


def recover_stale_sync_runs(
    settings: Settings,
    *,
    cutoff: str | datetime,
    apply: bool,
    clock: Callable[[], datetime] | None = None,
) -> SyncRunRecoveryReport:
    """List or terminalize stale running rows while excluding live operations."""

    normalized_cutoff = parse_recovery_cutoff(cutoff)
    paths = _require_established_runtime(settings)
    completed_at = (clock or (lambda: datetime.now(UTC)))()
    if completed_at.tzinfo is None or completed_at.utcoffset() is None:
        raise ValueError("recovery clock must return a timezone-aware datetime")
    completed_at = completed_at.astimezone(UTC)

    with ExternalRuntimeOperationLock(paths, allow_reentrant=False):
        engine = create_sqlite_engine(paths)
        try:
            factory = create_session_factory(engine)
            with factory() as session:
                repository = repositories_for(session).sync
                running = repository.running_runs()
                stale_count = sum(
                    1 for run in running if _is_stale(run.started_at, normalized_cutoff)
                )
                recovered_count = 0
                if apply:
                    recovered_count = repository.recover_stale_running(
                        cutoff=normalized_cutoff,
                        completed_at=completed_at,
                    )
                    session.commit()
                remaining_running_count = len(repository.running_runs())
        finally:
            engine.dispose()

    return SyncRunRecoveryReport(
        contract_version=SYNC_RUN_RECOVERY_CONTRACT_VERSION,
        operation="sync-run-recovery",
        mode="apply" if apply else "dry_run",
        status="ok",
        running_count=len(running),
        eligible_stale_count=stale_count,
        recovered_count=recovered_count,
        remaining_running_count=remaining_running_count,
        privacy={
            "raw_values_emitted": False,
            "private_identifiers_emitted": False,
            "tokens_emitted": False,
            "health_timestamps_emitted": False,
        },
    )


__all__ = [
    "SYNC_RUN_RECOVERY_CONTRACT_VERSION",
    "SyncRunRecoveryReport",
    "SyncRunRecoveryRuntimeError",
    "parse_recovery_cutoff",
    "recover_stale_sync_runs",
]
