"""Bounded Google Health incremental sync, coverage, pagination and checkpoints.

Production owner-live calls are out of scope for #88.  Tests inject a fake
HTTP transport.  Query mode and dataSourceFamily stay acquisition context,
not source identity.  Historical and incremental checkpoint namespaces are
isolated.  Reports never include health values, tokens, IDs or raw payloads.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from sqlalchemy import select

from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
from healthcheck.db.models import SyncStreamState
from healthcheck.db.repositories import repositories_for, restore_stored_utc
from healthcheck.google.auth import (
    ALLOWED_SCOPES,
    SCOPE_METRICS,
    SCOPE_SLEEP,
    GoogleAuthResult,
    GoogleAuthService,
    GoogleAuthStatus,
    GoogleHttpResponse,
    GoogleHttpTransport,
    GoogleSafeError,
    classify_google_oauth_error,
)
from healthcheck.google.contracts import (
    FAMILY_ALL_SOURCES,
    FAMILY_GOOGLE_SOURCES,
    FAMILY_GOOGLE_WEARABLES,
    GOOGLE_PROVIDER_CODE,
    GoogleQueryContext,
    GoogleQueryMode,
    GoogleSourceIdentity,
    GoogleSourceKind,
    GoogleStream,
)
from healthcheck.google.normalization import (
    normalize_google_payload,
)
from healthcheck.google.persistence import RawGooglePayload, google_persistence_for
from healthcheck.google.probe import (
    GOOGLE_API_ROOT,
    GoogleRecordType,
    GoogleSurfaceSpec,
    build_data_point_filter,
)
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.logging import log_event
from healthcheck.runtime import prepare_runtime

SYNC_CONTRACT_VERSION = "r04-google-sync-coverage-v1"
COVERAGE_RULE_VERSION = SYNC_CONTRACT_VERSION
COVERAGE_METRIC = "google_coverage"
COVERAGE_RESOLUTION = "civil_window"
INCREMENTAL_NAMESPACE = "incremental"
HISTORICAL_NAMESPACE = "historical"
REFRESH_NAMESPACE = "refresh"
INCREMENTAL_RUN_STREAM = "google_incremental"
HISTORICAL_RUN_STREAM = "google_historical"
REFRESH_RUN_STREAM = "google_refresh"
DEFAULT_FIRST_RUN_LOOKBACK_DAYS = 1
MAX_SYNC_PROVIDER_REQUESTS = 80
MAX_PAGES_PER_FETCH = 40
SLEEP_PAGE_SIZE = 25
DEFAULT_PAGE_SIZE = 500
MAX_RETRY_ATTEMPTS = 3
RETRY_STATUS_CODES = frozenset({429, 504})
RETRY_BACKOFF_SECONDS = (0.25, 0.5, 1.0)
HEART_RATE_ROLLUP_MAX_DAYS = 14
DEFAULT_ROLLUP_WINDOW_SIZE = "60s"
UNATTRIBUTED_SOURCE_INSTANCE = "unattributed"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FAMILY_SHORT = {
    "google-wearables": FAMILY_GOOGLE_WEARABLES,
    "google-sources": FAMILY_GOOGLE_SOURCES,
    "all-sources": FAMILY_ALL_SOURCES,
}
_STREAM_ALIASES = {
    "sleep": GoogleStream.SLEEP,
    "heart_rate": GoogleStream.HEART_RATE,
    "heart-rate": GoogleStream.HEART_RATE,
    "hrv": GoogleStream.HRV,
    "heart-rate-variability": GoogleStream.HRV,
    "heart_rate_variability": GoogleStream.HRV,
    "daily_hrv": GoogleStream.DAILY_HRV,
    "daily-heart-rate-variability": GoogleStream.DAILY_HRV,
    "daily_heart_rate_variability": GoogleStream.DAILY_HRV,
    "daily_resting_hr": GoogleStream.DAILY_RESTING_HR,
    "daily-resting-heart-rate": GoogleStream.DAILY_RESTING_HR,
    "daily_resting_heart_rate": GoogleStream.DAILY_RESTING_HR,
    "spo2": GoogleStream.SPO2,
    "oxygen-saturation": GoogleStream.SPO2,
    "oxygen_saturation": GoogleStream.SPO2,
    "daily_spo2": GoogleStream.DAILY_SPO2,
    "daily-oxygen-saturation": GoogleStream.DAILY_SPO2,
    "daily_oxygen_saturation": GoogleStream.DAILY_SPO2,
    "respiratory_rate_sleep": GoogleStream.RESPIRATORY_RATE_SLEEP,
    "respiratory-rate-sleep-summary": GoogleStream.RESPIRATORY_RATE_SLEEP,
    "respiratory_rate_sleep_summary": GoogleStream.RESPIRATORY_RATE_SLEEP,
    "daily_respiratory_rate": GoogleStream.DAILY_RESPIRATORY_RATE,
    "daily-respiratory-rate": GoogleStream.DAILY_RESPIRATORY_RATE,
}
_QUERY_MODE_ALIASES = {
    "list": GoogleQueryMode.LIST,
    "reconcile": GoogleQueryMode.RECONCILE,
    "rollup": GoogleQueryMode.ROLL_UP,
    "rollUp": GoogleQueryMode.ROLL_UP,
    "dailyrollup": GoogleQueryMode.DAILY_ROLL_UP,
    "dailyRollUp": GoogleQueryMode.DAILY_ROLL_UP,
}


class GoogleSyncStatus(StrEnum):
    """Outcome of one Google sync/backfill/refresh run or stream attempt."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    EMPTY = "empty"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    NOT_RUN = "not_run"
    REAUTH_REQUIRED = "reauth_required"
    SCOPE_REQUIRED = "scope_required"


class GoogleRunKind(StrEnum):
    INCREMENTAL = "incremental"
    HISTORICAL = "historical"
    REFRESH = "refresh"


@dataclass(frozen=True, slots=True)
class GoogleSyncSurface:
    """One accepted R04 Google Health stream with its list filter contract."""

    stream: GoogleStream
    data_type: str
    record_type: GoogleRecordType
    required_scope: str
    display_name: str

    @property
    def code(self) -> str:
        return self.stream.value


PRODUCTION_SYNC_SURFACES: tuple[GoogleSyncSurface, ...] = (
    GoogleSyncSurface(
        GoogleStream.SLEEP, "sleep", GoogleRecordType.SLEEP_SESSION, SCOPE_SLEEP, "Sleep"
    ),
    GoogleSyncSurface(
        GoogleStream.HEART_RATE, "heart-rate", GoogleRecordType.SAMPLE, SCOPE_METRICS, "Heart rate"
    ),
    GoogleSyncSurface(
        GoogleStream.HRV,
        "heart-rate-variability",
        GoogleRecordType.SAMPLE,
        SCOPE_METRICS,
        "Heart rate variability",
    ),
    GoogleSyncSurface(
        GoogleStream.DAILY_HRV,
        "daily-heart-rate-variability",
        GoogleRecordType.DAILY,
        SCOPE_METRICS,
        "Daily heart rate variability",
    ),
    GoogleSyncSurface(
        GoogleStream.DAILY_RESTING_HR,
        "daily-resting-heart-rate",
        GoogleRecordType.DAILY,
        SCOPE_METRICS,
        "Daily resting heart rate",
    ),
    GoogleSyncSurface(
        GoogleStream.SPO2,
        "oxygen-saturation",
        GoogleRecordType.SAMPLE,
        SCOPE_METRICS,
        "Oxygen saturation",
    ),
    GoogleSyncSurface(
        GoogleStream.DAILY_SPO2,
        "daily-oxygen-saturation",
        GoogleRecordType.DAILY,
        SCOPE_METRICS,
        "Daily oxygen saturation",
    ),
    GoogleSyncSurface(
        GoogleStream.RESPIRATORY_RATE_SLEEP,
        "respiratory-rate-sleep-summary",
        GoogleRecordType.SAMPLE,
        SCOPE_METRICS,
        "Respiratory rate sleep summary",
    ),
    GoogleSyncSurface(
        GoogleStream.DAILY_RESPIRATORY_RATE,
        "daily-respiratory-rate",
        GoogleRecordType.DAILY,
        SCOPE_METRICS,
        "Daily respiratory rate",
    ),
)
_SURFACE_BY_STREAM = {item.stream: item for item in PRODUCTION_SYNC_SURFACES}


@dataclass(frozen=True, slots=True)
class GoogleSyncAttempt:
    """Sanitized outcome of one stream/window fetch. No health values or tokens."""

    stream: str
    data_type: str
    query_mode: str
    data_source_family: str | None
    window_start: str
    window_end_exclusive: str
    status: GoogleSyncStatus
    coverage_status: str | None
    record_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    page_count: int = 0
    request_count: int = 0
    skipped: bool = False
    resume_cursor_present: bool = False
    error: GoogleSafeError | None = None
    not_run_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "stream": self.stream,
            "data_type": self.data_type,
            "query_mode": self.query_mode,
            "data_source_family": self.data_source_family,
            "window_start": self.window_start,
            "window_end_exclusive": self.window_end_exclusive,
            "status": self.status.value,
            "coverage_status": self.coverage_status,
            "record_count": self.record_count,
            "inserted_count": self.inserted_count,
            "updated_count": self.updated_count,
            "page_count": self.page_count,
            "request_count": self.request_count,
            "skipped": self.skipped,
            "resume_cursor_present": self.resume_cursor_present,
            "error": self.error.as_dict() if self.error else None,
        }
        if self.not_run_reason is not None:
            payload["not_run_reason"] = self.not_run_reason
        return payload


@dataclass(frozen=True, slots=True)
class GoogleSyncReport:
    """Privacy-safe machine-readable Google sync summary."""

    auth: GoogleAuthResult | None
    status: GoogleSyncStatus
    kind: GoogleRunKind
    window_start: str | None
    window_end_exclusive: str | None
    request_count: int
    query_mode: str
    data_source_family: str | None
    streams: tuple[str, ...]
    sync_run_id: str | None = None
    attempts: tuple[GoogleSyncAttempt, ...] = ()
    abort_reason: str | None = None
    skipped_complete_count: int = 0
    dry_run: bool = False

    def as_dict(self) -> dict[str, Any]:
        if self.auth is None:
            auth_payload: dict[str, Any] = {
                "contract_version": "r04-google-web-oauth-v1",
                "status": "not_attempted",
                "token_health": "unknown",
                "session_reused": False,
                "error": None,
            }
        else:
            auth_payload = self.auth.as_dict()
        return {
            "contract_version": SYNC_CONTRACT_VERSION,
            "source": {"provider_code": GOOGLE_PROVIDER_CODE},
            "auth": auth_payload,
            "sync": {
                "status": self.status.value,
                "kind": self.kind.value,
                "window_start": self.window_start,
                "window_end_exclusive": self.window_end_exclusive,
                "query_mode": self.query_mode,
                "data_source_family": self.data_source_family,
                "streams": list(self.streams),
                "request_count": self.request_count,
                "max_provider_requests": MAX_SYNC_PROVIDER_REQUESTS,
                "sleep_page_size": SLEEP_PAGE_SIZE,
                "list_ordering_assumed": False,
                "trailing_window_days": None,
                "dry_run": self.dry_run,
                "skipped_complete_count": self.skipped_complete_count,
                "abort_reason": self.abort_reason,
                "sync_run_id": self.sync_run_id,
            },
            "privacy": {
                "raw_values_emitted": False,
                "private_identifiers_emitted": False,
                "tokens_emitted": False,
                "health_timestamps_emitted": False,
                "page_tokens_emitted": False,
                "string_encoded_numerics_logged_as_values": False,
            },
            "attempts": [item.as_dict() for item in self.attempts],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n"


class _RequestBudget:
    def __init__(self, max_requests: int) -> None:
        self.max_requests = max_requests
        self.used = 0

    def remaining(self) -> int:
        return max(0, self.max_requests - self.used)

    def consume(self) -> bool:
        if self.used >= self.max_requests:
            return False
        self.used += 1
        return True


def validate_sync_date(value: date | str | None, *, field_name: str = "date") -> date:
    if value is None:
        return datetime.now(UTC).date()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise ValueError(f"{field_name} must use YYYY-MM-DD")
    return date.fromisoformat(value)


def validate_inclusive_window(
    start: date | str | None, end: date | str | None
) -> tuple[date, date]:
    if start is None or end is None:
        raise ValueError("explicit Google Health windows require --start and --end")
    start_date = validate_sync_date(start, field_name="start")
    end_date = validate_sync_date(end, field_name="end")
    if end_date < start_date:
        raise ValueError("window end must be on or after start")
    return start_date, end_date


def inclusive_to_exclusive_end(end_inclusive: date) -> date:
    return end_inclusive + timedelta(days=1)


def civil_bounds(start: date, end_exclusive: date) -> tuple[datetime, datetime]:
    if end_exclusive <= start:
        raise ValueError("exclusive window end must be after start")
    return (
        datetime(start.year, start.month, start.day, tzinfo=UTC),
        datetime(end_exclusive.year, end_exclusive.month, end_exclusive.day, tzinfo=UTC),
    )


def parse_google_stream(value: str) -> GoogleStream:
    token = _STREAM_ALIASES.get(value.strip())
    if token is None:
        raise ValueError(f"unsupported Google Health stream {value!r}")
    return token


def parse_google_streams(values: Sequence[str] | None) -> tuple[GoogleSyncSurface, ...]:
    if not values:
        return PRODUCTION_SYNC_SURFACES
    selected: list[GoogleSyncSurface] = []
    seen: set[GoogleStream] = set()
    for raw in values:
        stream = parse_google_stream(raw)
        if stream in seen:
            continue
        seen.add(stream)
        selected.append(_SURFACE_BY_STREAM[stream])
    return tuple(selected)


def parse_query_mode(value: str | GoogleQueryMode | None) -> GoogleQueryMode:
    if value is None:
        return GoogleQueryMode.LIST
    if isinstance(value, GoogleQueryMode):
        return value
    token = _QUERY_MODE_ALIASES.get(value.strip()) or _QUERY_MODE_ALIASES.get(value.strip().lower())
    if token is None:
        raise ValueError("query mode must be list, reconcile, rollUp or dailyRollUp")
    return token


def parse_data_source_family(value: str | None) -> str | None:
    if value is None or value == "" or value == "any":
        return None
    if value in _FAMILY_SHORT:
        return _FAMILY_SHORT[value]
    if value.startswith("users/") and "/dataSourceFamilies/" in value:
        return value
    raise ValueError("dataSourceFamily must be a known short name or full resource URI")


def allowed_query_modes(stream: GoogleStream) -> frozenset[GoogleQueryMode]:
    if stream is GoogleStream.HEART_RATE:
        return frozenset(
            {
                GoogleQueryMode.LIST,
                GoogleQueryMode.RECONCILE,
                GoogleQueryMode.ROLL_UP,
                GoogleQueryMode.DAILY_ROLL_UP,
            }
        )
    return frozenset({GoogleQueryMode.LIST, GoogleQueryMode.RECONCILE})


def page_size_for(surface: GoogleSyncSurface) -> int:
    if surface.stream is GoogleStream.SLEEP:
        return SLEEP_PAGE_SIZE
    return DEFAULT_PAGE_SIZE


def envelope_key(query_mode: GoogleQueryMode) -> str:
    if query_mode in {GoogleQueryMode.ROLL_UP, GoogleQueryMode.DAILY_ROLL_UP}:
        return "rollupDataPoints"
    return "dataPoints"


def checkpoint_stream_code(
    *,
    namespace: str,
    stream: GoogleStream,
    query_mode: GoogleQueryMode,
    data_source_family: str | None,
) -> str:
    family_key = "any"
    if data_source_family:
        family_key = data_source_family.rsplit("/", 1)[-1]
    return f"google:{namespace}:{stream.value}:{query_mode.value}:{family_key}"


def query_level_source_identity(query: GoogleQueryContext) -> GoogleSourceIdentity:
    """Identity when a response has no explicit provider dataSource metadata.

    Data type is never used as source identity. Family-level queries stay
    family_aggregate; otherwise the source is honestly unattributed.
    """

    if query.data_source_family:
        return GoogleSourceIdentity(
            source_kind=GoogleSourceKind.FAMILY_AGGREGATE,
            source_instance_id=query.data_source_family,
        )
    return GoogleSourceIdentity(
        source_kind=GoogleSourceKind.DATA_SOURCE,
        source_instance_id=UNATTRIBUTED_SOURCE_INSTANCE,
    )


def default_source_identity(
    surface: GoogleSyncSurface, query: GoogleQueryContext
) -> GoogleSourceIdentity:
    del surface
    return query_level_source_identity(query)


def source_identity_from_point(
    point: Mapping[str, Any] | None, query: GoogleQueryContext
) -> GoogleSourceIdentity:
    """Stable source identity from explicit provider dataSource metadata only."""

    if not isinstance(point, Mapping):
        return query_level_source_identity(query)
    data_source = point.get("dataSource")
    if not isinstance(data_source, Mapping):
        return query_level_source_identity(query)
    name = data_source.get("name")
    if isinstance(name, str) and name.strip():
        instance = name.strip()
        return GoogleSourceIdentity(
            source_kind=GoogleSourceKind.DATA_SOURCE,
            source_instance_id=instance,
            data_source_name=instance,
            platform=_optional_text(data_source.get("platform")),
            recording_method=_optional_text(data_source.get("recordingMethod")),
        )
    fingerprint = _explicit_source_fingerprint(data_source)
    if fingerprint is not None:
        return GoogleSourceIdentity(
            source_kind=GoogleSourceKind.DATA_SOURCE,
            source_instance_id=fingerprint,
            platform=_optional_text(data_source.get("platform")),
            recording_method=_optional_text(data_source.get("recordingMethod")),
        )
    return query_level_source_identity(query)


def identities_from_points(
    points: Sequence[Any], query: GoogleQueryContext
) -> tuple[GoogleSourceIdentity, ...]:
    """Unique source identities present on one page; empty if no points."""

    grouped: dict[str, GoogleSourceIdentity] = {}
    for point in points:
        if not isinstance(point, Mapping):
            continue
        identity = source_identity_from_point(point, query)
        grouped[identity.source_instance_id] = identity
    return tuple(grouped.values())


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _explicit_source_fingerprint(data_source: Mapping[str, Any]) -> str | None:
    parts: list[str] = []
    for key in ("platform", "recordingMethod"):
        text = _optional_text(data_source.get(key))
        if text is not None:
            parts.append(f"{key}={text}")
    device = data_source.get("device")
    if isinstance(device, Mapping):
        for key in ("manufacturer", "displayName", "formFactor"):
            text = _optional_text(device.get(key))
            if text is not None:
                parts.append(f"device.{key}={text}")
    application = data_source.get("application")
    if isinstance(application, Mapping):
        text = _optional_text(application.get("packageName"))
        if text is not None:
            parts.append(f"application.packageName={text}")
    if not parts:
        return None
    return "unattributed:" + ";".join(parts)


def parse_page_envelope(
    payload: Mapping[str, Any], query_mode: GoogleQueryMode
) -> tuple[list[Any], str | None, str]:
    """Classify one Google Health list/rollup page.

    A missing or empty collection WITH a nextPageToken is pagination-continue,
    not confirmed-empty and not shape-drift.  Observed live heart-rate first
    pages can omit ``dataPoints`` while still returning ``nextPageToken``.
    """

    raw_token = payload.get("nextPageToken")
    token = raw_token.strip() if isinstance(raw_token, str) and raw_token.strip() else None
    key = envelope_key(query_mode)
    if key not in payload:
        if token:
            return [], token, "continue"
        return [], None, "invalid"
    points = payload[key]
    if points is None:
        if token:
            return [], token, "continue"
        return [], None, "invalid"
    if not isinstance(points, list):
        return [], None, "invalid"
    if token:
        return points, token, "continue"
    return points, None, "complete"


def _attempt_status_for(coverage_status: str) -> GoogleSyncStatus:
    if coverage_status == "failed":
        return GoogleSyncStatus.FAILED
    if coverage_status == "confirmed_empty":
        return GoogleSyncStatus.EMPTY
    if coverage_status == "present":
        return GoogleSyncStatus.SUCCEEDED
    if coverage_status == "unavailable":
        return GoogleSyncStatus.UNAVAILABLE
    return GoogleSyncStatus.PARTIAL


def _roll_up_status(
    attempts: Sequence[GoogleSyncAttempt], abort_reason: str | None
) -> GoogleSyncStatus:
    if abort_reason == "reauth_required":
        return GoogleSyncStatus.REAUTH_REQUIRED
    executed = [item for item in attempts if item.status is not GoogleSyncStatus.NOT_RUN]
    if not executed:
        return GoogleSyncStatus.FAILED if abort_reason else GoogleSyncStatus.EMPTY
    statuses = {item.status for item in executed}
    good = {GoogleSyncStatus.SUCCEEDED, GoogleSyncStatus.EMPTY}
    bad = {
        GoogleSyncStatus.FAILED,
        GoogleSyncStatus.UNAVAILABLE,
        GoogleSyncStatus.SCOPE_REQUIRED,
    }
    if GoogleSyncStatus.REAUTH_REQUIRED in statuses:
        return GoogleSyncStatus.REAUTH_REQUIRED
    if statuses <= good:
        return GoogleSyncStatus.PARTIAL if abort_reason else GoogleSyncStatus.SUCCEEDED
    if statuses & good and (statuses & bad or GoogleSyncStatus.PARTIAL in statuses):
        return GoogleSyncStatus.PARTIAL
    if GoogleSyncStatus.PARTIAL in statuses:
        return GoogleSyncStatus.PARTIAL
    if statuses <= bad:
        return GoogleSyncStatus.FAILED
    return GoogleSyncStatus.PARTIAL


def _run_status_token(status: GoogleSyncStatus) -> str:
    if status is GoogleSyncStatus.SUCCEEDED:
        return "succeeded"
    if status is GoogleSyncStatus.PARTIAL:
        return "partial"
    return "failed"


class GoogleHealthSync:
    """Fetch, paginate, normalize and persist one bounded Google Health window."""

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
        clock: Callable[[], datetime] | None = None,
        max_provider_requests: int = MAX_SYNC_PROVIDER_REQUESTS,
        run_kind: GoogleRunKind = GoogleRunKind.INCREMENTAL,
    ) -> None:
        if max_provider_requests < 1:
            raise ValueError("max_provider_requests must be positive")
        if max_provider_requests > MAX_SYNC_PROVIDER_REQUESTS:
            raise ValueError("max_provider_requests exceeds the hard Google sync cap")
        self.settings = settings
        self.auth_service = auth_service
        self.transport = transport or (auth_service.transport if auth_service is not None else None)
        self.auth_result = auth_result
        self.access_token = access_token
        self.granted_scopes = granted_scopes
        self.sleeper = sleeper or (lambda _seconds: None)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.max_provider_requests = max_provider_requests
        self.run_kind = GoogleRunKind(run_kind)

    @property
    def namespace(self) -> str:
        return {
            GoogleRunKind.INCREMENTAL: INCREMENTAL_NAMESPACE,
            GoogleRunKind.HISTORICAL: HISTORICAL_NAMESPACE,
            GoogleRunKind.REFRESH: REFRESH_NAMESPACE,
        }[self.run_kind]

    @property
    def run_stream(self) -> str:
        return {
            GoogleRunKind.INCREMENTAL: INCREMENTAL_RUN_STREAM,
            GoogleRunKind.HISTORICAL: HISTORICAL_RUN_STREAM,
            GoogleRunKind.REFRESH: REFRESH_RUN_STREAM,
        }[self.run_kind]

    def run(
        self,
        *,
        as_of: date | str | None = None,
        start: date | str | None = None,
        end: date | str | None = None,
        streams: Sequence[str] | None = None,
        query_mode: str | GoogleQueryMode | None = None,
        data_source_family: str | None = None,
    ) -> GoogleSyncReport:
        surfaces = parse_google_streams(streams)
        mode = parse_query_mode(query_mode)
        family = parse_data_source_family(data_source_family)
        as_of_date: date | None = None
        if start is not None or end is not None:
            start_date, end_inclusive = validate_inclusive_window(start, end)
            window_start, window_end = start_date, inclusive_to_exclusive_end(end_inclusive)
        else:
            as_of_date = validate_sync_date(as_of)
            window_end = as_of_date + timedelta(days=1)
            window_start = window_end - timedelta(days=DEFAULT_FIRST_RUN_LOOKBACK_DAYS)
        return self._execute(
            window_start=window_start,
            window_end_exclusive=window_end,
            surfaces=surfaces,
            query_mode=mode,
            data_source_family=family,
            skip_complete=self.run_kind is not GoogleRunKind.REFRESH,
            per_stream_watermark=as_of_date is not None,
            as_of=as_of_date,
        )

    def run_window(
        self,
        *,
        start: date,
        end_exclusive: date,
        streams: Sequence[str] | None = None,
        query_mode: str | GoogleQueryMode | None = None,
        data_source_family: str | None = None,
        skip_complete: bool | None = None,
    ) -> GoogleSyncReport:
        surfaces = parse_google_streams(streams)
        mode = parse_query_mode(query_mode)
        family = parse_data_source_family(data_source_family)
        if skip_complete is None:
            skip = self.run_kind is not GoogleRunKind.REFRESH
        else:
            skip = skip_complete
        return self._execute(
            window_start=start,
            window_end_exclusive=end_exclusive,
            surfaces=surfaces,
            query_mode=mode,
            data_source_family=family,
            skip_complete=skip,
            per_stream_watermark=False,
            as_of=None,
        )

    def _execute(
        self,
        *,
        window_start: date,
        window_end_exclusive: date,
        surfaces: tuple[GoogleSyncSurface, ...],
        query_mode: GoogleQueryMode,
        data_source_family: str | None,
        skip_complete: bool,
        per_stream_watermark: bool = False,
        as_of: date | None = None,
    ) -> GoogleSyncReport:
        if window_end_exclusive <= window_start:
            raise ValueError("Google Health window end must be after start")
        span_days = (window_end_exclusive - window_start).days
        if (
            query_mode in {GoogleQueryMode.ROLL_UP, GoogleQueryMode.DAILY_ROLL_UP}
            and span_days > HEART_RATE_ROLLUP_MAX_DAYS
        ):
            raise ValueError(
                "heart-rate rollUp/dailyRollUp windows must be <= "
                f"{HEART_RATE_ROLLUP_MAX_DAYS} days"
            )
        paths = prepare_runtime(self.settings)
        migrate_database(paths)
        engine = create_sqlite_engine(paths)
        store = ContentAddressedGooglePayloadStore(paths.root / "artifacts")
        factory = create_session_factory(engine)
        try:
            return self._run(
                factory,
                store,
                window_start=window_start,
                window_end_exclusive=window_end_exclusive,
                surfaces=surfaces,
                query_mode=query_mode,
                data_source_family=data_source_family,
                skip_complete=skip_complete,
                per_stream_watermark=per_stream_watermark,
                as_of=as_of,
            )
        finally:
            engine.dispose()

    def _resolve_auth(self) -> tuple[GoogleAuthResult, str | None, frozenset[str]]:
        if self.auth_result is not None and self.access_token:
            scopes = self.granted_scopes if self.granted_scopes is not None else ALLOWED_SCOPES
            return self.auth_result, self.access_token, scopes
        if self.auth_service is None:
            auth = self.auth_result or GoogleAuthResult(
                status=GoogleAuthStatus.REAUTH_REQUIRED,
                error=GoogleSafeError("storage", "credential_missing"),
            )
            return auth, None, frozenset()
        auth = self.auth_result or self.auth_service.token_health()
        if not auth.ok:
            return auth, None, frozenset()
        token, live_auth = self.auth_service.load_access_token(refresh_if_needed=True)
        if not token or not live_auth.ok:
            return live_auth, None, frozenset()
        scopes = self.granted_scopes
        if scopes is None:
            try:
                scopes = self.auth_service._read_tokens().granted_scopes()
            except Exception:
                scopes = ALLOWED_SCOPES
        return live_auth, token, scopes

    def _run(
        self,
        factory,
        store: ContentAddressedGooglePayloadStore,
        *,
        window_start: date,
        window_end_exclusive: date,
        surfaces: tuple[GoogleSyncSurface, ...],
        query_mode: GoogleQueryMode,
        data_source_family: str | None,
        skip_complete: bool,
        per_stream_watermark: bool = False,
        as_of: date | None = None,
    ) -> GoogleSyncReport:
        auth, access_token, scopes = self._resolve_auth()
        requested_start, requested_end = civil_bounds(window_start, window_end_exclusive)
        if access_token is None or self.transport is None or not auth.ok:
            status = (
                GoogleSyncStatus.REAUTH_REQUIRED
                if auth.status is GoogleAuthStatus.REAUTH_REQUIRED
                else GoogleSyncStatus.FAILED
            )
            run_id = self._record_auth_failure(
                factory,
                status=status,
                requested_start=requested_start,
                requested_end=requested_end,
            )
            return GoogleSyncReport(
                auth=auth,
                status=status,
                kind=self.run_kind,
                window_start=window_start.isoformat(),
                window_end_exclusive=window_end_exclusive.isoformat(),
                request_count=0,
                query_mode=query_mode.value,
                data_source_family=data_source_family,
                streams=tuple(item.code for item in surfaces),
                sync_run_id=run_id,
                abort_reason=status.value,
            )

        budget = _RequestBudget(self.max_provider_requests)
        with factory() as session:
            provider = repositories_for(session).providers.get_or_create(
                GOOGLE_PROVIDER_CODE, "Google Health", "health_api"
            )
            run = repositories_for(session).sync.create_run(
                provider_id=provider.id,
                stream_code=self.run_stream,
                requested_start=requested_start,
                requested_end=requested_end,
            )
            session.commit()
            sync_run_id = run.id
            provider_id = provider.id

        attempts: list[GoogleSyncAttempt] = []
        abort_reason: str | None = None
        for surface in surfaces:
            if abort_reason == "reauth_required":
                attempts.append(
                    self._not_run_attempt(
                        surface,
                        query_mode,
                        data_source_family,
                        window_start,
                        window_end_exclusive,
                        reason="reauth_required",
                    )
                )
                continue
            attempt = self._ingest_surface(
                factory,
                store,
                surface=surface,
                query_mode=query_mode,
                data_source_family=data_source_family,
                window_start=window_start,
                window_end_exclusive=window_end_exclusive,
                provider_id=provider_id,
                sync_run_id=sync_run_id,
                access_token=access_token,
                scopes=scopes,
                budget=budget,
                skip_complete=skip_complete,
                per_stream_watermark=per_stream_watermark,
                as_of=as_of,
            )
            attempts.append(attempt)
            if attempt.status is GoogleSyncStatus.REAUTH_REQUIRED:
                abort_reason = "reauth_required"

        run_status = _roll_up_status(attempts, abort_reason)
        received = sum(item.record_count for item in attempts)
        accepted = sum(
            item.record_count
            for item in attempts
            if item.status
            in {GoogleSyncStatus.SUCCEEDED, GoogleSyncStatus.PARTIAL, GoogleSyncStatus.EMPTY}
        )
        failed = sum(
            1
            for item in attempts
            if item.status in {GoogleSyncStatus.FAILED, GoogleSyncStatus.REAUTH_REQUIRED}
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
                actual_start=requested_start,
                actual_end=requested_end,
            )
            session.commit()
        log_event(
            "google_health_sync",
            operation=f"google-{self.run_kind.value}",
            status=run_status.value,
            count=budget.used,
            reason=abort_reason or run_status.value,
        )
        return GoogleSyncReport(
            auth=auth,
            status=run_status,
            kind=self.run_kind,
            window_start=window_start.isoformat(),
            window_end_exclusive=window_end_exclusive.isoformat(),
            request_count=budget.used,
            query_mode=query_mode.value,
            data_source_family=data_source_family,
            streams=tuple(item.code for item in surfaces),
            sync_run_id=sync_run_id,
            attempts=tuple(attempts),
            abort_reason=abort_reason,
            skipped_complete_count=sum(1 for item in attempts if item.skipped),
        )

    def _record_auth_failure(
        self,
        factory,
        *,
        status: GoogleSyncStatus,
        requested_start: datetime,
        requested_end: datetime,
    ) -> str | None:
        with factory() as session:
            provider = repositories_for(session).providers.get_or_create(
                GOOGLE_PROVIDER_CODE, "Google Health", "health_api"
            )
            run = repositories_for(session).sync.create_run(
                provider_id=provider.id,
                stream_code=self.run_stream,
                requested_start=requested_start,
                requested_end=requested_end,
            )
            repositories_for(session).sync.finish_run(
                run.id,
                status=_run_status_token(status),
                item_count=0,
                received_count=0,
                accepted_count=0,
                failed_count=1,
                error_category=status.value,
                diagnostic_reason=status.value,
                actual_start=requested_start,
                actual_end=requested_end,
            )
            session.commit()
            return run.id

    def _not_run_attempt(
        self,
        surface: GoogleSyncSurface,
        query_mode: GoogleQueryMode,
        family: str | None,
        window_start: date,
        window_end_exclusive: date,
        *,
        reason: str,
        status: GoogleSyncStatus = GoogleSyncStatus.NOT_RUN,
        coverage_status: str | None = None,
    ) -> GoogleSyncAttempt:
        return GoogleSyncAttempt(
            stream=surface.code,
            data_type=surface.data_type,
            query_mode=query_mode.value,
            data_source_family=family,
            window_start=window_start.isoformat(),
            window_end_exclusive=window_end_exclusive.isoformat(),
            status=status,
            coverage_status=coverage_status,
            not_run_reason=reason,
        )

    def _ingest_surface(
        self,
        factory,
        store: ContentAddressedGooglePayloadStore,
        *,
        surface: GoogleSyncSurface,
        query_mode: GoogleQueryMode,
        data_source_family: str | None,
        window_start: date,
        window_end_exclusive: date,
        provider_id: str,
        sync_run_id: str,
        access_token: str,
        scopes: frozenset[str],
        budget: _RequestBudget,
        skip_complete: bool,
        per_stream_watermark: bool = False,
        as_of: date | None = None,
    ) -> GoogleSyncAttempt:
        query = GoogleQueryContext(query_mode=query_mode, data_source_family=data_source_family)
        state_code = checkpoint_stream_code(
            namespace=self.namespace,
            stream=surface.stream,
            query_mode=query_mode,
            data_source_family=data_source_family,
        )
        if per_stream_watermark and as_of is not None:
            window_start, window_end_exclusive = self._stream_watermark_window(
                factory,
                provider_id=provider_id,
                state_code=state_code,
                as_of=as_of,
            )
        start_utc, end_utc = civil_bounds(window_start, window_end_exclusive)
        if surface.required_scope not in scopes:
            return self._not_run_attempt(
                surface,
                query_mode,
                data_source_family,
                window_start,
                window_end_exclusive,
                reason="scope_required",
                status=GoogleSyncStatus.SCOPE_REQUIRED,
                coverage_status="unavailable",
            )
        if query_mode not in allowed_query_modes(surface.stream):
            self._write_checkpoint(
                factory,
                provider_id=provider_id,
                state_code=state_code,
                window_start=start_utc,
                window_end=end_utc,
                coverage_status="unavailable",
                complete=False,
                observed_count=None,
                cursor=None,
            )
            return self._not_run_attempt(
                surface,
                query_mode,
                data_source_family,
                window_start,
                window_end_exclusive,
                reason="unsupported_query_mode",
                status=GoogleSyncStatus.UNAVAILABLE,
                coverage_status="unavailable",
            )
        if skip_complete:
            completed = self._completed_coverage(
                factory,
                provider_id=provider_id,
                state_code=state_code,
                window_start=start_utc,
                window_end=end_utc,
            )
            if completed is not None:
                return GoogleSyncAttempt(
                    stream=surface.code,
                    data_type=surface.data_type,
                    query_mode=query_mode.value,
                    data_source_family=data_source_family,
                    window_start=window_start.isoformat(),
                    window_end_exclusive=window_end_exclusive.isoformat(),
                    status=_attempt_status_for(completed),
                    coverage_status=completed,
                    skipped=True,
                )

        resume_token = None
        if self.run_kind is not GoogleRunKind.REFRESH:
            resume_token = self._resume_token(
                factory,
                provider_id=provider_id,
                state_code=state_code,
                window_start=window_start,
                window_end_exclusive=window_end_exclusive,
            )
        pages: list[dict[str, Any]] = []
        collected: list[Any] = []
        page_count = 0
        request_count = 0
        inserted = 0
        updated = 0
        persist_records = self.run_kind is not GoogleRunKind.REFRESH
        next_token = resume_token
        identity = query_level_source_identity(query)

        while True:
            if page_count >= MAX_PAGES_PER_FETCH:
                self._write_checkpoint(
                    factory,
                    provider_id=provider_id,
                    state_code=state_code,
                    window_start=start_utc,
                    window_end=end_utc,
                    coverage_status="unknown",
                    complete=False,
                    observed_count=len(collected),
                    cursor=self._incomplete_cursor(
                        next_token, window_start, window_end_exclusive
                    ),
                )
                return GoogleSyncAttempt(
                    stream=surface.code,
                    data_type=surface.data_type,
                    query_mode=query_mode.value,
                    data_source_family=data_source_family,
                    window_start=window_start.isoformat(),
                    window_end_exclusive=window_end_exclusive.isoformat(),
                    status=GoogleSyncStatus.PARTIAL,
                    coverage_status="unknown",
                    record_count=len(collected),
                    inserted_count=inserted,
                    updated_count=updated,
                    page_count=page_count,
                    request_count=request_count,
                    resume_cursor_present=self._resume_cursor_flag(next_token),
                    error=GoogleSafeError("budget", "page_ceiling"),
                )
            if budget.remaining() <= 0:
                self._write_checkpoint(
                    factory,
                    provider_id=provider_id,
                    state_code=state_code,
                    window_start=start_utc,
                    window_end=end_utc,
                    coverage_status="unknown",
                    complete=False,
                    observed_count=len(collected),
                    cursor=self._incomplete_cursor(
                        next_token, window_start, window_end_exclusive
                    ),
                )
                return GoogleSyncAttempt(
                    stream=surface.code,
                    data_type=surface.data_type,
                    query_mode=query_mode.value,
                    data_source_family=data_source_family,
                    window_start=window_start.isoformat(),
                    window_end_exclusive=window_end_exclusive.isoformat(),
                    status=GoogleSyncStatus.PARTIAL,
                    coverage_status="unknown",
                    record_count=len(collected),
                    inserted_count=inserted,
                    updated_count=updated,
                    page_count=page_count,
                    request_count=request_count,
                    resume_cursor_present=self._resume_cursor_flag(next_token),
                    error=GoogleSafeError("budget", "request_ceiling"),
                )

            response, error, consumed = self._provider_get(
                surface,
                query=query,
                window_start=window_start,
                window_end_exclusive=window_end_exclusive,
                access_token=access_token,
                page_token=next_token,
                budget=budget,
            )
            request_count += consumed
            if error is not None:
                if response is not None:
                    self._persist_terminal(
                        factory,
                        store,
                        identity=identity,
                        query=query,
                        surface=surface,
                        payload=response.body,
                        parse_invalid=True,
                        window_start=start_utc,
                        window_end=end_utc,
                        sync_run_id=sync_run_id,
                        records=(),
                    )
                status = (
                    GoogleSyncStatus.REAUTH_REQUIRED
                    if error.error_code == "authentication_failed"
                    else GoogleSyncStatus.FAILED
                )
                self._write_checkpoint(
                    factory,
                    provider_id=provider_id,
                    state_code=state_code,
                    window_start=start_utc,
                    window_end=end_utc,
                    coverage_status="failed",
                    complete=False,
                    observed_count=len(collected),
                    cursor=self._incomplete_cursor(
                        next_token, window_start, window_end_exclusive
                    ),
                )
                return GoogleSyncAttempt(
                    stream=surface.code,
                    data_type=surface.data_type,
                    query_mode=query_mode.value,
                    data_source_family=data_source_family,
                    window_start=window_start.isoformat(),
                    window_end_exclusive=window_end_exclusive.isoformat(),
                    status=status,
                    coverage_status="failed",
                    record_count=len(collected),
                    inserted_count=inserted,
                    updated_count=updated,
                    page_count=page_count,
                    request_count=request_count,
                    resume_cursor_present=self._resume_cursor_flag(next_token),
                    error=error,
                )
            assert response is not None
            raw_body = response.body
            try:
                payload = response.json()
            except Exception:
                payload = None
            if not isinstance(payload, Mapping):
                self._persist_terminal(
                    factory,
                    store,
                    identity=identity,
                    query=query,
                    surface=surface,
                    payload=raw_body,
                    parse_invalid=True,
                    window_start=start_utc,
                    window_end=end_utc,
                    sync_run_id=sync_run_id,
                    records=(),
                )
                self._write_checkpoint(
                    factory,
                    provider_id=provider_id,
                    state_code=state_code,
                    window_start=start_utc,
                    window_end=end_utc,
                    coverage_status="failed",
                    complete=False,
                    observed_count=len(collected),
                    cursor=None,
                )
                return GoogleSyncAttempt(
                    stream=surface.code,
                    data_type=surface.data_type,
                    query_mode=query_mode.value,
                    data_source_family=data_source_family,
                    window_start=window_start.isoformat(),
                    window_end_exclusive=window_end_exclusive.isoformat(),
                    status=GoogleSyncStatus.FAILED,
                    coverage_status="failed",
                    record_count=len(collected),
                    inserted_count=inserted,
                    updated_count=updated,
                    page_count=page_count,
                    request_count=request_count,
                    error=GoogleSafeError("provider", "response_invalid", response.status),
                )

            points, token, kind = parse_page_envelope(payload, query_mode)
            if (
                surface.stream is GoogleStream.SLEEP
                and isinstance(points, list)
                and len(points) > SLEEP_PAGE_SIZE
            ):
                kind = "invalid"
            page_count += 1
            pages.append(dict(payload))
            if kind == "invalid":
                self._persist_terminal(
                    factory,
                    store,
                    identity=identity,
                    query=query,
                    surface=surface,
                    payload=payload,
                    parse_invalid=True,
                    window_start=start_utc,
                    window_end=end_utc,
                    sync_run_id=sync_run_id,
                    records=(),
                )
                self._write_checkpoint(
                    factory,
                    provider_id=provider_id,
                    state_code=state_code,
                    window_start=start_utc,
                    window_end=end_utc,
                    coverage_status="failed",
                    complete=False,
                    observed_count=len(collected),
                    cursor=None,
                )
                return GoogleSyncAttempt(
                    stream=surface.code,
                    data_type=surface.data_type,
                    query_mode=query_mode.value,
                    data_source_family=data_source_family,
                    window_start=window_start.isoformat(),
                    window_end_exclusive=window_end_exclusive.isoformat(),
                    status=GoogleSyncStatus.FAILED,
                    coverage_status="failed",
                    record_count=len(collected),
                    inserted_count=inserted,
                    updated_count=updated,
                    page_count=page_count,
                    request_count=request_count,
                    error=GoogleSafeError("provider", "shape_drift", response.status),
                )

            collected.extend(points)
            outcome = self._persist_page(
                factory,
                store,
                surface=surface,
                query=query,
                identity=identity,
                payload=payload,
                window_start=start_utc,
                window_end=end_utc,
                sync_run_id=sync_run_id,
                upsert_records=persist_records,
            )
            if outcome is None:
                self._write_checkpoint(
                    factory,
                    provider_id=provider_id,
                    state_code=state_code,
                    window_start=start_utc,
                    window_end=end_utc,
                    coverage_status="failed",
                    complete=False,
                    observed_count=len(collected),
                    cursor=None,
                )
                return GoogleSyncAttempt(
                    stream=surface.code,
                    data_type=surface.data_type,
                    query_mode=query_mode.value,
                    data_source_family=data_source_family,
                    window_start=window_start.isoformat(),
                    window_end_exclusive=window_end_exclusive.isoformat(),
                    status=GoogleSyncStatus.FAILED,
                    coverage_status="failed",
                    record_count=len(collected),
                    inserted_count=inserted,
                    updated_count=updated,
                    page_count=page_count,
                    request_count=request_count,
                    error=GoogleSafeError("provider", "shape_drift", response.status),
                )
            inserted += outcome[0]
            updated += outcome[1]
            if kind == "continue":
                next_token = token
                continue
            break

        if self.run_kind is GoogleRunKind.REFRESH:
            merged = {envelope_key(query_mode): collected}
            refresh_outcome = self._persist_page(
                factory,
                store,
                surface=surface,
                query=query,
                identity=identity,
                payload=merged,
                window_start=start_utc,
                window_end=end_utc,
                sync_run_id=sync_run_id,
                upsert_records=True,
            )
            if refresh_outcome is None:
                self._write_checkpoint(
                    factory,
                    provider_id=provider_id,
                    state_code=state_code,
                    window_start=start_utc,
                    window_end=end_utc,
                    coverage_status="failed",
                    complete=False,
                    observed_count=len(collected),
                    cursor=None,
                )
                return GoogleSyncAttempt(
                    stream=surface.code,
                    data_type=surface.data_type,
                    query_mode=query_mode.value,
                    data_source_family=data_source_family,
                    window_start=window_start.isoformat(),
                    window_end_exclusive=window_end_exclusive.isoformat(),
                    status=GoogleSyncStatus.FAILED,
                    coverage_status="failed",
                    record_count=len(collected),
                    page_count=page_count,
                    request_count=request_count,
                    error=GoogleSafeError("provider", "shape_drift"),
                )
            inserted += refresh_outcome[0]
            updated += refresh_outcome[1]

        coverage = "confirmed_empty" if not collected else "present"
        self._write_checkpoint(
            factory,
            provider_id=provider_id,
            state_code=state_code,
            window_start=start_utc,
            window_end=end_utc,
            coverage_status=coverage,
            complete=True,
            observed_count=len(collected),
            cursor=None,
            watermark=end_utc,
        )
        return GoogleSyncAttempt(
            stream=surface.code,
            data_type=surface.data_type,
            query_mode=query_mode.value,
            data_source_family=data_source_family,
            window_start=window_start.isoformat(),
            window_end_exclusive=window_end_exclusive.isoformat(),
            status=_attempt_status_for(coverage),
            coverage_status=coverage,
            record_count=len(collected),
            inserted_count=inserted,
            updated_count=updated,
            page_count=page_count,
            request_count=request_count,
        )

    def _provider_get(
        self,
        surface: GoogleSyncSurface,
        *,
        query: GoogleQueryContext,
        window_start: date,
        window_end_exclusive: date,
        access_token: str,
        page_token: str | None,
        budget: _RequestBudget,
    ) -> tuple[GoogleHttpResponse | None, GoogleSafeError | None, int]:
        assert self.transport is not None
        consumed = 0
        last_error: GoogleSafeError | None = None
        for attempt_index in range(MAX_RETRY_ATTEMPTS):
            if not budget.consume():
                return None, GoogleSafeError("budget", "request_ceiling"), consumed
            consumed += 1
            try:
                response = self._request_page(
                    surface,
                    query=query,
                    window_start=window_start,
                    window_end_exclusive=window_end_exclusive,
                    access_token=access_token,
                    page_token=page_token,
                )
            except Exception as exc:
                last_error = classify_google_oauth_error(exc)
                if last_error.error_code in {"invalid_grant", "authentication_failed"}:
                    return None, last_error, consumed
                return None, last_error, consumed
            if response.status in {401, 403}:
                return (
                    response,
                    GoogleSafeError("authentication", "authentication_failed", response.status),
                    consumed,
                )
            if response.status in RETRY_STATUS_CODES:
                last_error = GoogleSafeError("provider", "retryable", response.status)
                if attempt_index + 1 < MAX_RETRY_ATTEMPTS:
                    delay_index = min(attempt_index, len(RETRY_BACKOFF_SECONDS) - 1)
                    self.sleeper(RETRY_BACKOFF_SECONDS[delay_index])
                    continue
                return response, last_error, consumed
            if response.status >= 400:
                return (
                    response,
                    GoogleSafeError("provider", "provider_error", response.status),
                    consumed,
                )
            return response, None, consumed
        return None, last_error or GoogleSafeError("provider", "retryable"), consumed

    def _request_page(
        self,
        surface: GoogleSyncSurface,
        *,
        query: GoogleQueryContext,
        window_start: date,
        window_end_exclusive: date,
        access_token: str,
        page_token: str | None,
    ) -> GoogleHttpResponse:
        assert self.transport is not None
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        page_size = page_size_for(surface)
        if query.query_mode in {GoogleQueryMode.ROLL_UP, GoogleQueryMode.DAILY_ROLL_UP}:
            start_utc, end_utc = civil_bounds(window_start, window_end_exclusive)
            body: dict[str, Any] = {
                "range": {
                    "startTime": start_utc.strftime("%Y-%m-%dT00:00:00Z"),
                    "endTime": end_utc.strftime("%Y-%m-%dT00:00:00Z"),
                },
                "pageSize": page_size,
            }
            if query.query_mode is GoogleQueryMode.ROLL_UP:
                body["windowSize"] = DEFAULT_ROLLUP_WINDOW_SIZE
            if query.data_source_family:
                body["dataSourceFamily"] = query.data_source_family
            if page_token:
                body["pageToken"] = page_token
            suffix = (
                "rollUp" if query.query_mode is GoogleQueryMode.ROLL_UP else "dailyRollUp"
            )
            url = f"{GOOGLE_API_ROOT}/users/me/dataTypes/{surface.data_type}/dataPoints:{suffix}"
            return self.transport.request("POST", url, headers=headers, json_body=body)
        spec = GoogleSurfaceSpec(
            surface.code,
            surface.data_type,
            "list",
            surface.required_scope,
            surface.display_name,
            surface.record_type,
        )
        params: dict[str, str] = {
            "filter": build_data_point_filter(
                spec,
                window_start=window_start.isoformat(),
                window_end_exclusive=window_end_exclusive.isoformat(),
            ),
            "pageSize": str(page_size),
        }
        if query.data_source_family:
            params["dataSourceFamily"] = query.data_source_family
        if page_token:
            params["pageToken"] = page_token
        operation = "" if query.query_mode is GoogleQueryMode.LIST else ":reconcile"
        url = (
            f"{GOOGLE_API_ROOT}/users/me/dataTypes/{surface.data_type}/dataPoints{operation}"
            f"?{urlencode(params)}"
        )
        return self.transport.request("GET", url, headers=headers)

    def _persist_page(
        self,
        factory,
        store: ContentAddressedGooglePayloadStore,
        *,
        surface: GoogleSyncSurface,
        query: GoogleQueryContext,
        identity: GoogleSourceIdentity,
        payload: Mapping[str, Any],
        window_start: datetime,
        window_end: datetime,
        sync_run_id: str,
        upsert_records: bool,
    ) -> tuple[int, int] | None:
        from healthcheck.db.models import GooglePayloadStatus

        points, _token, kind = parse_page_envelope(payload, query.query_mode)
        continue_empty = kind == "continue" and not points
        result = normalize_google_payload(
            payload, stream=surface.stream, query=query, source_identity=None
        )
        if result.status is GooglePayloadStatus.INVALID and not continue_empty:
            self._persist_terminal(
                factory,
                store,
                identity=identity,
                query=query,
                surface=surface,
                payload=payload,
                parse_invalid=True,
                window_start=window_start,
                window_end=window_end,
                sync_run_id=sync_run_id,
                records=(),
            )
            return None
        parse_status = GooglePayloadStatus.EMPTY if continue_empty else result.status
        if not upsert_records:
            staging_identities = identities_from_points(points, query)
            if not staging_identities:
                return 0, 0
            inserted = 0
            updated = 0
            with factory() as session:
                repo = google_persistence_for(session, payload_store=store)
                for staging_identity in staging_identities:
                    outcome = repo.persist_observation(
                        identity=staging_identity,
                        query=query,
                        stream=surface.stream,
                        payload=payload,
                        records=(),
                        parse_status=parse_status,
                        source_window_start_utc=window_start,
                        source_window_end_utc=window_end,
                        sync_run_id=sync_run_id,
                        diagnostics=tuple(item.as_dict() for item in result.diagnostics),
                        unknown_fields=result.unknown_fields,
                    )
                    inserted += outcome.inserted_count
                    updated += outcome.updated_count
                session.commit()
            return inserted, updated
        if continue_empty or not result.records:
            with factory() as session:
                repo = google_persistence_for(session, payload_store=store)
                outcome = repo.persist_observation(
                    identity=identity,
                    query=query,
                    stream=surface.stream,
                    payload=payload,
                    records=(),
                    parse_status=parse_status,
                    source_window_start_utc=window_start,
                    source_window_end_utc=window_end,
                    sync_run_id=sync_run_id,
                    diagnostics=tuple(item.as_dict() for item in result.diagnostics),
                    unknown_fields=result.unknown_fields,
                )
                session.commit()
                return outcome.inserted_count, outcome.updated_count

        points_by_name: dict[str, Mapping[str, Any]] = {}
        for point in points:
            if not isinstance(point, Mapping):
                continue
            raw_name = point.get("name") or point.get("dataPointName")
            if isinstance(raw_name, str) and raw_name.strip():
                points_by_name[raw_name.strip()] = point
        grouped: dict[str, tuple[GoogleSourceIdentity, list[Any]]] = {}
        for record in result.records:
            point = points_by_name.get(record.external_record_id or "")
            record_identity = source_identity_from_point(point, query)
            bucket = grouped.setdefault(record_identity.source_instance_id, (record_identity, []))
            bucket[1].append(record)

        inserted = 0
        updated = 0
        with factory() as session:
            repo = google_persistence_for(session, payload_store=store)
            for record_identity, records in grouped.values():
                grouped_result = replace(
                    result, records=tuple(records), source_identity=record_identity
                )
                outcome = repo.persist_result(
                    grouped_result,
                    identity=record_identity,
                    payload=payload,
                    source_window_start_utc=window_start,
                    source_window_end_utc=window_end,
                    sync_run_id=sync_run_id,
                )
                inserted += outcome.inserted_count
                updated += outcome.updated_count
            session.commit()
        return inserted, updated

    def _persist_terminal(
        self,
        factory,
        store: ContentAddressedGooglePayloadStore,
        *,
        identity: GoogleSourceIdentity,
        query: GoogleQueryContext,
        surface: GoogleSyncSurface,
        payload: RawGooglePayload,
        parse_invalid: bool,
        window_start: datetime,
        window_end: datetime,
        sync_run_id: str,
        records: Sequence[Any],
    ) -> None:
        from healthcheck.db.models import GooglePayloadStatus

        media_type = "application/json"
        payload_format = "json"
        if isinstance(payload, (bytes, bytearray)):
            media_type = "application/octet-stream"
            payload_format = "binary"
        with factory() as session:
            repo = google_persistence_for(session, payload_store=store)
            repo.persist_observation(
                identity=identity,
                query=query,
                stream=surface.stream,
                payload=payload,
                records=records,
                parse_status=(
                    GooglePayloadStatus.INVALID if parse_invalid else GooglePayloadStatus.PARTIAL
                ),
                media_type=media_type,
                payload_format=payload_format,
                source_window_start_utc=window_start,
                source_window_end_utc=window_end,
                sync_run_id=sync_run_id,
            )
            session.commit()

    def _incomplete_cursor(
        self, page_token: str | None, window_start: date, window_end_exclusive: date
    ) -> str | None:
        if self.run_kind is GoogleRunKind.REFRESH:
            return None
        return self._cursor_payload(page_token, window_start, window_end_exclusive)

    def _resume_cursor_flag(self, page_token: str | None) -> bool:
        if self.run_kind is GoogleRunKind.REFRESH:
            return False
        return bool(page_token)

    def _stream_watermark_window(
        self,
        factory,
        *,
        provider_id: str,
        state_code: str,
        as_of: date,
    ) -> tuple[date, date]:
        exclusive_end = as_of + timedelta(days=1)
        first_start = exclusive_end - timedelta(days=DEFAULT_FIRST_RUN_LOOKBACK_DAYS)
        with factory() as session:
            state = session.scalar(
                select(SyncStreamState).where(
                    SyncStreamState.provider_id == provider_id,
                    SyncStreamState.acquisition_source_id.is_(None),
                    SyncStreamState.stream_code == state_code,
                )
            )
            if state is None or state.watermark is None:
                return first_start, exclusive_end
            watermark = restore_stored_utc(state.watermark).date()
        if watermark >= exclusive_end:
            return first_start, exclusive_end
        return watermark, exclusive_end

    def _completed_coverage(
        self,
        factory,
        *,
        provider_id: str,
        state_code: str,
        window_start: datetime,
        window_end: datetime,
    ) -> str | None:
        with factory() as session:
            rows = repositories_for(session).coverage.list(
                provider_id=provider_id,
                stream_code=state_code,
                metric_code=COVERAGE_METRIC,
                interval_start=window_start,
                interval_end=window_end,
            )
            for row in rows:
                start = restore_stored_utc(row.interval_start)
                end = restore_stored_utc(row.interval_end)
                if (
                    start == window_start
                    and end == window_end
                    and row.resolution == COVERAGE_RESOLUTION
                    and row.calculation_rule_version == COVERAGE_RULE_VERSION
                    and row.status in {"present", "confirmed_empty"}
                ):
                    return row.status
        return None

    def _resume_token(
        self,
        factory,
        *,
        provider_id: str,
        state_code: str,
        window_start: date,
        window_end_exclusive: date,
    ) -> str | None:
        with factory() as session:
            state = session.scalar(
                select(SyncStreamState).where(
                    SyncStreamState.provider_id == provider_id,
                    SyncStreamState.acquisition_source_id.is_(None),
                    SyncStreamState.stream_code == state_code,
                )
            )
            if state is None or not state.cursor:
                return None
            try:
                payload = json.loads(state.cursor)
            except json.JSONDecodeError:
                return None
            if not isinstance(payload, Mapping):
                return None
            if payload.get("window_start") != window_start.isoformat():
                return None
            if payload.get("window_end_exclusive") != window_end_exclusive.isoformat():
                return None
            token = payload.get("page_token")
            if isinstance(token, str) and token.strip():
                return token.strip()
        return None

    def _cursor_payload(
        self, page_token: str | None, window_start: date, window_end_exclusive: date
    ) -> str | None:
        if not page_token:
            return json.dumps(
                {
                    "window_start": window_start.isoformat(),
                    "window_end_exclusive": window_end_exclusive.isoformat(),
                    "page_token": None,
                },
                sort_keys=True,
            )
        return json.dumps(
            {
                "window_start": window_start.isoformat(),
                "window_end_exclusive": window_end_exclusive.isoformat(),
                "page_token": page_token,
            },
            sort_keys=True,
        )

    def _write_checkpoint(
        self,
        factory,
        *,
        provider_id: str,
        state_code: str,
        window_start: datetime,
        window_end: datetime,
        coverage_status: str,
        complete: bool,
        observed_count: int | None,
        cursor: str | None,
        watermark: datetime | None = None,
    ) -> None:
        now = self.clock()
        with factory() as session:
            provenance = repositories_for(session)
            if complete and coverage_status in {"present", "confirmed_empty"}:
                provenance.coverage.record(
                    provider_id=provider_id,
                    stream_code=state_code,
                    metric_code=COVERAGE_METRIC,
                    interval_start=window_start,
                    interval_end=window_end,
                    resolution=COVERAGE_RESOLUTION,
                    status=coverage_status,
                    calculation_rule_version=COVERAGE_RULE_VERSION,
                    observed_count=observed_count,
                )
            elif coverage_status in {"failed", "unknown", "unavailable"}:
                provenance.coverage.record(
                    provider_id=provider_id,
                    stream_code=state_code,
                    metric_code=COVERAGE_METRIC,
                    interval_start=window_start,
                    interval_end=window_end,
                    resolution=COVERAGE_RESOLUTION,
                    status=coverage_status,
                    calculation_rule_version=COVERAGE_RULE_VERSION,
                    observed_count=observed_count if coverage_status != "failed" else None,
                    diagnostic_reason=coverage_status,
                )
            state = session.scalar(
                select(SyncStreamState).where(
                    SyncStreamState.provider_id == provider_id,
                    SyncStreamState.acquisition_source_id.is_(None),
                    SyncStreamState.stream_code == state_code,
                )
            )
            if state is None:
                state = provenance.sync.get_or_create_state(
                    provider_id=provider_id,
                    stream_code=state_code,
                    last_attempt_at=now,
                    diagnostic_status=coverage_status,
                )
            state.last_attempt_at = now
            state.diagnostic_status = coverage_status
            if complete and coverage_status in {"present", "confirmed_empty"}:
                state.last_success_at = now
                state.cursor = None
                if watermark is not None:
                    previous = restore_stored_utc(state.watermark) if state.watermark else None
                    if previous is None or watermark >= previous:
                        state.watermark = watermark
            else:
                if cursor is not None:
                    state.cursor = cursor
            state.updated_at = now
            session.commit()


def request_used_page_token(url: str) -> str | None:
    """Test helper: extract pageToken from a request URL without logging it."""

    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("pageToken")
    if not values:
        return None
    token = values[0]
    return token or None


def run_google_incremental_sync(
    settings: Settings,
    *,
    auth_service: GoogleAuthService | None = None,
    transport: GoogleHttpTransport | None = None,
    auth_result: GoogleAuthResult | None = None,
    access_token: str | None = None,
    granted_scopes: frozenset[str] | None = None,
    as_of: date | str | None = None,
    start: date | str | None = None,
    end: date | str | None = None,
    streams: Sequence[str] | None = None,
    query_mode: str | GoogleQueryMode | None = None,
    data_source_family: str | None = None,
    max_provider_requests: int = MAX_SYNC_PROVIDER_REQUESTS,
    sleeper: Callable[[float], None] | None = None,
) -> GoogleSyncReport:
    return GoogleHealthSync(
        settings,
        auth_service=auth_service,
        transport=transport,
        auth_result=auth_result,
        access_token=access_token,
        granted_scopes=granted_scopes,
        sleeper=sleeper,
        max_provider_requests=max_provider_requests,
        run_kind=GoogleRunKind.INCREMENTAL,
    ).run(
        as_of=as_of,
        start=start,
        end=end,
        streams=streams,
        query_mode=query_mode,
        data_source_family=data_source_family,
    )


def run_google_refresh(
    settings: Settings,
    *,
    start: date | str,
    end: date | str,
    auth_service: GoogleAuthService | None = None,
    transport: GoogleHttpTransport | None = None,
    auth_result: GoogleAuthResult | None = None,
    access_token: str | None = None,
    granted_scopes: frozenset[str] | None = None,
    streams: Sequence[str] | None = None,
    query_mode: str | GoogleQueryMode | None = None,
    data_source_family: str | None = None,
    max_provider_requests: int = MAX_SYNC_PROVIDER_REQUESTS,
    sleeper: Callable[[float], None] | None = None,
) -> GoogleSyncReport:
    start_date, end_inclusive = validate_inclusive_window(start, end)
    return GoogleHealthSync(
        settings,
        auth_service=auth_service,
        transport=transport,
        auth_result=auth_result,
        access_token=access_token,
        granted_scopes=granted_scopes,
        sleeper=sleeper,
        max_provider_requests=max_provider_requests,
        run_kind=GoogleRunKind.REFRESH,
    ).run_window(
        start=start_date,
        end_exclusive=inclusive_to_exclusive_end(end_inclusive),
        streams=streams,
        query_mode=query_mode,
        data_source_family=data_source_family,
        skip_complete=False,
    )


__all__ = [
    "COVERAGE_RULE_VERSION",
    "DEFAULT_FIRST_RUN_LOOKBACK_DAYS",
    "DEFAULT_PAGE_SIZE",
    "HEART_RATE_ROLLUP_MAX_DAYS",
    "HISTORICAL_NAMESPACE",
    "INCREMENTAL_NAMESPACE",
    "MAX_PAGES_PER_FETCH",
    "MAX_RETRY_ATTEMPTS",
    "MAX_SYNC_PROVIDER_REQUESTS",
    "PRODUCTION_SYNC_SURFACES",
    "REFRESH_NAMESPACE",
    "RETRY_BACKOFF_SECONDS",
    "SLEEP_PAGE_SIZE",
    "SYNC_CONTRACT_VERSION",
    "UNATTRIBUTED_SOURCE_INSTANCE",
    "GoogleHealthSync",
    "GoogleRunKind",
    "GoogleSyncAttempt",
    "GoogleSyncReport",
    "GoogleSyncStatus",
    "GoogleSyncSurface",
    "checkpoint_stream_code",
    "inclusive_to_exclusive_end",
    "identities_from_points",
    "query_level_source_identity",
    "source_identity_from_point",
    "parse_data_source_family",
    "parse_google_streams",
    "parse_page_envelope",
    "parse_query_mode",
    "run_google_incremental_sync",
    "run_google_refresh",
    "validate_inclusive_window",
    "validate_sync_date",
]
