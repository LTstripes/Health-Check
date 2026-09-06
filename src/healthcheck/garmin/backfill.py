"""Owner-invoked one-time Garmin historical backfill.

This command is operationally distinct from the recurring incremental sync
loop.  It reuses the accepted #48 auth, provider, normalization, persistence,
and reconciliation path; it does not add a second ingestion stack, a
scheduler, FIT/GPS downloads, or new provider capabilities.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
from healthcheck.db.models import SyncStreamState
from healthcheck.db.repositories import repositories_for
from healthcheck.garmin.auth import (
    AUTH_CONTRACT_VERSION,
    GARMIN_AUTH_STORAGE,
    GarminAuthResult,
    GarminAuthStatus,
)
from healthcheck.garmin.capabilities import (
    GARMIN_PROVIDER_CODE,
    GARMINCONNECT_VERSION,
    VIVOACTIVE_5_DEVICE_CODE,
    VIVOACTIVE_5_MODEL,
)
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.garmin.sync import (
    ACTIVITY_PAGE_SIZE,
    DEFAULT_TRAILING_WINDOW_DAYS,
    INCREMENTAL_RUN_STREAM,
    MAX_ACTIVITY_PAGES,
    MAX_SYNC_PROVIDER_REQUESTS,
    MAX_TRAILING_WINDOW_DAYS,
    PRODUCTION_SYNC_SURFACES,
    GarminIncrementalSync,
    GarminSyncAttempt,
    GarminSyncStatus,
    GarminSyncSurface,
    _calendar_days,
    _day_bounds,
    _not_run_remainder,
    _roll_up_status,
    _run_status_token,
    _SyncBudget,
    validate_sync_date,
)
from healthcheck.logging import log_event
from healthcheck.runtime import prepare_runtime

BACKFILL_CONTRACT_VERSION = "r02-garmin-historical-backfill-v1"
HISTORICAL_RUN_STREAM = "garmin_historical"
HISTORICAL_CHECKPOINT_NAMESPACE = "garmin_historical"
DEFAULT_BACKFILL_CHUNK_DAYS = 7
MAX_BACKFILL_CHUNK_DAYS = 14
MAX_BACKFILL_SPAN_DAYS = 3660
MAX_BACKFILL_PROVIDER_REQUESTS = MAX_SYNC_PROVIDER_REQUESTS
_SURFACE_BY_CODE = {item.code: item for item in PRODUCTION_SYNC_SURFACES}


@dataclass(frozen=True, slots=True)
class GarminBackfillChunkPlan:
    """Sanitized planned chunk: dates, methods, and request bounds only."""

    index: int
    start: str
    end: str
    day_count: int
    per_day_methods: tuple[str, ...]
    range_methods: tuple[str, ...]
    per_day_request_count: int
    range_request_count_min: int
    range_request_count_max: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "day_count": self.day_count,
            "request_shape": {
                "per_day_methods": list(self.per_day_methods),
                "per_day_request_count": self.per_day_request_count,
                "range_methods": list(self.range_methods),
                "range_request_count_min": self.range_request_count_min,
                "range_request_count_max": self.range_request_count_max,
                "activity_page_size": ACTIVITY_PAGE_SIZE if self.range_methods else 0,
            },
        }


@dataclass(frozen=True, slots=True)
class GarminBackfillReport:
    """Deterministic machine-readable historical-backfill summary."""

    status: GarminSyncStatus
    start: str
    end: str
    chunk_days: int
    streams: tuple[str, ...]
    dry_run: bool
    request_count: int
    auth: GarminAuthResult | None = None
    sync_run_id: str | None = None
    attempts: tuple[GarminSyncAttempt, ...] = ()
    chunks: tuple[GarminBackfillChunkPlan, ...] = ()
    skipped_complete_count: int = 0
    remaining_chunk_count: int = 0
    remaining_day_count: int = 0
    abort_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        if self.auth is None:
            auth_payload: dict[str, Any] = {
                "contract_version": AUTH_CONTRACT_VERSION,
                "status": "not_attempted",
                "session_reused": False,
                "mfa": "not_attempted",
                "storage": GARMIN_AUTH_STORAGE,
                "error": None,
            }
        else:
            auth_payload = self.auth.as_dict()
        return {
            "contract_version": BACKFILL_CONTRACT_VERSION,
            "source": {
                "provider_code": GARMIN_PROVIDER_CODE,
                "target_device_code": VIVOACTIVE_5_DEVICE_CODE,
                "target_device_model": VIVOACTIVE_5_MODEL,
            },
            "library": {
                "name": "python-garminconnect",
                "version": GARMINCONNECT_VERSION,
            },
            "auth": auth_payload,
            "backfill": {
                "status": self.status.value,
                "start": self.start,
                "end": self.end,
                "chunk_days": self.chunk_days,
                "streams": list(self.streams),
                "dry_run": self.dry_run,
                "request_count": self.request_count,
                "max_provider_requests": MAX_BACKFILL_PROVIDER_REQUESTS,
                "sync_run_id": self.sync_run_id,
                "abort_reason": self.abort_reason,
                "skipped_complete_count": self.skipped_complete_count,
                "remaining_chunk_count": self.remaining_chunk_count,
                "remaining_day_count": self.remaining_day_count,
                "chunk_count": len(self.chunks),
                "historical_backfill": True,
                "gps_or_fit_downloaded": False,
                "incremental_run_stream": INCREMENTAL_RUN_STREAM,
                "incremental_trailing_window_unchanged": True,
                "default_trailing_window_days": DEFAULT_TRAILING_WINDOW_DAYS,
                "max_trailing_window_days": MAX_TRAILING_WINDOW_DAYS,
            },
            "privacy": {
                "raw_values_emitted": False,
                "private_identifiers_emitted": False,
                "tokens_emitted": False,
                "health_timestamps_emitted": False,
            },
            "chunks": [item.as_dict() for item in self.chunks],
            "attempts": [item.as_dict() for item in self.attempts],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def validate_backfill_range(start: date | str | None, end: date | str | None) -> tuple[date, date]:
    """Require an explicit inclusive local-date span; never default to all history."""

    if start is None or end is None:
        raise ValueError("garmin-backfill requires explicit --start and --end")
    start_date = validate_sync_date(start)
    end_date = validate_sync_date(end)
    if end_date < start_date:
        raise ValueError("garmin-backfill end must not precede start")
    span_days = (end_date - start_date).days + 1
    if span_days > MAX_BACKFILL_SPAN_DAYS:
        raise ValueError(
            f"garmin-backfill span must be at most {MAX_BACKFILL_SPAN_DAYS} days"
        )
    return start_date, end_date


def validate_backfill_chunk_days(value: int | None) -> int:
    days = DEFAULT_BACKFILL_CHUNK_DAYS if value is None else value
    if not isinstance(days, int) or isinstance(days, bool):
        raise ValueError("chunk_days must be an integer")
    if days < 1 or days > MAX_BACKFILL_CHUNK_DAYS:
        raise ValueError(f"chunk_days must be between 1 and {MAX_BACKFILL_CHUNK_DAYS}")
    return days


def resolve_backfill_surfaces(
    stream_codes: Sequence[str] | None,
) -> tuple[GarminSyncSurface, ...]:
    """Resolve an explicit subset of the accepted production surfaces."""

    if not stream_codes:
        return PRODUCTION_SYNC_SURFACES
    resolved: list[GarminSyncSurface] = []
    seen: set[str] = set()
    for raw in stream_codes:
        code = raw.strip() if isinstance(raw, str) else ""
        if not code:
            raise ValueError("garmin-backfill stream must be a non-empty code")
        if code not in _SURFACE_BY_CODE:
            raise ValueError("garmin-backfill stream is not an accepted production surface")
        if code in seen:
            continue
        seen.add(code)
        resolved.append(_SURFACE_BY_CODE[code])
    if not resolved:
        raise ValueError("garmin-backfill requires at least one stream")
    return tuple(resolved)


def plan_backfill_chunks(
    start: date,
    end: date,
    *,
    chunk_days: int,
    surfaces: Sequence[GarminSyncSurface],
) -> tuple[GarminBackfillChunkPlan, ...]:
    days = _calendar_days(start, end)
    per_day_methods = tuple(item.method for item in surfaces if item.per_day)
    range_methods = tuple(item.method for item in surfaces if not item.per_day)
    plans: list[GarminBackfillChunkPlan] = []
    for index in range(0, len(days), chunk_days):
        chunk = days[index : index + chunk_days]
        per_day_count = len(per_day_methods) * len(chunk)
        range_min = len(range_methods)
        range_max = MAX_ACTIVITY_PAGES if range_methods else 0
        plans.append(
            GarminBackfillChunkPlan(
                index=len(plans),
                start=chunk[0].isoformat(),
                end=chunk[-1].isoformat(),
                day_count=len(chunk),
                per_day_methods=per_day_methods,
                range_methods=range_methods,
                per_day_request_count=per_day_count,
                range_request_count_min=range_min,
                range_request_count_max=range_max,
            )
        )
    return tuple(plans)


def plan_garmin_historical_backfill(
    *,
    start: date | str | None,
    end: date | str | None,
    streams: Sequence[str] | None = None,
    chunk_days: int | None = None,
) -> GarminBackfillReport:
    """Return the intended date span/chunk/request shape without fetching."""

    start_date, end_date = validate_backfill_range(start, end)
    surfaces = resolve_backfill_surfaces(streams)
    days = validate_backfill_chunk_days(chunk_days)
    chunks = plan_backfill_chunks(start_date, end_date, chunk_days=days, surfaces=surfaces)
    return GarminBackfillReport(
        status=GarminSyncStatus.NOT_RUN,
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        chunk_days=days,
        streams=tuple(item.code for item in surfaces),
        dry_run=True,
        request_count=0,
        chunks=chunks,
        remaining_chunk_count=len(chunks),
        remaining_day_count=(end_date - start_date).days + 1,
    )


class GarminHistoricalBackfill:
    """Chunked, resumable owner-invoked historical Garmin import."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: Any | None = None,
        auth_result: GarminAuthResult | None = None,
        clock: Callable[[], datetime] | None = None,
        max_provider_requests: int = MAX_BACKFILL_PROVIDER_REQUESTS,
    ) -> None:
        self.settings = settings
        self.auth_result = auth_result or GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.ingest = GarminIncrementalSync(
            settings,
            client=client,
            auth_result=self.auth_result,
            clock=self.clock,
            max_provider_requests=max_provider_requests,
            run_stream=HISTORICAL_RUN_STREAM,
            checkpoint_namespace=HISTORICAL_CHECKPOINT_NAMESPACE,
            skip_complete_coverage=True,
        )

    def run(
        self,
        *,
        start: date | str | None,
        end: date | str | None,
        streams: Sequence[str] | None = None,
        chunk_days: int | None = None,
        dry_run: bool = False,
    ) -> GarminBackfillReport:
        start_date, end_date = validate_backfill_range(start, end)
        surfaces = resolve_backfill_surfaces(streams)
        days = validate_backfill_chunk_days(chunk_days)
        chunks = plan_backfill_chunks(start_date, end_date, chunk_days=days, surfaces=surfaces)
        if dry_run:
            return GarminBackfillReport(
                status=GarminSyncStatus.NOT_RUN,
                start=start_date.isoformat(),
                end=end_date.isoformat(),
                chunk_days=days,
                streams=tuple(item.code for item in surfaces),
                dry_run=True,
                request_count=0,
                auth=self.auth_result if self.auth_result.ok else None,
                chunks=chunks,
                remaining_chunk_count=len(chunks),
                remaining_day_count=(end_date - start_date).days + 1,
            )

        paths = prepare_runtime(self.settings)
        migrate_database(paths)
        engine = create_sqlite_engine(paths)
        store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
        factory = create_session_factory(engine)
        try:
            return self._run(
                factory,
                store,
                start=start_date,
                end=end_date,
                surfaces=surfaces,
                chunk_days=days,
                chunks=chunks,
            )
        finally:
            engine.dispose()

    def _run(
        self,
        factory,
        store: ContentAddressedGarminPayloadStore,
        *,
        start: date,
        end: date,
        surfaces: Sequence[GarminSyncSurface],
        chunk_days: int,
        chunks: Sequence[GarminBackfillChunkPlan],
    ) -> GarminBackfillReport:
        auth = self.auth_result
        if self.ingest.client is None or not auth.ok:
            status = (
                GarminSyncStatus.REAUTH_REQUIRED
                if auth.status is GarminAuthStatus.REAUTH_REQUIRED
                else GarminSyncStatus.FAILED
            )
            run_id = self.ingest._record_auth_failure(
                factory,
                status=status,
                window_start=start,
                window_end=end,
            )
            return GarminBackfillReport(
                status=status,
                start=start.isoformat(),
                end=end.isoformat(),
                chunk_days=chunk_days,
                streams=tuple(item.code for item in surfaces),
                dry_run=False,
                request_count=0,
                auth=auth,
                sync_run_id=run_id,
                chunks=chunks,
                remaining_chunk_count=len(chunks),
                remaining_day_count=(end - start).days + 1,
                abort_reason=status.value,
            )

        budget = _SyncBudget(max_requests=self.ingest.max_provider_requests)
        with factory() as session:
            provider = repositories_for(session).providers.get_or_create(
                GARMIN_PROVIDER_CODE,
                "Garmin Connect",
                "wearable",
            )
            run = repositories_for(session).sync.create_run(
                provider_id=provider.id,
                stream_code=HISTORICAL_RUN_STREAM,
                requested_start=_day_bounds(start)[0],
                requested_end=_day_bounds(end)[1],
            )
            session.commit()
            sync_run_id = run.id
            provider_id = provider.id

        attempts: list[GarminSyncAttempt] = []
        abort_reason: str | None = None
        remaining_chunk_count = len(chunks)
        remaining_day_count = (end - start).days + 1
        last_completed_chunk_end: date | None = None
        for plan in chunks:
            chunk_start = date.fromisoformat(plan.start)
            chunk_end = date.fromisoformat(plan.end)
            chunk_days_list = _calendar_days(chunk_start, chunk_end)
            chunk_attempts, abort_reason = self.ingest._ingest_window(
                factory,
                store,
                provider_id=provider_id,
                sync_run_id=sync_run_id,
                window_start=chunk_start,
                window_end=chunk_end,
                trailing_window_days=chunk_days,
                budget=budget,
                surfaces=surfaces,
                days=chunk_days_list,
            )
            if abort_reason is not None:
                chunk_attempts.extend(
                    _not_run_remainder(chunk_attempts, chunk_days_list, abort_reason, surfaces)
                )
            attempts.extend(chunk_attempts)
            chunk_executed = [
                item for item in chunk_attempts if item.status is not GarminSyncStatus.NOT_RUN
            ]
            chunk_failed = any(
                item.status
                in {
                    GarminSyncStatus.FAILED,
                    GarminSyncStatus.REAUTH_REQUIRED,
                    GarminSyncStatus.PARTIAL,
                    GarminSyncStatus.UNAVAILABLE,
                }
                or item.not_run_reason == "request_budget_exhausted"
                for item in chunk_attempts
            )
            if chunk_executed and not chunk_failed:
                last_completed_chunk_end = chunk_end
                self._write_job_checkpoint(
                    factory,
                    provider_id=provider_id,
                    cursor=chunk_end.isoformat(),
                    succeeded=True,
                )
            else:
                self._write_job_checkpoint(
                    factory,
                    provider_id=provider_id,
                    cursor=last_completed_chunk_end.isoformat()
                    if last_completed_chunk_end is not None
                    else None,
                    succeeded=False,
                )
            if abort_reason is not None:
                break
            remaining_chunk_count -= 1
            remaining_day_count -= plan.day_count

        if abort_reason is None:
            remaining_chunk_count = 0
            remaining_day_count = 0

        run_status = _roll_up_status(attempts, abort_reason)
        received = sum(item.record_count for item in attempts)
        accepted = sum(
            item.record_count
            for item in attempts
            if item.status
            in {GarminSyncStatus.SUCCEEDED, GarminSyncStatus.PARTIAL, GarminSyncStatus.EMPTY}
        )
        failed = sum(
            1
            for item in attempts
            if item.status in {GarminSyncStatus.FAILED, GarminSyncStatus.REAUTH_REQUIRED}
        )
        with factory() as session:
            repositories_for(session).sync.finish_run(
                sync_run_id,
                status=_run_status_token(run_status),
                item_count=len(attempts),
                received_count=received,
                accepted_count=accepted,
                failed_count=failed,
                error_category=abort_reason,
                diagnostic_reason=abort_reason,
                actual_start=_day_bounds(start)[0],
                actual_end=_day_bounds(end)[1],
            )
            session.commit()

        skipped_complete_count = sum(1 for item in attempts if item.skipped)
        log_event(
            "garmin_historical_backfill",
            operation="garmin-backfill",
            status=run_status.value,
            count=budget.used,
            reason=abort_reason or run_status.value,
        )
        return GarminBackfillReport(
            status=run_status,
            start=start.isoformat(),
            end=end.isoformat(),
            chunk_days=chunk_days,
            streams=tuple(item.code for item in surfaces),
            dry_run=False,
            request_count=budget.used,
            auth=auth,
            sync_run_id=sync_run_id,
            attempts=tuple(attempts),
            chunks=chunks,
            skipped_complete_count=skipped_complete_count,
            remaining_chunk_count=remaining_chunk_count,
            remaining_day_count=max(0, remaining_day_count),
            abort_reason=abort_reason,
        )

    def _write_job_checkpoint(
        self,
        factory,
        *,
        provider_id: str,
        cursor: str | None,
        succeeded: bool,
    ) -> None:
        now = self.clock()
        with factory() as session:
            previous = session.scalar(
                select(SyncStreamState).where(
                    SyncStreamState.provider_id == provider_id,
                    SyncStreamState.acquisition_source_id.is_(None),
                    SyncStreamState.stream_code == HISTORICAL_RUN_STREAM,
                )
            )
            kept_cursor = cursor
            if kept_cursor is None and previous is not None:
                kept_cursor = previous.cursor
            repositories_for(session).sync.get_or_create_state(
                provider_id=provider_id,
                acquisition_source_id=None,
                stream_code=HISTORICAL_RUN_STREAM,
                cursor=kept_cursor,
                last_success_at=now if succeeded else None,
                last_attempt_at=now,
                diagnostic_status="succeeded" if succeeded else "partial",
            )
            session.commit()


def run_garmin_historical_backfill(
    settings: Settings,
    *,
    client: Any | None = None,
    auth_result: GarminAuthResult | None = None,
    start: date | str | None = None,
    end: date | str | None = None,
    streams: Sequence[str] | None = None,
    chunk_days: int | None = None,
    dry_run: bool = False,
    max_provider_requests: int = MAX_BACKFILL_PROVIDER_REQUESTS,
) -> GarminBackfillReport:
    """Run or plan one owner-invoked historical Garmin backfill."""

    return GarminHistoricalBackfill(
        settings,
        client=client,
        auth_result=auth_result,
        max_provider_requests=max_provider_requests,
    ).run(
        start=start,
        end=end,
        streams=streams,
        chunk_days=chunk_days,
        dry_run=dry_run,
    )
