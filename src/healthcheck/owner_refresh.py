"""Bounded manual refresh of the owner Garmin and Google runtimes."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from healthcheck.config import Settings
from healthcheck.db.engine import database_readiness
from healthcheck.garmin.auth import GarminAuthService
from healthcheck.garmin.sync import (
    GarminIncrementalSync,
    GarminSyncReport,
    GarminSyncStatus,
    compute_sync_window,
    validate_sync_date,
    validate_trailing_window_days,
)
from healthcheck.google.auth import GoogleAuthService
from healthcheck.google.sync import (
    GoogleSyncAttempt,
    GoogleSyncReport,
    GoogleSyncStatus,
    _roll_up_status,
    run_google_refresh,
)
from healthcheck.runtime import RuntimePaths, resolve_runtime_paths

OWNER_REFRESH_CONTRACT_VERSION = "healthcheck-owner-refresh-v1"

# Fixed second Google layer required by R05 account_wearables_sleep_observations_v1.
OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_STREAMS: tuple[str, ...] = ("sleep",)
OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_QUERY_MODE = "reconcile"
OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_FAMILY = "google-wearables"
# The normal bounded refresh consumes up to 40 pages. Each resumed refresh
# revalidates one head page, then consumes up to 39 continuation pages. Two
# continuation rounds therefore complete the synthetic 82-page acceptance
# window while retaining the existing per-call provider caps.
OWNER_REFRESH_GOOGLE_HEART_RATE_CONTINUATION_ROUNDS = 2


class OwnerRefreshStatus(StrEnum):
    """Combined outcome of one bounded multi-step owner refresh."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    REAUTH_REQUIRED = "reauth_required"


class OwnerRefreshRuntimeError(ValueError):
    """The requested path is not an already-established Health-Check runtime."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class OwnerRefreshBusyError(RuntimeError):
    """Another owner refresh currently holds the same-profile lock."""


class OwnerRefreshLock:
    """Non-blocking process lock for one established external runtime profile."""

    def __init__(self, paths: RuntimePaths) -> None:
        self.path = paths.root / ".owner-refresh.lock"
        self._handle = None

    def __enter__(self) -> OwnerRefreshLock:
        try:
            self._handle = self.path.open("a+b")
        except OSError as exc:
            raise OwnerRefreshRuntimeError("runtime_lock_unavailable") from exc

        try:
            if os.name == "nt":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (ImportError, OSError) as exc:
            self._handle.close()
            self._handle = None
            raise OwnerRefreshBusyError from exc
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        if self._handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


def require_established_runtime(settings: Settings) -> RuntimePaths:
    """Validate an existing profile without creating any runtime paths."""

    paths = resolve_runtime_paths(settings)
    if not paths.root.is_dir():
        raise OwnerRefreshRuntimeError("runtime_missing")
    if not paths.config.is_file() or not paths.database.is_file():
        raise OwnerRefreshRuntimeError("runtime_not_established")
    try:
        readiness = database_readiness(paths)
    except (OSError, SQLAlchemyError) as exc:
        raise OwnerRefreshRuntimeError("runtime_not_established") from exc
    if not readiness["ready"]:
        raise OwnerRefreshRuntimeError("runtime_not_established")
    return paths


@dataclass(frozen=True, slots=True)
class OwnerRefreshReport:
    """Privacy-safe summary for one manual Garmin + dual-Google refresh."""

    status: OwnerRefreshStatus
    as_of: str
    window_start: str
    window_end: str
    trailing_window_days: int
    garmin: GarminSyncReport
    google: GoogleSyncReport
    google_wearables_sleep: GoogleSyncReport

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": OWNER_REFRESH_CONTRACT_VERSION,
            "operation": "owner-refresh",
            "refresh": {
                "status": self.status.value,
                "as_of": self.as_of,
                "window_start": self.window_start,
                "window_end": self.window_end,
                "trailing_window_days": self.trailing_window_days,
            },
            "garmin": self.garmin.as_dict(),
            "google": self.google.as_dict(),
            "google_wearables_sleep": self.google_wearables_sleep.as_dict(),
            "privacy": {
                "raw_values_emitted": False,
                "private_identifiers_emitted": False,
                "tokens_emitted": False,
                "health_timestamps_emitted": False,
                "page_tokens_emitted": False,
                "string_encoded_numerics_logged_as_values": False,
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def _combined_status(
    *statuses: GarminSyncStatus | GoogleSyncStatus,
) -> OwnerRefreshStatus:
    """Combine required refresh sub-step statuses into one owner outcome.

    Status contract:
    - REAUTH_REQUIRED if any required step needs reauthentication;
    - SUCCEEDED only when every required step is SUCCEEDED or EMPTY;
    - PARTIAL when at least one required step succeeded/empty and another did not;
    - FAILED when no required step succeeded/empty.
    """

    if any(
        status is GarminSyncStatus.REAUTH_REQUIRED or status is GoogleSyncStatus.REAUTH_REQUIRED
        for status in statuses
    ):
        return OwnerRefreshStatus.REAUTH_REQUIRED

    good = {
        GarminSyncStatus.SUCCEEDED,
        GarminSyncStatus.EMPTY,
        GoogleSyncStatus.SUCCEEDED,
        GoogleSyncStatus.EMPTY,
    }
    if all(status in good for status in statuses):
        return OwnerRefreshStatus.SUCCEEDED

    if any(status in good for status in statuses):
        return OwnerRefreshStatus.PARTIAL
    return OwnerRefreshStatus.FAILED


def _resumable_heart_rate_attempt(report: GoogleSyncReport) -> GoogleSyncAttempt | None:
    """Return the sole bounded page-ceiling HR attempt eligible to continue."""

    if report.status is not GoogleSyncStatus.PARTIAL:
        return None
    attempts = [item for item in report.attempts if item.stream == "heart_rate"]
    if len(attempts) != 1:
        return None
    attempt = attempts[0]
    error = attempt.error
    if (
        attempt.status is not GoogleSyncStatus.PARTIAL
        or not attempt.resume_cursor_present
        or error is None
        or error.error_class != "budget"
        or error.error_code != "page_ceiling"
    ):
        return None
    return attempt


def _consolidate_google_refresh_reports(
    reports: Sequence[GoogleSyncReport],
) -> GoogleSyncReport:
    """Keep one normal report while folding bounded HR continuation evidence."""

    if not reports:
        raise ValueError("at least one Google refresh report is required")
    primary = reports[0]
    if len(reports) == 1:
        return primary
    total_request_count = sum(report.request_count for report in reports)
    hr_indexes = [
        index for index, attempt in enumerate(primary.attempts) if attempt.stream == "heart_rate"
    ]
    if len(hr_indexes) != 1:
        return primary
    hr_index = hr_indexes[0]
    hr_attempts = [
        report.attempts[0]
        for report in reports[1:]
        if len(report.attempts) == 1 and report.attempts[0].stream == "heart_rate"
    ]
    if not hr_attempts:
        continuation = reports[-1]
        if continuation.status is GoogleSyncStatus.REAUTH_REQUIRED:
            abort_reason = continuation.abort_reason or continuation.status.value
            return replace(
                primary,
                status=GoogleSyncStatus.REAUTH_REQUIRED,
                request_count=total_request_count,
                abort_reason=abort_reason,
            )
        if continuation.status not in {
            GoogleSyncStatus.SUCCEEDED,
            GoogleSyncStatus.EMPTY,
        }:
            abort_reason = continuation.abort_reason or continuation.status.value
            return replace(
                primary,
                request_count=total_request_count,
                abort_reason=abort_reason,
            )
        return replace(primary, request_count=total_request_count)
    # Keep attempt counters scoped to their final provider operation so the
    # existing per-call cap remains visibly true. The enclosing report's
    # request_count is the honest aggregate across the normal call and bounded
    # continuation calls.
    consolidated = hr_attempts[-1]
    attempts = list(primary.attempts)
    attempts[hr_index] = consolidated
    abort_reason = next(
        (report.abort_reason for report in reversed(reports) if report.abort_reason is not None),
        primary.abort_reason,
    )
    return replace(
        primary,
        status=_roll_up_status(attempts, abort_reason),
        request_count=total_request_count,
        attempts=tuple(attempts),
        abort_reason=abort_reason,
        skipped_complete_count=sum(report.skipped_complete_count for report in reports),
    )


def _run_normal_google_refresh(
    settings: Settings,
    *,
    auth_service: GoogleAuthService,
    start: date | str,
    end: date | str,
    streams: list[str] | None,
    query_mode: str | None,
    data_source_family: str | None,
) -> GoogleSyncReport:
    """Run normal Google refresh plus only eligible bounded HR continuations."""

    reports = [
        run_google_refresh(
            settings,
            start=start,
            end=end,
            auth_service=auth_service,
            streams=streams,
            query_mode=query_mode,
            data_source_family=data_source_family,
        )
    ]
    for _ in range(OWNER_REFRESH_GOOGLE_HEART_RATE_CONTINUATION_ROUNDS):
        if _resumable_heart_rate_attempt(reports[-1]) is None:
            break
        reports.append(
            run_google_refresh(
                settings,
                start=start,
                end=end,
                auth_service=auth_service,
                streams=["heart_rate"],
                query_mode=query_mode,
                data_source_family=data_source_family,
            )
        )
    return _consolidate_google_refresh_reports(reports)


def run_owner_refresh(
    settings: Settings,
    *,
    as_of: str | None = None,
    trailing_window_days: int | None = None,
    is_cn: bool = False,
    streams: list[str] | None = None,
    query_mode: str | None = None,
    data_source_family: str | None = None,
) -> OwnerRefreshReport:
    """Run Garmin plus both Google refresh layers over one local-date window.

    Under the same established-runtime overlap lock this runs:

    1. existing bounded Garmin incremental sync;
    2. existing normal bounded Google refresh (CLI stream/query/family overrides
       apply only to this layer);
    3. fixed sleep-only Google refresh with ``query_mode=reconcile`` and
       ``data_source_family=google-wearables`` for the R05 exploratory cohort.

    Garmin remains the owner of incremental-window validation. Both Google
    layers receive the exact inclusive date window derived from that same
    validated Garmin window and retain their own refresh/checkpoint semantics.
    """

    paths = require_established_runtime(settings)
    as_of_date = validate_sync_date(as_of)
    window_days = validate_trailing_window_days(trailing_window_days)
    window_start, window_end = compute_sync_window(as_of_date, window_days)

    with OwnerRefreshLock(paths):
        garmin_auth = GarminAuthService(settings, is_cn=is_cn)
        garmin_client, garmin_auth_result = garmin_auth.load_existing()
        garmin = GarminIncrementalSync(
            settings,
            client=garmin_client,
            auth_result=garmin_auth_result,
        ).run(as_of=as_of_date, trailing_window_days=window_days)

        google_auth = GoogleAuthService(settings)
        google = _run_normal_google_refresh(
            settings,
            start=window_start,
            end=window_end,
            auth_service=google_auth,
            streams=streams,
            query_mode=query_mode,
            data_source_family=data_source_family,
        )
        google_wearables_sleep = run_google_refresh(
            settings,
            start=window_start,
            end=window_end,
            auth_service=google_auth,
            streams=list(OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_STREAMS),
            query_mode=OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_QUERY_MODE,
            data_source_family=OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_FAMILY,
        )

    return OwnerRefreshReport(
        status=_combined_status(garmin.status, google.status, google_wearables_sleep.status),
        as_of=as_of_date.isoformat(),
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        trailing_window_days=window_days,
        garmin=garmin,
        google=google,
        google_wearables_sleep=google_wearables_sleep,
    )


__all__ = [
    "OWNER_REFRESH_CONTRACT_VERSION",
    "OWNER_REFRESH_GOOGLE_HEART_RATE_CONTINUATION_ROUNDS",
    "OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_FAMILY",
    "OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_QUERY_MODE",
    "OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_STREAMS",
    "OwnerRefreshBusyError",
    "OwnerRefreshLock",
    "OwnerRefreshReport",
    "OwnerRefreshRuntimeError",
    "OwnerRefreshStatus",
    "require_established_runtime",
    "run_owner_refresh",
]
