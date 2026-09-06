"""Production Garmin incremental sync with a trailing reconciliation window.

This is the first R02 ingestion path.  It reuses owner-assisted auth, the
accepted capability allowlist, offline normalization, and raw/observation
persistence.  It does not backfill history, schedule itself, download GPS or
ORIGINAL FIT, or treat client-method presence as Vivoactive 5 evidence.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
from healthcheck.db.models import SyncStreamState
from healthcheck.db.repositories import repositories_for, restore_stored_utc
from healthcheck.garmin.auth import (
    GarminAuthResult,
    GarminAuthStatus,
    GarminSafeError,
    _silence_provider_logging,
    classify_garmin_error,
)
from healthcheck.garmin.capabilities import (
    GARMIN_PROVIDER_CODE,
    GARMINCONNECT_VERSION,
    VIVOACTIVE_5_DEVICE_CODE,
    VIVOACTIVE_5_MODEL,
    GarminStream,
)
from healthcheck.garmin.normalization import (
    GarminParseStatus,
    GarminSourceIdentity,
    garmin_source_identity,
    normalize_garmin_payload,
)
from healthcheck.garmin.persistence import (
    GARMIN_COVERAGE_RULE_VERSION,
    GarminPersistenceRepository,
)
from healthcheck.garmin.redaction import GarminDeviceAttribution, infer_device_attribution
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore, serialize_garmin_payload
from healthcheck.logging import log_event
from healthcheck.runtime import prepare_runtime

SYNC_CONTRACT_VERSION = "r02-garmin-incremental-sync-v1"
DEFAULT_TRAILING_WINDOW_DAYS = 7
MAX_TRAILING_WINDOW_DAYS = 14
MAX_SYNC_PROVIDER_REQUESTS = 140
ACTIVITY_PAGE_SIZE = 20
MAX_ACTIVITY_PAGES = 5
INCREMENTAL_RUN_STREAM = "garmin_incremental"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ACTIVITY_ENDPOINT_ATTRIBUTE = "garmin_connect_activities"
_ACTIVITY_ENDPOINT = "/activitylist-service/activities/search/activities"

_ALLOWED_METHODS = frozenset(
    {
        "get_user_summary",
        "get_sleep_data",
        "get_heart_rates",
        "get_rhr_day",
        "get_hrv_data",
        "get_stress_data",
        "get_body_battery",
        "get_spo2_data",
        "get_respiration_data",
        "connectapi",
    }
)
_FORBIDDEN_METHODS = frozenset(
    {
        "download_activity",
        "get_activity",
        "get_activity_details",
        "get_activities_by_date",
        "get_max_metrics",
        "get_training_readiness",
        "get_training_status",
        "get_body_battery_events",
    }
)


class GarminSyncStatus(StrEnum):
    """Outcome of one incremental sync run or one surface/day attempt."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    EMPTY = "empty"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    NOT_RUN = "not_run"
    REAUTH_REQUIRED = "reauth_required"


@dataclass(frozen=True, slots=True)
class GarminSyncSurface:
    """One allowlisted production fetch surface."""

    code: str
    method: str
    stream: GarminStream
    per_day: bool = True


PRODUCTION_SYNC_SURFACES: tuple[GarminSyncSurface, ...] = (
    GarminSyncSurface("daily_summary", "get_user_summary", GarminStream.DAILY_HEALTH),
    GarminSyncSurface("sleep", "get_sleep_data", GarminStream.SLEEP),
    GarminSyncSurface("heart_rate", "get_heart_rates", GarminStream.INTRADAY),
    GarminSyncSurface("resting_heart_rate", "get_rhr_day", GarminStream.DAILY_HEALTH),
    GarminSyncSurface("hrv_status", "get_hrv_data", GarminStream.DAILY_HEALTH),
    GarminSyncSurface("stress", "get_stress_data", GarminStream.INTRADAY),
    GarminSyncSurface("body_battery", "get_body_battery", GarminStream.INTRADAY),
    GarminSyncSurface("spo2", "get_spo2_data", GarminStream.INTRADAY),
    GarminSyncSurface("respiration", "get_respiration_data", GarminStream.INTRADAY),
    GarminSyncSurface("activities", "connectapi", GarminStream.ACTIVITY, per_day=False),
)

if any(surface.method not in _ALLOWED_METHODS for surface in PRODUCTION_SYNC_SURFACES):
    raise RuntimeError("Garmin incremental sync contains a method outside its read allowlist")
if any(surface.method in _FORBIDDEN_METHODS for surface in PRODUCTION_SYNC_SURFACES):
    raise RuntimeError("Garmin incremental sync allowlist includes a forbidden method")


@dataclass(frozen=True, slots=True)
class GarminSyncAttempt:
    """Sanitized outcome of one surface/date (or range) fetch."""

    surface: str
    stream: str
    method: str
    day: str | None
    status: GarminSyncStatus
    coverage_status: str | None
    record_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    replayed: bool = False
    request_count: int = 0
    device_attribution: str = GarminDeviceAttribution.UNATTRIBUTED.value
    error: GarminSafeError | None = None
    not_run_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "surface": self.surface,
            "stream": self.stream,
            "method": self.method,
            "day": self.day,
            "status": self.status.value,
            "coverage_status": self.coverage_status,
            "record_count": self.record_count,
            "inserted_count": self.inserted_count,
            "updated_count": self.updated_count,
            "replayed": self.replayed,
            "request_count": self.request_count,
            "device_attribution": self.device_attribution,
            "error": self.error.as_dict() if self.error else None,
        }
        if self.not_run_reason is not None:
            payload["not_run_reason"] = self.not_run_reason
        return payload


@dataclass(frozen=True, slots=True)
class GarminSyncReport:
    """Deterministic machine-readable incremental-sync summary."""

    auth: GarminAuthResult
    status: GarminSyncStatus
    as_of: str
    window_start: str | None
    window_end: str | None
    trailing_window_days: int
    request_count: int
    sync_run_id: str | None = None
    attempts: tuple[GarminSyncAttempt, ...] = ()
    abort_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": SYNC_CONTRACT_VERSION,
            "source": {
                "provider_code": GARMIN_PROVIDER_CODE,
                "target_device_code": VIVOACTIVE_5_DEVICE_CODE,
                "target_device_model": VIVOACTIVE_5_MODEL,
            },
            "library": {
                "name": "python-garminconnect",
                "version": GARMINCONNECT_VERSION,
            },
            "auth": self.auth.as_dict(),
            "sync": {
                "status": self.status.value,
                "as_of": self.as_of,
                "window_start": self.window_start,
                "window_end": self.window_end,
                "trailing_window_days": self.trailing_window_days,
                "request_count": self.request_count,
                "max_provider_requests": MAX_SYNC_PROVIDER_REQUESTS,
                "sync_run_id": self.sync_run_id,
                "abort_reason": self.abort_reason,
                "historical_backfill": False,
                "gps_or_fit_downloaded": False,
            },
            "privacy": {
                "raw_values_emitted": False,
                "private_identifiers_emitted": False,
                "tokens_emitted": False,
                "health_timestamps_emitted": False,
            },
            "attempts": [item.as_dict() for item in self.attempts],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n"


@dataclass
class _SyncBudget:
    used: int = 0
    max_requests: int = MAX_SYNC_PROVIDER_REQUESTS

    @property
    def remaining(self) -> int:
        return max(0, self.max_requests - self.used)

    def consume(self, count: int = 1) -> bool:
        if self.used + count > self.max_requests:
            return False
        self.used += count
        return True


def validate_sync_date(value: str | date | None, *, default: date | None = None) -> date:
    """Accept one calendar date, defaulting to the local today."""

    if value is None:
        return default or date.today()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value.strip()):
        raise ValueError("garmin-sync date must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError("garmin-sync date is invalid") from exc


def validate_trailing_window_days(value: int | None) -> int:
    """Keep the incremental window bounded; historical backfill is out of scope."""

    days = DEFAULT_TRAILING_WINDOW_DAYS if value is None else value
    if not isinstance(days, int) or isinstance(days, bool):
        raise ValueError("trailing_window_days must be an integer")
    if days < 1 or days > MAX_TRAILING_WINDOW_DAYS:
        raise ValueError(
            f"trailing_window_days must be between 1 and {MAX_TRAILING_WINDOW_DAYS}"
        )
    return days


def compute_sync_window(as_of: date, trailing_window_days: int) -> tuple[date, date]:
    """Return the inclusive local-date window for one incremental run.

    The first run is the trailing window only.  Later runs overlap that same
    trailing window so late Garmin corrections can update the current
    projection without a historical backfill.
    """

    days = validate_trailing_window_days(trailing_window_days)
    return as_of - timedelta(days=days - 1), as_of


def _calendar_days(start: date, end: date) -> tuple[date, ...]:
    if end < start:
        raise ValueError("sync window end must not precede start")
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return tuple(days)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return start, start + timedelta(days=1)


@contextmanager
def _disable_provider_retries(client: Any):
    """Disable pinned-provider retries for a deterministic hard request cap."""

    marker = object()
    previous = getattr(client, "retry_attempts", marker)
    changed = previous is not marker
    if changed:
        try:
            client.retry_attempts = 0
        except Exception:
            changed = False
    try:
        yield
    finally:
        if changed:
            try:
                client.retry_attempts = previous
            except Exception:
                pass


def _source_identity_for(payload: Any) -> GarminSourceIdentity:
    attribution = infer_device_attribution(payload).status
    if attribution is GarminDeviceAttribution.TARGET_DEVICE:
        return garmin_source_identity(
            device_attributed=True,
            device_code=VIVOACTIVE_5_DEVICE_CODE,
            device_model=VIVOACTIVE_5_MODEL,
        )
    return garmin_source_identity(device_attributed=False)


def _normalize_provider_payload(surface: GarminSyncSurface, payload: Any) -> Any:
    if payload is None:
        return {}
    if surface.stream is GarminStream.ACTIVITY:
        if isinstance(payload, Mapping) and "activities" in payload:
            return payload
        if _is_sequence(payload):
            return {"activities": list(payload)}
        if isinstance(payload, Mapping):
            return {"activities": [payload]}
        return payload
    if surface.code == "body_battery" and _is_sequence(payload):
        items = [item for item in payload if isinstance(item, Mapping)]
        if not items:
            return {}
        if len(items) == 1:
            return _raw_mapping_for_normalize(items[0])
        return _raw_mapping_for_normalize(items[0])
    return _raw_mapping_for_normalize(payload) if isinstance(payload, Mapping) else payload


def _raw_mapping_for_normalize(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Keep production payloads out of the synthetic fixture-envelope parser.

    The #29 envelope detector treats a top-level ``device`` key as fixture
    metadata. Provider responses may carry that key as attribution evidence,
    which is applied through ``source_identity`` instead of the envelope.
    """

    if payload.get("fixture_contract_version"):
        return payload
    if "payload" in payload and any(
        key in payload for key in ("fixture_contract_version", "source_kind", "fixture_id")
    ):
        return payload
    return {key: value for key, value in payload.items() if key != "device"}


def _payload_bytes(payload: Any) -> bytes:
    if payload is None:
        payload = {}
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    if isinstance(payload, Mapping):
        return serialize_garmin_payload(payload)
    if _is_sequence(payload):
        _reject_private_keys(payload)
        return json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    raise TypeError("Garmin provider payload must be an object, array, or bytes")


def _reject_private_keys(value: Any) -> None:
    forbidden = (
        "access_token",
        "authorization",
        "bearer",
        "client_secret",
        "cookie",
        "credential",
        "email",
        "mfa",
        "otp",
        "password",
        "refresh_token",
        "secret",
        "token",
        "username",
    )
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key).strip().lower()
            if any(part in key_text for part in forbidden):
                raise ValueError("private or credential-shaped payload key is not accepted")
            _reject_private_keys(nested)
    elif _is_sequence(value):
        for nested in value:
            _reject_private_keys(nested)


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, Mapping))


def _coverage_status_for(parse_status: GarminParseStatus, record_count: int) -> str:
    if parse_status is GarminParseStatus.INVALID and record_count == 0:
        return "failed"
    if parse_status is GarminParseStatus.EMPTY or record_count == 0:
        return "confirmed_empty"
    return "present"


def _attempt_status_for(coverage_status: str, parse_status: GarminParseStatus) -> GarminSyncStatus:
    if coverage_status == "failed" or parse_status is GarminParseStatus.INVALID:
        return GarminSyncStatus.FAILED
    if coverage_status == "confirmed_empty":
        return GarminSyncStatus.EMPTY
    return GarminSyncStatus.SUCCEEDED


class GarminIncrementalSync:
    """Fetch, normalize and persist one bounded incremental Garmin window."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: Any | None = None,
        auth_result: GarminAuthResult | None = None,
        clock: Callable[[], datetime] | None = None,
        max_provider_requests: int = MAX_SYNC_PROVIDER_REQUESTS,
    ) -> None:
        self.settings = settings
        self.client = client
        self.auth_result = auth_result or GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.max_provider_requests = max_provider_requests
        if self.max_provider_requests < 1:
            raise ValueError("max_provider_requests must be positive")
        if self.max_provider_requests > MAX_SYNC_PROVIDER_REQUESTS:
            raise ValueError("max_provider_requests exceeds the hard incremental cap")

    def run(
        self,
        *,
        as_of: date | str | None = None,
        trailing_window_days: int | None = None,
    ) -> GarminSyncReport:
        as_of_date = validate_sync_date(as_of)
        window_days = validate_trailing_window_days(trailing_window_days)
        window_start, window_end = compute_sync_window(as_of_date, window_days)
        paths = prepare_runtime(self.settings)
        migrate_database(paths)
        engine = create_sqlite_engine(paths)
        store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
        factory = create_session_factory(engine)
        try:
            return self._run(
                factory,
                store,
                as_of=as_of_date,
                window_start=window_start,
                window_end=window_end,
                trailing_window_days=window_days,
            )
        finally:
            engine.dispose()

    def _run(
        self,
        factory,
        store: ContentAddressedGarminPayloadStore,
        *,
        as_of: date,
        window_start: date,
        window_end: date,
        trailing_window_days: int,
    ) -> GarminSyncReport:
        auth = self.auth_result
        if self.client is None or not auth.ok:
            status = (
                GarminSyncStatus.REAUTH_REQUIRED
                if auth.status is GarminAuthStatus.REAUTH_REQUIRED
                else GarminSyncStatus.FAILED
            )
            run_id = self._record_auth_failure(
                factory,
                status=status,
                window_start=window_start,
                window_end=window_end,
            )
            return GarminSyncReport(
                auth=auth,
                status=status,
                as_of=as_of.isoformat(),
                window_start=window_start.isoformat(),
                window_end=window_end.isoformat(),
                trailing_window_days=trailing_window_days,
                request_count=0,
                sync_run_id=run_id,
                abort_reason=status.value,
            )

        budget = _SyncBudget(max_requests=self.max_provider_requests)
        attempts: list[GarminSyncAttempt] = []
        abort_reason: str | None = None
        with factory() as session:
            provider = repositories_for(session).providers.get_or_create(
                GARMIN_PROVIDER_CODE,
                "Garmin Connect",
                "wearable",
            )
            requested_start = _day_bounds(window_start)[0]
            requested_end = _day_bounds(window_end)[1]
            run = repositories_for(session).sync.create_run(
                provider_id=provider.id,
                stream_code=INCREMENTAL_RUN_STREAM,
                requested_start=requested_start,
                requested_end=requested_end,
            )
            session.commit()
            sync_run_id = run.id
            provider_id = provider.id

        days = _calendar_days(window_start, window_end)
        with _disable_provider_retries(self.client):
            for day in days:
                if abort_reason is not None:
                    break
                for surface in PRODUCTION_SYNC_SURFACES:
                    if not surface.per_day:
                        continue
                    attempt = self._sync_surface(
                        factory,
                        store,
                        provider_id=provider_id,
                        sync_run_id=sync_run_id,
                        surface=surface,
                        day=day,
                        window_start=window_start,
                        window_end=window_end,
                        trailing_window_days=trailing_window_days,
                        budget=budget,
                    )
                    attempts.append(attempt)
                    if attempt.status is GarminSyncStatus.REAUTH_REQUIRED:
                        abort_reason = "reauth_required"
                        break
                    if attempt.not_run_reason == "request_budget_exhausted":
                        abort_reason = "request_budget_exhausted"
                        break
            if abort_reason is None:
                activity_surface = next(
                    item for item in PRODUCTION_SYNC_SURFACES if item.code == "activities"
                )
                attempt = self._sync_surface(
                    factory,
                    store,
                    provider_id=provider_id,
                    sync_run_id=sync_run_id,
                    surface=activity_surface,
                    day=None,
                    window_start=window_start,
                    window_end=window_end,
                    trailing_window_days=trailing_window_days,
                    budget=budget,
                )
                attempts.append(attempt)
                if attempt.status is GarminSyncStatus.REAUTH_REQUIRED:
                    abort_reason = "reauth_required"
                elif attempt.not_run_reason == "request_budget_exhausted":
                    abort_reason = "request_budget_exhausted"

        if abort_reason is not None:
            attempts.extend(_not_run_remainder(attempts, days, abort_reason))

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
                actual_start=_day_bounds(window_start)[0],
                actual_end=_day_bounds(window_end)[1],
            )
            session.commit()

        log_event(
            "garmin_incremental_sync",
            operation="garmin-sync",
            status=run_status.value,
            count=budget.used,
            reason=abort_reason or run_status.value,
        )
        return GarminSyncReport(
            auth=auth,
            status=run_status,
            as_of=as_of.isoformat(),
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            trailing_window_days=trailing_window_days,
            request_count=budget.used,
            sync_run_id=sync_run_id,
            attempts=tuple(attempts),
            abort_reason=abort_reason,
        )

    def _record_auth_failure(
        self,
        factory,
        *,
        status: GarminSyncStatus,
        window_start: date,
        window_end: date,
    ) -> str | None:
        try:
            with factory() as session:
                provider = repositories_for(session).providers.get_or_create(
                    GARMIN_PROVIDER_CODE,
                    "Garmin Connect",
                    "wearable",
                )
                run = repositories_for(session).sync.create_run(
                    provider_id=provider.id,
                    stream_code=INCREMENTAL_RUN_STREAM,
                    requested_start=_day_bounds(window_start)[0],
                    requested_end=_day_bounds(window_end)[1],
                )
                repositories_for(session).sync.finish_run(
                    run.id,
                    status="failed",
                    item_count=0,
                    received_count=0,
                    accepted_count=0,
                    failed_count=0,
                    error_category=status.value,
                    diagnostic_reason=status.value,
                )
                session.commit()
                return run.id
        except Exception:
            return None

    def _sync_surface(
        self,
        factory,
        store: ContentAddressedGarminPayloadStore,
        *,
        provider_id: str,
        sync_run_id: str,
        surface: GarminSyncSurface,
        day: date | None,
        window_start: date,
        window_end: date,
        trailing_window_days: int,
        budget: _SyncBudget,
    ) -> GarminSyncAttempt:
        if surface.method not in _ALLOWED_METHODS or surface.method in _FORBIDDEN_METHODS:
            raise RuntimeError("attempted Garmin method outside the incremental allowlist")
        if budget.remaining <= 0:
            return GarminSyncAttempt(
                surface=surface.code,
                stream=surface.stream.value,
                method=surface.method,
                day=day.isoformat() if day is not None else None,
                status=GarminSyncStatus.NOT_RUN,
                coverage_status=None,
                not_run_reason="request_budget_exhausted",
            )

        fetched, error, request_count = self._fetch(surface, day, window_start, window_end, budget)
        if error is not None and error.error_class == "authentication":
            self._record_failure_checkpoint(
                factory,
                provider_id=provider_id,
                surface=surface,
                day=day or window_end,
                window_start=window_start if day is None else day,
                window_end=window_end if day is None else day,
                trailing_window_days=trailing_window_days,
                coverage_status="failed",
                diagnostic="reauth_required",
            )
            return GarminSyncAttempt(
                surface=surface.code,
                stream=surface.stream.value,
                method=surface.method,
                day=day.isoformat() if day is not None else None,
                status=GarminSyncStatus.REAUTH_REQUIRED,
                coverage_status="failed",
                request_count=request_count,
                error=error,
            )
        if error is not None:
            coverage = (
                "unavailable" if error.error_code == "unsupported_or_not_found" else "failed"
            )
            self._record_failure_checkpoint(
                factory,
                provider_id=provider_id,
                surface=surface,
                day=day or window_end,
                window_start=window_start if day is None else day,
                window_end=window_end if day is None else day,
                trailing_window_days=trailing_window_days,
                coverage_status=coverage,
                diagnostic=error.error_code,
            )
            return GarminSyncAttempt(
                surface=surface.code,
                stream=surface.stream.value,
                method=surface.method,
                day=day.isoformat() if day is not None else None,
                status=(
                    GarminSyncStatus.UNAVAILABLE
                    if coverage == "unavailable"
                    else GarminSyncStatus.FAILED
                ),
                coverage_status=coverage,
                request_count=request_count,
                error=error,
            )
        if fetched is None and request_count == 0:
            return GarminSyncAttempt(
                surface=surface.code,
                stream=surface.stream.value,
                method=surface.method,
                day=day.isoformat() if day is not None else None,
                status=GarminSyncStatus.NOT_RUN,
                coverage_status=None,
                not_run_reason="request_budget_exhausted",
            )

        return self._persist_payload(
            factory,
            store,
            provider_id=provider_id,
            sync_run_id=sync_run_id,
            surface=surface,
            day=day,
            window_start=window_start if day is None else day,
            window_end=window_end if day is None else day,
            trailing_window_days=trailing_window_days,
            payload=fetched,
            request_count=request_count,
        )

    def _fetch(
        self,
        surface: GarminSyncSurface,
        day: date | None,
        window_start: date,
        window_end: date,
        budget: _SyncBudget,
    ) -> tuple[Any, GarminSafeError | None, int]:
        if surface.code == "activities":
            return self._fetch_activities(window_start, window_end, budget)
        if not budget.consume():
            return None, None, 0
        method = getattr(self.client, surface.method, None)
        if not callable(method):
            return None, GarminSafeError("runtime", "method_unavailable"), 1
        day_text = (day or window_end).isoformat()
        try:
            with _silence_provider_logging():
                if surface.code == "body_battery":
                    payload = method(day_text, day_text)
                else:
                    payload = method(day_text)
        except Exception as exc:
            return None, classify_garmin_error(exc), 1
        return payload, None, 1

    def _fetch_activities(
        self,
        window_start: date,
        window_end: date,
        budget: _SyncBudget,
    ) -> tuple[Any, GarminSafeError | None, int]:
        endpoint = getattr(self.client, _ACTIVITY_ENDPOINT_ATTRIBUTE, None)
        connectapi = getattr(self.client, "connectapi", None)
        if endpoint != _ACTIVITY_ENDPOINT or not callable(connectapi):
            return None, GarminSafeError("runtime", "method_unavailable"), 0
        collected: list[Any] = []
        used = 0
        for page in range(MAX_ACTIVITY_PAGES):
            if not budget.consume():
                if used == 0:
                    return None, None, 0
                break
            used += 1
            try:
                with _silence_provider_logging():
                    page_payload = connectapi(
                        endpoint,
                        params={
                            "startDate": window_start.isoformat(),
                            "endDate": window_end.isoformat(),
                            "start": str(page * ACTIVITY_PAGE_SIZE),
                            "limit": str(ACTIVITY_PAGE_SIZE),
                        },
                    )
            except Exception as exc:
                return None, classify_garmin_error(exc), used
            if page_payload is None:
                break
            if _is_sequence(page_payload):
                items = list(page_payload)
            elif isinstance(page_payload, Mapping) and _is_sequence(page_payload.get("activities")):
                items = list(page_payload["activities"])
            else:
                return page_payload, None, used
            collected.extend(items)
            if len(items) < ACTIVITY_PAGE_SIZE:
                break
        return collected, None, used

    def _persist_payload(
        self,
        factory,
        store: ContentAddressedGarminPayloadStore,
        *,
        provider_id: str,
        sync_run_id: str,
        surface: GarminSyncSurface,
        day: date | None,
        window_start: date,
        window_end: date,
        trailing_window_days: int,
        payload: Any,
        request_count: int,
    ) -> GarminSyncAttempt:
        attribution = infer_device_attribution(payload).status
        identity = _source_identity_for(payload)
        normalized_payload = _normalize_provider_payload(surface, payload)
        window_start_utc, _ = _day_bounds(window_start)
        _, window_end_utc = _day_bounds(window_end)
        try:
            result = normalize_garmin_payload(
                normalized_payload,
                stream=surface.stream,
                source_identity=identity,
            )
            raw_bytes = _payload_bytes(payload)
        except Exception as exc:
            return self._failed_attempt(
                factory,
                provider_id=provider_id,
                surface=surface,
                day=day,
                window_start=window_start,
                window_end=window_end,
                trailing_window_days=trailing_window_days,
                request_count=request_count,
                attribution=attribution,
                exc=exc,
            )

        try:
            with factory() as session:
                persistence = GarminPersistenceRepository(session, payload_store=store)
                outcome = persistence.persist_result(
                    result,
                    payload=raw_bytes,
                    stream_code=surface.stream,
                    source_identity=identity,
                    received_at=self.clock(),
                    source_window_start_utc=window_start_utc,
                    source_window_end_utc=window_end_utc,
                    sync_run_id=sync_run_id,
                    source_filename=f"{surface.code}.json",
                )
                coverage_status = _coverage_status_for(result.status, len(outcome.records))
                self._write_checkpoint(
                    session,
                    provider_id=provider_id,
                    acquisition_source_id=outcome.source.acquisition_source_id,
                    surface=surface,
                    day=day or window_end,
                    window_start=window_start,
                    window_end=window_end,
                    trailing_window_days=trailing_window_days,
                    coverage_status=coverage_status,
                    observed_count=len(outcome.records),
                    succeeded=coverage_status in {"present", "confirmed_empty"},
                    diagnostic=result.status.value,
                )
                session.commit()
                return GarminSyncAttempt(
                    surface=surface.code,
                    stream=surface.stream.value,
                    method=surface.method,
                    day=day.isoformat() if day is not None else None,
                    status=_attempt_status_for(coverage_status, result.status),
                    coverage_status=coverage_status,
                    record_count=len(outcome.records),
                    inserted_count=outcome.inserted_count,
                    updated_count=outcome.updated_count,
                    replayed=outcome.replayed,
                    request_count=request_count,
                    device_attribution=attribution.value,
                )
        except Exception as exc:
            return self._failed_attempt(
                factory,
                provider_id=provider_id,
                surface=surface,
                day=day,
                window_start=window_start,
                window_end=window_end,
                trailing_window_days=trailing_window_days,
                request_count=request_count,
                attribution=attribution,
                exc=exc,
            )

    def _failed_attempt(
        self,
        factory,
        *,
        provider_id: str,
        surface: GarminSyncSurface,
        day: date | None,
        window_start: date,
        window_end: date,
        trailing_window_days: int,
        request_count: int,
        attribution: GarminDeviceAttribution,
        exc: BaseException,
    ) -> GarminSyncAttempt:
        error = classify_garmin_error(exc)
        self._record_failure_checkpoint(
            factory,
            provider_id=provider_id,
            surface=surface,
            day=day or window_end,
            window_start=window_start,
            window_end=window_end,
            trailing_window_days=trailing_window_days,
            coverage_status="failed",
            diagnostic=error.error_code,
        )
        return GarminSyncAttempt(
            surface=surface.code,
            stream=surface.stream.value,
            method=surface.method,
            day=day.isoformat() if day is not None else None,
            status=GarminSyncStatus.FAILED,
            coverage_status="failed",
            request_count=request_count,
            device_attribution=attribution.value,
            error=error,
        )

    def _record_failure_checkpoint(
        self,
        factory,
        *,
        provider_id: str,
        surface: GarminSyncSurface,
        day: date,
        window_start: date,
        window_end: date,
        trailing_window_days: int,
        coverage_status: str,
        diagnostic: str,
    ) -> None:
        with factory() as session:
            self._write_checkpoint(
                session,
                provider_id=provider_id,
                acquisition_source_id=None,
                surface=surface,
                day=day,
                window_start=window_start,
                window_end=window_end,
                trailing_window_days=trailing_window_days,
                coverage_status=coverage_status,
                observed_count=None,
                succeeded=False,
                diagnostic=diagnostic,
            )
            session.commit()

    def _write_checkpoint(
        self,
        session: Session,
        *,
        provider_id: str,
        acquisition_source_id: str | None,
        surface: GarminSyncSurface,
        day: date,
        window_start: date,
        window_end: date,
        trailing_window_days: int,
        coverage_status: str,
        observed_count: int | None,
        succeeded: bool,
        diagnostic: str,
    ) -> None:
        interval_start, _ = _day_bounds(window_start)
        _, interval_end = _day_bounds(window_end)
        provenance = repositories_for(session)
        provenance.coverage.record(
            provider_id=provider_id,
            acquisition_source_id=acquisition_source_id,
            stream_code=surface.stream.value,
            metric_code=surface.code,
            interval_start=interval_start,
            interval_end=interval_end,
            resolution="day",
            status=coverage_status,
            calculation_rule_version=GARMIN_COVERAGE_RULE_VERSION,
            observed_count=observed_count if coverage_status != "failed" else None,
            expected_count=None,
            diagnostic_reason=diagnostic,
        )
        now = self.clock()
        previous = session.scalar(
            select(SyncStreamState).where(
                SyncStreamState.provider_id == provider_id,
                SyncStreamState.acquisition_source_id.is_(None),
                SyncStreamState.stream_code == surface.code,
            )
        )
        watermark = None
        last_success = None
        cursor = None
        if succeeded:
            day_start, _ = _day_bounds(day)
            previous_watermark = (
                restore_stored_utc(previous.watermark) if previous is not None else None
            )
            watermark = (
                day_start
                if previous_watermark is None or day_start >= previous_watermark
                else previous_watermark
            )
            last_success = now
            cursor = day.isoformat()
            if previous is not None and previous.cursor is not None and previous.cursor > cursor:
                cursor = previous.cursor
        provenance.sync.get_or_create_state(
            provider_id=provider_id,
            acquisition_source_id=None,
            stream_code=surface.code,
            cursor=cursor,
            watermark=watermark,
            trailing_window_days=trailing_window_days,
            diagnostic_status=coverage_status if succeeded else diagnostic,
            last_success_at=last_success,
            last_attempt_at=now,
        )


def _not_run_remainder(
    attempts: Sequence[GarminSyncAttempt],
    days: Sequence[date],
    abort_reason: str,
) -> tuple[GarminSyncAttempt, ...]:
    seen = {(item.surface, item.day) for item in attempts}
    remainder: list[GarminSyncAttempt] = []
    for surface in PRODUCTION_SYNC_SURFACES:
        if surface.per_day:
            for day in days:
                key = (surface.code, day.isoformat())
                if key in seen:
                    continue
                remainder.append(
                    GarminSyncAttempt(
                        surface=surface.code,
                        stream=surface.stream.value,
                        method=surface.method,
                        day=day.isoformat(),
                        status=GarminSyncStatus.NOT_RUN,
                        coverage_status=None,
                        not_run_reason=abort_reason,
                    )
                )
        elif (surface.code, None) not in seen:
            remainder.append(
                GarminSyncAttempt(
                    surface=surface.code,
                    stream=surface.stream.value,
                    method=surface.method,
                    day=None,
                    status=GarminSyncStatus.NOT_RUN,
                    coverage_status=None,
                    not_run_reason=abort_reason,
                )
            )
    return tuple(remainder)


def _roll_up_status(
    attempts: Sequence[GarminSyncAttempt], abort_reason: str | None
) -> GarminSyncStatus:
    if abort_reason == "reauth_required":
        return GarminSyncStatus.REAUTH_REQUIRED
    executed = [item for item in attempts if item.status is not GarminSyncStatus.NOT_RUN]
    if not executed:
        return GarminSyncStatus.FAILED if abort_reason else GarminSyncStatus.EMPTY
    statuses = {item.status for item in executed}
    good = {GarminSyncStatus.SUCCEEDED, GarminSyncStatus.EMPTY}
    bad = {GarminSyncStatus.FAILED, GarminSyncStatus.UNAVAILABLE}
    if GarminSyncStatus.REAUTH_REQUIRED in statuses:
        return GarminSyncStatus.REAUTH_REQUIRED
    if statuses <= good:
        return GarminSyncStatus.PARTIAL if abort_reason else GarminSyncStatus.SUCCEEDED
    if statuses & good and (statuses & bad or GarminSyncStatus.PARTIAL in statuses):
        return GarminSyncStatus.PARTIAL
    if GarminSyncStatus.PARTIAL in statuses:
        return GarminSyncStatus.PARTIAL
    if statuses <= bad:
        return GarminSyncStatus.FAILED
    return GarminSyncStatus.PARTIAL


def _run_status_token(status: GarminSyncStatus) -> str:
    if status is GarminSyncStatus.SUCCEEDED:
        return "succeeded"
    if status is GarminSyncStatus.PARTIAL:
        return "partial"
    return "failed"


def run_garmin_incremental_sync(
    settings: Settings,
    *,
    client: Any | None = None,
    auth_result: GarminAuthResult | None = None,
    as_of: date | str | None = None,
    trailing_window_days: int | None = None,
    max_provider_requests: int = MAX_SYNC_PROVIDER_REQUESTS,
) -> GarminSyncReport:
    """Run one incremental Garmin sync against an authenticated or fake client."""

    return GarminIncrementalSync(
        settings,
        client=client,
        auth_result=auth_result,
        max_provider_requests=max_provider_requests,
    ).run(as_of=as_of, trailing_window_days=trailing_window_days)
