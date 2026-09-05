"""Small allowlisted Garmin capability probe and sanitized report contract."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

from healthcheck.garmin.auth import (
    GarminAuthResult,
    GarminAuthStatus,
    GarminSafeError,
    _silence_provider_logging,
    classify_garmin_error,
)
from healthcheck.garmin.capabilities import (
    CAPABILITY_MATRIX,
    GARMIN_PROVIDER_CODE,
    GARMINCONNECT_VERSION,
    VIVOACTIVE_5_DEVICE_CODE,
    VIVOACTIVE_5_MODEL,
    GarminCapability,
)
from healthcheck.garmin.redaction import (
    GARMIN_SAFE_FIELD_PATHS,
    GarminDeviceAttribution,
    GarminPayloadShape,
    GarminValueState,
    field_state_at_path,
    field_state_counts,
    infer_device_attribution,
    summarize_garmin_payload,
)

PROBE_CONTRACT_VERSION = "r02-garmin-capability-spike-v1"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_PROVIDER_REQUESTS = 27
_ACTIVITY_DISCOVERY_METHOD = "connectapi"
_ACTIVITY_DISCOVERY_ENDPOINT_ATTRIBUTE = "garmin_connect_activities"
_ACTIVITY_DISCOVERY_ENDPOINT = "/activitylist-service/activities/search/activities"
_ACTIVITY_DETAIL_KWARGS = {"maxchart": 1, "maxpoly": 0}

_SLEEP_FIELD_PATHS = (
    "dailySleepDTO",
    "dailySleepDTO.sleepTimeSeconds",
    "dailySleepDTO.napTimeSeconds",
    "dailySleepDTO.deepSleepSeconds",
    "dailySleepDTO.lightSleepSeconds",
    "dailySleepDTO.remSleepSeconds",
    "dailySleepDTO.awakeSleepSeconds",
    "dailySleepDTO.avgSleepHRV",
    "dailySleepDTO.avgSpO2",
    "dailySleepDTO.avgRespirationValue",
    "dailySleepDTO.sleepScores",
    "dailySleepDTO.sleepScores.overall.value",
    "dailySleepDTO.sleepScores.totalDuration.value",
    "dailySleepDTO.sleepScores.stress.value",
    "dailySleepDTO.sleepScores.awakeCount.value",
    "dailySleepDTO.sleepScores.remPercentage.value",
    "dailySleepDTO.sleepScores.restlessness.value",
    "dailySleepDTO.sleepScores.lightPercentage.value",
    "dailySleepDTO.sleepScores.deepPercentage.value",
    "levels",
    "napEvents",
)
_SLEEP_METRIC_PATHS = (
    "dailySleepDTO.sleepTimeSeconds",
)
_SLEEP_SCORE_FIELD_PATHS = (
    "dailySleepDTO.sleepScores",
    "dailySleepDTO.sleepScores.overall.value",
    "dailySleepDTO.sleepScores.totalDuration.value",
    "dailySleepDTO.sleepScores.stress.value",
    "dailySleepDTO.sleepScores.awakeCount.value",
    "dailySleepDTO.sleepScores.remPercentage.value",
    "dailySleepDTO.sleepScores.restlessness.value",
    "dailySleepDTO.sleepScores.lightPercentage.value",
    "dailySleepDTO.sleepScores.deepPercentage.value",
)
_SLEEP_SCORE_METRIC_PATHS = (
    "dailySleepDTO.sleepScores.overall.value",
)
_SLEEP_STAGE_FIELD_PATHS = (
    "dailySleepDTO.deepSleepSeconds",
    "dailySleepDTO.lightSleepSeconds",
    "dailySleepDTO.remSleepSeconds",
    "dailySleepDTO.awakeSleepSeconds",
    "levels",
)
_SLEEP_STAGE_METRIC_PATHS = _SLEEP_STAGE_FIELD_PATHS
_NAP_FIELD_PATHS = (
    "dailySleepDTO.napTimeSeconds",
)
_NAP_METRIC_PATHS = _NAP_FIELD_PATHS
_HRV_FIELD_PATHS = (
    "hrvSummary",
    "hrvSummary.weeklyAvg",
    "hrvSummary.lastNightAvg",
    "hrvSummary.lastNight5MinHigh",
    "hrvSummary.status",
    "hrvSummary.baseline",
    "hrvSummary.baseline.lowUpper",
    "hrvSummary.baseline.balancedLow",
    "hrvSummary.baseline.balancedUpper",
    "hrvSummary.baseline.markerValue",
    "hrvReadings",
)
_HRV_METRIC_PATHS = (
    "hrvSummary.weeklyAvg",
    "hrvSummary.lastNightAvg",
    "hrvSummary.lastNight5MinHigh",
)
_ACTIVITY_FIELD_PATHS = (
    "activityType.typeKey",
    "activityType",
    "duration",
    "movingDuration",
    "elapsedDuration",
    "distance",
    "averageSpeed",
    "maxSpeed",
    "averageHR",
    "maxHR",
    "avgPower",
    "maxPower",
    "normPower",
    "aerobicTrainingEffect",
    "anaerobicTrainingEffect",
    "activityTrainingLoad",
    "trainingEffectLabel",
    "averageRunningCadenceInStepsPerMinute",
    "maxRunningCadenceInStepsPerMinute",
    "metricDescriptors",
    "metricDescriptors.0.key",
    "metricDescriptors.0.metricsIndex",
    "activityDetailMetrics",
    "activityDetailMetrics.0.metrics",
)
_ACTIVITY_METRIC_PATHS = (
    "activityType.typeKey",
    "duration",
    "movingDuration",
    "elapsedDuration",
    "distance",
    "averageSpeed",
    "maxSpeed",
    "averageHR",
    "maxHR",
    "avgPower",
    "maxPower",
    "normPower",
    "aerobicTrainingEffect",
    "anaerobicTrainingEffect",
    "activityTrainingLoad",
    "trainingEffectLabel",
    "averageRunningCadenceInStepsPerMinute",
    "maxRunningCadenceInStepsPerMinute",
)


class GarminProbeStatus(StrEnum):
    """Outcome of one allowlisted method/response observation."""

    NOT_RUN = "not_run"
    SUCCEEDED = "succeeded"
    EMPTY = "empty"
    NULL = "null"
    UNSUPPORTED = "unsupported"
    SHAPE_DRIFT = "shape_drift"
    METHOD_UNAVAILABLE = "method_unavailable"
    REAUTH_REQUIRED = "reauth_required"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass(frozen=True, slots=True)
class _ProbeSpec:
    code: str
    methods: tuple[str, ...]
    operation: str
    expected_shapes: tuple[str, ...]
    field_paths: tuple[str, ...] = ()
    metric_paths: tuple[str, ...] = ()
    static_capability: GarminCapability | None = None


@dataclass(frozen=True, slots=True)
class _CallObservation:
    operation: str
    method: str
    method_callable: bool
    request_succeeded: bool | None
    status: GarminProbeStatus
    summary: GarminPayloadShape | None = None
    field_states: tuple[tuple[str, GarminValueState], ...] = ()
    field_state_counts: tuple[tuple[str, int], ...] = ()
    attribution: GarminDeviceAttribution = GarminDeviceAttribution.UNKNOWN
    observed_metric_paths: tuple[str, ...] = ()
    error: GarminSafeError | None = None
    not_run_reason: str | None = None


@dataclass(frozen=True, slots=True)
class GarminCapabilityObservation:
    """One report row.  All fields are structural or fixed-vocabulary data."""

    code: str
    display_name: str
    static_audit_status: str
    static_device_support: str
    methods: tuple[str, ...]
    method_callable: bool
    request_succeeded: bool | None
    status: GarminProbeStatus
    value_state: str
    payload_shapes: tuple[str, ...]
    field_paths: tuple[str, ...]
    shape_counts: tuple[tuple[str, int], ...]
    field_state_counts: tuple[tuple[str, int], ...]
    device_attribution: GarminDeviceAttribution
    target_device_evidence: bool
    method_calls: tuple[dict[str, Any], ...] = ()
    errors: tuple[GarminSafeError, ...] = ()
    recovery_time_visibility: str | None = None
    not_run_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "display_name": self.display_name,
            "static_audit_status": self.static_audit_status,
            "static_device_support": self.static_device_support,
            "methods": list(self.methods),
            "method_callable": self.method_callable,
            "request_succeeded": self.request_succeeded,
            "status": self.status.value,
            "value_state": self.value_state,
            "payload_shapes": list(self.payload_shapes),
            "field_paths": list(self.field_paths),
            "shape_counts": {key: count for key, count in self.shape_counts},
            "field_state_counts": {key: count for key, count in self.field_state_counts},
            "device_attribution": self.device_attribution.value,
            "target_device_evidence": self.target_device_evidence,
            "method_calls": list(self.method_calls),
            "errors": [error.as_dict() for error in self.errors],
        }
        if self.recovery_time_visibility is not None:
            result["recovery_time_visibility"] = self.recovery_time_visibility
        if self.not_run_reason is not None:
            result["not_run_reason"] = self.not_run_reason
        return result


@dataclass(frozen=True, slots=True)
class GarminCapabilityReport:
    """Deterministic machine-readable capability summary."""

    auth: GarminAuthResult
    window_day_count: int
    activity_requested: bool
    activity_selected: bool
    request_count: int
    capabilities: tuple[GarminCapabilityObservation, ...]
    abort_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": PROBE_CONTRACT_VERSION,
            "source": {
                "provider_code": GARMIN_PROVIDER_CODE,
                "target_device_code": VIVOACTIVE_5_DEVICE_CODE,
                "target_device_model": VIVOACTIVE_5_MODEL,
            },
            "library": {
                "name": "python-garminconnect",
                "version": GARMINCONNECT_VERSION,
            },
            "application": {
                "name": "Garmin Connect",
                "version": "unknown",
            },
            "auth": self.auth.as_dict(),
            "probe": {
                "window_day_count": self.window_day_count,
                "activity_requested": self.activity_requested,
                "activity_selected": self.activity_selected,
                "request_count": self.request_count,
                "max_provider_requests": MAX_PROVIDER_REQUESTS,
                "abort_reason": self.abort_reason,
                "raw_payloads_retained": False,
                "database_writes": False,
            },
            "privacy": {
                "raw_values_emitted": False,
                "private_identifiers_emitted": False,
                "tokens_emitted": False,
                "health_timestamps_emitted": False,
            },
            "capabilities": [item.as_dict() for item in self.capabilities],
        }

    def to_json(self) -> str:
        """Serialize the summary with stable key ordering and no raw data."""

        return json.dumps(self.as_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n"


_SPECIAL_DAILY_SUMMARY = _ProbeSpec(
    code="daily_summary",
    methods=("get_user_summary",),
    operation="daily_summary",
    expected_shapes=("object",),
    field_paths=("calendarDate", "userActivitySummary"),
)
_SPECIAL_INTRADAY = _ProbeSpec(
    code="intraday_time_series",
    methods=("get_heart_rates",),
    operation="heart_rate",
    expected_shapes=("object",),
    field_paths=(
        "heartRateValues",
        "heartRateValue",
        "heartRate",
        "heartRateBpm",
        "timeOffset",
    ),
    metric_paths=("heartRateValues", "heartRateValue"),
)
_SPECIAL_ACTIVITY_DETAILS = _ProbeSpec(
    code="activity_details",
    methods=("get_activity", "get_activity_details"),
    operation="activity_detail",
    expected_shapes=("object",),
    field_paths=_ACTIVITY_FIELD_PATHS,
    metric_paths=_ACTIVITY_METRIC_PATHS,
)


def _static_spec(
    code: str,
    methods: tuple[str, ...],
    operation: str,
    expected_shapes: tuple[str, ...],
    field_paths: tuple[str, ...] = (),
    metric_paths: tuple[str, ...] = (),
) -> _ProbeSpec:
    capability = next(item for item in CAPABILITY_MATRIX if item.code == code)
    return _ProbeSpec(
        code=code,
        methods=methods,
        operation=operation,
        expected_shapes=expected_shapes,
        field_paths=field_paths,
        metric_paths=metric_paths,
        static_capability=capability,
    )


_PROBE_SPECS: tuple[_ProbeSpec, ...] = (
    _SPECIAL_DAILY_SUMMARY,
    _static_spec(
        "sleep",
        ("get_sleep_data",),
        "sleep",
        ("object",),
        _SLEEP_FIELD_PATHS,
        metric_paths=_SLEEP_METRIC_PATHS,
    ),
    _static_spec(
        "sleep_score",
        ("get_sleep_data",),
        "sleep",
        ("object",),
        _SLEEP_SCORE_FIELD_PATHS,
        metric_paths=_SLEEP_SCORE_METRIC_PATHS,
    ),
    _static_spec(
        "sleep_stages",
        ("get_sleep_data",),
        "sleep",
        ("object",),
        _SLEEP_STAGE_FIELD_PATHS,
        metric_paths=_SLEEP_STAGE_METRIC_PATHS,
    ),
    _static_spec(
        "naps",
        ("get_sleep_data",),
        "naps",
        ("object",),
        _NAP_FIELD_PATHS,
        metric_paths=_NAP_METRIC_PATHS,
    ),
    _static_spec(
        "heart_rate",
        ("get_heart_rates",),
        "heart_rate",
        ("object",),
        ("heartRateValues", "heartRateValue", "heartRate", "heartRateBpm"),
        metric_paths=("heartRateValues", "heartRateValue", "heartRate", "heartRateBpm"),
    ),
    _static_spec(
        "resting_heart_rate",
        ("get_rhr_day",),
        "resting_heart_rate",
        ("object",),
        ("allMetrics.metricsMap.WELLNESS_RESTING_HEART_RATE.0.value",),
        metric_paths=("allMetrics.metricsMap.WELLNESS_RESTING_HEART_RATE.0.value",),
    ),
    _static_spec(
        "hrv_status",
        ("get_hrv_data",),
        "hrv_status",
        ("object",),
        _HRV_FIELD_PATHS,
        metric_paths=_HRV_METRIC_PATHS,
    ),
    _static_spec(
        "stress",
        ("get_stress_data",),
        "stress",
        ("object",),
        (
            "avgStressLevel",
            "maxStressLevel",
            "stressValuesArray",
            "stressValues",
            "stress",
            "stressLevel",
            "stressDuration",
            "restStressDuration",
        ),
        metric_paths=(
            "avgStressLevel",
            "maxStressLevel",
            "stressValuesArray",
            "stressValues",
            "stressLevel",
        ),
    ),
    _static_spec(
        "body_battery",
        ("get_body_battery",),
        "body_battery",
        ("array",),
        (
            "charged",
            "drained",
            "bodyBatteryValuesArray",
            "bodyBatteryValueDescriptorDTOList",
        ),
        metric_paths=(
            "charged", "drained", "bodyBatteryValuesArray",
        ),
    ),
    _static_spec(
        "spo2",
        ("get_spo2_data",),
        "spo2",
        ("object",),
        (
            "averageSpO2",
            "lastSevenDaysAvgSpO2",
            "spo2Values",
            "spo2",
            "spo2Percent",
        ),
        metric_paths=(
            "averageSpO2",
            "lastSevenDaysAvgSpO2",
            "spo2Values",
            "spo2",
            "spo2Percent",
        ),
    ),
    _static_spec(
        "respiration",
        ("get_respiration_data",),
        "respiration",
        ("object",),
        (
            "avgSleepRespirationValue",
            "respirationValues",
            "respiration",
            "respirationRate",
        ),
        metric_paths=(
            "avgSleepRespirationValue",
            "respirationValues",
            "respiration",
            "respirationRate",
        ),
    ),
    _static_spec(
        "vo2_max",
        ("get_max_metrics",),
        "vo2_max",
        ("object",),
        ("maxMetrics.vo2MaxRunning", "vo2Max", "vo2MaxRunning"),
        metric_paths=("maxMetrics.vo2MaxRunning",),
    ),
    _static_spec(
        "recovery_time",
        ("get_activity", "get_activity_details"),
        "recovery_time",
        ("object", "bytes"),
        ("recoveryTimeSeconds", "recoveryTime"),
    ),
    _static_spec(
        "training_readiness",
        ("get_training_readiness",),
        "training_readiness",
        ("array",),
        ("score", "level"),
        metric_paths=("score",),
    ),
    _static_spec(
        "training_status",
        ("get_training_status",),
        "training_status",
        ("object",),
        ("trainingStatus.value", "trainingStatus"),
        metric_paths=("trainingStatus.value", "trainingStatus"),
    ),
    _static_spec(
        "unified_training_status",
        ("get_training_status",),
        "training_status",
        ("object",),
    ),
    _static_spec(
        "training_effect",
        ("get_activity", "get_activity_details"),
        "activity_detail",
        ("object",),
        ("aerobicTrainingEffect", "anaerobicTrainingEffect"),
        metric_paths=("aerobicTrainingEffect", "anaerobicTrainingEffect"),
    ),
    _static_spec(
        "acute_training_load",
        ("get_activity", "get_activity_details"),
        "activity_detail",
        ("object",),
        ("activityTrainingLoad",),
        metric_paths=("activityTrainingLoad",),
    ),
    _static_spec(
        "activities",
        (_ACTIVITY_DISCOVERY_METHOD,),
        "activities",
        ("array",),
        _ACTIVITY_FIELD_PATHS,
        metric_paths=_ACTIVITY_METRIC_PATHS,
    ),
    _SPECIAL_ACTIVITY_DETAILS,
    _SPECIAL_INTRADAY,
    _static_spec(
        "cycling_metrics",
        (_ACTIVITY_DISCOVERY_METHOD, "get_activity", "get_activity_details"),
        "cycling_metrics",
        ("object", "bytes"),
        _ACTIVITY_FIELD_PATHS,
        metric_paths=_ACTIVITY_METRIC_PATHS,
    ),
)

_ALLOWED_METHODS = frozenset(
    {
        "get_user_summary",
        "get_sleep_data",
        "get_body_battery",
        "get_body_battery_events",
        "get_heart_rates",
        "get_rhr_day",
        "get_hrv_data",
        "get_stress_data",
        "get_spo2_data",
        "get_respiration_data",
        "get_max_metrics",
        "get_training_readiness",
        "get_training_status",
        "connectapi",
        "get_activity",
        "get_activity_details",
    }
)

if any(method not in _ALLOWED_METHODS for spec in _PROBE_SPECS for method in spec.methods):
    raise RuntimeError("Garmin probe contains a method outside its read allowlist")
if any(
    path not in GARMIN_SAFE_FIELD_PATHS
    for spec in _PROBE_SPECS
    for path in (*spec.field_paths, *spec.metric_paths)
):
    raise RuntimeError("Garmin probe contains a field outside its static redaction allowlist")


def validate_probe_dates(values: Sequence[str] | None) -> tuple[str, ...]:
    """Accept only one or two adjacent owner-selected calendar dates."""

    if values is None or not values or len(values) > 2:
        raise ValueError("capability probe requires one or two dates")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not _DATE_RE.fullmatch(value.strip()):
            raise ValueError("capability probe dates must use YYYY-MM-DD")
        try:
            date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError("capability probe date is invalid") from exc
        normalized.append(value.strip())
    if len(set(normalized)) != len(normalized):
        raise ValueError("capability probe dates must be distinct")
    normalized.sort()
    if len(normalized) == 2:
        left = date.fromisoformat(normalized[0])
        right = date.fromisoformat(normalized[1])
        if (right - left).days != 1:
            raise ValueError("capability probe dates must be adjacent")
    return tuple(normalized)


@contextmanager
def _bounded_provider_requests(client: Any) -> Any:
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


class GarminCapabilityProbe:
    """Run the fixed small read-only probe against an authenticated client."""

    def __init__(self, client: Any | None) -> None:
        self.client = client

    def run(
        self,
        dates: Sequence[str],
        *,
        auth_result: GarminAuthResult | None = None,
    ) -> GarminCapabilityReport:
        requested_dates = validate_probe_dates(dates)
        auth = auth_result or GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED)
        if self.client is None or not auth.ok:
            return self._not_run_report(auth, len(requested_dates))

        observations: dict[str, list[_CallObservation]] = {}
        auth_lost = False
        abort_reason: str | None = None
        self._request_count = 0
        with _bounded_provider_requests(self.client):
            for requested_date in requested_dates:
                date_observations: dict[str, _CallObservation] = {}
                for method, operation, expected_shapes, field_paths in (
                    (
                        "get_user_summary",
                        "daily_summary",
                        ("object",),
                        _SPECIAL_DAILY_SUMMARY.field_paths,
                    ),
                    (
                        "get_sleep_data",
                        "sleep",
                        ("object",),
                        _SLEEP_FIELD_PATHS,
                    ),
                    (
                        "get_heart_rates",
                        "heart_rate",
                        ("object",),
                        _SPECIAL_INTRADAY.field_paths,
                    ),
                    (
                        "get_rhr_day",
                        "resting_heart_rate",
                        ("object",),
                        (
                            "allMetrics.metricsMap.WELLNESS_RESTING_HEART_RATE.0.value",
                        ),
                    ),
                    (
                        "get_hrv_data",
                        "hrv_status",
                        ("object",),
                        _HRV_FIELD_PATHS,
                    ),
                    (
                        "get_stress_data",
                        "stress",
                        ("object",),
                        (
                            "avgStressLevel",
                            "maxStressLevel",
                            "stressValuesArray",
                            "stressValues",
                            "stress",
                            "stressLevel",
                            "stressDuration",
                            "restStressDuration",
                        ),
                    ),
                    (
                        "get_body_battery",
                        "body_battery",
                        ("array",),
                        (
                            "charged",
                            "drained",
                            "bodyBatteryValuesArray",
                            "bodyBatteryValueDescriptorDTOList",
                        ),
                    ),
                    (
                        "get_spo2_data",
                        "spo2",
                        ("object",),
                        (
                            "averageSpO2",
                            "lastSevenDaysAvgSpO2",
                            "spo2Values",
                            "spo2",
                            "spo2Percent",
                        ),
                    ),
                    (
                        "get_respiration_data",
                        "respiration",
                        ("object",),
                        (
                            "avgSleepRespirationValue",
                            "respirationValues",
                            "respiration",
                            "respirationRate",
                        ),
                    ),
                    (
                        "get_max_metrics",
                        "vo2_max",
                        ("object",),
                        ("maxMetrics.vo2MaxRunning", "vo2Max", "vo2MaxRunning"),
                    ),
                    (
                        "get_training_readiness",
                        "training_readiness",
                        ("array",),
                        ("score", "level"),
                    ),
                    (
                        "get_training_status",
                        "training_status",
                        ("object",),
                        ("trainingStatus.value", "trainingStatus"),
                    ),
                ):
                    observation, _ = self._invoke(
                        method,
                        operation,
                        (requested_date,),
                        expected_shapes,
                        field_paths,
                    )
                    observations.setdefault(operation, []).append(observation)
                    date_observations[operation] = observation
                    if observation.status is GarminProbeStatus.REAUTH_REQUIRED:
                        auth_lost = True
                        abort_reason = "reauth_required"
                        break
                    if observation.not_run_reason is not None:
                        abort_reason = observation.not_run_reason
                        break
                if (sleep_observation := date_observations.get("sleep")) is not None:
                    observations.setdefault("naps", []).append(sleep_observation)
                if auth_lost:
                    break

            activity_id: str | None = None
            if not auth_lost and abort_reason is None:
                activity_observation, activity_payload = self._invoke_activity_discovery(
                    requested_dates[0], requested_dates[-1]
                )
                observations.setdefault("activities", []).append(activity_observation)
                observations.setdefault("cycling_metrics", []).append(activity_observation)
                if activity_observation.status is GarminProbeStatus.REAUTH_REQUIRED:
                    auth_lost = True
                    abort_reason = "reauth_required"
                elif activity_observation.status is GarminProbeStatus.SUCCEEDED:
                    activity_id = _select_activity_id(activity_payload)
                activity_payload = None

            if not auth_lost and abort_reason is None and activity_id is not None:
                for method, operation, expected_shapes, field_paths, call_kwargs in (
                    (
                        "get_activity",
                        "activity_detail",
                        ("object",),
                        _ACTIVITY_FIELD_PATHS,
                        None,
                    ),
                    (
                        "get_activity_details",
                        "activity_detail",
                        ("object",),
                        _ACTIVITY_FIELD_PATHS,
                        _ACTIVITY_DETAIL_KWARGS,
                    ),
                ):
                    observation, _ = self._invoke(
                        method,
                        operation,
                        (activity_id,),
                        expected_shapes,
                        field_paths,
                        kwargs=call_kwargs,
                    )
                    observations.setdefault(operation, []).append(observation)
                    observations.setdefault("cycling_metrics", []).append(observation)
                    if observation.status is GarminProbeStatus.REAUTH_REQUIRED:
                        auth_lost = True
                        abort_reason = "reauth_required"
                        break
                    if observation.not_run_reason is not None:
                        abort_reason = observation.not_run_reason
                        break

            # ORIGINAL FIT is deliberately not downloaded: a correct bounded
            # FIT parser is not part of this spike, and the raw download can
            # contain GPS tracks.  Keep the question explicitly unevaluated.

        capabilities = tuple(
            self._build_observation(
                spec,
                observations.get(spec.operation, ()),
                activity_id is not None,
                not_run_reason=abort_reason,
            )
            for spec in _PROBE_SPECS
        )
        return GarminCapabilityReport(
            auth=auth,
            window_day_count=len(requested_dates),
            activity_requested=True,
            activity_selected=activity_id is not None,
            request_count=self._request_count,
            capabilities=capabilities,
            abort_reason=abort_reason,
        )

    def _invoke_activity_discovery(
        self,
        start_date: str,
        end_date: str,
    ) -> tuple[_CallObservation, Any | None]:
        """Use one fixed endpoint request instead of the provider paginator."""

        endpoint = getattr(self.client, _ACTIVITY_DISCOVERY_ENDPOINT_ATTRIBUTE, None)
        if endpoint != _ACTIVITY_DISCOVERY_ENDPOINT:
            return (
                _CallObservation(
                    operation="activities",
                    method=_ACTIVITY_DISCOVERY_METHOD,
                    method_callable=False,
                    request_succeeded=False,
                    status=GarminProbeStatus.METHOD_UNAVAILABLE,
                ),
                None,
            )
        return self._invoke(
            _ACTIVITY_DISCOVERY_METHOD,
            "activities",
            (endpoint,),
            ("array",),
            _ACTIVITY_FIELD_PATHS,
            kwargs={
                "params": {
                    "startDate": start_date,
                    "endDate": end_date,
                    "start": "0",
                    "limit": "1",
                }
            },
        )

    def _invoke(
        self,
        method_name: str,
        operation: str,
        args: tuple[Any, ...],
        expected_shapes: tuple[str, ...],
        field_paths: Sequence[str],
        *,
        kwargs: Mapping[str, Any] | None = None,
    ) -> tuple[_CallObservation, Any | None]:
        if method_name not in _ALLOWED_METHODS:
            raise RuntimeError("attempted Garmin method outside read allowlist")
        method = getattr(self.client, method_name, None)
        if not callable(method):
            return (
                _CallObservation(
                    operation=operation,
                    method=method_name,
                    method_callable=False,
                    request_succeeded=False,
                    status=GarminProbeStatus.METHOD_UNAVAILABLE,
                ),
                None,
            )
        if self._request_count >= MAX_PROVIDER_REQUESTS:
            return (
                _CallObservation(
                    operation=operation,
                    method=method_name,
                    method_callable=True,
                    request_succeeded=None,
                    status=GarminProbeStatus.NOT_RUN,
                    not_run_reason="request_budget_exhausted",
                ),
                None,
            )
        self._request_count += 1
        try:
            with _silence_provider_logging():
                response = method(*args, **dict(kwargs or {}))
        except Exception as exc:
            error = classify_garmin_error(exc)
            if error.error_code == "unsupported_or_not_found":
                status = GarminProbeStatus.UNSUPPORTED
            elif error.error_class == "authentication":
                status = GarminProbeStatus.REAUTH_REQUIRED
            else:
                status = GarminProbeStatus.FAILED
            return (
                _CallObservation(
                    operation=operation,
                    method=method_name,
                    method_callable=True,
                    request_succeeded=False,
                    status=status,
                    error=error,
                ),
                None,
            )

        traversal_limit = 1 if operation == "activities" else 64
        summary = summarize_garmin_payload(response, max_array_items=traversal_limit)
        if summary.value_state is GarminValueState.NULL:
            status = GarminProbeStatus.NULL
        elif summary.value_state is GarminValueState.EMPTY:
            status = GarminProbeStatus.EMPTY
        elif summary.root_shape not in expected_shapes:
            status = GarminProbeStatus.SHAPE_DRIFT
        else:
            status = GarminProbeStatus.SUCCEEDED
        attribution = infer_device_attribution(response, max_array_items=traversal_limit).status
        return (
            _CallObservation(
                operation=operation,
                method=method_name,
                method_callable=True,
                request_succeeded=True,
                status=status,
                summary=summary,
                field_states=tuple(
                    (
                        path,
                        field_state_at_path(
                            response,
                            path,
                            max_array_items=traversal_limit,
                        ),
                    )
                    for path in field_paths
                ),
                field_state_counts=tuple(
                    sorted(
                        field_state_counts(
                            response,
                            field_paths,
                            max_array_items=traversal_limit,
                        ).items()
                    )
                ),
                attribution=attribution,
                observed_metric_paths=tuple(
                    path
                    for path in field_paths
                    if _metric_field_is_observed(
                        response,
                        path,
                        max_array_items=traversal_limit,
                    )
                ),
            ),
            response,
        )

    def _build_observation(
        self,
        spec: _ProbeSpec,
        calls: Sequence[_CallObservation],
        activity_selected: bool,
        *,
        not_run_reason: str | None = None,
    ) -> GarminCapabilityObservation:
        static_status = (
            spec.static_capability.audit_status.value
            if spec.static_capability is not None
            else "not_in_static_matrix"
        )
        static_support = (
            spec.static_capability.device_support.value
            if spec.static_capability is not None
            else "unknown"
        )
        if not calls:
            method_callable = bool(
                self.client is not None
                and all(callable(getattr(self.client, method, None)) for method in spec.methods)
            )
            reason = not_run_reason or (
                "no_activity_selected"
                if spec.operation
                in {"activity_detail", "original_fit", "recovery_time", "cycling_metrics"}
                and not activity_selected
                else None
            )
            method_calls: tuple[dict[str, Any], ...] = ()
            return GarminCapabilityObservation(
                code=spec.code,
                display_name=_display_name(spec),
                static_audit_status=static_status,
                static_device_support=static_support,
                methods=spec.methods,
                method_callable=method_callable,
                request_succeeded=None,
                status=GarminProbeStatus.NOT_RUN,
                value_state=GarminValueState.UNKNOWN.value,
                payload_shapes=(),
                field_paths=(),
                shape_counts=(),
                field_state_counts=(),
                device_attribution=GarminDeviceAttribution.UNKNOWN,
                target_device_evidence=False,
                method_calls=method_calls,
                recovery_time_visibility=(
                    "not_evaluated" if spec.code == "recovery_time" else None
                ),
                not_run_reason=reason,
            )

        statuses = {call.status for call in calls}
        request_succeeded = all(call.request_succeeded is True for call in calls)
        status = _combine_statuses(statuses)
        summaries = [call.summary for call in calls if call.summary is not None]
        payload_shapes = tuple(sorted({summary.root_shape for summary in summaries}))
        field_paths = tuple(sorted({path for summary in summaries for path in summary.field_paths}))
        shape_counter: dict[str, int] = {}
        for summary in summaries:
            for key, count in summary.shape_counts:
                shape_counter[key] = shape_counter.get(key, 0) + count
        expected_states: dict[str, int] = {}
        for call in calls:
            if call.summary is not None:
                for key, count in call.field_state_counts:
                    expected_states[key] = expected_states.get(key, 0) + count
        attribution = _combine_attribution(call.attribution for call in calls)
        errors = _unique_errors(call.error for call in calls)
        value_paths = spec.metric_paths or spec.field_paths
        value_states = {
            _call_value_state(
                call,
                value_paths,
                metric_only=bool(spec.metric_paths),
            ).value
            for call in calls
            if call.summary is not None
        }
        value_state = (
            next(iter(value_states))
            if len(value_states) == 1
            else ("mixed" if value_states else GarminValueState.UNKNOWN.value)
        )
        if spec.code == "recovery_time":
            value_state = GarminValueState.UNKNOWN.value
        target_evidence = (
            bool(spec.metric_paths)
            and attribution is GarminDeviceAttribution.TARGET_DEVICE
            and any(
                call.status is GarminProbeStatus.SUCCEEDED
                and set(call.observed_metric_paths).intersection(spec.metric_paths)
                for call in calls
            )
        )
        recovery_visibility = "not_evaluated" if spec.code == "recovery_time" else None
        return GarminCapabilityObservation(
            code=spec.code,
            display_name=_display_name(spec),
            static_audit_status=static_status,
            static_device_support=static_support,
            methods=spec.methods,
            method_callable=bool(
                self.client is not None
                and all(callable(getattr(self.client, method, None)) for method in spec.methods)
            ),
            request_succeeded=request_succeeded,
            status=status,
            value_state=value_state,
            payload_shapes=payload_shapes,
            field_paths=field_paths,
            shape_counts=tuple(sorted(shape_counter.items())),
            field_state_counts=tuple(sorted(expected_states.items())),
            device_attribution=attribution,
            target_device_evidence=target_evidence,
            method_calls=tuple(_call_as_dict(call, spec.field_paths) for call in calls),
            errors=errors,
            recovery_time_visibility=recovery_visibility,
            not_run_reason=None,
        )

    def _not_run_report(
        self, auth: GarminAuthResult, window_day_count: int
    ) -> GarminCapabilityReport:
        capabilities = tuple(
            self._build_observation(spec, (), False, not_run_reason="auth_not_ready")
            for spec in _PROBE_SPECS
        )
        return GarminCapabilityReport(
            auth=auth,
            window_day_count=window_day_count,
            activity_requested=False,
            activity_selected=False,
            request_count=0,
            capabilities=capabilities,
        )


def run_capability_probe(
    client: Any | None,
    dates: Sequence[str],
    *,
    auth_result: GarminAuthResult | None = None,
) -> GarminCapabilityReport:
    """Convenience wrapper for owner code and synthetic tests."""

    return GarminCapabilityProbe(client).run(dates, auth_result=auth_result)


def _display_name(spec: _ProbeSpec) -> str:
    if spec.static_capability is not None:
        return spec.static_capability.display_name
    return {
        "daily_summary": "Daily summary",
        "activity_details": "Activity details",
        "intraday_time_series": "Intraday / time-series",
    }.get(spec.code, spec.code.replace("_", " ").title())


def _combine_statuses(statuses: set[GarminProbeStatus]) -> GarminProbeStatus:
    if not statuses:
        return GarminProbeStatus.NOT_RUN
    if GarminProbeStatus.REAUTH_REQUIRED in statuses:
        return GarminProbeStatus.REAUTH_REQUIRED
    if GarminProbeStatus.FAILED in statuses:
        return GarminProbeStatus.PARTIAL if len(statuses) > 1 else GarminProbeStatus.FAILED
    if GarminProbeStatus.METHOD_UNAVAILABLE in statuses:
        return (
            GarminProbeStatus.PARTIAL if len(statuses) > 1 else GarminProbeStatus.METHOD_UNAVAILABLE
        )
    if GarminProbeStatus.SHAPE_DRIFT in statuses:
        return GarminProbeStatus.PARTIAL if len(statuses) > 1 else GarminProbeStatus.SHAPE_DRIFT
    if GarminProbeStatus.UNSUPPORTED in statuses:
        return GarminProbeStatus.PARTIAL if len(statuses) > 1 else GarminProbeStatus.UNSUPPORTED
    if len(statuses) > 1:
        return GarminProbeStatus.PARTIAL
    return next(iter(statuses))


def _combine_attribution(
    values: Sequence[GarminDeviceAttribution] | Any,
) -> GarminDeviceAttribution:
    normalized = set(values)
    if GarminDeviceAttribution.MIXED in normalized or {
        GarminDeviceAttribution.TARGET_DEVICE,
        GarminDeviceAttribution.OTHER_DEVICE,
    }.issubset(normalized):
        return GarminDeviceAttribution.MIXED
    if GarminDeviceAttribution.UNKNOWN in normalized:
        return GarminDeviceAttribution.UNKNOWN
    if len(normalized) == 1 and GarminDeviceAttribution.TARGET_DEVICE in normalized:
        return GarminDeviceAttribution.TARGET_DEVICE
    if len(normalized) == 1 and GarminDeviceAttribution.OTHER_DEVICE in normalized:
        return GarminDeviceAttribution.OTHER_DEVICE
    if normalized - {GarminDeviceAttribution.UNATTRIBUTED}:
        return GarminDeviceAttribution.UNKNOWN
    return GarminDeviceAttribution.UNATTRIBUTED


def _unique_errors(values: Sequence[GarminSafeError] | Any) -> tuple[GarminSafeError, ...]:
    result: list[GarminSafeError] = []
    for value in values:
        if value is not None and value not in result:
            result.append(value)
    return tuple(result)


def _call_as_dict(call: _CallObservation, expected_paths: Sequence[str]) -> dict[str, Any]:
    summary = call.summary
    result: dict[str, Any] = {
        "method": call.method,
        "method_callable": call.method_callable,
        "request_succeeded": call.request_succeeded,
        "status": call.status.value,
        "payload_shape": summary.root_shape if summary else None,
        "value_state": summary.value_state.value if summary else GarminValueState.UNKNOWN.value,
        "item_count": summary.item_count if summary else None,
        "field_paths": list(summary.field_paths) if summary else [],
        "shape_counts": dict(summary.shape_counts) if summary else {},
        "device_attribution": call.attribution.value,
        "error": call.error.as_dict() if call.error else None,
    }
    if summary is not None and expected_paths:
        result["field_state_counts"] = dict(call.field_state_counts)
    if call.not_run_reason is not None:
        result["not_run_reason"] = call.not_run_reason
    return result


def _call_value_state(
    call: _CallObservation,
    expected_paths: Sequence[str],
    *,
    metric_only: bool = False,
) -> GarminValueState:
    if call.summary is None:
        return GarminValueState.UNKNOWN
    if call.summary.value_state in {GarminValueState.NULL, GarminValueState.EMPTY}:
        return call.summary.value_state
    if not expected_paths:
        return GarminValueState.UNKNOWN
    expected = set(expected_paths)
    states = [state for path, state in call.field_states if path in expected]
    if not states:
        return GarminValueState.UNKNOWN
    unique = set(states)
    if metric_only:
        if set(call.observed_metric_paths).intersection(expected):
            return GarminValueState.PRESENT
        if GarminValueState.NULL in unique:
            return GarminValueState.NULL
        if GarminValueState.EMPTY in unique:
            return GarminValueState.EMPTY
        if GarminValueState.PRESENT in unique:
            return GarminValueState.UNKNOWN
        if len(unique) == 1:
            return states[0]
        return GarminValueState.UNKNOWN
    if GarminValueState.PRESENT in unique:
        return GarminValueState.PRESENT
    if len(unique) == 1:
        return states[0]
    return GarminValueState.UNKNOWN


def _metric_field_is_observed(
    value: Any,
    path: str,
    *,
    max_array_items: int,
) -> bool:
    """Return true only when a bounded path reaches an actual metric leaf."""

    if max_array_items < 1:
        raise ValueError("metric limits must be positive")
    return any(
        _metric_leaf_is_observed(candidate)
        for candidate in _iter_path_values(value, tuple(path.split(".")), max_array_items)
    )


def _iter_path_values(
    value: Any,
    segments: tuple[str, ...],
    max_array_items: int,
) -> Iterator[Any]:
    if not segments:
        yield value
        return
    segment = segments[0]
    if isinstance(value, Mapping):
        try:
            if segment in value:
                yield from _iter_path_values(value[segment], segments[1:], max_array_items)
        except (KeyError, TypeError, ValueError):
            return
        return
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return
    iterator = iter(value)
    if segment.isdigit():
        index = int(segment)
        if index >= max_array_items:
            return
        for current_index in range(index + 1):
            try:
                nested = next(iterator)
            except StopIteration:
                return
            if current_index == index:
                yield from _iter_path_values(nested, segments[1:], max_array_items)
        return
    for _ in range(max_array_items):
        try:
            nested = next(iterator)
        except StopIteration:
            return
        yield from _iter_path_values(nested, segments, max_array_items)


def _metric_leaf_is_observed(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, Mapping):
        return False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        try:
            return len(value) > 0
        except (TypeError, ValueError):
            return next(iter(value), None) is not None
    if isinstance(value, (str, bytes, bytearray)):
        return bool(value)
    return True


def _select_activity_id(value: Any) -> str | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None
    iterator = iter(value)
    for _ in range(1):
        try:
            item = next(iterator)
        except StopIteration:
            break
        if not isinstance(item, Mapping):
            continue
        for key in ("activityId", "activity_id", "id"):
            candidate = item.get(key)
            if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate > 0:
                return str(candidate)
            if (
                isinstance(candidate, str)
                and candidate.strip().isdigit()
                and int(candidate.strip()) > 0
            ):
                return candidate.strip()
    return None


def _recovery_time_visibility(value: Any) -> str:
    """Report the FIT question as unevaluated until a real parser exists."""

    del value
    return "not_evaluated"


__all__ = [
    "GarminCapabilityObservation",
    "GarminCapabilityProbe",
    "GarminCapabilityReport",
    "GarminProbeStatus",
    "MAX_PROVIDER_REQUESTS",
    "PROBE_CONTRACT_VERSION",
    "run_capability_probe",
    "validate_probe_dates",
]
