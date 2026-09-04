"""Static Garmin/Vivoactive 5 capability inventory.

This module is deliberately a data-only R02 preparation boundary.  It does
not import a Garmin client, create a client, read credentials, make network
requests, persist data, or perform backfill.  The client method and field
columns describe a possible source surface only; they are never used as
device evidence.

``audit_status`` is the status recorded by the R00 static source/device
review.  ``owner_account_verification`` remains ``not_run`` in this slice,
because no live Garmin account is accessed here.  A later ingestion task must
require an attributed payload from the target device/account before retaining
a value as Vivoactive 5-produced.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

CAPABILITY_CONTRACT_VERSION = "r02-garmin-capability-contract-v1"
GARMIN_PROVIDER_CODE = "garmin_connect"
GARMINCONNECT_VERSION = "0.3.12"
VIVOACTIVE_5_DEVICE_CODE = "garmin_vivoactive_5"
VIVOACTIVE_5_MODEL = "Vivoactive 5"
OWNER_ACCOUNT_VERIFICATION_NOT_RUN = "not_run"


class GarminStream(StrEnum):
    """Typed source stream names used by the future R02 adapter."""

    DAILY_HEALTH = "daily_health"
    SLEEP = "sleep"
    ACTIVITY = "activity"
    INTRADAY = "intraday"
    ORIGINAL_FIT = "original_fit"


class DeviceSupport(StrEnum):
    """What the R00 review says about the physical target device."""

    SUPPORTED = "supported"
    CONDITIONAL = "conditional"
    WATCH_ONLY = "watch_only"
    NOT_SUPPORTED = "not_supported"
    NOT_DEVICE_PRODUCED = "not_device_produced"
    PARTICIPANT_ONLY = "participant_only"
    UNKNOWN = "unknown"


class CapabilityStatus(StrEnum):
    """R00 matrix disposition, kept separate from client surface details."""

    VERIFIED = "verified"
    VERIFIED_CONDITIONAL = "verified_conditional"
    WATCH_ONLY = "watch_only"
    UNAVAILABLE = "unavailable"
    NOT_DEVICE_PRODUCED = "not_device_produced"
    PARTICIPANT_ONLY = "participant_only"
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class GarminCapability:
    """One static row of the Garmin/Vivoactive 5 capability matrix.

    ``client_methods`` and ``client_fields`` intentionally have no bearing on
    ``audit_status``.  They are included so a future adapter can map source
    responses without silently turning a library schema into device support.
    """

    code: str
    display_name: str
    stream: GarminStream
    device_support: DeviceSupport
    watch_summary: str
    connect_surface: str
    audit_status: CapabilityStatus
    client_methods: tuple[str, ...] = ()
    client_fields: tuple[str, ...] = ()
    owner_account_verification: str = OWNER_ACCOUNT_VERIFICATION_NOT_RUN
    observation_requirement: str = (
        "Require a payload value attributed to the target device/account; "
        "client method or field presence alone is insufficient."
    )
    notes: str = ""
    live_spike_questions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        code = self.code.strip()
        if not code:
            raise ValueError("Garmin capability code is required")
        if any(character.isupper() or character.isspace() for character in code):
            raise ValueError("Garmin capability code must be lowercase and contain no spaces")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "display_name", _required_text(self.display_name, "display_name"))
        object.__setattr__(self, "stream", GarminStream(self.stream))
        object.__setattr__(self, "device_support", DeviceSupport(self.device_support))
        object.__setattr__(self, "audit_status", CapabilityStatus(self.audit_status))
        object.__setattr__(
            self, "watch_summary", _required_text(self.watch_summary, "watch_summary")
        )
        object.__setattr__(
            self,
            "connect_surface",
            _required_text(self.connect_surface, "connect_surface"),
        )
        object.__setattr__(
            self,
            "client_methods",
            _text_tuple(self.client_methods, "client_methods"),
        )
        object.__setattr__(
            self,
            "client_fields",
            _text_tuple(self.client_fields, "client_fields"),
        )
        object.__setattr__(
            self,
            "owner_account_verification",
            _required_text(self.owner_account_verification, "owner_account_verification"),
        )
        object.__setattr__(
            self,
            "observation_requirement",
            _required_text(self.observation_requirement, "observation_requirement"),
        )
        object.__setattr__(self, "notes", self.notes.strip())
        object.__setattr__(
            self,
            "live_spike_questions",
            _text_tuple(self.live_spike_questions, "live_spike_questions"),
        )

    @property
    def status(self) -> CapabilityStatus:
        """Compatibility alias for callers that call the matrix status ``status``."""

        return self.audit_status

    @property
    def method_presence_is_device_evidence(self) -> bool:
        """Always false: endpoint/schema presence is not a device proof."""

        return False

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe row without inventing live verification."""

        return {
            "code": self.code,
            "display_name": self.display_name,
            "stream": self.stream.value,
            "device_support": self.device_support.value,
            "watch_summary": self.watch_summary,
            "connect_surface": self.connect_surface,
            "client_methods": list(self.client_methods),
            "client_fields": list(self.client_fields),
            "audit_status": self.audit_status.value,
            "owner_account_verification": self.owner_account_verification,
            "method_presence_is_device_evidence": self.method_presence_is_device_evidence,
            "observation_requirement": self.observation_requirement,
            "notes": self.notes,
            "live_spike_questions": list(self.live_spike_questions),
        }


@dataclass(frozen=True, slots=True)
class GarminCapabilityInventory:
    """Immutable inventory metadata and its ordered capability rows."""

    provider_code: str
    device_code: str
    device_model: str
    client_name: str
    client_version: str
    contract_version: str
    capabilities: tuple[GarminCapability, ...]
    owner_account_verification: str = OWNER_ACCOUNT_VERIFICATION_NOT_RUN

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider_code", _required_text(self.provider_code, "provider_code")
        )
        object.__setattr__(self, "device_code", _required_text(self.device_code, "device_code"))
        object.__setattr__(self, "device_model", _required_text(self.device_model, "device_model"))
        object.__setattr__(self, "client_name", _required_text(self.client_name, "client_name"))
        object.__setattr__(
            self, "client_version", _required_text(self.client_version, "client_version")
        )
        object.__setattr__(
            self, "contract_version", _required_text(self.contract_version, "contract_version")
        )
        capabilities = tuple(self.capabilities)
        if not capabilities:
            raise ValueError("Garmin capability inventory cannot be empty")
        codes = [item.code for item in capabilities]
        if len(codes) != len(set(codes)):
            raise ValueError("Garmin capability codes must be unique")
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(
            self,
            "owner_account_verification",
            _required_text(self.owner_account_verification, "owner_account_verification"),
        )

    def __iter__(self) -> Iterator[GarminCapability]:
        return iter(self.capabilities)

    def __len__(self) -> int:
        return len(self.capabilities)

    def __getitem__(self, index: int) -> GarminCapability:
        return self.capabilities[index]

    def get(self, code: str) -> GarminCapability:
        normalized = _normalize_code(code)
        for capability in self.capabilities:
            if capability.code == normalized:
                return capability
        raise KeyError(f"unknown Garmin capability: {code}")

    def live_spike_questions(self) -> tuple[str, ...]:
        """Return de-duplicated future live-spike questions in matrix order."""

        questions: list[str] = []
        for capability in self.capabilities:
            for question in capability.live_spike_questions:
                if question not in questions:
                    questions.append(question)
        return tuple(questions)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_code": self.provider_code,
            "device_code": self.device_code,
            "device_model": self.device_model,
            "client_name": self.client_name,
            "client_version": self.client_version,
            "contract_version": self.contract_version,
            "owner_account_verification": self.owner_account_verification,
            "capabilities": [item.as_dict() for item in self.capabilities],
        }


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Garmin {name} is required")
    return value.strip()


def _text_tuple(values: Sequence[str], name: str) -> tuple[str, ...]:
    result = tuple(_required_text(value, name) for value in values)
    if len(result) != len(set(result)):
        raise ValueError(f"Garmin {name} must not contain duplicates")
    return result


_LIVE_AUTH_AND_RECONNECT = (
    "Prove owner-region login/MFA, token refresh/reconnect, and Windows at-rest storage "
    "in the owner-controlled live environment."
)
_LIVE_BACKFILL = (
    "Probe backfill depth, rate limits, and a safe trailing reconciliation window per stream."
)
_LIVE_ACCOUNT_AVAILABILITY = (
    "Record actual payload availability and device attribution for this capability when "
    "Vivoactive 5 is the only source device."
)


GARMIN_CAPABILITY_INVENTORY = GarminCapabilityInventory(
    provider_code=GARMIN_PROVIDER_CODE,
    device_code=VIVOACTIVE_5_DEVICE_CODE,
    device_model=VIVOACTIVE_5_MODEL,
    client_name="python-garminconnect",
    client_version=GARMINCONNECT_VERSION,
    contract_version=CAPABILITY_CONTRACT_VERSION,
    capabilities=(
        GarminCapability(
            code="sleep",
            display_name="Sleep",
            stream=GarminStream.SLEEP,
            device_support=DeviceSupport.SUPPORTED,
            watch_summary="Yes",
            connect_surface="Detailed sleep",
            client_methods=("get_sleep_data",),
            audit_status=CapabilityStatus.VERIFIED,
            notes=(
                "Static R00 source/device review; owner payload remains unverified in this slice."
            ),
            live_spike_questions=(
                _LIVE_AUTH_AND_RECONNECT,
                _LIVE_BACKFILL,
                _LIVE_ACCOUNT_AVAILABILITY,
            ),
        ),
        GarminCapability(
            code="sleep_score",
            display_name="Sleep Score",
            stream=GarminStream.SLEEP,
            device_support=DeviceSupport.SUPPORTED,
            watch_summary="Yes",
            connect_surface="Sleep payload overall score",
            client_methods=("get_sleep_data",),
            client_fields=("sleepScore",),
            audit_status=CapabilityStatus.VERIFIED,
            notes="Keep provider-native score distinct from any future Health-Check score.",
            live_spike_questions=(_LIVE_ACCOUNT_AVAILABILITY,),
        ),
        GarminCapability(
            code="sleep_stages",
            display_name="Sleep stages",
            stream=GarminStream.SLEEP,
            device_support=DeviceSupport.SUPPORTED,
            watch_summary="Yes",
            connect_surface="Raw levels and stage totals",
            client_methods=("get_sleep_data",),
            client_fields=("levels",),
            audit_status=CapabilityStatus.VERIFIED,
            live_spike_questions=(_LIVE_ACCOUNT_AVAILABILITY,),
        ),
        GarminCapability(
            code="naps",
            display_name="Naps",
            stream=GarminStream.SLEEP,
            device_support=DeviceSupport.CONDITIONAL,
            watch_summary="Timer/total; included in sleep statistics",
            connect_surface="Watch/app/web totals and events",
            client_methods=("get_sleep_data", "get_body_battery_events"),
            client_fields=("napTimeSeconds",),
            audit_status=CapabilityStatus.VERIFIED_CONDITIONAL,
            notes="Totals/events are verified by the static audit; exact intervals are not.",
            live_spike_questions=(
                "Verify exact nap interval representation and timezone behavior in owner payloads.",
            ),
        ),
        GarminCapability(
            code="heart_rate",
            display_name="Heart rate",
            stream=GarminStream.INTRADAY,
            device_support=DeviceSupport.SUPPORTED,
            watch_summary="Wrist and activity heart rate",
            connect_surface="Daily history and activity/FIT records",
            client_methods=("get_heart_rates",),
            audit_status=CapabilityStatus.VERIFIED,
            live_spike_questions=(_LIVE_BACKFILL, _LIVE_ACCOUNT_AVAILABILITY),
        ),
        GarminCapability(
            code="resting_heart_rate",
            display_name="Resting heart rate",
            stream=GarminStream.DAILY_HEALTH,
            device_support=DeviceSupport.SUPPORTED,
            watch_summary="Current and seven-day watch view",
            connect_surface="Daily history",
            client_methods=("get_rhr_day",),
            audit_status=CapabilityStatus.VERIFIED,
            live_spike_questions=(_LIVE_ACCOUNT_AVAILABILITY,),
        ),
        GarminCapability(
            code="hrv_status",
            display_name="HRV / HRV Status",
            stream=GarminStream.DAILY_HEALTH,
            device_support=DeviceSupport.SUPPORTED,
            watch_summary="Overnight after baseline",
            connect_surface="Status and trends",
            client_methods=("get_hrv_data",),
            audit_status=CapabilityStatus.VERIFIED,
            live_spike_questions=(_LIVE_ACCOUNT_AVAILABILITY,),
        ),
        GarminCapability(
            code="stress",
            display_name="Stress",
            stream=GarminStream.INTRADAY,
            device_support=DeviceSupport.SUPPORTED,
            watch_summary="Yes",
            connect_surface="Daily timeline",
            client_methods=("get_stress_data",),
            audit_status=CapabilityStatus.VERIFIED,
            live_spike_questions=(_LIVE_ACCOUNT_AVAILABILITY,),
        ),
        GarminCapability(
            code="body_battery",
            display_name="Body Battery",
            stream=GarminStream.INTRADAY,
            device_support=DeviceSupport.SUPPORTED,
            watch_summary="Yes",
            connect_surface="Trends and events",
            client_methods=("get_body_battery_events",),
            client_fields=("bodyBatteryChargedValue", "bodyBatteryDrainedValue"),
            audit_status=CapabilityStatus.VERIFIED,
            live_spike_questions=(_LIVE_ACCOUNT_AVAILABILITY,),
        ),
        GarminCapability(
            code="spo2",
            display_name="SpO2",
            stream=GarminStream.INTRADAY,
            device_support=DeviceSupport.CONDITIONAL,
            watch_summary="Spot/all-day/sleep depending on setting and region",
            connect_surface="Trends",
            client_methods=("get_spo2_data",),
            audit_status=CapabilityStatus.VERIFIED_CONDITIONAL,
            live_spike_questions=(
                "Verify setting/region-dependent SpO2 availability, sampling, and "
                "sleep payload semantics.",
            ),
        ),
        GarminCapability(
            code="respiration",
            display_name="Respiration",
            stream=GarminStream.INTRADAY,
            device_support=DeviceSupport.CONDITIONAL,
            watch_summary="Current/sleep/all-day with activity-type limits",
            connect_surface="Daily and sleep records",
            client_methods=("get_respiration_data",),
            audit_status=CapabilityStatus.VERIFIED_CONDITIONAL,
            live_spike_questions=(
                "Verify activity-type limits, sampling, and sleep/all-day respiration semantics.",
            ),
        ),
        GarminCapability(
            code="vo2_max",
            display_name="VO2 Max",
            stream=GarminStream.DAILY_HEALTH,
            device_support=DeviceSupport.SUPPORTED,
            watch_summary="Running estimate",
            connect_surface="Max metrics",
            client_methods=("get_max_metrics",),
            audit_status=CapabilityStatus.UNVERIFIED,
            notes="Watch/endpoint surface is reviewed; owner payload availability is not.",
            live_spike_questions=(_LIVE_ACCOUNT_AVAILABILITY,),
        ),
        GarminCapability(
            code="recovery_time",
            display_name="Recovery Time",
            stream=GarminStream.ORIGINAL_FIT,
            device_support=DeviceSupport.WATCH_ONLY,
            watch_summary="Yes, on-watch up to four days",
            connect_surface="Not promised in Connect for a sole Vivoactive 5 account",
            client_fields=("recoveryTimeSeconds",),
            audit_status=CapabilityStatus.WATCH_ONLY,
            notes="Possible ORIGINAL FIT field; no dedicated client method is evidence.",
            live_spike_questions=(
                "Inspect a downloaded ORIGINAL FIT file for Recovery Time; keep it "
                "unverified if absent or ambiguous.",
            ),
        ),
        GarminCapability(
            code="training_readiness",
            display_name="Training Readiness",
            stream=GarminStream.DAILY_HEALTH,
            device_support=DeviceSupport.NOT_SUPPORTED,
            watch_summary="No for Vivoactive 5 under the reviewed classification",
            connect_surface="No Vivoactive 5-produced value",
            client_methods=("get_training_readiness",),
            audit_status=CapabilityStatus.UNAVAILABLE,
            notes=(
                "The library method exists, but this row remains unavailable for a "
                "sole Vivoactive 5."
            ),
            live_spike_questions=(
                "Confirm that a sole-Vivoactive-5 account does not expose a "
                "provider-produced value.",
            ),
        ),
        GarminCapability(
            code="training_status",
            display_name="Training Status",
            stream=GarminStream.DAILY_HEALTH,
            device_support=DeviceSupport.NOT_DEVICE_PRODUCED,
            watch_summary="Garmin classifies Vivoactive 5 as non-compatible",
            connect_surface="May appear only if another compatible device computes it",
            client_methods=("get_training_status",),
            audit_status=CapabilityStatus.NOT_DEVICE_PRODUCED,
            notes="Account-level presence must not be labelled as Vivoactive 5 evidence.",
            live_spike_questions=(
                "Check for any account-level value while the Vivoactive 5 is the "
                "only wearable; do not attribute it automatically.",
            ),
        ),
        GarminCapability(
            code="unified_training_status",
            display_name="Unified Training Status",
            stream=GarminStream.DAILY_HEALTH,
            device_support=DeviceSupport.PARTICIPANT_ONLY,
            watch_summary="Primary wearable may participate; cannot provide status alone",
            connect_surface="Account-level with another compatible device",
            audit_status=CapabilityStatus.PARTICIPANT_ONLY,
            notes="Participation is not production of Training Status by this device.",
            live_spike_questions=(
                "Identify all contributing devices before interpreting any account-level "
                "unified status.",
            ),
        ),
        GarminCapability(
            code="training_effect",
            display_name="Training Effect",
            stream=GarminStream.ACTIVITY,
            device_support=DeviceSupport.UNKNOWN,
            watch_summary="Not documented for Vivoactive 5 in the reviewed manual/comparison",
            connect_surface="Sole-Vivoactive-5 behavior unverified",
            client_fields=("trainingEffect",),
            audit_status=CapabilityStatus.UNVERIFIED,
            notes="Typed activity field presence is not device evidence.",
            live_spike_questions=(
                "Verify whether sole-Vivoactive-5 activities contain Training Effect "
                "and what produces the field.",
            ),
        ),
        GarminCapability(
            code="acute_training_load",
            display_name="Acute/Training Load",
            stream=GarminStream.ACTIVITY,
            device_support=DeviceSupport.UNKNOWN,
            watch_summary="Not documented for Vivoactive 5 in the reviewed manual/comparison",
            connect_surface="Sole-Vivoactive-5 behavior unverified",
            client_fields=("trainingLoad",),
            audit_status=CapabilityStatus.UNVERIFIED,
            notes="Typed activity field presence is not device evidence.",
            live_spike_questions=(
                "Verify whether sole-Vivoactive-5 activities contain Acute/Training "
                "Load and what produces the field.",
            ),
        ),
        GarminCapability(
            code="activities",
            display_name="Activities",
            stream=GarminStream.ACTIVITY,
            device_support=DeviceSupport.SUPPORTED,
            watch_summary="GPS and activity profiles",
            connect_surface="Activity list, details, and downloads",
            client_methods=("get_activities_by_date", "download_activity"),
            audit_status=CapabilityStatus.VERIFIED,
            live_spike_questions=(_LIVE_BACKFILL, _LIVE_ACCOUNT_AVAILABILITY),
        ),
        GarminCapability(
            code="cycling_metrics",
            display_name="Cycling metrics",
            stream=GarminStream.ACTIVITY,
            device_support=DeviceSupport.CONDITIONAL,
            watch_summary="Basic speed/distance/HR; cadence accessory and eBike fields",
            connect_surface="Recorded activity fields and FIT download",
            client_methods=("get_activities_by_date", "download_activity"),
            client_fields=("speed", "distance", "heartRate", "cadence", "power", "cyclingDynamics"),
            audit_status=CapabilityStatus.VERIFIED_CONDITIONAL,
            notes="Basic metrics are reviewed; power/dynamics/cycling VO2 remain unverified.",
            live_spike_questions=(
                "Verify cycling power, advanced dynamics, cycling VO2, accessory "
                "attribution, and eBike fields for this setup.",
            ),
        ),
    ),
)

CAPABILITY_MATRIX: tuple[GarminCapability, ...] = GARMIN_CAPABILITY_INVENTORY.capabilities

# Common aliases are intentionally read-only convenience names; they do not
# create a second source of truth for the matrix.
_CAPABILITY_ALIASES = {
    "hr": "heart_rate",
    "rhr": "resting_heart_rate",
    "hrv": "hrv_status",
    "training_load": "acute_training_load",
}


def capability_inventory() -> GarminCapabilityInventory:
    """Return the immutable R02 inventory; no runtime discovery is performed."""

    return GARMIN_CAPABILITY_INVENTORY


def capability_matrix() -> tuple[dict[str, Any], ...]:
    """Return JSON-safe matrix rows for reports or contract tests."""

    return tuple(item.as_dict() for item in CAPABILITY_MATRIX)


def get_capability(code: str) -> GarminCapability:
    """Look up one row without inferring support from a method name."""

    normalized = _normalize_code(code)
    return GARMIN_CAPABILITY_INVENTORY.get(normalized)


def live_spike_questions() -> tuple[str, ...]:
    """Return the deduplicated future owner-controlled live-spike checklist."""

    return GARMIN_CAPABILITY_INVENTORY.live_spike_questions()


def _normalize_code(code: str) -> str:
    if not isinstance(code, str):
        raise TypeError("Garmin capability code must be text")
    normalized = code.strip().lower()
    return _CAPABILITY_ALIASES.get(normalized, normalized)


__all__ = [
    "CAPABILITY_CONTRACT_VERSION",
    "CAPABILITY_MATRIX",
    "GARMIN_CAPABILITY_INVENTORY",
    "GARMINCONNECT_VERSION",
    "GARMIN_PROVIDER_CODE",
    "VIVOACTIVE_5_DEVICE_CODE",
    "VIVOACTIVE_5_MODEL",
    "CapabilityStatus",
    "DeviceSupport",
    "GarminCapability",
    "GarminCapabilityInventory",
    "GarminStream",
    "capability_inventory",
    "capability_matrix",
    "get_capability",
    "live_spike_questions",
]
