"""Bounded manual refresh of the owner Garmin and Google runtimes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from healthcheck.config import Settings
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

OWNER_REFRESH_CONTRACT_VERSION = "healthcheck-owner-refresh-v1"


class OwnerRefreshStatus(StrEnum):
    """Combined outcome of one bounded two-provider refresh."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    REAUTH_REQUIRED = "reauth_required"


@dataclass(frozen=True, slots=True)
class OwnerRefreshReport:
    """Privacy-safe summary for one manual Garmin + Google refresh."""

    status: OwnerRefreshStatus
    as_of: str
    window_start: str
    window_end: str
    trailing_window_days: int
    garmin: GarminSyncReport
    google: GoogleSyncReport

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
    garmin: GarminSyncStatus, google: GoogleSyncStatus
) -> OwnerRefreshStatus:
    statuses = (garmin, google)
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
    """Run both bounded provider refreshes over the same local-date window.

    Garmin remains the owner of incremental-window validation.  Google receives
    the exact inclusive date window derived from that same validated Garmin
    window, while retaining its own refresh/checkpoint semantics.
    """

    as_of_date = validate_sync_date(as_of)
    window_days = validate_trailing_window_days(trailing_window_days)
    window_start, window_end = compute_sync_window(as_of_date, window_days)

    garmin_auth = GarminAuthService(settings, is_cn=is_cn)
    garmin_client, garmin_auth_result = garmin_auth.load_existing()
    garmin = GarminIncrementalSync(
        settings,
        client=garmin_client,
        auth_result=garmin_auth_result,
    ).run(as_of=as_of_date, trailing_window_days=window_days)

    google = run_google_refresh(
        settings,
        start=window_start,
        end=window_end,
        auth_service=GoogleAuthService(settings),
        streams=streams,
        query_mode=query_mode,
        data_source_family=data_source_family,
    )

    return OwnerRefreshReport(
        status=_combined_status(garmin.status, google.status),
        as_of=as_of_date.isoformat(),
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        trailing_window_days=window_days,
        garmin=garmin,
        google=google,
    )


__all__ = [
    "OWNER_REFRESH_CONTRACT_VERSION",
    "OwnerRefreshReport",
    "OwnerRefreshStatus",
    "run_owner_refresh",
]
