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
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from numbers import Real
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
from healthcheck.db.models import GarminSource, GarminSourceRecord, SyncStreamState
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
    CapabilityStatus,
    GarminStream,
    get_capability,
)
from healthcheck.garmin.contracts import is_forbidden_payload_key
from healthcheck.garmin.normalization import (
    PROVIDER_SOURCE_KIND,
    GarminFieldState,
    GarminMetricDTO,
    GarminNormalizationResult,
    GarminParseStatus,
    GarminRecordDTO,
    GarminSourceIdentity,
    GarminTemporalDTO,
    GarminTemporalPrecision,
    garmin_source_identity,
    normalize_garmin_payload,
    stable_garmin_reconciliation_key,
)
from healthcheck.garmin.persistence import (
    GARMIN_COVERAGE_RULE_VERSION,
    PROJECTION_CURRENT,
    RECONCILIATION_CONTRACT_VERSION,
    GarminCollectionScope,
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

# Expected typed metric for checkpoint success. daily_summary is structural.
SURFACE_EXPECTED_METRICS: dict[str, tuple[str, ...]] = {
    "daily_summary": (),
    "sleep": ("sleep_duration_seconds",),
    "heart_rate": ("heart_rate_bpm",),
    "resting_heart_rate": ("resting_heart_rate_bpm",),
    "hrv_status": ("hrv_weekly_average_ms",),
    "stress": ("stress",),
    "body_battery": ("body_battery",),
    "spo2": ("spo2_percent",),
    "respiration": ("respiration_bpm",),
    "activities": ("duration_seconds",),
}
_SERIES_FIELDS: dict[str, tuple[str, ...]] = {
    "heart_rate": ("heartRateValues", "heartRateValue"),
    "stress": ("stressValuesArray", "stressValues"),
    "body_battery": ("bodyBatteryValuesArray",),
    "spo2": ("spo2Values",),
    "respiration": ("respirationValues",),
}
_SERIES_SCALAR_ALIASES: dict[str, str] = {
    "heart_rate": "heartRate",
    "stress": "stress",
    "body_battery": "bodyBattery",
    "spo2": "spo2",
    "respiration": "respiration",
}
_SERIES_METRIC: dict[str, tuple[str, str, str]] = {
    "heart_rate": ("heart_rate", "heart_rate_bpm", "bpm"),
    "stress": ("stress", "stress", "points"),
    "body_battery": ("body_battery", "body_battery", "points"),
    "spo2": ("spo2", "spo2_percent", "%"),
    "respiration": ("respiration", "respiration_bpm", "breaths/min"),
}
_BODY_BATTERY_TIME_DESCRIPTOR_NAMES = (
    "millis",
    "timestamp",
    "time",
    "startgmt",
    "starttimestampgmt",
)
_BODY_BATTERY_LEVEL_DESCRIPTOR_NAMES = (
    "bodybatterylevel",
    "bodybattery",
    "level",
    "value",
)


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
    skipped: bool = False
    failure_stage: str | None = None

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
        if self.skipped:
            payload["skipped"] = True
        if self.failure_stage is not None:
            payload["failure_stage"] = self.failure_stage
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
    """Keep the incremental window bounded; historical backfill is a separate command."""

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
            source_kind=PROVIDER_SOURCE_KIND,
            device_attributed=True,
            device_code=VIVOACTIVE_5_DEVICE_CODE,
            device_model=VIVOACTIVE_5_MODEL,
        )
    return garmin_source_identity(source_kind=PROVIDER_SOURCE_KIND, device_attributed=False)


def _normalize_provider_payload(
    surface: GarminSyncSurface, payload: Any, *, day: date | None = None
) -> Any:
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
        item = _body_battery_item(payload, day=day)
        if not item:
            return {}
        return _adapt_known_provider_shape(surface, _raw_mapping_for_normalize(item))
    if isinstance(payload, Mapping):
        return _adapt_known_provider_shape(surface, _raw_mapping_for_normalize(payload))
    return payload


def _body_battery_item(payload: Any, day: date | None) -> Mapping[str, Any]:
    if _classify_body_battery_payload(payload, day) != "matched":
        return {}
    if isinstance(payload, Mapping):
        return payload
    items = [item for item in payload if isinstance(item, Mapping)] if _is_sequence(payload) else []
    if day is None:
        return items[0] if items else {}
    for item in items:
        if _mapping_calendar_date(item) == day:
            return item
    return {}


def _classify_body_battery_payload(payload: Any, day: date | None) -> str:
    if payload is None:
        return "empty"
    if isinstance(payload, Mapping):
        return "matched"
    if not _is_sequence(payload):
        return "shape_drift"
    items = [item for item in payload if isinstance(item, Mapping)]
    if not items:
        return "empty"
    if day is None:
        return "matched"
    dated = False
    for item in items:
        item_day = _mapping_calendar_date(item)
        if item_day is None:
            continue
        dated = True
        if item_day == day:
            return "matched"
    if dated:
        return "no_matching_day"
    return "undated"


def _mapping_calendar_date(item: Mapping[str, Any]) -> date | None:
    for key in ("calendarDate", "date"):
        parsed = _parse_calendar_day(item.get(key))
        if parsed is not None:
            return parsed
    return None


def _parse_calendar_day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if len(text) >= 10 and _DATE_RE.fullmatch(text[:10]):
            if len(text) == 10 or text[10] in {"T", " ", "t"}:
                try:
                    return date.fromisoformat(text[:10])
                except ValueError:
                    return None
    return None


def _adapt_known_provider_shape(
    surface: GarminSyncSurface, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Copy reviewed #36 series/summary leaves onto the #29 scalar aliases."""

    adapted = dict(payload)
    if surface.code == "body_battery":
        if "calendarDate" not in adapted and "date" in adapted:
            parsed_day = _parse_calendar_day(adapted["date"])
            adapted["calendarDate"] = (
                parsed_day.isoformat() if parsed_day is not None else adapted["date"]
            )
        if "startTimeGMT" not in adapted and "startTimestampGMT" in adapted:
            adapted["startTimeGMT"] = adapted["startTimestampGMT"]
        if "startTimeLocal" not in adapted and "startTimestampLocal" in adapted:
            adapted["startTimeLocal"] = adapted["startTimestampLocal"]
    if surface.code == "stress" and "stress" not in adapted:
        for key in ("avgStressLevel", "maxStressLevel"):
            value = adapted.get(key)
            if _is_finite_number(value):
                adapted["stress"] = value
                break
    if surface.code == "spo2" and "spo2" not in adapted:
        for key in ("averageSpO2", "lastSevenDaysAvgSpO2"):
            value = adapted.get(key)
            if _is_finite_number(value):
                adapted["spo2"] = value
                break
    if surface.code == "respiration" and "respiration" not in adapted:
        value = adapted.get("avgSleepRespirationValue")
        if _is_finite_number(value):
            adapted["respiration"] = value
    alias = _SERIES_SCALAR_ALIASES.get(surface.code)
    if alias is not None and alias not in adapted:
        scalar = _summary_scalar(surface.code, adapted)
        if scalar is not None:
            adapted[alias] = scalar
    return adapted


def _summary_scalar(surface_code: str, payload: Mapping[str, Any]) -> int | float | None:
    samples = _series_samples(
        payload, _SERIES_FIELDS.get(surface_code, ()), surface_code=surface_code
    )
    if not samples:
        return None
    return samples[-1][2]


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, Real):
        return False
    if isinstance(value, float) and (value != value or value in {float("inf"), float("-inf")}):
        return False
    return True


def _series_samples(
    payload: Mapping[str, Any],
    keys: Sequence[str],
    *,
    surface_code: str | None = None,
) -> tuple[tuple[int, Any, int | float], ...]:
    descriptors = _series_descriptors(payload) if surface_code == "body_battery" else {}
    for key in keys:
        raw = payload.get(key)
        samples = _parse_series(raw, descriptors=descriptors)
        if samples:
            return samples
    return ()


def _series_descriptors(payload: Mapping[str, Any]) -> dict[str, int]:
    raw = payload.get("bodyBatteryValueDescriptorDTOList")
    if not _is_sequence(raw):
        return {}
    indices: dict[str, int] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        index = item.get("index", item.get("bodyBatteryValueDescriptorIndex"))
        key = item.get("key", item.get("bodyBatteryValueDescriptorKey"))
        if isinstance(index, bool) or not isinstance(index, int) or not isinstance(key, str):
            continue
        normalized = key.strip().lower()
        if normalized:
            indices[normalized] = index
    return indices


def _descriptor_index(descriptors: Mapping[str, int], names: Sequence[str]) -> int | None:
    for name in names:
        if name in descriptors:
            return descriptors[name]
    return None


def _parse_series(
    raw: Any, *, descriptors: Mapping[str, int] | None = None
) -> tuple[tuple[int, Any, int | float], ...]:
    if not _is_sequence(raw):
        if _is_finite_number(raw):
            return ((0, None, raw),)
        return ()
    samples: list[tuple[int, Any, int | float]] = []
    for index, item in enumerate(raw):
        stamp, value = _series_item_stamp_value(item, descriptors or {})
        if _is_finite_number(value):
            samples.append((index, stamp, value))
    return tuple(samples)


def _series_item_stamp_value(
    item: Any, descriptors: Mapping[str, int]
) -> tuple[Any, Any]:
    if _is_sequence(item) and len(item) >= 2:
        time_index = _descriptor_index(descriptors, _BODY_BATTERY_TIME_DESCRIPTOR_NAMES)
        level_index = _descriptor_index(descriptors, _BODY_BATTERY_LEVEL_DESCRIPTOR_NAMES)
        stamp = item[time_index] if time_index is not None and time_index < len(item) else item[0]
        if level_index is not None and level_index < len(item):
            value = item[level_index]
        else:
            value = item[1]
            if len(item) >= 3 and (
                isinstance(value, bool)
                or (
                    _is_finite_number(value)
                    and value in {0, 1}
                    and _is_finite_number(item[2])
                    and 0 <= float(item[2]) <= 100
                )
            ):
                value = item[2]
            elif not _is_finite_number(value):
                value = next(
                    (candidate for candidate in item[1:] if _is_finite_number(candidate)),
                    value,
                )
        return stamp, value
    if isinstance(item, Mapping):
        stamp = (
            item.get("timestamp")
            or item.get("startGMT")
            or item.get("time")
            or item.get("millis")
        )
        value = item.get("value")
        if value is None:
            for key in (
                "bodyBatteryLevel",
                "bodyBattery",
                "heartRate",
                "stress",
                "spo2",
                "respiration",
            ):
                if key in item:
                    value = item[key]
                    break
        return stamp, value
    if _is_finite_number(item):
        return None, item
    return None, None


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
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if is_forbidden_payload_key(key):
                raise ValueError("private or credential-shaped payload key is not accepted")
            _reject_private_keys(nested)
    elif _is_sequence(value):
        for nested in value:
            _reject_private_keys(nested)


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, Mapping))


def _prepare_normalization_result(
    surface: GarminSyncSurface,
    payload: Any,
    result: GarminNormalizationResult,
    *,
    day: date | None,
) -> GarminNormalizationResult:
    if isinstance(payload, Mapping):
        mapping = payload
    else:
        mapped = _normalize_provider_payload(surface, payload, day=day)
        mapping = mapped if isinstance(mapped, Mapping) else {}
    if not isinstance(mapping, Mapping):
        mapping = {}
    sample_records = _series_records(surface, mapping, result, day=day)
    records = [_reconcile_record(surface, item) for item in (*result.records, *sample_records)]
    status = result.status
    if sample_records and status in {GarminParseStatus.EMPTY, GarminParseStatus.INVALID}:
        status = GarminParseStatus.OK
    elif sample_records and status is GarminParseStatus.PARTIAL:
        if _has_expected_metric(surface, records, mapping):
            status = GarminParseStatus.OK
    return replace(result, records=tuple(records), status=status)


def _reconcile_record(surface: GarminSyncSurface, record: GarminRecordDTO) -> GarminRecordDTO:
    sample_token = record.sample_token or _temporal_sample_token(record.temporal)
    return replace(
        record,
        sample_token=sample_token,
        idempotency_key=stable_garmin_reconciliation_key(
            record.source,
            record.stream,
            surface=surface.code,
            temporal=record.temporal,
            record_id=record.record_id,
            sample_token=sample_token,
            sample_index=None if sample_token or record.record_id else record.record_index,
        ),
    )


def _series_records(
    surface: GarminSyncSurface,
    payload: Mapping[str, Any],
    result: GarminNormalizationResult,
    *,
    day: date | None,
) -> tuple[GarminRecordDTO, ...]:
    spec = _SERIES_METRIC.get(surface.code)
    if spec is None or result.source is None:
        return ()
    samples = _series_samples(
        payload, _SERIES_FIELDS.get(surface.code, ()), surface_code=surface.code
    )
    if not samples:
        return ()
    capability_code, metric_code, unit = spec
    try:
        capability_status = get_capability(capability_code).audit_status
    except KeyError:
        capability_status = CapabilityStatus.UNVERIFIED
    series_key = next(
        (key for key in _SERIES_FIELDS.get(surface.code, ()) if _is_sequence(payload.get(key))),
        _SERIES_FIELDS[surface.code][0],
    )
    records: list[GarminRecordDTO] = []
    for index, stamp, value in samples:
        parent_temporal = result.records[0].temporal if result.records else None
        temporal = _sample_temporal(stamp, day=day, fallback=parent_temporal)
        metric = GarminMetricDTO(
            capability_code=capability_code,
            metric_code=metric_code,
            field_path=f"payload.{series_key}",
            state=GarminFieldState.VALUE,
            value=value,
            unit=unit,
            capability_status=capability_status,
            source_device_attributed=result.source.device_attributed,
        )
        records.append(
            GarminRecordDTO(
                stream=surface.stream,
                source=result.source,
                temporal=temporal,
                sample_token=_sample_token(stamp),
                idempotency_key=stable_garmin_reconciliation_key(
                    result.source,
                    surface.stream,
                    surface=surface.code,
                    temporal=temporal,
                    sample_token=_sample_token(stamp),
                    sample_index=None if _sample_token(stamp) else index,
                ),
                record_index=index,
                metrics=(metric,),
                status=GarminParseStatus.OK,
                source_path=f"payload.{series_key}[{index}]",
            )
        )
    return tuple(records)


def _sample_token(stamp: Any) -> str | None:
    if stamp is None:
        return None
    if isinstance(stamp, datetime):
        measured = stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=UTC)
        return f"stamp:{measured.astimezone(UTC).isoformat()}"
    if isinstance(stamp, str):
        text = stamp.strip()
        return f"stamp:{text}" if text else None
    if isinstance(stamp, Real) and not isinstance(stamp, bool):
        return f"stamp:{stamp}"
    return None


def _temporal_sample_token(temporal: GarminTemporalDTO | None) -> str | None:
    if temporal is None or temporal.measured_at_utc is None:
        return None
    return f"stamp:{temporal.measured_at_utc.astimezone(UTC).isoformat()}"


def _collection_scope(
    surface: GarminSyncSurface,
    *,
    day: date | None,
    window_start: date,
    window_end: date,
    fetch_complete: bool,
    coverage_status: str,
) -> GarminCollectionScope:
    prefixes = tuple(f"payload.{name}" for name in _SERIES_FIELDS.get(surface.code, ()))
    if surface.code == "activities":
        kind = "activity_window"
        start, end = window_start, window_end
    elif prefixes:
        kind = "day_series"
        start = end = day or window_end
    else:
        kind = "day_singleton"
        start = end = day or window_end
    return GarminCollectionScope(
        surface=surface.code,
        stream=surface.stream.value,
        kind=kind,
        window_start=start,
        window_end=end,
        complete=fetch_complete and coverage_status in {"present", "confirmed_empty"},
        source_path_prefixes=prefixes,
    )


def _sample_temporal(
    stamp: Any, *, day: date | None, fallback: GarminTemporalDTO | None
) -> GarminTemporalDTO:
    if isinstance(stamp, datetime):
        measured = stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=UTC)
        return GarminTemporalDTO(
            precision=GarminTemporalPrecision.UTC_INSTANT,
            measured_at_utc=measured.astimezone(UTC),
            local_date=day or measured.astimezone(UTC).date(),
            source_field="payload.series",
        )
    if isinstance(stamp, str):
        text = stamp.strip()
        try:
            iso = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
            parsed = datetime.fromisoformat(iso)
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return GarminTemporalDTO(
                precision=GarminTemporalPrecision.UTC_INSTANT,
                measured_at_utc=parsed.astimezone(UTC),
                local_date=day or parsed.astimezone(UTC).date(),
                source_field="payload.series",
                source_local_timestamp=text if parsed.tzinfo is None else None,
            )
    if isinstance(stamp, Real) and not isinstance(stamp, bool) and stamp >= 1_000_000_000:
        seconds = float(stamp) / 1000.0 if stamp >= 1_000_000_000_000 else float(stamp)
        measured = datetime.fromtimestamp(seconds, tz=UTC)
        return GarminTemporalDTO(
            precision=GarminTemporalPrecision.UTC_INSTANT,
            measured_at_utc=measured,
            local_date=day or measured.date(),
            source_field="payload.series",
        )
    if day is not None:
        return GarminTemporalDTO(
            precision=GarminTemporalPrecision.DATE_ONLY,
            local_date=day,
            local_date_source="calendarDate",
        )
    if fallback is not None:
        return fallback
    return GarminTemporalDTO(precision=GarminTemporalPrecision.UNKNOWN)


def _has_expected_metric(
    surface: GarminSyncSurface,
    records: Sequence[GarminRecordDTO],
    payload: Any,
) -> bool:
    expected = SURFACE_EXPECTED_METRICS.get(surface.code)
    if expected is None:
        return False
    if not expected:
        return _structural_summary_present(payload)
    for record in records:
        for code in expected:
            metric = record.metric(code)
            if metric is not None and metric.has_value:
                return True
    return False


def _structural_summary_present(payload: Any) -> bool:
    if not isinstance(payload, Mapping) or not payload:
        return False
    return any(key in payload for key in ("calendarDate", "userActivitySummary"))


def _coverage_status_for(
    surface: GarminSyncSurface,
    result: GarminNormalizationResult,
    payload: Any,
    *,
    day: date | None = None,
) -> str:
    if surface.code == "body_battery" and _is_sequence(payload):
        attribution = _classify_body_battery_payload(payload, day)
        if attribution == "empty":
            return "confirmed_empty"
        if attribution in {"no_matching_day", "undated", "shape_drift"}:
            return "unknown"
    if result.status is GarminParseStatus.INVALID and not result.records:
        return "failed"
    if _explicit_empty_series(surface, payload, day=day) and not _has_expected_metric(
        surface, result.records, payload
    ):
        return "confirmed_empty"
    if result.status is GarminParseStatus.EMPTY and not result.records:
        return "confirmed_empty"
    if not result.records:
        return "confirmed_empty"
    if _has_expected_metric(surface, result.records, payload):
        return "present"
    if _reviewed_empty_provider_shell(surface, payload, result):
        return "confirmed_empty"
    return "unknown"


def _explicit_empty_series(
    surface: GarminSyncSurface, payload: Any, *, day: date | None
) -> bool:
    keys = _SERIES_FIELDS.get(surface.code)
    if not keys:
        return False
    mapping = _normalize_provider_payload(surface, payload, day=day)
    if not isinstance(mapping, Mapping):
        return False
    if surface.code == "body_battery" and _reviewed_empty_body_battery_levels(mapping):
        return True
    seen = False
    for key in keys:
        if key not in mapping:
            continue
        seen = True
        raw = mapping[key]
        if not _is_reviewed_empty_series_field(surface, raw):
            return False
    return seen


def _is_reviewed_empty_series_field(surface: GarminSyncSurface, raw: Any) -> bool:
    if _is_sequence(raw) and len(raw) == 0:
        return True
    # Reviewed live empty HR is `heartRateValues: null` as well as `[]`.
    return surface.code == "heart_rate" and raw is None


def _reviewed_empty_provider_shell(
    surface: GarminSyncSurface,
    payload: Any,
    result: GarminNormalizationResult,
) -> bool:
    """True only for the #59 reviewed sleep/respiration provider-empty shells."""

    if surface.code == "sleep":
        return _reviewed_empty_sleep_shell(surface, payload, result)
    if surface.code == "respiration":
        return _reviewed_empty_respiration_shell(surface, payload, result)
    return False


def _explicit_null(container: Mapping[str, Any], key: str) -> bool:
    return key in container and container[key] is None


def _reviewed_empty_sleep_shell(
    surface: GarminSyncSurface, payload: Any, result: GarminNormalizationResult
) -> bool:
    """Reviewed empty sleep: DTO object with explicit-null duration and nap, no data."""

    if not isinstance(payload, Mapping):
        return False
    dto = payload.get("dailySleepDTO")
    if not isinstance(dto, Mapping):
        return False
    if not _explicit_null(dto, "sleepTimeSeconds"):
        return False
    if not _explicit_null(dto, "napTimeSeconds"):
        return False
    if _recognized_sleep_duration_or_stage(result.records):
        return False
    return not _has_expected_metric(surface, result.records, payload)


def _recognized_sleep_duration_or_stage(records: Sequence[GarminRecordDTO]) -> bool:
    for record in records:
        duration = record.metric("sleep_duration_seconds")
        if duration is not None and duration.has_value:
            return True
        stages = record.metric("sleep_stages")
        if stages is not None and stages.has_value and stages.collection:
            return True
    return False


def _reviewed_empty_respiration_shell(
    surface: GarminSyncSurface, payload: Any, result: GarminNormalizationResult
) -> bool:
    """Reviewed empty respiration: null avg, no accepted scalars/series, no bpm."""

    if not isinstance(payload, Mapping):
        return False
    if not _explicit_null(payload, "avgSleepRespirationValue"):
        return False
    if "respiration" in payload or "respirationRate" in payload:
        return False
    if "respirationValues" in payload:
        return False
    if _series_samples(payload, ("respirationValues",), surface_code="respiration"):
        return False
    return not _has_expected_metric(surface, result.records, payload)


def _reviewed_empty_body_battery_levels(payload: Mapping[str, Any]) -> bool:
    """True only for matching-day BB with recognized time+level schema and all-null levels."""

    raw = payload.get("bodyBatteryValuesArray")
    if not _is_sequence(raw) or not raw:
        return False
    descriptors = _series_descriptors(payload)
    time_index = _descriptor_index(descriptors, _BODY_BATTERY_TIME_DESCRIPTOR_NAMES)
    level_index = _descriptor_index(descriptors, _BODY_BATTERY_LEVEL_DESCRIPTOR_NAMES)
    if time_index is None or level_index is None or time_index == level_index:
        return False
    for item in raw:
        if not _is_sequence(item):
            return False
        if time_index >= len(item) or level_index >= len(item):
            return False
        if item[level_index] is not None:
            return False
    return True


def _attempt_status_for(coverage_status: str) -> GarminSyncStatus:
    if coverage_status == "failed":
        return GarminSyncStatus.FAILED
    if coverage_status == "confirmed_empty":
        return GarminSyncStatus.EMPTY
    if coverage_status == "present":
        return GarminSyncStatus.SUCCEEDED
    if coverage_status == "unavailable":
        return GarminSyncStatus.UNAVAILABLE
    return GarminSyncStatus.PARTIAL


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
        run_stream: str = INCREMENTAL_RUN_STREAM,
        checkpoint_namespace: str | None = None,
        skip_complete_coverage: bool = False,
        reprocess_outdated: bool = False,
    ) -> None:
        self.settings = settings
        self.client = client
        self.auth_result = auth_result or GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.max_provider_requests = max_provider_requests
        self.run_stream = run_stream
        self.checkpoint_namespace = checkpoint_namespace
        self.skip_complete_coverage = skip_complete_coverage
        self.reprocess_outdated = reprocess_outdated
        if self.max_provider_requests < 1:
            raise ValueError("max_provider_requests must be positive")
        if self.max_provider_requests > MAX_SYNC_PROVIDER_REQUESTS:
            raise ValueError("max_provider_requests exceeds the hard incremental cap")

    def _state_stream_code(self, surface: GarminSyncSurface) -> str:
        if self.checkpoint_namespace:
            return f"{self.checkpoint_namespace}:{surface.code}"
        return surface.code

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
                stream_code=self.run_stream,
                requested_start=requested_start,
                requested_end=requested_end,
            )
            session.commit()
            sync_run_id = run.id
            provider_id = provider.id

        days = _calendar_days(window_start, window_end)
        attempts, abort_reason = self._ingest_window(
            factory,
            store,
            provider_id=provider_id,
            sync_run_id=sync_run_id,
            window_start=window_start,
            window_end=window_end,
            trailing_window_days=trailing_window_days,
            budget=budget,
            surfaces=PRODUCTION_SYNC_SURFACES,
            days=days,
        )

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
                    stream_code=self.run_stream,
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

    def _ingest_window(
        self,
        factory,
        store: ContentAddressedGarminPayloadStore,
        *,
        provider_id: str,
        sync_run_id: str,
        window_start: date,
        window_end: date,
        trailing_window_days: int,
        budget: _SyncBudget,
        surfaces: Sequence[GarminSyncSurface],
        days: Sequence[date],
    ) -> tuple[list[GarminSyncAttempt], str | None]:
        attempts: list[GarminSyncAttempt] = []
        abort_reason: str | None = None
        with _disable_provider_retries(self.client):
            for day in days:
                if abort_reason is not None:
                    break
                for surface in surfaces:
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
                activity_surface = next((item for item in surfaces if not item.per_day), None)
                if activity_surface is not None:
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
        return attempts, abort_reason

    def _completed_coverage_status(
        self,
        factory,
        *,
        provider_id: str,
        surface: GarminSyncSurface,
        window_start: date,
        window_end: date,
    ) -> str | None:
        interval_start, _ = _day_bounds(window_start)
        _, interval_end = _day_bounds(window_end)
        with factory() as session:
            rows = repositories_for(session).coverage.list(
                provider_id=provider_id,
                stream_code=surface.stream.value,
                metric_code=surface.code,
                interval_start=interval_start,
                interval_end=interval_end,
            )
        present = False
        empty = False
        for row in rows:
            start = restore_stored_utc(row.interval_start)
            end = restore_stored_utc(row.interval_end)
            if start != interval_start or end != interval_end or row.resolution != "day":
                continue
            if row.status == "present":
                present = True
            elif row.status == "confirmed_empty":
                empty = True
        if present:
            return "present"
        if empty:
            return "confirmed_empty"
        return None

    def _surface_reconciliation_is_current(
        self,
        factory,
        *,
        provider_id: str,
        surface: GarminSyncSurface,
        window_start: date,
        window_end: date,
    ) -> bool:
        with factory() as session:
            rows = list(
                session.scalars(
                    select(GarminSourceRecord)
                    .join(GarminSource, GarminSource.id == GarminSourceRecord.garmin_source_id)
                    .where(
                        GarminSource.provider_id == provider_id,
                        GarminSourceRecord.surface_code == surface.code,
                        GarminSourceRecord.projection_status == PROJECTION_CURRENT,
                        GarminSourceRecord.source_local_date >= window_start,
                        GarminSourceRecord.source_local_date <= window_end,
                    )
                )
            )
        if not rows:
            return False
        return all(
            row.reconciliation_contract_version == RECONCILIATION_CONTRACT_VERSION for row in rows
        )

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
        coverage_start = window_start if day is None else day
        coverage_end = window_end if day is None else day
        if self.skip_complete_coverage:
            completed = self._completed_coverage_status(
                factory,
                provider_id=provider_id,
                surface=surface,
                window_start=coverage_start,
                window_end=coverage_end,
            )
            if completed is not None and (
                not self.reprocess_outdated
                or completed != "present"
                or self._surface_reconciliation_is_current(
                    factory,
                    provider_id=provider_id,
                    surface=surface,
                    window_start=coverage_start,
                    window_end=coverage_end,
                )
            ):
                return GarminSyncAttempt(
                    surface=surface.code,
                    stream=surface.stream.value,
                    method=surface.method,
                    day=day.isoformat() if day is not None else None,
                    status=_attempt_status_for(completed),
                    coverage_status=completed,
                    replayed=True,
                    skipped=True,
                )
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

        fetched, error, request_count, fetch_complete = self._fetch(
            surface, day, window_start, window_end, budget
        )
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
                failure_stage="fetch",
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
                failure_stage="fetch",
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
            fetch_complete=fetch_complete,
        )

    def _fetch(
        self,
        surface: GarminSyncSurface,
        day: date | None,
        window_start: date,
        window_end: date,
        budget: _SyncBudget,
    ) -> tuple[Any, GarminSafeError | None, int, bool]:
        if surface.code == "activities":
            return self._fetch_activities(window_start, window_end, budget)
        if not budget.consume():
            return None, None, 0, False
        method = getattr(self.client, surface.method, None)
        if not callable(method):
            return None, GarminSafeError("runtime", "method_unavailable"), 1, False
        day_text = (day or window_end).isoformat()
        try:
            with _silence_provider_logging():
                if surface.code == "body_battery":
                    payload = method(day_text, day_text)
                else:
                    payload = method(day_text)
        except Exception as exc:
            return None, classify_garmin_error(exc), 1, False
        return payload, None, 1, True

    def _fetch_activities(
        self,
        window_start: date,
        window_end: date,
        budget: _SyncBudget,
    ) -> tuple[Any, GarminSafeError | None, int, bool]:
        endpoint = getattr(self.client, _ACTIVITY_ENDPOINT_ATTRIBUTE, None)
        connectapi = getattr(self.client, "connectapi", None)
        if endpoint != _ACTIVITY_ENDPOINT or not callable(connectapi):
            return None, GarminSafeError("runtime", "method_unavailable"), 0, False
        collected: list[Any] = []
        used = 0
        complete = True
        for page in range(MAX_ACTIVITY_PAGES):
            if not budget.consume():
                if used == 0:
                    return None, None, 0, False
                complete = False
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
                return None, classify_garmin_error(exc), used, False
            if page_payload is None:
                break
            if _is_sequence(page_payload):
                items = list(page_payload)
            elif isinstance(page_payload, Mapping) and _is_sequence(page_payload.get("activities")):
                items = list(page_payload["activities"])
            else:
                return page_payload, None, used, False
            collected.extend(items)
            if len(items) < ACTIVITY_PAGE_SIZE:
                break
            if page == MAX_ACTIVITY_PAGES - 1:
                complete = False
        return collected, None, used, complete

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
        fetch_complete: bool,
    ) -> GarminSyncAttempt:
        attribution = infer_device_attribution(payload).status
        identity = _source_identity_for(payload)
        normalized_payload = _normalize_provider_payload(surface, payload, day=day)
        window_start_utc, _ = _day_bounds(window_start)
        _, window_end_utc = _day_bounds(window_end)
        try:
            result = normalize_garmin_payload(
                normalized_payload,
                stream=surface.stream,
                source_identity=identity,
            )
            result = _prepare_normalization_result(surface, payload, result, day=day)
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
                failure_stage="normalization",
            )
        try:
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
                failure_stage="raw_payload_validation",
            )

        try:
            with factory() as session:
                persistence = GarminPersistenceRepository(session, payload_store=store)
                coverage_status = _coverage_status_for(surface, result, payload, day=day)
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
                    collection_scope=_collection_scope(
                        surface,
                        day=day,
                        window_start=window_start,
                        window_end=window_end,
                        fetch_complete=fetch_complete,
                        coverage_status=coverage_status,
                    ),
                )
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
                    status=_attempt_status_for(coverage_status),
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
                failure_stage="persistence",
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
        failure_stage: str,
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
            failure_stage=failure_stage,
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
                SyncStreamState.stream_code == self._state_stream_code(surface),
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
            stream_code=self._state_stream_code(surface),
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
    surfaces: Sequence[GarminSyncSurface] = PRODUCTION_SYNC_SURFACES,
) -> tuple[GarminSyncAttempt, ...]:
    seen = {(item.surface, item.day) for item in attempts}
    remainder: list[GarminSyncAttempt] = []
    for surface in surfaces:
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
