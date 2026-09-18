"""Offline R04 Google Health identity and typed-normalization contracts.

The DTOs in this module are deliberately Google-specific.  They describe
immutable, already-acquired evidence and its typed projection; they do not
make provider calls, perform sync, or implement R05 cross-source
canonicalization.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from healthcheck.db.models import (
    GoogleMetricState,
    GooglePayloadStatus,
    GoogleQueryMode,
    GoogleSourceKind,
)

GOOGLE_PROVIDER_CODE = "google_health"
SOURCE_CONTRACT_VERSION = "r04-google-source-contract-v1"
PERSISTENCE_CONTRACT_VERSION = "r04-google-persistence-contract-v1"
NORMALIZATION_CONTRACT_VERSION = "r04-google-persistence-shell-v2"
OBSERVATION_KEY_VERSION = "google-observation-v1"
GOOGLE_INPUT_METHOD = "provider_api"
GOOGLE_SOURCE_APPLICATION = "google-health-api"

FAMILY_GOOGLE_WEARABLES = "users/me/dataSourceFamilies/google-wearables"
FAMILY_GOOGLE_SOURCES = "users/me/dataSourceFamilies/google-sources"
FAMILY_ALL_SOURCES = "users/me/dataSourceFamilies/all-sources"
KNOWN_DATA_SOURCE_FAMILIES = (
    FAMILY_GOOGLE_WEARABLES,
    FAMILY_GOOGLE_SOURCES,
    FAMILY_ALL_SOURCES,
)

GOOGLE_STREAMS = (
    "sleep",
    "heart_rate",
    "hrv",
    "daily_hrv",
    "daily_resting_hr",
    "spo2",
    "daily_spo2",
    "respiratory_rate_sleep",
    "daily_respiratory_rate",
)


class GoogleStream(StrEnum):
    """Initial R04 Google Health stream codes."""

    SLEEP = "sleep"
    HEART_RATE = "heart_rate"
    HRV = "hrv"
    DAILY_HRV = "daily_hrv"
    DAILY_RESTING_HR = "daily_resting_hr"
    SPO2 = "spo2"
    DAILY_SPO2 = "daily_spo2"
    RESPIRATORY_RATE_SLEEP = "respiratory_rate_sleep"
    DAILY_RESPIRATORY_RATE = "daily_respiratory_rate"


class GoogleTemporalPrecision(StrEnum):
    UNKNOWN = "unknown"
    DATE = "date"
    INSTANT = "instant"
    LOCAL = "local"


class GoogleIntervalKind(StrEnum):
    """Explicit interval kinds retained by the Google projection."""

    ROLL_UP = "roll_up"
    DAILY_ROLL_UP = "daily_roll_up"
    SLEEP_SESSION = "sleep_session"
    SLEEP_OUT_OF_BED = "sleep_out_of_bed"


@dataclass(frozen=True, slots=True)
class GoogleSourceIdentity:
    """Stable provider/source/device identity from explicit metadata only."""

    source_kind: GoogleSourceKind
    source_instance_id: str
    provider_code: str = GOOGLE_PROVIDER_CODE
    data_source_name: str | None = None
    data_source_id: str | None = None
    platform: str | None = None
    recording_method: str | None = None
    device_attributed: bool = False
    device_code: str | None = None
    device_manufacturer: str | None = None
    device_model: str | None = None
    device_uid: str | None = None
    source_contract_version: str = SOURCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        kind = GoogleSourceKind(self.source_kind)
        object.__setattr__(self, "source_kind", kind)
        instance = _required_text(self.source_instance_id, "Google source_instance_id")
        object.__setattr__(self, "source_instance_id", instance)
        provider = _required_text(self.provider_code, "Google provider_code")
        if provider != GOOGLE_PROVIDER_CODE:
            raise ValueError("Google persistence uses provider_code google_health")
        object.__setattr__(self, "provider_code", provider)
        if kind is GoogleSourceKind.FAMILY_AGGREGATE:
            _validate_data_source_family(instance)
            if self.device_attributed:
                raise ValueError("family-aggregate Google evidence cannot claim device attribution")
            for field_name in (
                "device_code",
                "device_manufacturer",
                "device_model",
                "device_uid",
            ):
                if getattr(self, field_name) is not None:
                    raise ValueError("family-aggregate Google evidence cannot invent device fields")
            return
        if self.device_attributed:
            if not self.device_code or not self.device_model:
                raise ValueError(
                    "attributed Google identity requires explicit device_code and device_model"
                )
        else:
            for field_name in (
                "device_code",
                "device_manufacturer",
                "device_model",
                "device_uid",
            ):
                if getattr(self, field_name) is not None:
                    raise ValueError(
                        "unattributed Google identity cannot carry invented device fields"
                    )


@dataclass(frozen=True, slots=True)
class GoogleQueryContext:
    """Acquisition/query context. Not stable source identity."""

    query_mode: GoogleQueryMode
    data_source_family: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_mode", GoogleQueryMode(self.query_mode))
        family = self.data_source_family
        if family is not None:
            object.__setattr__(self, "data_source_family", _validate_data_source_family(family))


@dataclass(frozen=True, slots=True)
class GoogleTemporalDTO:
    """UTC + local/offset/date-only evidence for one typed record."""

    precision: GoogleTemporalPrecision = GoogleTemporalPrecision.UNKNOWN
    local_date: date | None = None
    measured_at_utc: datetime | None = None
    local_wall_time: str | None = None
    source_local_timestamp: str | None = None
    source_utc_offset_minutes: int | None = None
    source_timezone: str | None = None
    source_field: str | None = None
    source_local_field: str | None = None
    source_utc_field: str | None = None
    state: GoogleMetricState = GoogleMetricState.VALUE

    def __post_init__(self) -> None:
        object.__setattr__(self, "precision", GoogleTemporalPrecision(self.precision))
        object.__setattr__(self, "state", GoogleMetricState(self.state))
        offset = self.source_utc_offset_minutes
        if offset is not None and (
            not isinstance(offset, int)
            or isinstance(offset, bool)
            or offset < -1439
            or offset > 1439
        ):
            raise ValueError("Google source UTC offset must be between -1439 and 1439 minutes")
        if self.precision is GoogleTemporalPrecision.INSTANT and self.measured_at_utc is None:
            raise ValueError("instant Google evidence requires a UTC timestamp")
        if self.precision is GoogleTemporalPrecision.LOCAL and not self.local_wall_time:
            raise ValueError("local Google evidence requires a local wall time")

    def as_dict(self) -> dict[str, object]:
        return {
            "precision": self.precision.value,
            "state": self.state.value,
            "local_date": self.local_date.isoformat() if self.local_date is not None else None,
            "measured_at_utc": (
                self.measured_at_utc.isoformat() if self.measured_at_utc is not None else None
            ),
            "local_wall_time": self.local_wall_time,
            "source_local_timestamp": self.source_local_timestamp,
            "source_utc_offset_minutes": self.source_utc_offset_minutes,
            "source_timezone": self.source_timezone,
            "source_field": self.source_field,
            "source_local_field": self.source_local_field,
            "source_utc_field": self.source_utc_field,
        }


@dataclass(frozen=True, slots=True)
class GoogleMetricDTO:
    """Minimum metric shell with missing/null/value/invalid state."""

    metric_code: str
    field_path: str
    state: GoogleMetricState
    value_number: float | None = None
    value_text: str | None = None
    unit: str | None = None
    reason: str | None = None
    collection_json: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_code", _required_text(self.metric_code, "metric_code"))
        object.__setattr__(self, "field_path", _required_text(self.field_path, "field_path"))
        object.__setattr__(self, "state", GoogleMetricState(self.state))
        if self.state is not GoogleMetricState.VALUE:
            if (
                self.value_number is not None
                or self.value_text is not None
                or self.collection_json is not None
            ):
                raise ValueError("non-value Google metric state cannot carry a value")

    def as_dict(self) -> dict[str, object]:
        return {
            "metric_code": self.metric_code,
            "field_path": self.field_path,
            "state": self.state.value,
            "value_number": self.value_number,
            "value_text": self.value_text,
            "unit": self.unit,
            "reason": self.reason,
            "collection_json": self.collection_json,
        }


@dataclass(frozen=True, slots=True)
class GoogleDataSourceDTO:
    """Source metadata embedded in one Google ``DataPoint``.

    This is evidence only.  It never creates or upgrades a stable physical
    device identity.  Device attribution remains the responsibility of the
    explicit :class:`GoogleSourceIdentity` supplied by the caller.
    """

    state: GoogleMetricState = GoogleMetricState.MISSING
    field_path: str = "$.dataSource"
    fields: tuple[GoogleMetricDTO, ...] = field(default_factory=tuple)
    source_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", GoogleMetricState(self.state))
        object.__setattr__(
            self, "field_path", _required_text(self.field_path, "dataSource field_path")
        )
        normalized = tuple(self.fields)
        if any(not isinstance(item, GoogleMetricDTO) for item in normalized):
            raise TypeError("Google data-source fields must be GoogleMetricDTO values")
        if self.state is not GoogleMetricState.VALUE and normalized:
            raise ValueError("non-value Google dataSource state cannot carry nested fields")
        object.__setattr__(self, "fields", normalized)
        if self.source_name is not None:
            if not isinstance(self.source_name, str) or not self.source_name.strip():
                raise ValueError("Google data-source source_name must be text when supplied")
            object.__setattr__(self, "source_name", self.source_name.strip())

    def field(self, metric_code: str) -> GoogleMetricDTO | None:
        """Return one nested source field by its stable projection code."""

        return next((item for item in self.fields if item.metric_code == metric_code), None)

    @property
    def platform(self) -> GoogleMetricDTO | None:
        return self.field("data_source_platform")

    @property
    def recording_method(self) -> GoogleMetricDTO | None:
        return self.field("data_source_recording_method")

    @property
    def device_form_factor(self) -> GoogleMetricDTO | None:
        return self.field("data_source_device_form_factor")

    @property
    def device_manufacturer(self) -> GoogleMetricDTO | None:
        return self.field("data_source_device_manufacturer")

    @property
    def device_display_name(self) -> GoogleMetricDTO | None:
        return self.field("data_source_device_display_name")

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "field_path": self.field_path,
            "source_name": self.source_name,
            "fields": [item.as_dict() for item in self.fields],
        }


@dataclass(frozen=True, slots=True)
class GoogleIntervalDTO:
    """A typed Google interval retaining both endpoint temporal evidence."""

    start: GoogleTemporalDTO
    end: GoogleTemporalDTO
    interval_kind: GoogleIntervalKind
    state: GoogleMetricState = GoogleMetricState.VALUE

    def __post_init__(self) -> None:
        object.__setattr__(self, "interval_kind", GoogleIntervalKind(self.interval_kind))
        object.__setattr__(self, "state", GoogleMetricState(self.state))
        if not isinstance(self.start, GoogleTemporalDTO) or not isinstance(
            self.end, GoogleTemporalDTO
        ):
            raise TypeError("Google interval endpoints must be GoogleTemporalDTO values")

    def as_dict(self) -> dict[str, object]:
        return {
            "interval_kind": self.interval_kind.value,
            "state": self.state.value,
            "start": self.start.as_dict(),
            "end": self.end.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class GoogleSleepStageDTO:
    """One typed Google sleep-stage interval."""

    ordinal: int
    stage_type: str
    start: GoogleTemporalDTO
    end: GoogleTemporalDTO
    create_time: str | None = None
    update_time: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ordinal, int) or isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError("Google sleep-stage ordinal must be nonnegative")
        object.__setattr__(self, "stage_type", _required_text(self.stage_type, "sleep stage type"))
        if not isinstance(self.start, GoogleTemporalDTO) or not isinstance(
            self.end, GoogleTemporalDTO
        ):
            raise TypeError("Google sleep-stage endpoints must be GoogleTemporalDTO values")
        for field_name in ("create_time", "update_time"):
            value = getattr(self, field_name)
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"Google sleep-stage {field_name} must be text when supplied")
                object.__setattr__(self, field_name, value.strip())

    def as_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "stage_type": self.stage_type,
            "start": self.start.as_dict(),
            "end": self.end.as_dict(),
            "create_time": self.create_time,
            "update_time": self.update_time,
        }


@dataclass(frozen=True, slots=True)
class GoogleRecordDTO:
    """Minimum typed-record shell for later R04-03b normalization."""

    stream: GoogleStream
    idempotency_key: str
    temporal: GoogleTemporalDTO
    status: GooglePayloadStatus = GooglePayloadStatus.OK
    external_record_id: str | None = None
    record_index: int | None = None
    wake_date: date | None = None
    metrics: tuple[GoogleMetricDTO, ...] = field(default_factory=tuple)
    interval: GoogleIntervalDTO | None = None
    sleep_interval: GoogleIntervalDTO | None = None
    sleep_stages: tuple[GoogleSleepStageDTO, ...] = field(default_factory=tuple)
    sleep_stages_state: GoogleMetricState = GoogleMetricState.MISSING
    out_of_bed_segments: tuple[GoogleIntervalDTO, ...] = field(default_factory=tuple)
    out_of_bed_state: GoogleMetricState = GoogleMetricState.MISSING
    data_source: GoogleDataSourceDTO | None = None
    diagnostics: tuple[Mapping[str, object], ...] = field(default_factory=tuple)
    unknown_fields: tuple[Mapping[str, object], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream", GoogleStream(self.stream))
        object.__setattr__(
            self, "idempotency_key", _required_text(self.idempotency_key, "idempotency_key")
        )
        object.__setattr__(self, "status", GooglePayloadStatus(self.status))
        if self.record_index is not None and self.record_index < 0:
            raise ValueError("Google record_index must be nonnegative")
        object.__setattr__(self, "metrics", tuple(self.metrics))
        if any(not isinstance(item, GoogleMetricDTO) for item in self.metrics):
            raise TypeError("Google record metrics must be GoogleMetricDTO values")
        for field_name in ("interval", "sleep_interval"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, GoogleIntervalDTO):
                raise TypeError(f"Google {field_name} must be a GoogleIntervalDTO")
        stages = tuple(self.sleep_stages)
        if any(not isinstance(item, GoogleSleepStageDTO) for item in stages):
            raise TypeError("Google sleep stages must be GoogleSleepStageDTO values")
        object.__setattr__(self, "sleep_stages", stages)
        object.__setattr__(self, "sleep_stages_state", GoogleMetricState(self.sleep_stages_state))
        out_of_bed = tuple(self.out_of_bed_segments)
        if any(not isinstance(item, GoogleIntervalDTO) for item in out_of_bed):
            raise TypeError("Google out-of-bed segments must be GoogleIntervalDTO values")
        object.__setattr__(self, "out_of_bed_segments", out_of_bed)
        object.__setattr__(self, "out_of_bed_state", GoogleMetricState(self.out_of_bed_state))
        if self.data_source is not None and not isinstance(self.data_source, GoogleDataSourceDTO):
            raise TypeError("Google data_source must be a GoogleDataSourceDTO")
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(self, "unknown_fields", tuple(self.unknown_fields))
        if any(not isinstance(item, Mapping) for item in self.diagnostics):
            raise TypeError("Google record diagnostics must be mappings")
        if any(not isinstance(item, Mapping) for item in self.unknown_fields):
            raise TypeError("Google record unknown fields must be mappings")

    def as_dict(self) -> dict[str, object]:
        return {
            "stream": self.stream.value,
            "idempotency_key": self.idempotency_key,
            "external_record_id": self.external_record_id,
            "record_index": self.record_index,
            "status": self.status.value,
            "wake_date": self.wake_date.isoformat() if self.wake_date is not None else None,
            "temporal": self.temporal.as_dict(),
            "metrics": [item.as_dict() for item in self.metrics],
            "interval": self.interval.as_dict() if self.interval is not None else None,
            "sleep_interval": (
                self.sleep_interval.as_dict() if self.sleep_interval is not None else None
            ),
            "sleep_stages_state": self.sleep_stages_state.value,
            "sleep_stages": [item.as_dict() for item in self.sleep_stages],
            "out_of_bed_state": self.out_of_bed_state.value,
            "out_of_bed_segments": [item.as_dict() for item in self.out_of_bed_segments],
            "data_source": self.data_source.as_dict() if self.data_source is not None else None,
            "diagnostics": list(self.diagnostics),
            "unknown_fields": list(self.unknown_fields),
        }


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _validate_data_source_family(value: str) -> str:
    family = _required_text(value, "dataSourceFamily")
    if "/dataSourceFamilies/" not in family or not family.startswith("users/"):
        raise ValueError("dataSourceFamily must be a full users/.../dataSourceFamilies/... URI")
    return family


__all__ = [
    "FAMILY_ALL_SOURCES",
    "FAMILY_GOOGLE_SOURCES",
    "FAMILY_GOOGLE_WEARABLES",
    "GOOGLE_INPUT_METHOD",
    "GOOGLE_PROVIDER_CODE",
    "GOOGLE_SOURCE_APPLICATION",
    "GOOGLE_STREAMS",
    "KNOWN_DATA_SOURCE_FAMILIES",
    "NORMALIZATION_CONTRACT_VERSION",
    "OBSERVATION_KEY_VERSION",
    "PERSISTENCE_CONTRACT_VERSION",
    "SOURCE_CONTRACT_VERSION",
    "GoogleMetricDTO",
    "GoogleMetricState",
    "GoogleDataSourceDTO",
    "GoogleIntervalDTO",
    "GoogleIntervalKind",
    "GooglePayloadStatus",
    "GoogleQueryContext",
    "GoogleQueryMode",
    "GoogleRecordDTO",
    "GoogleSleepStageDTO",
    "GoogleSourceIdentity",
    "GoogleSourceKind",
    "GoogleStream",
    "GoogleTemporalDTO",
    "GoogleTemporalPrecision",
]
