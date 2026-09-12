"""Owner-invoked bounded Google Health historical backfill.

Operationally distinct from incremental sync: explicit start/end, deterministic
chunks, isolated historical checkpoints, and resume from completed coverage.
It reuses the #88 fetch/pagination/retry/persistence engine and never writes
Garmin tables or performs owner-live calls from worker space.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from healthcheck.config import Settings
from healthcheck.google.auth import GoogleAuthResult, GoogleAuthService, GoogleHttpTransport
from healthcheck.google.contracts import GoogleQueryMode
from healthcheck.google.sync import (
    HEART_RATE_ROLLUP_MAX_DAYS,
    MAX_SYNC_PROVIDER_REQUESTS,
    SYNC_CONTRACT_VERSION,
    GoogleHealthSync,
    GoogleRunKind,
    GoogleSyncAttempt,
    GoogleSyncReport,
    GoogleSyncStatus,
    _roll_up_status,
    inclusive_to_exclusive_end,
    parse_data_source_family,
    parse_google_streams,
    parse_query_mode,
    validate_inclusive_window,
)

BACKFILL_CONTRACT_VERSION = "r04-google-historical-backfill-v1"
DEFAULT_BACKFILL_CHUNK_DAYS = 7
MAX_BACKFILL_CHUNK_DAYS = 14
MAX_BACKFILL_SPAN_DAYS = 3660
MAX_BACKFILL_PROVIDER_REQUESTS = MAX_SYNC_PROVIDER_REQUESTS


@dataclass(frozen=True, slots=True)
class GoogleBackfillChunkPlan:
    """Sanitized planned chunk: dates and request bounds only."""

    index: int
    start: str
    end: str
    day_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "day_count": self.day_count,
        }


def validate_chunk_days(value: int | None, *, query_mode: GoogleQueryMode) -> int:
    chunk_days = DEFAULT_BACKFILL_CHUNK_DAYS if value is None else value
    if not isinstance(chunk_days, int) or isinstance(chunk_days, bool) or chunk_days < 1:
        raise ValueError("chunk_days must be a positive integer")
    maximum = MAX_BACKFILL_CHUNK_DAYS
    if query_mode in {GoogleQueryMode.ROLL_UP, GoogleQueryMode.DAILY_ROLL_UP}:
        maximum = min(maximum, HEART_RATE_ROLLUP_MAX_DAYS)
    if chunk_days > maximum:
        raise ValueError(f"chunk_days must be <= {maximum}")
    return chunk_days


def plan_google_historical_chunks(
    start: date,
    end_inclusive: date,
    *,
    chunk_days: int,
) -> tuple[GoogleBackfillChunkPlan, ...]:
    if end_inclusive < start:
        raise ValueError("window end must be on or after start")
    span = (end_inclusive - start).days + 1
    if span > MAX_BACKFILL_SPAN_DAYS:
        raise ValueError(f"historical backfill span must be <= {MAX_BACKFILL_SPAN_DAYS} days")
    chunks: list[GoogleBackfillChunkPlan] = []
    cursor = start
    index = 0
    while cursor <= end_inclusive:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end_inclusive)
        chunks.append(
            GoogleBackfillChunkPlan(
                index=index,
                start=cursor.isoformat(),
                end=chunk_end.isoformat(),
                day_count=(chunk_end - cursor).days + 1,
            )
        )
        cursor = chunk_end + timedelta(days=1)
        index += 1
    return tuple(chunks)


def plan_google_historical_backfill(
    *,
    start: date | str,
    end: date | str,
    streams: Sequence[str] | None = None,
    chunk_days: int | None = None,
    query_mode: str | GoogleQueryMode | None = None,
    data_source_family: str | None = None,
) -> GoogleSyncReport:
    start_date, end_inclusive = validate_inclusive_window(start, end)
    mode = parse_query_mode(query_mode)
    family = parse_data_source_family(data_source_family)
    surfaces = parse_google_streams(streams)
    validate_chunk_days(chunk_days, query_mode=mode)
    return GoogleSyncReport(
        auth=None,
        status=GoogleSyncStatus.SUCCEEDED,
        kind=GoogleRunKind.HISTORICAL,
        window_start=start_date.isoformat(),
        window_end_exclusive=inclusive_to_exclusive_end(end_inclusive).isoformat(),
        request_count=0,
        query_mode=mode.value,
        data_source_family=family,
        streams=tuple(item.code for item in surfaces),
        dry_run=True,
        attempts=(),
    )


class GoogleHistoricalBackfill:
    """Run one bounded historical backfill using isolated checkpoints."""

    def __init__(
        self,
        settings: Settings,
        *,
        auth_service: GoogleAuthService | None = None,
        transport: GoogleHttpTransport | None = None,
        auth_result: GoogleAuthResult | None = None,
        access_token: str | None = None,
        granted_scopes: frozenset[str] | None = None,
        sleeper: Callable[[float], None] | None = None,
        max_provider_requests: int = MAX_BACKFILL_PROVIDER_REQUESTS,
    ) -> None:
        self.settings = settings
        self.auth_service = auth_service
        self.transport = transport
        self.auth_result = auth_result
        self.access_token = access_token
        self.granted_scopes = granted_scopes
        self.sleeper = sleeper
        self.max_provider_requests = max_provider_requests

    def run(
        self,
        *,
        start: date | str,
        end: date | str,
        streams: Sequence[str] | None = None,
        chunk_days: int | None = None,
        query_mode: str | GoogleQueryMode | None = None,
        data_source_family: str | None = None,
    ) -> GoogleSyncReport:
        start_date, end_inclusive = validate_inclusive_window(start, end)
        mode = parse_query_mode(query_mode)
        family = parse_data_source_family(data_source_family)
        surfaces = parse_google_streams(streams)
        days = validate_chunk_days(chunk_days, query_mode=mode)
        chunks = plan_google_historical_chunks(start_date, end_inclusive, chunk_days=days)
        attempts: list[GoogleSyncAttempt] = []
        request_count = 0
        abort_reason: str | None = None
        last_report: GoogleSyncReport | None = None
        remaining_budget = self.max_provider_requests
        for chunk in chunks:
            if abort_reason == "reauth_required" or remaining_budget < 1:
                if remaining_budget < 1 and abort_reason != "reauth_required":
                    abort_reason = abort_reason or "request_ceiling"
                for surface in surfaces:
                    attempts.append(
                        GoogleSyncAttempt(
                            stream=surface.code,
                            data_type=surface.data_type,
                            query_mode=mode.value,
                            data_source_family=family,
                            window_start=chunk.start,
                            window_end_exclusive=inclusive_to_exclusive_end(
                                date.fromisoformat(chunk.end)
                            ).isoformat(),
                            status=GoogleSyncStatus.NOT_RUN,
                            coverage_status=None,
                            not_run_reason=abort_reason or "request_ceiling",
                        )
                    )
                continue
            chunk_start = date.fromisoformat(chunk.start)
            chunk_end = date.fromisoformat(chunk.end)
            engine = GoogleHealthSync(
                self.settings,
                auth_service=self.auth_service,
                transport=self.transport,
                auth_result=self.auth_result,
                access_token=self.access_token,
                granted_scopes=self.granted_scopes,
                sleeper=self.sleeper,
                max_provider_requests=remaining_budget,
                run_kind=GoogleRunKind.HISTORICAL,
            )
            report = engine.run_window(
                start=chunk_start,
                end_exclusive=inclusive_to_exclusive_end(chunk_end),
                streams=[item.code for item in surfaces],
                query_mode=mode,
                data_source_family=family,
                skip_complete=True,
            )
            last_report = report
            request_count += report.request_count
            remaining_budget = max(0, remaining_budget - report.request_count)
            attempts.extend(report.attempts)
            if report.abort_reason == "reauth_required":
                abort_reason = "reauth_required"
            elif remaining_budget < 1 and abort_reason is None:
                abort_reason = "request_ceiling"
        status = _roll_up_status(attempts, abort_reason)
        skipped = sum(1 for item in attempts if item.skipped)
        return GoogleSyncReport(
            auth=last_report.auth if last_report is not None else self.auth_result,
            status=status,
            kind=GoogleRunKind.HISTORICAL,
            window_start=start_date.isoformat(),
            window_end_exclusive=inclusive_to_exclusive_end(end_inclusive).isoformat(),
            request_count=request_count,
            query_mode=mode.value,
            data_source_family=family,
            streams=tuple(item.code for item in surfaces),
            sync_run_id=last_report.sync_run_id if last_report is not None else None,
            attempts=tuple(attempts),
            abort_reason=abort_reason,
            skipped_complete_count=skipped,
        )


def run_google_historical_backfill(
    settings: Settings,
    *,
    start: date | str,
    end: date | str,
    streams: Sequence[str] | None = None,
    chunk_days: int | None = None,
    query_mode: str | GoogleQueryMode | None = None,
    data_source_family: str | None = None,
    auth_service: GoogleAuthService | None = None,
    transport: GoogleHttpTransport | None = None,
    auth_result: GoogleAuthResult | None = None,
    access_token: str | None = None,
    granted_scopes: frozenset[str] | None = None,
    sleeper: Callable[[float], None] | None = None,
    max_provider_requests: int = MAX_BACKFILL_PROVIDER_REQUESTS,
) -> GoogleSyncReport:
    return GoogleHistoricalBackfill(
        settings,
        auth_service=auth_service,
        transport=transport,
        auth_result=auth_result,
        access_token=access_token,
        granted_scopes=granted_scopes,
        sleeper=sleeper,
        max_provider_requests=max_provider_requests,
    ).run(
        start=start,
        end=end,
        streams=streams,
        chunk_days=chunk_days,
        query_mode=query_mode,
        data_source_family=data_source_family,
    )


__all__ = [
    "BACKFILL_CONTRACT_VERSION",
    "DEFAULT_BACKFILL_CHUNK_DAYS",
    "MAX_BACKFILL_CHUNK_DAYS",
    "MAX_BACKFILL_PROVIDER_REQUESTS",
    "MAX_BACKFILL_SPAN_DAYS",
    "SYNC_CONTRACT_VERSION",
    "GoogleBackfillChunkPlan",
    "GoogleHistoricalBackfill",
    "plan_google_historical_backfill",
    "plan_google_historical_chunks",
    "run_google_historical_backfill",
    "validate_chunk_days",
]
