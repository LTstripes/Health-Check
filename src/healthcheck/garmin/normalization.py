"""Pure offline normalization for the synthetic R02 Garmin payload contract.

This module deliberately stops at an immutable DTO boundary.  It accepts the
synthetic envelope defined by :mod:`healthcheck.garmin.contracts`, projects the
small set of reviewed fixture shapes into typed records, and reports shape
drift as sanitized diagnostics.  It does not import a Garmin client, read
credentials, make HTTP calls, or persist anything.

Important semantics:

* ``calendarDate`` is a local date, not a UTC midnight instant;
* aware timestamps are normalized to UTC while retaining local wall-time
  evidence, explicit GMT/UTC fields define naive values as UTC, and genuinely
  local-only naive values retain no invented timezone;
* a missing field, JSON ``null``, and numeric zero have different states;
* source/device attribution is metadata and is never inferred from a client
  method, a field name, or an account-level value;
* stable idempotency keys use source identity plus stable record identity, with
  a semantic fallback only when a source record id is absent.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from numbers import Real
from typing import Any

from healthcheck.garmin.capabilities import (
    GARMIN_PROVIDER_CODE,
    CapabilityStatus,
    GarminStream,
    get_capability,
)
from healthcheck.garmin.contracts import (
    CAPABILITY_FIXTURE_CONTRACT_VERSION,
    GarminCapabilityFixture,
    GarminCapabilityFixtureError,
    is_forbidden_payload_key,
)

NORMALIZATION_CONTRACT_VERSION = "r02-garmin-normalization-contract-v1"
GARMIN_NORMALIZATION_CONTRACT_VERSION = NORMALIZATION_CONTRACT_VERSION
SYNTHETIC_SOURCE_KIND = "synthetic"
PROVIDER_SOURCE_KIND = "provider"
ALLOWED_SOURCE_KINDS = frozenset({SYNTHETIC_SOURCE_KIND, PROVIDER_SOURCE_KIND})

_MISSING = object()
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SAFE_TEXT_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]*$")


class GarminFieldState(StrEnum):
    """Presence state for one source field.

    ``VALUE`` includes an explicit numeric zero.  ``MISSING`` means that the
    path was absent, while ``NULL`` means that the path existed with JSON
    ``null``.  They are intentionally not collapsed.
    """

    MISSING = "missing"
    NULL = "null"
    VALUE = "value"
    PRESENT = "value"  # Readable compatibility alias for callers.
    INVALID = "invalid"


class GarminParseStatus(StrEnum):
    """Overall deterministic outcome of one offline parse."""

    OK = "ok"
    PARTIAL = "partial"
    EMPTY = "empty"
    INVALID = "invalid"


class GarminTemporalPrecision(StrEnum):
    """Precision carried by a Garmin temporal value."""

    UNKNOWN = "unknown"
    DATE_ONLY = "date"
    DATE = "date"  # Compatibility alias.
    UTC_INSTANT = "instant"
    INSTANT = "instant"  # Compatibility alias.
    LOCAL_WALL_TIME = "local"
    LOCAL = "local"  # Compatibility alias.


@dataclass(frozen=True, slots=True)
class GarminDiagnostic:
    """A stable, sanitized parser diagnostic.

    Diagnostics carry paths and contract reason codes, never raw values or a
    payload dump.  The messages are selected from a fixed vocabulary by the
    parser so malformed values cannot leak into logs or API responses.
    """

    code: str
    message: str
    path: str | None = None
    severity: str = "warning"

    def __post_init__(self) -> None:
        code = self.code.strip().lower()
        severity = self.severity.strip().lower()
        if not _SAFE_TEXT_RE.fullmatch(code):
            raise ValueError("diagnostic code must be a stable text token")
        if severity not in {"warning", "error"}:
            raise ValueError("diagnostic severity must be warning or error")
        if not self.message.strip():
            raise ValueError("diagnostic message is required")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "severity", severity)
        if self.path is not None:
            object.__setattr__(self, "path", self.path.strip() or None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class GarminSourceIdentity:
    """Provider/device identity used by downstream idempotency.

    Synthetic fixtures keep ``source_kind=synthetic``. Production Garmin API
    ingestion uses ``source_kind=provider``. Device attribution remains an
    explicit envelope/payload fact and is never inferred from a client method.
    """

    source_kind: str
    provider_code: str
    device_attributed: bool
    device_code: str | None = None
    device_model: str | None = None
    source_instance_id: str | None = None

    def __post_init__(self) -> None:
        source_kind = _required_text(self.source_kind, "source_kind").lower()
        provider_code = _required_text(self.provider_code, "provider_code").lower()
        if source_kind not in ALLOWED_SOURCE_KINDS:
            raise ValueError("Garmin source_kind must be synthetic or provider")
        if provider_code != GARMIN_PROVIDER_CODE:
            raise ValueError("source provider must be garmin_connect")
        if not isinstance(self.device_attributed, bool):
            raise ValueError("device_attributed must be boolean")
        device_code = _optional_text(self.device_code)
        device_model = _optional_text(self.device_model)
        if self.device_attributed and (device_code is None or device_model is None):
            raise ValueError("attributed source requires device code and model")
        if not self.device_attributed and (device_code is not None or device_model is not None):
            raise ValueError("unattributed source must not carry device identity")
        source_instance_id = _optional_text(self.source_instance_id)
        if source_instance_id is None:
            source_instance_id = _source_instance_id(
                source_kind=source_kind,
                provider_code=provider_code,
                device_attributed=self.device_attributed,
                device_code=device_code,
                device_model=device_model,
            )
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "provider_code", provider_code)
        object.__setattr__(self, "device_code", device_code)
        object.__setattr__(self, "device_model", device_model)
        object.__setattr__(self, "source_instance_id", source_instance_id)

    @classmethod
    def from_fixture(cls, fixture: GarminCapabilityFixture) -> GarminSourceIdentity:
        """Build identity from an already validated R02 fixture."""

        if not isinstance(fixture, GarminCapabilityFixture):
            raise TypeError("fixture must be GarminCapabilityFixture")
        return cls(
            source_kind=SYNTHETIC_SOURCE_KIND,
            provider_code=fixture.provider_code,
            device_attributed=fixture.device_attributed,
            device_code=fixture.device_code,
            device_model=fixture.device_model,
        )

    @property
    def device_evidence(self) -> bool:
        """Whether the envelope explicitly attributes data to a device."""

        return self.device_attributed

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "provider_code": self.provider_code,
            "source_instance_id": self.source_instance_id,
            "device": {
                "attributed": self.device_attributed,
                "code": self.device_code,
                "model": self.device_model,
            },
        }


def garmin_source_identity(
    *,
    provider_code: str = GARMIN_PROVIDER_CODE,
    device_attributed: bool = False,
    device_code: str | None = None,
    device_model: str | None = None,
    source_kind: str = SYNTHETIC_SOURCE_KIND,
) -> GarminSourceIdentity:
    """Create a validated Garmin source identity."""

    return GarminSourceIdentity(
        source_kind=source_kind,
        provider_code=provider_code,
        device_attributed=device_attributed,
        device_code=device_code,
        device_model=device_model,
    )


def garmin_source_instance_id(
    *,
    provider_code: str = GARMIN_PROVIDER_CODE,
    device_attributed: bool = False,
    device_code: str | None = None,
    device_model: str | None = None,
) -> str:
    """Return the stable source-instance id for synthetic source metadata."""

    identity = garmin_source_identity(
        provider_code=provider_code,
        device_attributed=device_attributed,
        device_code=device_code,
        device_model=device_model,
    )
    assert identity.source_instance_id is not None
    return identity.source_instance_id


@dataclass(frozen=True, slots=True)
class GarminTemporalDTO:
    """UTC/local/date-only temporal projection."""

    precision: GarminTemporalPrecision
    measured_at_utc: datetime | None = None
    local_wall_time: str | None = None
    local_date: date | None = None
    source_field: str | None = None
    local_date_source: str | None = None
    source_local_timestamp: str | None = None
    source_timezone: str | None = None
    source_utc_offset_minutes: int | None = None
    source_local_field: str | None = None
    source_utc_field: str | None = None

    def __post_init__(self) -> None:
        precision = GarminTemporalPrecision(self.precision)
        measured_at_utc = self.measured_at_utc
        if measured_at_utc is not None:
            if measured_at_utc.tzinfo is None or measured_at_utc.utcoffset() is None:
                raise ValueError("measured_at_utc must be timezone-aware")
            measured_at_utc = measured_at_utc.astimezone(UTC)
        if precision is GarminTemporalPrecision.DATE_ONLY and measured_at_utc is not None:
            raise ValueError("date-only temporal values must not carry a UTC instant")
        if precision is GarminTemporalPrecision.UTC_INSTANT and measured_at_utc is None:
            raise ValueError("instant temporal values require a UTC instant")
        if precision is GarminTemporalPrecision.LOCAL_WALL_TIME and not self.local_wall_time:
            raise ValueError("local temporal values require a wall time")
        source_utc_offset_minutes = self.source_utc_offset_minutes
        if source_utc_offset_minutes is not None and not isinstance(source_utc_offset_minutes, int):
            raise ValueError("source_utc_offset_minutes must be an integer")
        object.__setattr__(self, "precision", precision)
        object.__setattr__(self, "measured_at_utc", measured_at_utc)
        if self.local_wall_time is not None:
            object.__setattr__(self, "local_wall_time", self.local_wall_time.strip())
        if self.source_local_timestamp is not None:
            object.__setattr__(
                self, "source_local_timestamp", self.source_local_timestamp.strip() or None
            )
        if self.source_timezone is not None:
            object.__setattr__(self, "source_timezone", self.source_timezone.strip() or None)
        if self.source_field is not None:
            object.__setattr__(self, "source_field", self.source_field.strip() or None)
        if self.local_date_source is not None:
            object.__setattr__(self, "local_date_source", self.local_date_source.strip() or None)
        if self.source_local_field is not None:
            object.__setattr__(self, "source_local_field", self.source_local_field.strip() or None)
        if self.source_utc_field is not None:
            object.__setattr__(self, "source_utc_field", self.source_utc_field.strip() or None)

    @property
    def local_wall_time_with_offset(self) -> str | None:
        """Return the original local timestamp representation, if retained."""

        return self.source_local_timestamp

    @property
    def local_offset_minutes(self) -> int | None:
        """Readable alias for the source local UTC offset evidence."""

        return self.source_utc_offset_minutes

    @property
    def local_timezone(self) -> str | None:
        """Readable alias for the source timezone evidence."""

        return self.source_timezone

    @property
    def local_source_field(self) -> str | None:
        """Readable alias for the source local-time field path."""

        return self.source_local_field

    @property
    def utc_source_field(self) -> str | None:
        """Readable alias for the source UTC/GMT field path."""

        return self.source_utc_field

    def time_key(self) -> str:
        if self.measured_at_utc is not None:
            return self.measured_at_utc.isoformat()
        if self.local_wall_time is not None:
            return self.local_wall_time
        if self.local_date is not None:
            return self.local_date.isoformat()
        return "unknown-time"

    def as_dict(self) -> dict[str, Any]:
        return {
            "precision": self.precision.value,
            "measured_at_utc": (
                self.measured_at_utc.isoformat() if self.measured_at_utc is not None else None
            ),
            "local_wall_time": self.local_wall_time,
            "local_date": self.local_date.isoformat() if self.local_date is not None else None,
            "source_field": self.source_field,
            "local_date_source": self.local_date_source,
            "source_local_timestamp": self.source_local_timestamp,
            "source_timezone": self.source_timezone,
            "source_utc_offset_minutes": self.source_utc_offset_minutes,
            "source_local_field": self.source_local_field,
            "source_utc_field": self.source_utc_field,
        }


def parse_garmin_time(
    value: Any,
    *,
    calendar_date: Any = _MISSING,
    source_field: str | None = "time",
    field_semantics: str | None = None,
    source_timezone: str | None = None,
    source_utc_offset_minutes: int | None = None,
) -> GarminTemporalDTO:
    """Parse a Garmin ISO/date value without inventing timezone information.

    Invalid values produce an ``UNKNOWN`` DTO; the normalization entrypoint
    adds the corresponding typed diagnostic.  This small non-throwing helper
    is useful to offline callers that only need temporal projection.
    """

    parsed, _ = _parse_garmin_time(
        value,
        calendar_date=calendar_date,
        source_field=source_field,
        field_semantics=field_semantics,
        source_timezone=source_timezone,
        source_utc_offset_minutes=source_utc_offset_minutes,
    )
    return parsed


parse_garmin_timestamp = parse_garmin_time


@dataclass(frozen=True, slots=True)
class GarminSleepStageDTO:
    """One typed sleep-level interval."""

    start: GarminTemporalDTO
    end: GarminTemporalDTO
    activity_level: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.as_dict(),
            "end": self.end.as_dict(),
            "activity_level": self.activity_level,
        }


@dataclass(frozen=True, slots=True)
class GarminMetricDTO:
    """Typed field projection preserving source presence and capability status."""

    capability_code: str
    metric_code: str
    field_path: str
    state: GarminFieldState
    value: int | float | str | None = None
    unit: str | None = None
    reason: str | None = None
    capability_status: CapabilityStatus | None = None
    source_device_attributed: bool = False
    collection: tuple[GarminSleepStageDTO, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", GarminFieldState(self.state))
        if self.capability_status is not None:
            object.__setattr__(self, "capability_status", CapabilityStatus(self.capability_status))
        if not isinstance(self.source_device_attributed, bool):
            raise ValueError("source_device_attributed must be boolean")
        if not self.capability_code.strip() or not self.metric_code.strip():
            raise ValueError("Garmin metric codes are required")
        object.__setattr__(self, "capability_code", self.capability_code.strip())
        object.__setattr__(self, "metric_code", self.metric_code.strip())
        object.__setattr__(self, "field_path", self.field_path.strip())
        if self.unit is not None:
            object.__setattr__(self, "unit", self.unit.strip() or None)
        if self.reason is not None:
            object.__setattr__(self, "reason", self.reason.strip() or None)
        object.__setattr__(self, "collection", tuple(self.collection))

    @property
    def present(self) -> bool:
        return self.state is not GarminFieldState.MISSING

    @property
    def has_value(self) -> bool:
        return self.state is GarminFieldState.VALUE

    @property
    def is_null(self) -> bool:
        return self.state is GarminFieldState.NULL

    @property
    def is_zero(self) -> bool:
        return (
            self.has_value
            and isinstance(self.value, Real)
            and not isinstance(self.value, bool)
            and self.value == 0
        )

    @property
    def device_evidence(self) -> bool:
        """Whether this value may be described as target-device evidence."""

        return (
            self.has_value
            and self.source_device_attributed
            and self.capability_status
            in {
                CapabilityStatus.VERIFIED,
                CapabilityStatus.VERIFIED_CONDITIONAL,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability_code": self.capability_code,
            "metric_code": self.metric_code,
            "field_path": self.field_path,
            "state": self.state.value,
            "value": self.value,
            "unit": self.unit,
            "reason": self.reason,
            "capability_status": (
                self.capability_status.value if self.capability_status is not None else None
            ),
            "source_device_attributed": self.source_device_attributed,
            "device_evidence": self.device_evidence,
            "collection": [item.as_dict() for item in self.collection],
        }


@dataclass(frozen=True, slots=True)
class GarminUnknownFieldDTO:
    """Shape-drift evidence without retaining an untyped payload value."""

    path: str
    observed_shape: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "observed_shape": self.observed_shape}


@dataclass(frozen=True, slots=True)
class GarminRecordDTO:
    """One deterministic normalized Garmin source record."""

    stream: GarminStream
    source: GarminSourceIdentity
    temporal: GarminTemporalDTO
    idempotency_key: str
    record_id: str | None = None
    activity_type: str | None = None
    record_index: int | None = None
    metrics: tuple[GarminMetricDTO, ...] = ()
    unknown_fields: tuple[GarminUnknownFieldDTO, ...] = ()
    diagnostics: tuple[GarminDiagnostic, ...] = ()
    status: GarminParseStatus = GarminParseStatus.OK
    source_path: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream", GarminStream(self.stream))
        object.__setattr__(
            self,
            "metrics",
            tuple(sorted(self.metrics, key=lambda item: (item.metric_code, item.field_path))),
        )
        object.__setattr__(
            self,
            "unknown_fields",
            tuple(sorted(self.unknown_fields, key=lambda item: item.path)),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(sorted(self.diagnostics, key=_diagnostic_sort_key)),
        )
        object.__setattr__(self, "status", GarminParseStatus(self.status))

    @property
    def measured_at_utc(self) -> datetime | None:
        return self.temporal.measured_at_utc

    @property
    def local_date(self) -> date | None:
        return self.temporal.local_date

    def metric(self, code: str) -> GarminMetricDTO | None:
        """Find a metric by capability code or canonical metric code."""

        normalized = code.strip().lower()
        for item in self.metrics:
            if item.metric_code.lower() == normalized:
                return item
        for item in self.metrics:
            if item.capability_code.lower() == normalized:
                return item
        return None

    def metrics_for_capability(self, code: str) -> tuple[GarminMetricDTO, ...]:
        """Return all fields mapped to one R02 capability row."""

        normalized = code.strip().lower()
        return tuple(item for item in self.metrics if item.capability_code.lower() == normalized)

    def metric_codes(self) -> tuple[str, ...]:
        return tuple(item.metric_code for item in self.metrics if item.has_value)

    def present_metrics(self) -> tuple[GarminMetricDTO, ...]:
        return tuple(item for item in self.metrics if item.present)

    def usable_metrics(self) -> tuple[GarminMetricDTO, ...]:
        return tuple(item for item in self.metrics if item.has_value)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stream": self.stream.value,
            "source": self.source.as_dict(),
            "record_id": self.record_id,
            "activity_type": self.activity_type,
            "record_index": self.record_index,
            "temporal": self.temporal.as_dict(),
            "idempotency_key": self.idempotency_key,
            "metrics": [item.as_dict() for item in self.metrics],
            "unknown_fields": [item.as_dict() for item in self.unknown_fields],
            "diagnostics": [item.as_dict() for item in self.diagnostics],
            "status": self.status.value,
            "source_path": self.source_path,
        }


@dataclass(frozen=True, slots=True)
class GarminNormalizationResult:
    """Typed result for one synthetic Garmin envelope."""

    status: GarminParseStatus
    stream: GarminStream | None
    source: GarminSourceIdentity | None
    records: tuple[GarminRecordDTO, ...] = ()
    diagnostics: tuple[GarminDiagnostic, ...] = ()
    unknown_fields: tuple[GarminUnknownFieldDTO, ...] = ()
    fixture_id: str | None = None
    contract_version: str = NORMALIZATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.stream is not None:
            object.__setattr__(self, "stream", GarminStream(self.stream))
        object.__setattr__(self, "status", GarminParseStatus(self.status))
        object.__setattr__(
            self,
            "records",
            tuple(
                sorted(
                    self.records,
                    key=lambda item: (
                        item.idempotency_key,
                        item.record_id or "",
                        item.source_path or "",
                    ),
                )
            ),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(sorted(self.diagnostics, key=_diagnostic_sort_key)),
        )
        object.__setattr__(
            self,
            "unknown_fields",
            tuple(sorted(self.unknown_fields, key=lambda item: item.path)),
        )

    @property
    def ok(self) -> bool:
        return self.status is GarminParseStatus.OK

    @property
    def is_empty(self) -> bool:
        return self.status is GarminParseStatus.EMPTY

    @property
    def partial(self) -> bool:
        return self.status is GarminParseStatus.PARTIAL

    @property
    def idempotency_keys(self) -> tuple[str, ...]:
        return tuple(item.idempotency_key for item in self.records)

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "status": self.status.value,
            "stream": self.stream.value if self.stream is not None else None,
            "fixture_id": self.fixture_id,
            "source": self.source.as_dict() if self.source is not None else None,
            "records": [item.as_dict() for item in self.records],
            "unknown_fields": [item.as_dict() for item in self.unknown_fields],
            "diagnostics": [item.as_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class _ScalarSpec:
    capability_code: str
    metric_code: str
    paths: tuple[str, ...]
    kind: str
    unit: str | None = None


_SLEEP_SCALARS = (
    _ScalarSpec(
        "sleep",
        "sleep_duration_seconds",
        ("dailySleepDTO.sleepTimeSeconds",),
        "number",
        "seconds",
    ),
    _ScalarSpec(
        "sleep_score",
        "sleep_score",
        ("dailySleepDTO.sleepScores.overall.value",),
        "number",
        "points",
    ),
    _ScalarSpec(
        "naps",
        "nap_duration_seconds",
        ("dailySleepDTO.napTimeSeconds",),
        "number",
        "seconds",
    ),
)

_DAILY_SCALARS = (
    _ScalarSpec(
        "resting_heart_rate",
        "resting_heart_rate_bpm",
        (
            "allMetrics.metricsMap.WELLNESS_RESTING_HEART_RATE.0.value",
            "restingHeartRate",
        ),
        "number",
        "bpm",
    ),
    _ScalarSpec(
        "hrv_status",
        "hrv_weekly_average_ms",
        ("hrvSummary.weeklyAvg", "hrvStatus.weeklyAverage"),
        "number",
        "ms",
    ),
    _ScalarSpec(
        "vo2_max",
        "vo2_max_running",
        ("maxMetrics.vo2MaxRunning",),
        "number",
        "ml/kg/min",
    ),
    _ScalarSpec(
        "training_readiness",
        "training_readiness",
        ("trainingReadiness.score", "trainingReadiness"),
        "number_or_text",
        "points",
    ),
    _ScalarSpec(
        "training_status",
        "training_status",
        ("trainingStatus.value", "trainingStatus"),
        "text",
        None,
    ),
)

_ACTIVITY_SCALARS = (
    _ScalarSpec(
        "activities",
        "duration_seconds",
        ("duration", "durationSeconds"),
        "number",
        "seconds",
    ),
    _ScalarSpec(
        "activities",
        "distance_meters",
        ("distance", "distanceMeters"),
        "number",
        "meters",
    ),
    _ScalarSpec(
        "training_effect",
        "training_effect",
        ("aerobicTrainingEffect", "trainingEffect"),
        "number",
        "points",
    ),
    _ScalarSpec(
        "acute_training_load",
        "acute_training_load",
        ("activityTrainingLoad", "trainingLoad"),
        "number",
        "points",
    ),
    _ScalarSpec(
        "cycling_metrics", "speed_mps", ("averageSpeed", "metrics.speedMps"), "number", "m/s"
    ),
    _ScalarSpec(
        "cycling_metrics", "heart_rate_bpm", ("averageHR", "metrics.heartRateBpm"), "number", "bpm"
    ),
    _ScalarSpec(
        "cycling_metrics",
        "cadence_rpm",
        ("averageRunningCadenceInStepsPerMinute", "metrics.cadenceRpm"),
        "number",
        "rpm",
    ),
    _ScalarSpec(
        "cycling_metrics", "power_watts", ("avgPower", "metrics.powerWatts"), "number", "watts"
    ),
)

_FIT_SCALARS = (
    _ScalarSpec(
        "recovery_time",
        "recovery_time_seconds",
        ("fitRecords.0.recoveryTimeSeconds", "recoveryTimeSeconds"),
        "number",
        "seconds",
    ),
)

_INTRADAY_SCALARS = (
    _ScalarSpec(
        "heart_rate",
        "heart_rate_bpm",
        ("heartRate", "heartRateBpm", "heartRateValue"),
        "number",
        "bpm",
    ),
    _ScalarSpec(
        "stress",
        "stress",
        ("stress", "stressLevel", "avgStressLevel", "maxStressLevel"),
        "number",
        "points",
    ),
    _ScalarSpec(
        "body_battery",
        "body_battery",
        ("bodyBattery", "bodyBatteryLevel"),
        "number",
        "points",
    ),
    _ScalarSpec(
        "spo2",
        "spo2_percent",
        ("spo2", "spo2Percent", "averageSpO2", "lastSevenDaysAvgSpO2"),
        "number",
        "%",
    ),
    _ScalarSpec(
        "respiration",
        "respiration_bpm",
        ("respiration", "respirationRate", "avgSleepRespirationValue"),
        "number",
        "breaths/min",
    ),
)

_CALENDAR_PATHS = ("calendarDate", "date", "dailySleepDTO.calendarDate")
_COMMON_TIME_PATHS = (
    "startTimeGMT",
    "startTimeLocal",
    "startTime",
    "timestamp",
    "time",
    "sleepStartGMT",
)
_PAIRED_LOCAL_TIME_PATHS = ("startTimeLocal",)
_PAIRED_UTC_TIME_PATHS = ("startTimeGMT", "startTimeUTC")
_TIMEZONE_PATHS = (
    "timeZone",
    "timezone",
    "timeZoneId",
    "timezoneId",
    "zone",
    "sourceTimezone",
)
_UTC_OFFSET_PATHS = (
    "sourceUtcOffsetMinutes",
    "utcOffsetMinutes",
    "timeZoneOffsetMinutes",
    "timezoneOffsetMinutes",
    "sourceUtcOffset",
    "utcOffset",
    "timeZoneOffset",
    "timezoneOffset",
)


def stable_garmin_idempotency_key(
    source: GarminSourceIdentity | str,
    stream: GarminStream | str,
    record_id: str | None = None,
    *,
    temporal: GarminTemporalDTO | None = None,
    metrics: Iterable[GarminMetricDTO | tuple[str, Any, str | None]] = (),
) -> str:
    """Return a deterministic record or semantic idempotency key.

    A stable source record id is preferred.  Without one, only present,
    non-null typed metric values participate in the semantic fallback; missing
    fields and explicit nulls do not masquerade as values, while a numeric zero
    is included exactly like any other present value.
    """

    source_instance_id = _source_instance_value(source)
    normalized_stream = GarminStream(stream).value
    normalized_record_id = _optional_text(record_id)
    if normalized_record_id is not None:
        payload = {
            "kind": "record",
            "source_instance_id": source_instance_id,
            "stream": normalized_stream,
            "record_id": normalized_record_id,
        }
        return f"garmin:v1:record:{_digest(payload)}"

    normalized_metrics = sorted(
        _metric_key_value(item) for item in metrics if _metric_is_usable(item)
    )
    payload = {
        "kind": "semantic",
        "source_instance_id": source_instance_id,
        "stream": normalized_stream,
        "time": temporal.time_key() if temporal is not None else "unknown-time",
        "metrics": normalized_metrics,
    }
    return f"garmin:v1:semantic:{_digest(payload)}"


def garmin_record_idempotency_key(
    source: GarminSourceIdentity | str,
    stream: GarminStream | str,
    record_id: str,
) -> str:
    """Explicit helper for the stable ``(source, stream, record_id)`` key."""

    return stable_garmin_idempotency_key(source, stream, record_id)


def garmin_semantic_idempotency_key(
    source: GarminSourceIdentity | str,
    stream: GarminStream | str,
    temporal: GarminTemporalDTO,
    metrics: Iterable[GarminMetricDTO | tuple[str, Any, str | None]] = (),
) -> str:
    """Explicit helper for the no-record-id semantic fallback."""

    return stable_garmin_idempotency_key(source, stream, None, temporal=temporal, metrics=metrics)


def stable_garmin_reconciliation_key(
    source: GarminSourceIdentity | str,
    stream: GarminStream | str,
    *,
    surface: str,
    temporal: GarminTemporalDTO | None = None,
    record_id: str | None = None,
    sample_index: int | None = None,
    sample_token: str | None = None,
) -> str:
    """Stable current-projection key that does not include mutable metric values.

    Provider record IDs still win.  Id-less production records reconcile by
    source, stream, surface, temporal identity and optional sample identity so
    a trailing-window value correction updates one current row.
    """

    normalized_record_id = _optional_text(record_id)
    if normalized_record_id is not None:
        return stable_garmin_idempotency_key(source, stream, normalized_record_id)
    payload = {
        "kind": "reconcile",
        "source_instance_id": _source_instance_value(source),
        "stream": GarminStream(stream).value,
        "surface": _required_text(surface, "reconciliation surface"),
        "time": temporal.time_key() if temporal is not None else "unknown-time",
        "sample_index": sample_index,
        "sample_token": _optional_text(sample_token),
    }
    return f"garmin:v1:reconcile:{_digest(payload)}"


def normalize_garmin_payload(
    value: GarminCapabilityFixture | Mapping[str, Any],
    *,
    stream: GarminStream | str | None = None,
    source_identity: GarminSourceIdentity | None = None,
) -> GarminNormalizationResult:
    """Normalize a synthetic Garmin fixture or raw synthetic payload.

    A full fixture envelope is preferred because it carries the frozen source
    and device attribution.  Raw mappings are accepted for deterministic unit
    probes only when a stream is supplied; absent source metadata is treated as
    an unattributed synthetic Garmin account value.
    """

    envelope = _coerce_envelope(value, stream=stream, source_identity=source_identity)
    if envelope["fatal"]:
        return GarminNormalizationResult(
            status=GarminParseStatus.INVALID,
            stream=envelope["stream"],
            source=envelope["source"],
            diagnostics=tuple(envelope["diagnostics"]),
            unknown_fields=tuple(envelope["unknown_fields"]),
            fixture_id=envelope["fixture_id"],
        )

    normalized_stream: GarminStream = envelope["stream"]
    source: GarminSourceIdentity = envelope["source"]
    payload = envelope["payload"]
    diagnostics: list[GarminDiagnostic] = list(envelope["diagnostics"])
    unknown_fields: list[GarminUnknownFieldDTO] = list(envelope["unknown_fields"])
    records: list[GarminRecordDTO] = []

    if not isinstance(payload, Mapping):
        diagnostics.append(_diag("payload_shape_drift", "payload", "error"))
    elif normalized_stream is GarminStream.ACTIVITY:
        records, collection_unknown, collection_diagnostics = _parse_activity_payload(
            payload, source
        )
        unknown_fields.extend(collection_unknown)
        diagnostics.extend(collection_diagnostics)
    elif not payload:
        diagnostics.append(_diag("empty_payload", "payload", "warning"))
    else:
        record, record_unknown, record_diagnostics = _parse_single_payload(
            payload, normalized_stream, source
        )
        unknown_fields.extend(record_unknown)
        diagnostics.extend(record_diagnostics)
        if record is not None:
            records.append(record)

    status = _overall_status(records, diagnostics, payload)
    return GarminNormalizationResult(
        status=status,
        stream=normalized_stream,
        source=source,
        records=tuple(records),
        diagnostics=tuple(diagnostics),
        unknown_fields=tuple(unknown_fields),
        fixture_id=envelope["fixture_id"],
    )


def normalize_synthetic_garmin_payload(
    value: GarminCapabilityFixture | Mapping[str, Any],
    *,
    stream: GarminStream | str | None = None,
    source_identity: GarminSourceIdentity | None = None,
) -> GarminNormalizationResult:
    """Explicitly named alias for the offline-only entrypoint."""

    return normalize_garmin_payload(value, stream=stream, source_identity=source_identity)


parse_synthetic_garmin_payload = normalize_synthetic_garmin_payload
normalize_synthetic_fixture = normalize_synthetic_garmin_payload
normalize_fixture = normalize_synthetic_garmin_payload


def _coerce_envelope(
    value: GarminCapabilityFixture | Mapping[str, Any],
    *,
    stream: GarminStream | str | None,
    source_identity: GarminSourceIdentity | None,
) -> dict[str, Any]:
    diagnostics: list[GarminDiagnostic] = []
    unknown_fields: list[GarminUnknownFieldDTO] = []
    fixture_id: str | None = None

    if isinstance(value, GarminCapabilityFixture):
        fixture = value
        parsed_stream = fixture.stream
        source = GarminSourceIdentity.from_fixture(fixture)
        if source_identity is not None and source_identity != source:
            diagnostics.append(_diag("source_identity_conflict", "source", "error"))
            return {
                "fatal": True,
                "stream": parsed_stream,
                "source": source,
                "payload": {},
                "fixture_id": fixture.fixture_id,
                "diagnostics": diagnostics,
                "unknown_fields": unknown_fields,
            }
        return {
            "fatal": False,
            "stream": parsed_stream,
            "source": source,
            "payload": fixture.payload,
            "fixture_id": fixture.fixture_id,
            "diagnostics": diagnostics,
            "unknown_fields": unknown_fields,
        }

    if not isinstance(value, Mapping):
        return {
            "fatal": True,
            "stream": None,
            "source": None,
            "payload": {},
            "fixture_id": None,
            "diagnostics": [_diag("invalid_input", None, "error")],
            "unknown_fields": unknown_fields,
        }

    if _contains_forbidden_key(value):
        return {
            "fatal": True,
            "stream": None,
            "source": None,
            "payload": {},
            "fixture_id": None,
            "diagnostics": [_diag("private_shape_rejected", None, "error")],
            "unknown_fields": unknown_fields,
        }

    is_envelope = "payload" in value or any(
        key in value for key in ("fixture_contract_version", "source_kind", "fixture_id", "device")
    )
    if not is_envelope:
        if stream is None:
            return {
                "fatal": True,
                "stream": None,
                "source": source_identity,
                "payload": {},
                "fixture_id": None,
                "diagnostics": [_diag("stream_required", None, "error")],
                "unknown_fields": unknown_fields,
            }
        try:
            parsed_stream = GarminStream(stream)
        except (TypeError, ValueError):
            return {
                "fatal": True,
                "stream": None,
                "source": source_identity,
                "payload": {},
                "fixture_id": None,
                "diagnostics": [_diag("invalid_stream", "stream", "error")],
                "unknown_fields": unknown_fields,
            }
        source = source_identity
        if source is None:
            source = garmin_source_identity()
        return {
            "fatal": False,
            "stream": parsed_stream,
            "source": source,
            "payload": value,
            "fixture_id": None,
            "diagnostics": diagnostics,
            "unknown_fields": unknown_fields,
        }

    contract_version = value.get("fixture_contract_version")
    source_kind = value.get("source_kind")
    fixture_id_value = value.get("fixture_id")
    fixture_id = fixture_id_value if isinstance(fixture_id_value, str) else None
    if contract_version != CAPABILITY_FIXTURE_CONTRACT_VERSION:
        diagnostics.append(_diag("invalid_fixture_contract", "fixture_contract_version", "error"))
    if source_kind != SYNTHETIC_SOURCE_KIND:
        diagnostics.append(_diag("non_synthetic_source", "source_kind", "error"))
    if not isinstance(fixture_id_value, str) or not fixture_id_value.startswith("synthetic-"):
        diagnostics.append(_diag("invalid_fixture_id", "fixture_id", "error"))

    try:
        parsed_stream = GarminStream(value.get("stream_code"))
    except (TypeError, ValueError):
        parsed_stream = None
        diagnostics.append(_diag("invalid_stream", "stream_code", "error"))

    device = value.get("device")
    if not isinstance(device, Mapping):
        diagnostics.append(_diag("device_shape_drift", "device", "error"))
        source = source_identity
    else:
        try:
            source = GarminSourceIdentity(
                source_kind=SYNTHETIC_SOURCE_KIND,
                provider_code=value.get("provider_code"),
                device_attributed=device.get("attributed"),
                device_code=device.get("code"),
                device_model=device.get("model"),
            )
        except (TypeError, ValueError):
            source = source_identity
            diagnostics.append(_diag("source_identity_invalid", "device", "error"))

    if value.get("provider_code") != GARMIN_PROVIDER_CODE:
        diagnostics.append(_diag("invalid_provider", "provider_code", "error"))

    payload = value.get("payload")
    if not isinstance(payload, Mapping):
        diagnostics.append(_diag("payload_shape_drift", "payload", "error"))
        payload = {}

    if source is not None and source_identity is not None and source != source_identity:
        diagnostics.append(_diag("source_identity_conflict", "source", "error"))

    # Reuse the stricter #28 fixture validator for privacy and envelope rules.
    # A stale payload_fields path is the one intentional exception: the R02
    # normalizer must still return a typed partial result for provider shape
    # drift instead of throwing before it can report the drift.
    try:
        GarminCapabilityFixture.from_mapping(value)
    except GarminCapabilityFixtureError as exc:
        text = str(exc)
        if text.startswith("payload field path is absent"):
            diagnostics.append(_diag("fixture_field_map_drift", "payload_fields", "warning"))
        else:
            diagnostics.append(_diag("invalid_fixture_envelope", None, "error"))

    if parsed_stream is None or source is None:
        fatal = True
    else:
        fatal = any(item.severity == "error" for item in diagnostics)
    return {
        "fatal": fatal,
        "stream": parsed_stream,
        "source": source,
        "payload": payload,
        "fixture_id": fixture_id,
        "diagnostics": diagnostics,
        "unknown_fields": unknown_fields,
    }


def _parse_activity_payload(
    payload: Mapping[str, Any], source: GarminSourceIdentity
) -> tuple[list[GarminRecordDTO], list[GarminUnknownFieldDTO], list[GarminDiagnostic]]:
    records: list[GarminRecordDTO] = []
    unknown_fields: list[GarminUnknownFieldDTO] = []
    diagnostics: list[GarminDiagnostic] = []
    activities = payload.get("activities", _MISSING)
    if activities is _MISSING:
        diagnostics.append(_diag("missing_activity_collection", "payload.activities", "warning"))
        return records, _unknown_top_level(payload, {"activities"}), diagnostics
    if activities is None or not _is_sequence(activities):
        diagnostics.append(_diag("activity_collection_shape_drift", "payload.activities", "error"))
        return records, _unknown_top_level(payload, {"activities"}), diagnostics
    if not activities:
        diagnostics.append(_diag("empty_activity_collection", "payload.activities", "warning"))
        return records, _unknown_top_level(payload, {"activities"}), diagnostics

    seen_ids: set[str] = set()
    for index, raw in enumerate(activities):
        item_path = f"payload.activities[{index}]"
        if not isinstance(raw, Mapping):
            diagnostics.append(_diag("activity_item_shape_drift", item_path, "error"))
            continue
        record, item_unknown, item_diagnostics = _parse_record(
            raw,
            GarminStream.ACTIVITY,
            source,
            record_index=None,
            source_path="payload.activities",
        )
        unknown_fields.extend(item_unknown)
        diagnostics.extend(item_diagnostics)
        if record is None:
            continue
        if record.record_id is not None and record.record_id in seen_ids:
            diagnostics.append(_diag("duplicate_activity_id", "payload.activities", "error"))
        if record.record_id is not None:
            seen_ids.add(record.record_id)
        records.append(record)
    unknown_fields.extend(
        _unknown_top_level(
            payload,
            {"activities"},
        )
    )
    return records, unknown_fields, diagnostics


def _parse_single_payload(
    payload: Mapping[str, Any], stream: GarminStream, source: GarminSourceIdentity
) -> tuple[GarminRecordDTO | None, list[GarminUnknownFieldDTO], list[GarminDiagnostic]]:
    record, unknown_fields, diagnostics = _parse_record(
        payload, stream, source, record_index=None, source_path="payload"
    )
    return record, unknown_fields, diagnostics


def _parse_record_temporal(
    raw: Mapping[str, Any], source_path: str
) -> tuple[GarminTemporalDTO, list[GarminDiagnostic]]:
    """Parse record time fields while retaining paired Local/GMT evidence."""

    calendar_path, calendar_value = _first_present(raw, _CALENDAR_PATHS)
    local_path, local_value = _first_present(raw, _PAIRED_LOCAL_TIME_PATHS)
    utc_path, utc_value = _first_present(raw, _PAIRED_UTC_TIME_PATHS)
    if local_path is None and utc_path is None:
        timestamp_path, timestamp_value = _first_present(raw, _COMMON_TIME_PATHS)
        return _parse_garmin_time(
            timestamp_value,
            calendar_date=calendar_value,
            source_field=(
                f"{source_path}.{timestamp_path}" if timestamp_path is not None else None
            ),
        )

    diagnostics: list[GarminDiagnostic] = []
    parsed_calendar = None
    if calendar_value is not _MISSING:
        parsed_calendar = _parse_date(calendar_value)
        if parsed_calendar is None:
            diagnostics.append(
                _diag("invalid_calendar_date", f"{source_path}.{calendar_path}", "error")
            )
    component_calendar = calendar_value if parsed_calendar is not None else _MISSING
    source_timezone, source_utc_offset_minutes = _source_time_evidence(raw)

    local_temporal = None
    if local_path is not None:
        local_temporal, local_diagnostics = _parse_garmin_time(
            local_value,
            calendar_date=component_calendar,
            source_field=f"{source_path}.{local_path}",
            field_semantics="local",
            source_timezone=source_timezone,
            source_utc_offset_minutes=source_utc_offset_minutes,
        )
        diagnostics.extend(local_diagnostics)

    utc_temporal = None
    if utc_path is not None:
        utc_temporal, utc_diagnostics = _parse_garmin_time(
            utc_value,
            calendar_date=component_calendar,
            source_field=f"{source_path}.{utc_path}",
            field_semantics="utc",
        )
        diagnostics.extend(utc_diagnostics)

    return _merge_paired_temporal(
        local_temporal=local_temporal,
        utc_temporal=utc_temporal,
        local_field=f"{source_path}.{local_path}" if local_path is not None else None,
        utc_field=f"{source_path}.{utc_path}" if utc_path is not None else None,
        parsed_calendar=parsed_calendar,
        diagnostics=diagnostics,
    )


def _merge_paired_temporal(
    *,
    local_temporal: GarminTemporalDTO | None,
    utc_temporal: GarminTemporalDTO | None,
    local_field: str | None,
    utc_field: str | None,
    parsed_calendar: date | None,
    diagnostics: list[GarminDiagnostic],
) -> tuple[GarminTemporalDTO, list[GarminDiagnostic]]:
    """Combine Local/GMT values without discarding either source meaning."""

    local_instant = local_temporal.measured_at_utc if local_temporal is not None else None
    utc_instant = utc_temporal.measured_at_utc if utc_temporal is not None else None
    if local_instant is not None and utc_instant is not None and local_instant != utc_instant:
        diagnostics.append(_diag("paired_time_mismatch", utc_field or local_field, "error"))

    measured_at_utc = utc_instant or local_instant
    if measured_at_utc is not None:
        precision = GarminTemporalPrecision.UTC_INSTANT
    elif (
        local_temporal is not None
        and local_temporal.precision is GarminTemporalPrecision.LOCAL_WALL_TIME
    ):
        precision = GarminTemporalPrecision.LOCAL_WALL_TIME
    elif (
        local_temporal is not None and local_temporal.precision is GarminTemporalPrecision.DATE_ONLY
    ) or (utc_temporal is not None and utc_temporal.precision is GarminTemporalPrecision.DATE_ONLY):
        precision = GarminTemporalPrecision.DATE_ONLY
    else:
        precision = GarminTemporalPrecision.UNKNOWN

    local_date = parsed_calendar
    local_date_source = "calendarDate" if parsed_calendar is not None else None
    if local_date is None and local_temporal is not None:
        local_date = local_temporal.local_date
        local_date_source = local_temporal.local_date_source
    if local_date is None and utc_temporal is not None:
        local_date = utc_temporal.local_date
        local_date_source = utc_temporal.local_date_source

    if utc_instant is not None:
        source_field = utc_field
    elif (
        local_temporal is not None
        and local_temporal.precision is not GarminTemporalPrecision.UNKNOWN
    ):
        source_field = local_field
    elif utc_temporal is not None and utc_temporal.precision is not GarminTemporalPrecision.UNKNOWN:
        source_field = utc_field
    else:
        source_field = local_field or utc_field

    return (
        GarminTemporalDTO(
            precision=precision,
            measured_at_utc=measured_at_utc,
            local_wall_time=local_temporal.local_wall_time if local_temporal else None,
            local_date=local_date,
            source_field=source_field,
            local_date_source=local_date_source,
            source_local_timestamp=(
                local_temporal.source_local_timestamp if local_temporal else None
            ),
            source_timezone=local_temporal.source_timezone if local_temporal else None,
            source_utc_offset_minutes=(
                local_temporal.source_utc_offset_minutes if local_temporal else None
            ),
            source_local_field=local_field,
            source_utc_field=utc_field,
        ),
        diagnostics,
    )


def _parse_record(
    raw: Mapping[str, Any],
    stream: GarminStream,
    source: GarminSourceIdentity,
    *,
    record_index: int | None,
    source_path: str,
) -> tuple[GarminRecordDTO | None, list[GarminUnknownFieldDTO], list[GarminDiagnostic]]:
    diagnostics: list[GarminDiagnostic] = []
    unknown_fields: list[GarminUnknownFieldDTO] = []
    if not raw:
        diagnostics.append(_diag("empty_record", source_path, "warning"))
        return None, unknown_fields, diagnostics

    record_id, record_id_path = _record_id(raw, stream)
    if record_id_path is not None and record_id is None:
        diagnostics.append(
            _diag("record_id_shape_drift", f"{source_path}.{record_id_path}", "error")
        )

    temporal, temporal_diagnostics = _parse_record_temporal(raw, source_path)
    diagnostics.extend(temporal_diagnostics)
    if temporal.precision is GarminTemporalPrecision.UNKNOWN:
        diagnostics.append(_diag("missing_time", source_path, "warning"))

    specs = _specs_for_stream(stream)
    metrics: list[GarminMetricDTO] = []
    for spec in specs:
        metric, metric_diagnostics = _parse_scalar(raw, spec, source_path)
        metrics.append(metric)
        diagnostics.extend(metric_diagnostics)

    if stream is GarminStream.SLEEP:
        stage_metric, stage_diagnostics = _parse_sleep_levels(raw, source_path)
        metrics.append(stage_metric)
        diagnostics.extend(stage_diagnostics)

    metrics = [replace(item, source_device_attributed=source.device_attributed) for item in metrics]

    activity_type = raw.get("activityType")
    if isinstance(activity_type, Mapping):
        activity_type = activity_type.get("typeKey")
        if activity_type is not None and not isinstance(activity_type, str):
            diagnostics.append(
                _diag("activity_type_shape_drift", f"{source_path}.activityType.typeKey", "error")
            )
            activity_type = None
    elif activity_type is not None and not isinstance(activity_type, str):
        diagnostics.append(
            _diag("activity_type_shape_drift", f"{source_path}.activityType", "error")
        )
        activity_type = None
    elif isinstance(activity_type, str):
        activity_type = activity_type.strip() or None

    known_roots = _known_roots(stream)
    unknown_fields.extend(_unknown_fields(raw, source_path, stream, known_roots))

    idempotency_key = stable_garmin_idempotency_key(
        source,
        stream,
        record_id,
        temporal=temporal,
        metrics=metrics,
    )
    invalid_metric = any(item.state is GarminFieldState.INVALID for item in metrics)
    missing_metric = any(item.state is GarminFieldState.MISSING for item in metrics)
    has_partial_collection = any(item.reason == "partial_collection" for item in metrics)
    if invalid_metric:
        status = (
            GarminParseStatus.PARTIAL
            if any(item.has_value for item in metrics)
            else GarminParseStatus.INVALID
        )
    elif (
        missing_metric
        or has_partial_collection
        or any(item.severity in {"warning", "error"} for item in diagnostics)
    ):
        status = GarminParseStatus.PARTIAL
    else:
        status = GarminParseStatus.OK

    record = GarminRecordDTO(
        stream=stream,
        source=source,
        temporal=temporal,
        idempotency_key=idempotency_key,
        record_id=record_id,
        activity_type=activity_type,
        record_index=record_index,
        metrics=tuple(metrics),
        unknown_fields=tuple(unknown_fields),
        diagnostics=tuple(diagnostics),
        status=status,
        source_path=source_path,
    )
    return record, unknown_fields, diagnostics


def _specs_for_stream(stream: GarminStream) -> tuple[_ScalarSpec, ...]:
    if stream is GarminStream.SLEEP:
        return _SLEEP_SCALARS
    if stream is GarminStream.DAILY_HEALTH:
        return _DAILY_SCALARS
    if stream is GarminStream.ACTIVITY:
        return _ACTIVITY_SCALARS
    if stream is GarminStream.ORIGINAL_FIT:
        return _FIT_SCALARS
    return _INTRADAY_SCALARS


def _parse_scalar(
    raw: Mapping[str, Any], spec: _ScalarSpec, source_path: str
) -> tuple[GarminMetricDTO, list[GarminDiagnostic]]:
    field_path, value = _first_present(raw, spec.paths)
    full_path = f"{source_path}.{field_path or spec.paths[0]}"
    capability_status = _capability_status(spec.capability_code)
    if value is _MISSING:
        return (
            GarminMetricDTO(
                capability_code=spec.capability_code,
                metric_code=spec.metric_code,
                field_path=full_path,
                state=GarminFieldState.MISSING,
                unit=spec.unit,
                capability_status=capability_status,
            ),
            [],
        )
    if value is None:
        return (
            GarminMetricDTO(
                capability_code=spec.capability_code,
                metric_code=spec.metric_code,
                field_path=full_path,
                state=GarminFieldState.NULL,
                unit=spec.unit,
                capability_status=capability_status,
            ),
            [],
        )
    if spec.kind in {"number", "number_or_text"}:
        if isinstance(value, bool):
            return _invalid_metric(spec, full_path, "boolean_not_numeric")
        if isinstance(value, Real):
            numeric = float(value) if isinstance(value, float) else value
            if isinstance(numeric, float) and not math.isfinite(numeric):
                return _invalid_metric(spec, full_path, "non_finite_value")
            return (
                GarminMetricDTO(
                    capability_code=spec.capability_code,
                    metric_code=spec.metric_code,
                    field_path=full_path,
                    state=GarminFieldState.VALUE,
                    value=numeric,
                    unit=spec.unit,
                    capability_status=capability_status,
                ),
                [],
            )
        if spec.kind == "number_or_text" and isinstance(value, str) and value.strip():
            return (
                GarminMetricDTO(
                    capability_code=spec.capability_code,
                    metric_code=spec.metric_code,
                    field_path=full_path,
                    state=GarminFieldState.VALUE,
                    value=value.strip(),
                    unit=spec.unit,
                    capability_status=capability_status,
                ),
                [],
            )
        reason = "numeric_string_not_coerced" if isinstance(value, str) else "shape_drift"
        return _invalid_metric(spec, full_path, reason)
    if spec.kind == "text":
        if isinstance(value, str) and value.strip():
            return (
                GarminMetricDTO(
                    capability_code=spec.capability_code,
                    metric_code=spec.metric_code,
                    field_path=full_path,
                    state=GarminFieldState.VALUE,
                    value=value.strip(),
                    unit=spec.unit,
                    capability_status=capability_status,
                ),
                [],
            )
        return _invalid_metric(
            spec, full_path, "empty_text" if isinstance(value, str) else "shape_drift"
        )
    return _invalid_metric(spec, full_path, "unsupported_parser_kind")


def _invalid_metric(
    spec: _ScalarSpec, field_path: str, reason: str
) -> tuple[GarminMetricDTO, list[GarminDiagnostic]]:
    code = (
        "numeric_string_not_coerced"
        if reason == "numeric_string_not_coerced"
        else "field_shape_drift"
    )
    return (
        GarminMetricDTO(
            capability_code=spec.capability_code,
            metric_code=spec.metric_code,
            field_path=field_path,
            state=GarminFieldState.INVALID,
            reason=reason,
            unit=spec.unit,
            capability_status=_capability_status(spec.capability_code),
        ),
        [_diag(code, field_path, "error")],
    )


def _parse_sleep_levels(
    raw: Mapping[str, Any], source_path: str
) -> tuple[GarminMetricDTO, list[GarminDiagnostic]]:
    field_path = f"{source_path}.levels"
    value = raw.get("levels", _MISSING)
    capability_status = _capability_status("sleep_stages")
    if value is _MISSING:
        return (
            GarminMetricDTO(
                capability_code="sleep_stages",
                metric_code="sleep_stages",
                field_path=field_path,
                state=GarminFieldState.MISSING,
                unit=None,
                capability_status=capability_status,
            ),
            [],
        )
    if value is None:
        return (
            GarminMetricDTO(
                capability_code="sleep_stages",
                metric_code="sleep_stages",
                field_path=field_path,
                state=GarminFieldState.NULL,
                capability_status=capability_status,
            ),
            [],
        )
    if not _is_sequence(value):
        return (
            GarminMetricDTO(
                capability_code="sleep_stages",
                metric_code="sleep_stages",
                field_path=field_path,
                state=GarminFieldState.INVALID,
                reason="shape_drift",
                capability_status=capability_status,
            ),
            [_diag("field_shape_drift", field_path, "error")],
        )

    stages: list[GarminSleepStageDTO] = []
    diagnostics: list[GarminDiagnostic] = []
    for index, item in enumerate(value):
        item_path = f"{field_path}[{index}]"
        if not isinstance(item, Mapping):
            diagnostics.append(_diag("sleep_stage_shape_drift", item_path, "error"))
            continue
        start, start_diagnostics = _parse_record_temporal(item, item_path)
        end, end_diagnostics = _parse_garmin_time(
            item.get("endTimeGMT", item.get("endTime", _MISSING)),
            source_field=(
                f"{item_path}.endTimeGMT" if "endTimeGMT" in item else f"{item_path}.endTime"
            ),
        )
        if start_diagnostics or end_diagnostics:
            diagnostics.extend(start_diagnostics)
            diagnostics.extend(end_diagnostics)
            diagnostics.append(_diag("sleep_stage_time_invalid", item_path, "error"))
            continue
        if (
            start.precision is GarminTemporalPrecision.UNKNOWN
            or end.precision is GarminTemporalPrecision.UNKNOWN
        ):
            diagnostics.append(_diag("sleep_stage_time_missing", item_path, "error"))
            continue
        if (
            start.measured_at_utc is not None
            and end.measured_at_utc is not None
            and end.measured_at_utc <= start.measured_at_utc
        ):
            diagnostics.append(_diag("sleep_stage_interval_invalid", item_path, "error"))
            continue
        activity_level = item.get("activityLevel")
        if activity_level is not None and not isinstance(activity_level, str):
            diagnostics.append(_diag("sleep_stage_level_shape_drift", item_path, "warning"))
            activity_level = None
        stages.append(
            GarminSleepStageDTO(
                start=start,
                end=end,
                activity_level=activity_level.strip() if isinstance(activity_level, str) else None,
            )
        )
    reason = "partial_collection" if diagnostics and stages else None
    state = GarminFieldState.VALUE if not diagnostics or stages else GarminFieldState.INVALID
    return (
        GarminMetricDTO(
            capability_code="sleep_stages",
            metric_code="sleep_stages",
            field_path=field_path,
            state=state,
            reason=reason or ("shape_drift" if diagnostics else None),
            collection=tuple(stages),
            capability_status=capability_status,
        ),
        diagnostics,
    )


def _parse_garmin_time(
    value: Any,
    *,
    calendar_date: Any = _MISSING,
    source_field: str | None = "time",
    field_semantics: str | None = None,
    source_timezone: str | None = None,
    source_utc_offset_minutes: int | None = None,
) -> tuple[GarminTemporalDTO, list[GarminDiagnostic]]:
    """Parse one temporal source value with field-level UTC/local semantics."""

    diagnostics: list[GarminDiagnostic] = []
    parsed_date: date | None = None
    if calendar_date is not _MISSING:
        parsed_date = _parse_date(calendar_date)
        if parsed_date is None:
            diagnostics.append(_diag("invalid_calendar_date", "calendarDate", "error"))

    semantics = _temporal_field_semantics(field_semantics, source_field)
    source_timezone = _text_evidence(source_timezone)
    source_utc_offset_minutes = _offset_minutes(source_utc_offset_minutes)

    if value is _MISSING or value is None:
        if parsed_date is not None:
            return (
                GarminTemporalDTO(
                    precision=GarminTemporalPrecision.DATE_ONLY,
                    local_date=parsed_date,
                    source_field=None,
                    local_date_source="calendarDate",
                ),
                diagnostics,
            )
        return (
            GarminTemporalDTO(GarminTemporalPrecision.UNKNOWN, source_field=source_field),
            diagnostics,
        )

    parsed: datetime | date | None = None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if _DATE_ONLY_RE.fullmatch(text):
            parsed = _parse_date(text)
        else:
            try:
                parsed_text = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
                parsed = datetime.fromisoformat(parsed_text)
            except (TypeError, ValueError):
                parsed = None

    if parsed is None:
        diagnostics.append(_diag("invalid_datetime", source_field, "error"))
        return (
            GarminTemporalDTO(
                precision=GarminTemporalPrecision.UNKNOWN,
                local_date=parsed_date,
                source_field=source_field,
                local_date_source="calendarDate" if parsed_date is not None else None,
                source_timezone=source_timezone,
                source_utc_offset_minutes=source_utc_offset_minutes,
            ),
            diagnostics,
        )
    if isinstance(parsed, date) and not isinstance(parsed, datetime):
        return (
            GarminTemporalDTO(
                precision=GarminTemporalPrecision.DATE_ONLY,
                local_date=parsed_date or parsed,
                source_field=source_field,
                local_date_source="calendarDate" if parsed_date is not None else source_field,
                source_local_timestamp=(
                    _source_temporal_text(value) if semantics == "local" else None
                ),
                source_timezone=source_timezone if semantics == "local" else None,
                source_utc_offset_minutes=(
                    source_utc_offset_minutes if semantics == "local" else None
                ),
                source_local_field=source_field if semantics == "local" else None,
                source_utc_field=source_field if semantics == "utc" else None,
            ),
            diagnostics,
        )

    assert isinstance(parsed, datetime)
    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        parsed_offset_minutes = _offset_minutes(int(parsed.utcoffset().total_seconds() // 60))
        if semantics == "utc":
            return (
                GarminTemporalDTO(
                    precision=GarminTemporalPrecision.UTC_INSTANT,
                    measured_at_utc=parsed.astimezone(UTC),
                    local_date=parsed_date or parsed.date(),
                    source_field=source_field,
                    local_date_source=(
                        "calendarDate" if parsed_date is not None else "source_offset"
                    ),
                    source_utc_field=source_field,
                ),
                diagnostics,
            )
        return (
            GarminTemporalDTO(
                precision=GarminTemporalPrecision.UTC_INSTANT,
                measured_at_utc=parsed.astimezone(UTC),
                local_date=parsed_date or parsed.date(),
                source_field=source_field,
                local_date_source="calendarDate" if parsed_date is not None else "source_offset",
                local_wall_time=parsed.replace(tzinfo=None).isoformat(),
                source_local_timestamp=_source_temporal_text(value),
                source_timezone=source_timezone,
                source_utc_offset_minutes=parsed_offset_minutes,
                source_local_field=source_field,
                source_utc_field=source_field,
            ),
            diagnostics,
        )
    if semantics == "utc":
        return (
            GarminTemporalDTO(
                precision=GarminTemporalPrecision.UTC_INSTANT,
                measured_at_utc=parsed.replace(tzinfo=UTC),
                local_date=parsed_date or parsed.date(),
                source_field=source_field,
                local_date_source=("calendarDate" if parsed_date is not None else "utc_field"),
                source_utc_field=source_field,
            ),
            diagnostics,
        )
    return (
        GarminTemporalDTO(
            precision=GarminTemporalPrecision.LOCAL_WALL_TIME,
            local_wall_time=parsed.isoformat(),
            local_date=parsed_date or parsed.date(),
            source_field=source_field,
            local_date_source="calendarDate" if parsed_date is not None else "local_wall_time",
            source_local_timestamp=_source_temporal_text(value),
            source_timezone=source_timezone,
            source_utc_offset_minutes=source_utc_offset_minutes,
            source_local_field=source_field,
        ),
        diagnostics,
    )


def _temporal_field_semantics(field_semantics: str | None, source_field: str | None) -> str:
    if field_semantics is not None:
        normalized = field_semantics.strip().lower()
        if normalized in {"utc", "gmt", "instant"}:
            return "utc"
        if normalized in {"local", "wall", "wall_time"}:
            return "local"
        if normalized in {"generic", "unknown"}:
            return "generic"
    if source_field:
        leaf = source_field.rsplit(".", 1)[-1].lower()
        if "gmt" in leaf or leaf.endswith("utc"):
            return "utc"
        if "local" in leaf:
            return "local"
    return "generic"


def _source_temporal_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _source_time_evidence(raw: Mapping[str, Any]) -> tuple[str | None, int | None]:
    _, timezone_value = _first_present(raw, _TIMEZONE_PATHS)
    source_timezone = _text_evidence(timezone_value)
    offset_path, offset_value = _first_present(raw, _UTC_OFFSET_PATHS)
    source_utc_offset_minutes = _parse_source_offset(offset_path, offset_value)
    return source_timezone, source_utc_offset_minutes


def _parse_source_offset(path: str | None, value: Any) -> int | None:
    if path is None or value is _MISSING:
        return None
    if isinstance(value, str):
        return _parse_offset_text(value)
    if path.lower().endswith("minutes"):
        return _offset_minutes(value)
    return None


def _parse_offset_text(value: str) -> int | None:
    text = value.strip()
    if text.upper() in {"Z", "UTC", "GMT"}:
        return 0
    match = re.fullmatch(r"([+-])(\d{1,2})(?::?(\d{2}))?", text)
    if match is None:
        return None
    hours = int(match.group(2))
    minutes = int(match.group(3) or 0)
    if minutes >= 60:
        return None
    offset = hours * 60 + minutes
    if offset > 23 * 60 + 59:
        return None
    return -offset if match.group(1) == "-" else offset


def _offset_minutes(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if -23 * 60 - 59 <= value <= 23 * 60 + 59:
        return value
    return None


def _text_evidence(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _record_id(raw: Mapping[str, Any], stream: GarminStream) -> tuple[str | None, str | None]:
    paths = {
        GarminStream.ACTIVITY: ("activityId", "id", "recordId"),
        GarminStream.ORIGINAL_FIT: ("fileName", "activityId", "id"),
    }.get(stream, ("recordId", "id"))
    path, value = _first_present(raw, paths)
    if value is _MISSING:
        return None, None
    if isinstance(value, str) and value.strip():
        return value.strip(), path
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value), path
    return None, path


def _unknown_fields(
    raw: Mapping[str, Any],
    source_path: str,
    stream: GarminStream,
    known_roots: set[str],
) -> list[GarminUnknownFieldDTO]:
    result: list[GarminUnknownFieldDTO] = []
    for key, value in raw.items():
        if not isinstance(key, str):
            result.append(
                GarminUnknownFieldDTO(f"{source_path}.<non-text-key>", type(value).__name__)
            )
            continue
        if key not in known_roots:
            result.append(GarminUnknownFieldDTO(f"{source_path}.{key}", _shape_name(value)))
    if isinstance(raw.get("metrics"), Mapping):
        known_metric_keys = {
            "speedMps",
            "heartRateBpm",
            "cadenceRpm",
            "powerWatts",
            "cyclingDynamics",
        }
        result.extend(
            GarminUnknownFieldDTO(f"{source_path}.metrics.{key}", _shape_name(value))
            for key, value in raw["metrics"].items()
            if key not in known_metric_keys
        )
    if isinstance(raw.get("hrvStatus"), Mapping):
        result.extend(
            GarminUnknownFieldDTO(f"{source_path}.hrvStatus.{key}", _shape_name(value))
            for key, value in raw["hrvStatus"].items()
            if key not in {"weeklyAverage", "status"}
        )
    if isinstance(raw.get("maxMetrics"), Mapping):
        result.extend(
            GarminUnknownFieldDTO(f"{source_path}.maxMetrics.{key}", _shape_name(value))
            for key, value in raw["maxMetrics"].items()
            if key != "vo2MaxRunning"
        )
    if stream is GarminStream.SLEEP and _is_sequence(raw.get("levels")):
        for index, item in enumerate(raw["levels"]):
            if not isinstance(item, Mapping):
                continue
            for key, value in item.items():
                if key not in {
                    "startTimeGMT",
                    "startTime",
                    "endTimeGMT",
                    "endTime",
                    "activityLevel",
                }:
                    result.append(
                        GarminUnknownFieldDTO(
                            f"{source_path}.levels[{index}].{key}", _shape_name(value)
                        )
                    )
    return result


def _known_roots(stream: GarminStream) -> set[str]:
    roots = {
        "calendarDate",
        "startTimeGMT",
        "startTimeLocal",
        "startTimeUTC",
        "startTime",
        "timestamp",
        "time",
        "sleepStartGMT",
        "recordId",
        "id",
    }
    roots.update(_TIMEZONE_PATHS)
    roots.update(_UTC_OFFSET_PATHS)
    for spec in _specs_for_stream(stream):
        for path in spec.paths:
            roots.add(path.split(".")[0])
    if stream is GarminStream.SLEEP:
        roots.add("levels")
    if stream is GarminStream.INTRADAY:
        roots.update(
            {
                "date",
                "heartRateValues",
                "heartRateValue",
                "avgStressLevel",
                "maxStressLevel",
                "stressValuesArray",
                "stressValues",
                "bodyBatteryValuesArray",
                "bodyBatteryValueDescriptorDTOList",
                "charged",
                "drained",
                "startTimestampGMT",
                "startTimestampLocal",
                "endTimestampGMT",
                "endTimestampLocal",
                "averageSpO2",
                "lastSevenDaysAvgSpO2",
                "spo2Values",
                "avgSleepRespirationValue",
                "respirationValues",
            }
        )
    if stream is GarminStream.ORIGINAL_FIT:
        roots.update({"fileName", "fitRecords"})
    if stream is GarminStream.ACTIVITY:
        roots.update({"activityId", "activityType"})
    return roots


def _unknown_top_level(
    payload: Mapping[str, Any], known_keys: set[str]
) -> list[GarminUnknownFieldDTO]:
    return [
        GarminUnknownFieldDTO(f"payload.{key}", _shape_name(value))
        for key, value in payload.items()
        if key not in known_keys
    ]


def _overall_status(
    records: Sequence[GarminRecordDTO],
    diagnostics: Sequence[GarminDiagnostic],
    payload: Any,
) -> GarminParseStatus:
    if not records:
        if any(item.severity == "error" for item in diagnostics):
            return GarminParseStatus.INVALID
        return GarminParseStatus.EMPTY
    if any(item.status is GarminParseStatus.INVALID for item in records):
        return (
            GarminParseStatus.PARTIAL
            if any(item.status is not GarminParseStatus.INVALID for item in records)
            else GarminParseStatus.INVALID
        )
    if any(item.status is GarminParseStatus.PARTIAL for item in records):
        return GarminParseStatus.PARTIAL
    if any(item.severity == "error" for item in diagnostics):
        return GarminParseStatus.PARTIAL
    if any(item.severity == "warning" for item in diagnostics):
        return GarminParseStatus.PARTIAL
    if isinstance(payload, Mapping) and not payload:
        return GarminParseStatus.EMPTY
    return GarminParseStatus.OK


def _first_present(value: Mapping[str, Any], paths: Sequence[str]) -> tuple[str | None, Any]:
    for path in paths:
        result = _read_path(value, path)
        if result is not _MISSING:
            return path, result
    return None, _MISSING


def _read_path(value: Any, path: str) -> Any:
    current = value
    for segment in path.split("."):
        if isinstance(current, Mapping):
            if segment not in current:
                return _MISSING
            current = current[segment]
        elif _is_sequence(current):
            try:
                current = current[int(segment)]
            except (IndexError, TypeError, ValueError):
                return _MISSING
        else:
            return _MISSING
    return current


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and _DATE_ONLY_RE.fullmatch(value.strip()):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _shape_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, Mapping):
        return "object"
    if _is_sequence(value):
        return "array"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Real):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if is_forbidden_payload_key(key):
                return True
            if _contains_forbidden_key(nested):
                return True
    elif _is_sequence(value):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _capability_status(code: str) -> CapabilityStatus | None:
    try:
        return get_capability(code).audit_status
    except (KeyError, TypeError):
        return None


def _metric_is_usable(value: GarminMetricDTO | tuple[str, Any, str | None]) -> bool:
    if isinstance(value, GarminMetricDTO):
        return value.has_value
    return len(value) >= 2 and value[1] is not None


def _metric_key_value(value: GarminMetricDTO | tuple[str, Any, str | None]) -> tuple[str, str, str]:
    if isinstance(value, GarminMetricDTO):
        metric_code = value.metric_code
        metric_value: Any = value.value
        unit = value.unit
        if value.collection:
            metric_value = [
                {
                    "start": item.start.time_key(),
                    "end": item.end.time_key(),
                    "activity_level": item.activity_level,
                }
                for item in value.collection
            ]
    else:
        metric_code, metric_value, unit = value
    if isinstance(metric_value, float):
        metric_text = repr(float(metric_value))
    else:
        metric_text = _canonical_json(metric_value)
    return str(metric_code), metric_text, str(unit or "")


def _source_instance_value(source: GarminSourceIdentity | str) -> str:
    if isinstance(source, GarminSourceIdentity):
        return source.source_instance_id or ""
    normalized = _optional_text(source)
    if normalized is None:
        raise ValueError("source instance id is required")
    return normalized


def _source_instance_id(
    *,
    source_kind: str,
    provider_code: str,
    device_attributed: bool,
    device_code: str | None,
    device_model: str | None,
) -> str:
    payload = {
        "source_kind": source_kind,
        "provider_code": provider_code,
        "device_attributed": device_attributed,
        "device_code": device_code.lower() if device_code else None,
        "device_model": " ".join(device_model.casefold().split()) if device_model else None,
    }
    return f"garmin:source:{_digest(payload)}"


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("text value is required")
    normalized = value.strip()
    return normalized or None


def _diag(code: str, path: str | None, severity: str) -> GarminDiagnostic:
    messages = {
        "invalid_input": "input must be a synthetic Garmin object",
        "stream_required": "stream is required for a raw payload",
        "invalid_stream": "stream code is not supported",
        "invalid_fixture_contract": "fixture contract version is not supported",
        "non_synthetic_source": "only synthetic source envelopes are accepted",
        "invalid_fixture_id": "fixture id must identify synthetic data",
        "device_shape_drift": "device metadata has an invalid shape",
        "source_identity_invalid": "source or device identity is invalid",
        "invalid_provider": "provider is not Garmin Connect",
        "source_identity_conflict": "supplied source identity conflicts with envelope identity",
        "invalid_fixture_envelope": "synthetic fixture envelope failed validation",
        "fixture_field_map_drift": "fixture field map does not match the observed payload shape",
        "payload_shape_drift": "payload must be an object",
        "empty_payload": "payload contains no source fields",
        "missing_activity_collection": "activity collection is absent",
        "activity_collection_shape_drift": "activity collection must be an array",
        "empty_activity_collection": "activity collection is explicitly empty",
        "activity_item_shape_drift": "activity item must be an object",
        "activity_type_shape_drift": "activity type must be text",
        "duplicate_activity_id": "activity id is duplicated in the envelope",
        "empty_record": "record contains no source fields",
        "record_id_shape_drift": "record identity field must be non-empty text or a whole number",
        "invalid_calendar_date": "calendar date is not a valid date-only value",
        "invalid_datetime": "timestamp is not a valid ISO temporal value",
        "paired_time_mismatch": "paired local and GMT times disagree on the UTC instant",
        "missing_time": "record has no usable source time",
        "field_shape_drift": "field has an unsupported source shape",
        "numeric_string_not_coerced": "numeric field is not silently coerced from text",
        "sleep_stage_shape_drift": "sleep stage item must be an object",
        "sleep_stage_time_invalid": "sleep stage time is invalid",
        "sleep_stage_time_missing": "sleep stage time is missing",
        "sleep_stage_interval_invalid": "sleep stage interval is not increasing",
        "sleep_stage_level_shape_drift": "sleep stage level has an unsupported shape",
        "private_shape_rejected": "private or credential-shaped fields are not accepted",
    }
    return GarminDiagnostic(
        code=code,
        message=messages.get(code, "synthetic Garmin field could not be normalized"),
        path=path,
        severity=severity,
    )


def _diagnostic_sort_key(item: GarminDiagnostic) -> tuple[str, str, str, str]:
    return (item.severity, item.code, item.path or "", item.message)


stable_idempotency_key = stable_garmin_idempotency_key


__all__ = [
    "GARMIN_NORMALIZATION_CONTRACT_VERSION",
    "NORMALIZATION_CONTRACT_VERSION",
    "GarminDiagnostic",
    "GarminFieldState",
    "GarminMetricDTO",
    "GarminNormalizationResult",
    "GarminParseStatus",
    "GarminRecordDTO",
    "GarminSleepStageDTO",
    "GarminSourceIdentity",
    "GarminTemporalDTO",
    "GarminTemporalPrecision",
    "GarminUnknownFieldDTO",
    "garmin_record_idempotency_key",
    "garmin_semantic_idempotency_key",
    "garmin_source_identity",
    "garmin_source_instance_id",
    "normalize_fixture",
    "normalize_garmin_payload",
    "normalize_synthetic_fixture",
    "normalize_synthetic_garmin_payload",
    "parse_garmin_time",
    "parse_garmin_timestamp",
    "parse_synthetic_garmin_payload",
    "stable_garmin_idempotency_key",
    "stable_idempotency_key",
]
