"""Bounded manual refresh of the owner Garmin and Google runtimes."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
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
from healthcheck.google.sync import GoogleSyncReport, GoogleSyncStatus, run_google_refresh
from healthcheck.runtime import RuntimePaths, resolve_runtime_paths

OWNER_REFRESH_CONTRACT_VERSION = "healthcheck-owner-refresh-v1"

# Fixed second Google layer required by R05 account_wearables_sleep_observations_v1.
OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_STREAMS: tuple[str, ...] = ("sleep",)
OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_QUERY_MODE = "reconcile"
OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_FAMILY = "google-wearables"


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
        google = run_google_refresh(
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
