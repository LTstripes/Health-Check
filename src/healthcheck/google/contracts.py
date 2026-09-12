"""Offline R04 Google Health persistence contracts.

These types describe synthetic identity, query context, and a minimum
typed-record shell.  They are not a live client, OAuth flow, or full
health-normalization parser.
"""

from __future__ import annotations

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
NORMALIZATION_CONTRACT_VERSION = "r04-google-persistence-shell-v1"
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
                raise ValueError(
                    "family-aggregate Google evidence cannot claim device attribution"
                )
            for field_name in (
                "device_code",
                "device_manufacturer",
                "device_model",
                "device_uid",
            ):
                if getattr(self, field_name) is not None:
                    raise ValueError(
                        "family-aggregate Google evidence cannot invent device fields"
                    )
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "precision", GoogleTemporalPrecision(self.precision))
        offset = self.source_utc_offset_minutes
        if offset is not None and (offset < -1439 or offset > 1439):
            raise ValueError("Google source UTC offset must be between -1439 and 1439 minutes")
        if self.precision is GoogleTemporalPrecision.INSTANT and self.measured_at_utc is None:
            raise ValueError("instant Google evidence requires a UTC timestamp")
        if self.precision is GoogleTemporalPrecision.LOCAL and not self.local_wall_time:
            raise ValueError("local Google evidence requires a local wall time")


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream", GoogleStream(self.stream))
        object.__setattr__(
            self, "idempotency_key", _required_text(self.idempotency_key, "idempotency_key")
        )
        object.__setattr__(self, "status", GooglePayloadStatus(self.status))
        if self.record_index is not None and self.record_index < 0:
            raise ValueError("Google record_index must be nonnegative")
        object.__setattr__(self, "metrics", tuple(self.metrics))


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
    "GooglePayloadStatus",
    "GoogleQueryContext",
    "GoogleQueryMode",
    "GoogleRecordDTO",
    "GoogleSourceIdentity",
    "GoogleSourceKind",
    "GoogleStream",
    "GoogleTemporalDTO",
    "GoogleTemporalPrecision",
]
