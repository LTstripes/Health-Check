"""Bounded manual refresh of the owner Garmin and Google runtimes."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from healthcheck.config import Settings
from healthcheck.db.engine import database_readiness
from healthcheck.external_runtime_lock import (
    ExternalRuntimeOperationBusyError,
    ExternalRuntimeOperationLock,
    ExternalRuntimeOperationLockError,
)
from healthcheck.garmin.auth import GarminAuthService
from healthcheck.garmin.sync import (
    GarminIncrementalSync,
    GarminSyncReport,
    GarminSyncStatus,
    compute_sync_window,
    validate_sync_date,
    validate_trailing_window_days,
)
from healthcheck.garmin.training import TRAINING_CONTRACT_VERSION, GarminTrainingSync
from healthcheck.google.auth import GoogleAuthService
from healthcheck.google.contracts import GoogleQueryMode, GoogleStream
from healthcheck.google.sync import (
    GoogleRunKind,
    GoogleSyncAttempt,
    GoogleSyncReport,
    GoogleSyncStatus,
    _roll_up_status,
    inclusive_to_exclusive_end,
    parse_data_source_family,
    parse_google_streams,
    parse_query_mode,
    run_google_refresh,
    validate_inclusive_window,
)
from healthcheck.runtime import RuntimePaths, resolve_runtime_paths

OWNER_REFRESH_CONTRACT_VERSION = "healthcheck-owner-refresh-v1"

# Fixed second Google layer required by R05 account_wearables_sleep_observations_v1.
OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_STREAMS: tuple[str, ...] = ("sleep",)
OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_QUERY_MODE = "reconcile"
OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_FAMILY = "google-wearables"
# The normal bounded refresh consumes up to 40 pages. Each resumed refresh
# revalidates one head page, then consumes up to 39 continuation pages. Two
# continuation rounds therefore complete a synthetic 82-page daily acceptance
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


class OwnerRefreshBusyError(ExternalRuntimeOperationBusyError):
    """Another owner refresh currently holds the same-profile lock."""


class OwnerRefreshLock(ExternalRuntimeOperationLock):
    """Shared runtime lock with the owner-refresh overlap contract preserved."""

    busy_error_type = OwnerRefreshBusyError

    def __init__(self, paths: RuntimePaths) -> None:
        super().__init__(paths, allow_reentrant=False)

    def __enter__(self) -> OwnerRefreshLock:
        try:
            super().__enter__()
        except ExternalRuntimeOperationLockError as exc:
            raise OwnerRefreshRuntimeError("runtime_lock_unavailable") from exc
        return self


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
    """Privacy-safe summary for one manual Garmin/Training and dual-Google refresh."""

    status: OwnerRefreshStatus
    as_of: str
    window_start: str
    window_end: str
    trailing_window_days: int
    garmin: GarminSyncReport
    garmin_training: dict[str, Any]
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
            "garmin_training": dict(self.garmin_training),
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
    *statuses: GarminSyncStatus | GoogleSyncStatus | str,
) -> OwnerRefreshStatus:
    """Combine required refresh sub-step statuses into one owner outcome.

    Status contract:
    - REAUTH_REQUIRED if any required step needs reauthentication;
    - SUCCEEDED only when every required step is SUCCEEDED or EMPTY;
    - PARTIAL when at least one required step succeeded/empty and another did not;
    - FAILED when no required step succeeded/empty.
    """

    values = tuple(status.value if isinstance(status, StrEnum) else status for status in statuses)
    if "reauth_required" in values:
        return OwnerRefreshStatus.REAUTH_REQUIRED

    good = {
        GarminSyncStatus.SUCCEEDED.value,
        GarminSyncStatus.EMPTY.value,
        GoogleSyncStatus.SUCCEEDED.value,
        GoogleSyncStatus.EMPTY.value,
    }
    if all(status in good for status in values):
        return OwnerRefreshStatus.SUCCEEDED

    if any(status in good for status in values):
        return OwnerRefreshStatus.PARTIAL
    return OwnerRefreshStatus.FAILED


def _safe_garmin_training_report(report: dict[str, Any]) -> dict[str, Any]:
    """Keep only the accepted Garmin Training sync's sanitized summary fields."""

    valid_statuses = {"succeeded", "partial", "failed", "reauth_required"}
    status = report.get("status")
    safe_status = status if isinstance(status, str) and status in valid_statuses else "failed"
    safe = {
        "contract_version": TRAINING_CONTRACT_VERSION,
        "status": safe_status,
        "status_historical_backfill": False,
        "raw_values_emitted": False,
        "private_identifiers_emitted": False,
    }
    for key in ("request_count", "readiness_requested_days", "inserted_count", "updated_count"):
        value = report.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            safe[key] = value
    return safe


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
    """Run normal Google refresh, daily-partitioning only list-mode HR."""

    selected = parse_google_streams(streams)
    mode = parse_query_mode(query_mode)
    heart_rate_selected = any(item.stream is GoogleStream.HEART_RATE for item in selected)
    if mode is not GoogleQueryMode.LIST or not heart_rate_selected:
        return run_google_refresh(
            settings,
            start=start,
            end=end,
            auth_service=auth_service,
            streams=streams,
            query_mode=query_mode,
            data_source_family=data_source_family,
        )

    window_start, window_end = validate_inclusive_window(start, end)
    family = parse_data_source_family(data_source_family)
    non_heart_rate_streams = [
        item.code for item in selected if item.stream is not GoogleStream.HEART_RATE
    ]
    non_heart_rate_report = None
    if non_heart_rate_streams:
        non_heart_rate_report = run_google_refresh(
            settings,
            start=window_start,
            end=window_end,
            auth_service=auth_service,
            streams=non_heart_rate_streams,
            query_mode=query_mode,
            data_source_family=data_source_family,
        )

    daily_reports: list[GoogleSyncReport] = []
    daily_attempts: list[GoogleSyncAttempt] = []
    abort_reason = non_heart_rate_report.abort_reason if non_heart_rate_report else None
    stop_days = (
        non_heart_rate_report is not None
        and non_heart_rate_report.status is GoogleSyncStatus.REAUTH_REQUIRED
    )
    current_day = window_end
    while current_day >= window_start:
        if stop_days:
            daily_attempts.append(
                _not_run_heart_rate_day(
                    current_day,
                    query_mode=mode,
                    data_source_family=family,
                    reason=abort_reason or "previous_day_incomplete",
                )
            )
            current_day -= timedelta(days=1)
            continue

        report = _run_heart_rate_day(
            settings,
            auth_service=auth_service,
            day=current_day,
            query_mode=query_mode,
            data_source_family=data_source_family,
        )
        daily_reports.append(report)
        if report.attempts:
            daily_attempts.extend(report.attempts)
        else:
            daily_attempts.append(
                _not_run_heart_rate_day(
                    current_day,
                    query_mode=mode,
                    data_source_family=family,
                    reason=report.abort_reason or report.status.value,
                )
            )
        if report.status not in {GoogleSyncStatus.SUCCEEDED, GoogleSyncStatus.EMPTY}:
            abort_reason = report.abort_reason
            if report.status is GoogleSyncStatus.REAUTH_REQUIRED:
                abort_reason = "reauth_required"
            stop_days = True
        current_day -= timedelta(days=1)

    attempts: list[GoogleSyncAttempt] = []
    non_heart_rate_attempts = {
        item.stream: item
        for item in (non_heart_rate_report.attempts if non_heart_rate_report else ())
    }
    for surface in selected:
        if surface.stream is GoogleStream.HEART_RATE:
            attempts.extend(daily_attempts)
        elif surface.code in non_heart_rate_attempts:
            attempts.append(non_heart_rate_attempts[surface.code])

    reports = ([non_heart_rate_report] if non_heart_rate_report else []) + daily_reports
    last_report = reports[-1] if reports else None
    return GoogleSyncReport(
        auth=last_report.auth if last_report else None,
        status=_roll_up_status(attempts, abort_reason),
        kind=GoogleRunKind.REFRESH,
        window_start=window_start.isoformat(),
        window_end_exclusive=inclusive_to_exclusive_end(window_end).isoformat(),
        request_count=sum(report.request_count for report in reports),
        query_mode=mode.value,
        data_source_family=family,
        streams=tuple(item.code for item in selected),
        sync_run_id=last_report.sync_run_id if last_report else None,
        attempts=tuple(attempts),
        abort_reason=abort_reason,
        skipped_complete_count=sum(report.skipped_complete_count for report in reports),
    )


def _not_run_heart_rate_day(
    day: date,
    *,
    query_mode: GoogleQueryMode,
    data_source_family: str | None,
    reason: str,
) -> GoogleSyncAttempt:
    """Describe one untouched older HR day without inventing coverage."""

    return GoogleSyncAttempt(
        stream=GoogleStream.HEART_RATE.value,
        data_type="heart-rate",
        query_mode=query_mode.value,
        data_source_family=data_source_family,
        window_start=day.isoformat(),
        window_end_exclusive=(day + timedelta(days=1)).isoformat(),
        status=GoogleSyncStatus.NOT_RUN,
        coverage_status=None,
        not_run_reason=reason,
    )


def _run_heart_rate_day(
    settings: Settings,
    *,
    auth_service: GoogleAuthService,
    day: date,
    query_mode: str | None,
    data_source_family: str | None,
) -> GoogleSyncReport:
    """Run one independently staged HR day with bounded continuation."""

    reports = [
        run_google_refresh(
            settings,
            start=day,
            end=day,
            auth_service=auth_service,
            streams=[GoogleStream.HEART_RATE.value],
            query_mode=query_mode,
            data_source_family=data_source_family,
            checkpoint_partition=day.isoformat(),
        )
    ]
    for _ in range(OWNER_REFRESH_GOOGLE_HEART_RATE_CONTINUATION_ROUNDS):
        if _resumable_heart_rate_attempt(reports[-1]) is None:
            break
        reports.append(
            run_google_refresh(
                settings,
                start=day,
                end=day,
                auth_service=auth_service,
                streams=[GoogleStream.HEART_RATE.value],
                query_mode=query_mode,
                data_source_family=data_source_family,
                checkpoint_partition=day.isoformat(),
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
    2. accepted bounded Garmin Training sync using the same Garmin client and
       exact validated date window;
    3. existing normal bounded Google refresh (CLI stream/query/family overrides
       apply only to this layer);
    4. fixed sleep-only Google refresh with ``query_mode=reconcile`` and
       ``data_source_family=google-wearables`` for the R05 exploratory cohort.

    Garmin remains the owner of incremental-window validation. Training and both
    Google layers receive the exact inclusive date window derived from that same
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
        garmin_training = _safe_garmin_training_report(
            GarminTrainingSync(
                settings,
                client=garmin_client,
                auth_result=garmin_auth_result,
            ).run(start=window_start, end=window_end)
        )

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
        status=_combined_status(
            garmin.status,
            garmin_training["status"],
            google.status,
            google_wearables_sleep.status,
        ),
        as_of=as_of_date.isoformat(),
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        trailing_window_days=window_days,
        garmin=garmin,
        garmin_training=garmin_training,
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
