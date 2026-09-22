"""Bounded privacy-safe Garmin Training Phase A structural probe."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from numbers import Real
from typing import Any

from healthcheck.garmin.auth import (
    GarminAuthResult,
    GarminAuthStatus,
    GarminSafeError,
    _silence_provider_logging,
    classify_garmin_error,
)

TRAINING_PROBE_CONTRACT_VERSION = "garmin-training-phase-a-probe-v1"
MAX_TRAINING_DATES = 4
MAX_MAX_METRIC_RANGES = 2
MAX_MAX_METRIC_RANGE_DAYS = 7
MAX_ACTIVITY_PAGE_SIZE = 20
MAX_ACTIVITY_SUMMARIES = 3
MAX_DATA_READS = 19
MAX_DYNAMIC_ENTRIES = 20

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ACTIVITY_ENDPOINT_ATTRIBUTE = "garmin_connect_activities"
_ACTIVITY_ENDPOINT = "/activitylist-service/activities/search/activities"
_ALLOWED_METHODS = frozenset(
    {
        "get_devices",
        "get_primary_training_device",
        "get_training_status",
        "get_training_readiness",
        "get_max_metrics_range",
        "get_max_metrics",
        "connectapi",
        "get_activity",
    }
)


class TrainingProbeStatus(StrEnum):
    """Sanitized disposition for the probe or one provider read."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    EMPTY = "empty"
    NULL = "null"
    UNSUPPORTED = "unsupported"
    SHAPE_DRIFT = "shape_drift"
    METHOD_UNAVAILABLE = "method_unavailable"
    REAUTH_REQUIRED = "reauth_required"
    RATE_LIMITED = "rate_limited"
    PROVIDER_ERROR = "provider_error"
    NOT_RUN = "not_run"


class FieldValueState(StrEnum):
    """Value-free classification for one allowlisted field."""

    MISSING = "missing"
    NULL = "null"
    EMPTY = "empty"
    ZERO = "zero"
    NONZERO = "nonzero"
    PRESENT = "present"
    INVALID = "invalid"


class AttributionClass(StrEnum):
    """Coarse association only; none of these proves metric production."""

    ACCOUNT = "account"
    ASSOCIATED_DEVICE = "associated_device"
    ACTIVITY_RECORDER = "activity_recorder"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DateRange:
    start: str
    end: str

    @property
    def day_count(self) -> int:
        return (date.fromisoformat(self.end) - date.fromisoformat(self.start)).days + 1

    def contains(self, value: str) -> bool:
        return self.start <= value <= self.end


@dataclass(frozen=True, slots=True)
class TrainingProbeRequest:
    dates: tuple[str, ...]
    max_ranges: tuple[DateRange, ...]
    max_date: str
    activity_window: DateRange
    activity_ids: tuple[str, ...]
    repeat_date: str | None

    def sampling_dict(self) -> dict[str, Any]:
        """Return only bounded counts and booleans, never dates or IDs."""

        return {
            "training_date_count": len(self.dates),
            "max_metric_range_count": len(self.max_ranges),
            "max_metric_range_max_days": MAX_MAX_METRIC_RANGE_DAYS,
            "single_day_max_metrics": True,
            "activity_page_limit": MAX_ACTIVITY_PAGE_SIZE,
            "activity_summary_requested_count": len(self.activity_ids),
            "repeat_requested": self.repeat_date is not None,
        }


@dataclass(frozen=True, slots=True)
class _FieldSpec:
    label: str
    path: tuple[str, ...]
    kind: str = "presence"


@dataclass(slots=True)
class _CallResult:
    public: dict[str, Any]
    fingerprint: tuple[Any, ...] | None = None
    payload: Any | None = None


@dataclass(frozen=True, slots=True)
class GarminTrainingProbeReport:
    """Sanitized report wrapper suitable for stdout only."""

    payload: dict[str, Any]

    @property
    def completed(self) -> bool:
        return self.payload["status"] == TrainingProbeStatus.COMPLETED.value

    def as_dict(self) -> dict[str, Any]:
        return self.payload

    def to_json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=True, sort_keys=True) + "\n"


_DEVICE_FIELDS = (
    _FieldSpec("devices[].deviceId", ("*", "deviceId"), "identity"),
    _FieldSpec("devices[].unitId", ("*", "unitId"), "identity"),
    _FieldSpec("devices[].productDisplayName", ("*", "productDisplayName")),
    _FieldSpec("devices[].deviceTypePk", ("*", "deviceTypePk"), "identity"),
)

_PRIMARY_DEVICE_FIELDS = (
    _FieldSpec("primary.deviceId", ("deviceId",), "identity"),
    _FieldSpec("primary.unitId", ("unitId",), "identity"),
    _FieldSpec("primary.productDisplayName", ("productDisplayName",)),
    _FieldSpec("primary.primaryTrainingDevice", ("primaryTrainingDevice",), "boolean"),
    _FieldSpec("primary.priorityOrder", ("priorityOrder",), "numeric"),
)

_STATUS_FIELDS = (
    _FieldSpec(
        "status.latestTrainingStatusData.<device>.calendarDate",
        ("mostRecentTrainingStatus", "latestTrainingStatusData", "*", "calendarDate"),
        "date",
    ),
    _FieldSpec(
        "status.latestTrainingStatusData.<device>.deviceId",
        ("mostRecentTrainingStatus", "latestTrainingStatusData", "*", "deviceId"),
        "identity",
    ),
    _FieldSpec(
        "status.latestTrainingStatusData.<device>.trainingStatus",
        ("mostRecentTrainingStatus", "latestTrainingStatusData", "*", "trainingStatus"),
        "numeric",
    ),
    _FieldSpec(
        "status.latestTrainingStatusData.<device>.trainingStatusFeedbackPhrase",
        (
            "mostRecentTrainingStatus",
            "latestTrainingStatusData",
            "*",
            "trainingStatusFeedbackPhrase",
        ),
    ),
    _FieldSpec(
        "status.latestTrainingStatusData.<device>.weeklyTrainingLoad",
        ("mostRecentTrainingStatus", "latestTrainingStatusData", "*", "weeklyTrainingLoad"),
        "numeric",
    ),
    _FieldSpec(
        "status.latestTrainingStatusData.<device>.fitnessTrend",
        ("mostRecentTrainingStatus", "latestTrainingStatusData", "*", "fitnessTrend"),
        "numeric",
    ),
    _FieldSpec(
        "status.latestTrainingStatusData.<device>.primaryTrainingDevice",
        (
            "mostRecentTrainingStatus",
            "latestTrainingStatusData",
            "*",
            "primaryTrainingDevice",
        ),
        "boolean",
    ),
    _FieldSpec(
        "status.latestTrainingStatusData.<device>.acuteTrainingLoadDTO.dailyTrainingLoadAcute",
        (
            "mostRecentTrainingStatus",
            "latestTrainingStatusData",
            "*",
            "acuteTrainingLoadDTO",
            "dailyTrainingLoadAcute",
        ),
        "numeric",
    ),
    _FieldSpec(
        "status.latestTrainingStatusData.<device>.acuteTrainingLoadDTO.dailyTrainingLoadChronic",
        (
            "mostRecentTrainingStatus",
            "latestTrainingStatusData",
            "*",
            "acuteTrainingLoadDTO",
            "dailyTrainingLoadChronic",
        ),
        "numeric",
    ),
    _FieldSpec(
        "status.latestTrainingStatusData.<device>.acuteTrainingLoadDTO.acwrPercent",
        (
            "mostRecentTrainingStatus",
            "latestTrainingStatusData",
            "*",
            "acuteTrainingLoadDTO",
            "acwrPercent",
        ),
        "numeric",
    ),
    _FieldSpec(
        "status.latestTrainingStatusData.<device>.acuteTrainingLoadDTO.dailyAcuteChronicWorkloadRatio",
        (
            "mostRecentTrainingStatus",
            "latestTrainingStatusData",
            "*",
            "acuteTrainingLoadDTO",
            "dailyAcuteChronicWorkloadRatio",
        ),
        "numeric",
    ),
    _FieldSpec(
        "status.latestTrainingStatusData.<device>.acuteTrainingLoadDTO.acwrStatus",
        (
            "mostRecentTrainingStatus",
            "latestTrainingStatusData",
            "*",
            "acuteTrainingLoadDTO",
            "acwrStatus",
        ),
    ),
    _FieldSpec(
        "status.loadBalance.<device>.monthlyLoadAerobicLow",
        (
            "mostRecentTrainingLoadBalance",
            "metricsTrainingLoadBalanceDTOMap",
            "*",
            "monthlyLoadAerobicLow",
        ),
        "numeric",
    ),
    _FieldSpec(
        "status.loadBalance.<device>.monthlyLoadAerobicHigh",
        (
            "mostRecentTrainingLoadBalance",
            "metricsTrainingLoadBalanceDTOMap",
            "*",
            "monthlyLoadAerobicHigh",
        ),
        "numeric",
    ),
    _FieldSpec(
        "status.loadBalance.<device>.monthlyLoadAnaerobic",
        (
            "mostRecentTrainingLoadBalance",
            "metricsTrainingLoadBalanceDTOMap",
            "*",
            "monthlyLoadAnaerobic",
        ),
        "numeric",
    ),
    _FieldSpec(
        "status.loadBalance.<device>.monthlyLoadAerobicLowTargetMin",
        (
            "mostRecentTrainingLoadBalance",
            "metricsTrainingLoadBalanceDTOMap",
            "*",
            "monthlyLoadAerobicLowTargetMin",
        ),
        "numeric",
    ),
    _FieldSpec(
        "status.loadBalance.<device>.monthlyLoadAerobicLowTargetMax",
        (
            "mostRecentTrainingLoadBalance",
            "metricsTrainingLoadBalanceDTOMap",
            "*",
            "monthlyLoadAerobicLowTargetMax",
        ),
        "numeric",
    ),
    _FieldSpec(
        "status.loadBalance.<device>.monthlyLoadAerobicHighTargetMin",
        (
            "mostRecentTrainingLoadBalance",
            "metricsTrainingLoadBalanceDTOMap",
            "*",
            "monthlyLoadAerobicHighTargetMin",
        ),
        "numeric",
    ),
    _FieldSpec(
        "status.loadBalance.<device>.monthlyLoadAerobicHighTargetMax",
        (
            "mostRecentTrainingLoadBalance",
            "metricsTrainingLoadBalanceDTOMap",
            "*",
            "monthlyLoadAerobicHighTargetMax",
        ),
        "numeric",
    ),
    _FieldSpec(
        "status.loadBalance.<device>.monthlyLoadAnaerobicTargetMin",
        (
            "mostRecentTrainingLoadBalance",
            "metricsTrainingLoadBalanceDTOMap",
            "*",
            "monthlyLoadAnaerobicTargetMin",
        ),
        "numeric",
    ),
    _FieldSpec(
        "status.loadBalance.<device>.monthlyLoadAnaerobicTargetMax",
        (
            "mostRecentTrainingLoadBalance",
            "metricsTrainingLoadBalanceDTOMap",
            "*",
            "monthlyLoadAnaerobicTargetMax",
        ),
        "numeric",
    ),
    _FieldSpec(
        "status.mostRecentVO2Max.generic.vo2MaxValue",
        ("mostRecentVO2Max", "generic", "vo2MaxValue"),
        "numeric",
    ),
    _FieldSpec(
        "status.mostRecentVO2Max.cycling.vo2MaxValue",
        ("mostRecentVO2Max", "cycling", "vo2MaxValue"),
        "numeric",
    ),
)

_READINESS_FIELDS = (
    _FieldSpec("readiness[].calendarDate", ("*", "calendarDate"), "date"),
    _FieldSpec("readiness[].timestamp", ("*", "timestamp")),
    _FieldSpec("readiness[].timestampLocal", ("*", "timestampLocal")),
    _FieldSpec("readiness[].deviceId", ("*", "deviceId"), "identity"),
    _FieldSpec("readiness[].score", ("*", "score"), "numeric"),
    _FieldSpec("readiness[].level", ("*", "level")),
    _FieldSpec("readiness[].recoveryTime", ("*", "recoveryTime"), "numeric"),
    _FieldSpec(
        "readiness[].recoveryTimeFactorPercent",
        ("*", "recoveryTimeFactorPercent"),
        "numeric",
    ),
    _FieldSpec(
        "readiness[].recoveryTimeFactorFeedback",
        ("*", "recoveryTimeFactorFeedback"),
    ),
    _FieldSpec("readiness[].recoveryTimeChangePhrase", ("*", "recoveryTimeChangePhrase")),
    _FieldSpec("readiness[].acuteLoad", ("*", "acuteLoad"), "numeric"),
    _FieldSpec("readiness[].acwrFactorPercent", ("*", "acwrFactorPercent"), "numeric"),
    _FieldSpec("readiness[].acwrFactorFeedback", ("*", "acwrFactorFeedback")),
    _FieldSpec("readiness[].inputContext", ("*", "inputContext")),
    _FieldSpec("readiness[].primaryActivityTracker", ("*", "primaryActivityTracker"), "boolean"),
    _FieldSpec("readiness[].validSleep", ("*", "validSleep"), "boolean"),
)

_MAX_METRIC_FIELDS = (
    _FieldSpec("maxMetrics.calendarDate", ("calendarDate",), "date"),
    _FieldSpec("maxMetrics.deviceId", ("deviceId",), "identity"),
    _FieldSpec("maxMetrics.vo2MaxRunning", ("maxMetrics", "vo2MaxRunning"), "numeric"),
    _FieldSpec("maxMetrics.vo2MaxCycling", ("maxMetrics", "vo2MaxCycling"), "numeric"),
    _FieldSpec("maxMetrics.generic.vo2MaxValue", ("generic", "vo2MaxValue"), "numeric"),
    _FieldSpec("maxMetrics.cycling.vo2MaxValue", ("cycling", "vo2MaxValue"), "numeric"),
)

_ACTIVITY_LIST_FIELDS = (
    _FieldSpec("activities[].activityId", ("*", "activityId"), "identity"),
    _FieldSpec("activities[].activityType.typeKey", ("*", "activityType", "typeKey")),
    _FieldSpec("activities[].startTimeLocal", ("*", "startTimeLocal")),
    _FieldSpec("activities[].startTimeGMT", ("*", "startTimeGMT")),
    _FieldSpec("activities[].deviceId", ("*", "deviceId"), "identity"),
    _FieldSpec("activities[].aerobicTrainingEffect", ("*", "aerobicTrainingEffect"), "numeric"),
    _FieldSpec("activities[].anaerobicTrainingEffect", ("*", "anaerobicTrainingEffect"), "numeric"),
    _FieldSpec("activities[].activityTrainingLoad", ("*", "activityTrainingLoad"), "numeric"),
    _FieldSpec("activities[].trainingEffectLabel", ("*", "trainingEffectLabel")),
)

_ACTIVITY_SUMMARY_FIELDS = tuple(
    _FieldSpec(spec.label.replace("activities[]", "activity"), spec.path[1:], spec.kind)
    for spec in _ACTIVITY_LIST_FIELDS
)

_STATUS_DYNAMIC_PATHS = {
    "latest_training_status_device_count": (
        "mostRecentTrainingStatus",
        "latestTrainingStatusData",
    ),
    "load_balance_device_count": (
        "mostRecentTrainingLoadBalance",
        "metricsTrainingLoadBalanceDTOMap",
    ),
}


def validate_training_probe_request(
    dates: Sequence[str] | None,
    max_ranges: Sequence[Sequence[str]] | None,
    max_date: str | None,
    activity_start: str | None,
    activity_end: str | None,
    activity_ids: Sequence[str] | None = None,
    repeat_date: str | None = None,
) -> TrainingProbeRequest:
    """Validate the explicit sample without widening it or inventing defaults."""

    if not dates or len(dates) > MAX_TRAINING_DATES:
        raise ValueError("training probe requires one to four dates")
    normalized_dates = tuple(_normalize_date(value) for value in dates)
    if len(set(normalized_dates)) != len(normalized_dates):
        raise ValueError("training probe dates must be distinct")

    if max_date is None:
        raise ValueError("training probe requires one explicit max-metrics date")
    normalized_max_date = _normalize_date(max_date)

    normalized_ranges: list[DateRange] = []
    if max_ranges is not None:
        if len(max_ranges) > MAX_MAX_METRIC_RANGES:
            raise ValueError("training probe accepts at most two max-metrics ranges")
        for value in max_ranges:
            if len(value) != 2:
                raise ValueError("max-metrics range requires start and end")
            current = _normalize_range(value[0], value[1])
            if current.day_count > MAX_MAX_METRIC_RANGE_DAYS:
                raise ValueError("max-metrics range is too wide")
            normalized_ranges.append(current)

    if activity_start is None or activity_end is None:
        raise ValueError("training probe requires an explicit activity window")
    activity_window = _normalize_range(activity_start, activity_end)

    normalized_ids: list[str] = []
    for value in activity_ids or ():
        candidate = value.strip() if isinstance(value, str) else ""
        if not candidate.isdigit() or int(candidate) <= 0:
            raise ValueError("activity IDs must be positive integers")
        normalized_ids.append(str(int(candidate)))
    if len(normalized_ids) > MAX_ACTIVITY_SUMMARIES:
        raise ValueError("training probe accepts at most three activity IDs")
    if len(set(normalized_ids)) != len(normalized_ids):
        raise ValueError("training probe activity IDs must be distinct")

    normalized_repeat = _normalize_date(repeat_date) if repeat_date is not None else None
    if normalized_repeat is not None and normalized_repeat not in normalized_dates:
        raise ValueError("repeat date must be one of the explicit training dates")

    return TrainingProbeRequest(
        dates=normalized_dates,
        max_ranges=tuple(normalized_ranges),
        max_date=normalized_max_date,
        activity_window=activity_window,
        activity_ids=tuple(normalized_ids),
        repeat_date=normalized_repeat,
    )


class GarminTrainingPhaseAProbe:
    """Run only the issue #175 allowlisted provider reads."""

    def __init__(self, client: Any | None) -> None:
        self.client = client
        self._request_count = 0
        self._abort_reason: str | None = None

    def run(
        self,
        request: TrainingProbeRequest,
        *,
        auth_result: GarminAuthResult | None = None,
    ) -> GarminTrainingProbeReport:
        auth = auth_result or GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED)
        if self.client is None or not auth.ok:
            return self._auth_not_ready_report(request, auth)

        observations: list[dict[str, Any]] = []
        fingerprints: dict[tuple[str, int], tuple[Any, ...] | None] = {}
        repeat_consistency = {"training_status": "not_run", "training_readiness": "not_run"}
        max_results: list[tuple[DateRange, _CallResult]] = []
        single_max: _CallResult | None = None
        matched_activity_ids: list[str] = []
        activity_selection = {
            "requested_count": len(request.activity_ids),
            "matched_count": 0,
            "unmatched_count": 0,
        }

        with _disable_provider_retries(self.client):
            device_roster = self._call(
                "device_roster",
                "get_devices",
                (),
                "array",
                _DEVICE_FIELDS,
                request_role="device_roster",
            )
            self._append_call(observations, device_roster)
            if self._abort_reason is None:
                self._append_call(
                    observations,
                    self._call(
                        "primary_training_device",
                        "get_primary_training_device",
                        (),
                        "object",
                        _PRIMARY_DEVICE_FIELDS,
                        request_role="primary_training_device",
                    ),
                )

            for index, requested_date in enumerate(request.dates, start=1):
                if self._abort_reason is not None:
                    break
                status = self._call(
                    "training_status",
                    "get_training_status",
                    (requested_date,),
                    "object",
                    _STATUS_FIELDS,
                    request_role=f"training_date_{index}",
                    requested_date=requested_date,
                    dynamic_paths=_STATUS_DYNAMIC_PATHS,
                )
                self._append_call(observations, status)
                fingerprints[("training_status", index)] = status.fingerprint
                if self._abort_reason is not None:
                    break
                readiness = self._call(
                    "training_readiness",
                    "get_training_readiness",
                    (requested_date,),
                    "array",
                    _READINESS_FIELDS,
                    request_role=f"training_date_{index}",
                    requested_date=requested_date,
                )
                self._append_call(observations, readiness)
                fingerprints[("training_readiness", index)] = readiness.fingerprint

            for index, current_range in enumerate(request.max_ranges, start=1):
                if self._abort_reason is not None:
                    break
                result = self._call(
                    "max_metrics_range",
                    "get_max_metrics_range",
                    (current_range.start, current_range.end),
                    "object",
                    _MAX_METRIC_FIELDS,
                    request_role=f"max_range_{index}",
                )
                self._append_call(observations, result)
                max_results.append((current_range, result))

            if self._abort_reason is None:
                single_max = self._call(
                    "max_metrics_single_day",
                    "get_max_metrics",
                    (request.max_date,),
                    "object",
                    _MAX_METRIC_FIELDS,
                    request_role="max_single_day",
                    requested_date=request.max_date,
                )
                self._append_call(observations, single_max)

            activity_page: _CallResult | None = None
            if self._abort_reason is None:
                endpoint = getattr(self.client, _ACTIVITY_ENDPOINT_ATTRIBUTE, None)
                if endpoint == _ACTIVITY_ENDPOINT:
                    activity_page = self._call(
                        "activity_search_page",
                        "connectapi",
                        (endpoint,),
                        "array",
                        _ACTIVITY_LIST_FIELDS,
                        request_role="activity_search_page",
                        kwargs={
                            "params": {
                                "startDate": request.activity_window.start,
                                "endDate": request.activity_window.end,
                                "start": "0",
                                "limit": str(MAX_ACTIVITY_PAGE_SIZE),
                            }
                        },
                    )
                else:
                    activity_page = self._method_unavailable(
                        "activity_search_page", "connectapi", "activity_search_page"
                    )
                self._append_call(observations, activity_page)
                available_ids = _activity_ids(activity_page.payload)
                matched_activity_ids = [
                    value for value in request.activity_ids if value in available_ids
                ]
                activity_selection["matched_count"] = len(matched_activity_ids)
                activity_selection["unmatched_count"] = len(request.activity_ids) - len(
                    matched_activity_ids
                )
                activity_page.payload = None

            for index, activity_id in enumerate(matched_activity_ids, start=1):
                if self._abort_reason is not None:
                    break
                self._append_call(
                    observations,
                    self._call(
                        "activity_summary",
                        "get_activity",
                        (activity_id,),
                        "object",
                        _ACTIVITY_SUMMARY_FIELDS,
                        request_role=f"activity_summary_{index}",
                    ),
                )

            if request.repeat_date is not None and self._abort_reason is None:
                original_index = request.dates.index(request.repeat_date) + 1
                for surface, method, expected, fields, dynamic_paths in (
                    (
                        "training_status",
                        "get_training_status",
                        "object",
                        _STATUS_FIELDS,
                        _STATUS_DYNAMIC_PATHS,
                    ),
                    (
                        "training_readiness",
                        "get_training_readiness",
                        "array",
                        _READINESS_FIELDS,
                        {},
                    ),
                ):
                    if self._abort_reason is not None:
                        break
                    repeated = self._call(
                        surface,
                        method,
                        (request.repeat_date,),
                        expected,
                        fields,
                        request_role="repeat_date",
                        requested_date=request.repeat_date,
                        dynamic_paths=dynamic_paths,
                    )
                    self._append_call(observations, repeated)
                    original = fingerprints.get((surface, original_index))
                    repeat_consistency[surface] = _compare_fingerprints(
                        original, repeated.fingerprint
                    )

        max_consistency = []
        for index, (current_range, result) in enumerate(max_results, start=1):
            if not current_range.contains(request.max_date):
                disposition = "unknown"
            elif (
                single_max is None
                or single_max.public["status"] != TrainingProbeStatus.SUCCEEDED.value
                or result.public["status"] != TrainingProbeStatus.SUCCEEDED.value
            ):
                disposition = "unknown"
            else:
                disposition = _compare_fingerprints(single_max.fingerprint, result.fingerprint)
            max_consistency.append({"range_index": index, "disposition": disposition})

        incomplete = self._is_incomplete(observations, activity_selection)
        report_status = self._overall_status(observations, incomplete)
        return GarminTrainingProbeReport(
            {
                "contract_version": TRAINING_PROBE_CONTRACT_VERSION,
                "operation": "garmin-training-phase-a",
                "status": report_status.value,
                "sample_incomplete": incomplete,
                "shape_drift": any(
                    item["status"] == TrainingProbeStatus.SHAPE_DRIFT.value for item in observations
                ),
                "abort_reason": self._abort_reason,
                "auth": auth.as_dict(),
                "sampling": request.sampling_dict(),
                "request_budget": {
                    "max_data_reads": MAX_DATA_READS,
                    "data_reads": self._request_count,
                    "provider_retries_disabled": True,
                    "automatic_expansion": False,
                },
                "activity_selection": activity_selection,
                "consistency": {
                    "repeat": repeat_consistency,
                    "single_vs_range": max_consistency,
                },
                "observations": observations,
                "semantic_boundaries": {
                    "requested_date_is_source_date": False,
                    "most_recent_is_daily_measurement": False,
                    "first_element_assumed_primary": False,
                    "primary_device_proves_metric_producer": False,
                    "native_values_computed": False,
                    "recovery_time_json_only": True,
                },
                "privacy": {
                    "raw_payloads_emitted": False,
                    "exact_metric_values_emitted": False,
                    "device_ids_emitted": False,
                    "activity_ids_emitted": False,
                    "dates_or_timestamps_emitted": False,
                    "dynamic_keys_emitted": False,
                    "provider_payloads_persisted": False,
                    "database_or_checkpoint_writes": False,
                },
            }
        )

    def _call(
        self,
        surface: str,
        method_name: str,
        args: tuple[Any, ...],
        expected_shape: str,
        fields: Sequence[_FieldSpec],
        *,
        request_role: str,
        requested_date: str | None = None,
        kwargs: Mapping[str, Any] | None = None,
        dynamic_paths: Mapping[str, tuple[str, ...]] | None = None,
    ) -> _CallResult:
        if method_name not in _ALLOWED_METHODS:
            raise RuntimeError("attempted Garmin method outside training probe allowlist")
        method = getattr(self.client, method_name, None)
        if not callable(method):
            return self._method_unavailable(surface, method_name, request_role)
        if self._request_count >= MAX_DATA_READS:
            self._abort_reason = "request_budget_exhausted"
            return _CallResult(
                {
                    "surface": surface,
                    "request_role": request_role,
                    "method": method_name,
                    "request_made": False,
                    "status": TrainingProbeStatus.NOT_RUN.value,
                    "root_shape": None,
                    "item_count": None,
                    "count_truncated": False,
                    "snapshot_cardinality": None,
                    "field_state_counts": {},
                    "dynamic_entry_counts": {},
                    "dynamic_keys_redacted": True,
                    "source_date_relation": "unknown",
                    "attribution_class": AttributionClass.UNKNOWN.value,
                    "metric_producer_proven": False,
                    "error": None,
                }
            )
        self._request_count += 1
        try:
            with _silence_provider_logging():
                payload = method(*args, **dict(kwargs or {}))
        except Exception as exc:
            error = classify_garmin_error(exc)
            status = _error_status(error)
            if status in {
                TrainingProbeStatus.REAUTH_REQUIRED,
                TrainingProbeStatus.RATE_LIMITED,
            }:
                self._abort_reason = status.value
            elif error.error_code == "provider_unavailable":
                self._abort_reason = "provider_unavailable"
            return _CallResult(
                {
                    "surface": surface,
                    "request_role": request_role,
                    "method": method_name,
                    "request_made": True,
                    "status": status.value,
                    "root_shape": None,
                    "item_count": None,
                    "count_truncated": False,
                    "snapshot_cardinality": None,
                    "field_state_counts": {},
                    "dynamic_entry_counts": {},
                    "dynamic_keys_redacted": True,
                    "source_date_relation": "unknown",
                    "attribution_class": AttributionClass.UNKNOWN.value,
                    "metric_producer_proven": False,
                    "error": error.as_dict(),
                }
            )

        root_shape = _root_shape(payload)
        item_count, count_truncated = _bounded_item_count(payload)
        states = _field_state_counts(payload, fields)
        status = _payload_status(payload, root_shape, expected_shape)
        dynamic_counts = {
            label: _dynamic_entry_count(payload, path)
            for label, path in (dynamic_paths or {}).items()
        }
        return _CallResult(
            {
                "surface": surface,
                "request_role": request_role,
                "method": method_name,
                "request_made": True,
                "status": status.value,
                "root_shape": root_shape,
                "item_count": item_count,
                "count_truncated": count_truncated,
                "snapshot_cardinality": item_count if root_shape == "array" else None,
                "field_state_counts": states,
                "dynamic_entry_counts": dynamic_counts,
                "dynamic_keys_redacted": True,
                "source_date_relation": _source_date_relation(payload, requested_date),
                "attribution_class": _attribution(surface, states, dynamic_counts).value,
                "metric_producer_proven": False,
                "error": None,
            },
            fingerprint=_field_fingerprint(payload, fields),
            payload=payload,
        )

    def _method_unavailable(self, surface: str, method_name: str, request_role: str) -> _CallResult:
        return _CallResult(
            {
                "surface": surface,
                "request_role": request_role,
                "method": method_name,
                "request_made": False,
                "status": TrainingProbeStatus.METHOD_UNAVAILABLE.value,
                "root_shape": None,
                "item_count": None,
                "count_truncated": False,
                "snapshot_cardinality": None,
                "field_state_counts": {},
                "dynamic_entry_counts": {},
                "dynamic_keys_redacted": True,
                "source_date_relation": "unknown",
                "attribution_class": AttributionClass.UNKNOWN.value,
                "metric_producer_proven": False,
                "error": None,
            }
        )

    @staticmethod
    def _append_call(observations: list[dict[str, Any]], result: _CallResult) -> None:
        observations.append(result.public)
        if result.public["surface"] != "activity_search_page":
            result.payload = None

    def _is_incomplete(
        self,
        observations: Sequence[Mapping[str, Any]],
        activity_selection: Mapping[str, int],
    ) -> bool:
        incomplete_statuses = {
            TrainingProbeStatus.SHAPE_DRIFT.value,
            TrainingProbeStatus.METHOD_UNAVAILABLE.value,
            TrainingProbeStatus.REAUTH_REQUIRED.value,
            TrainingProbeStatus.RATE_LIMITED.value,
            TrainingProbeStatus.PROVIDER_ERROR.value,
            TrainingProbeStatus.NOT_RUN.value,
        }
        return (
            self._abort_reason is not None
            or activity_selection["unmatched_count"] > 0
            or any(item["status"] in incomplete_statuses for item in observations)
        )

    def _overall_status(
        self,
        observations: Sequence[Mapping[str, Any]],
        incomplete: bool,
    ) -> TrainingProbeStatus:
        if self._abort_reason == TrainingProbeStatus.REAUTH_REQUIRED.value:
            return TrainingProbeStatus.REAUTH_REQUIRED
        if self._abort_reason == TrainingProbeStatus.RATE_LIMITED.value:
            return TrainingProbeStatus.RATE_LIMITED
        if not incomplete:
            return TrainingProbeStatus.COMPLETED
        if any(item["status"] == TrainingProbeStatus.SUCCEEDED.value for item in observations):
            return TrainingProbeStatus.PARTIAL
        return TrainingProbeStatus.FAILED

    def _auth_not_ready_report(
        self, request: TrainingProbeRequest, auth: GarminAuthResult
    ) -> GarminTrainingProbeReport:
        status = (
            TrainingProbeStatus.REAUTH_REQUIRED
            if auth.status is GarminAuthStatus.REAUTH_REQUIRED
            else TrainingProbeStatus.FAILED
        )
        return GarminTrainingProbeReport(
            {
                "contract_version": TRAINING_PROBE_CONTRACT_VERSION,
                "operation": "garmin-training-phase-a",
                "status": status.value,
                "sample_incomplete": True,
                "shape_drift": False,
                "abort_reason": status.value,
                "auth": auth.as_dict(),
                "sampling": request.sampling_dict(),
                "request_budget": {
                    "max_data_reads": MAX_DATA_READS,
                    "data_reads": 0,
                    "provider_retries_disabled": True,
                    "automatic_expansion": False,
                },
                "activity_selection": {
                    "requested_count": len(request.activity_ids),
                    "matched_count": 0,
                    "unmatched_count": len(request.activity_ids),
                },
                "consistency": {
                    "repeat": {
                        "training_status": "not_run",
                        "training_readiness": "not_run",
                    },
                    "single_vs_range": [],
                },
                "observations": [],
                "semantic_boundaries": {
                    "requested_date_is_source_date": False,
                    "most_recent_is_daily_measurement": False,
                    "first_element_assumed_primary": False,
                    "primary_device_proves_metric_producer": False,
                    "native_values_computed": False,
                    "recovery_time_json_only": True,
                },
                "privacy": {
                    "raw_payloads_emitted": False,
                    "exact_metric_values_emitted": False,
                    "device_ids_emitted": False,
                    "activity_ids_emitted": False,
                    "dates_or_timestamps_emitted": False,
                    "dynamic_keys_emitted": False,
                    "provider_payloads_persisted": False,
                    "database_or_checkpoint_writes": False,
                },
            }
        )


def _normalize_date(value: str) -> str:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value.strip()):
        raise ValueError("training probe dates must use YYYY-MM-DD")
    normalized = value.strip()
    try:
        date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("training probe date is invalid") from exc
    return normalized


def _normalize_range(start: str, end: str) -> DateRange:
    normalized = DateRange(_normalize_date(start), _normalize_date(end))
    if normalized.start > normalized.end:
        raise ValueError("training probe range start must not follow end")
    return normalized


@contextmanager
def _disable_provider_retries(client: Any) -> Any:
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


def _root_shape(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "array"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Real):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (bytes, bytearray)):
        return "bytes"
    return "unknown"


def _bounded_item_count(value: Any) -> tuple[int | None, bool]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None, False
    count = len(value)
    return min(count, MAX_DYNAMIC_ENTRIES), count > MAX_DYNAMIC_ENTRIES


def _payload_status(payload: Any, root_shape: str, expected_shape: str) -> TrainingProbeStatus:
    if payload is None:
        return TrainingProbeStatus.NULL
    if root_shape in {"array", "object"} and len(payload) == 0:
        return TrainingProbeStatus.EMPTY
    if root_shape != expected_shape:
        return TrainingProbeStatus.SHAPE_DRIFT
    return TrainingProbeStatus.SUCCEEDED


def _field_state_counts(payload: Any, fields: Sequence[_FieldSpec]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for spec in fields:
        values = list(_iter_path_values(payload, spec.path))
        states = Counter(_value_state(value, spec.kind).value for value in values)
        if not values:
            states[FieldValueState.MISSING.value] = 1
        result[spec.label] = dict(sorted(states.items()))
    return result


def _iter_path_values(value: Any, path: tuple[str, ...]) -> Any:
    if not path:
        yield value
        return
    segment = path[0]
    if segment == "*":
        if isinstance(value, Mapping):
            iterator = iter(value.values())
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            iterator = iter(value)
        else:
            return
        for index, nested in enumerate(iterator):
            if index >= MAX_DYNAMIC_ENTRIES:
                break
            yield from _iter_path_values(nested, path[1:])
        return
    if isinstance(value, Mapping) and segment in value:
        yield from _iter_path_values(value[segment], path[1:])


def _value_state(value: Any, kind: str) -> FieldValueState:
    if value is None:
        return FieldValueState.NULL
    if kind == "numeric":
        if isinstance(value, bool) or not isinstance(value, Real):
            return FieldValueState.INVALID
        if not math.isfinite(float(value)):
            return FieldValueState.INVALID
        return FieldValueState.ZERO if value == 0 else FieldValueState.NONZERO
    if kind == "date":
        if not isinstance(value, str):
            return FieldValueState.INVALID
        try:
            date.fromisoformat(value)
        except ValueError:
            return FieldValueState.INVALID
        return FieldValueState.PRESENT
    if kind == "identity":
        if isinstance(value, bool):
            return FieldValueState.INVALID
        if isinstance(value, int):
            return FieldValueState.PRESENT if value > 0 else FieldValueState.INVALID
        if isinstance(value, str):
            return FieldValueState.PRESENT if value.strip() else FieldValueState.EMPTY
        return FieldValueState.INVALID
    if kind == "boolean":
        return FieldValueState.PRESENT if isinstance(value, bool) else FieldValueState.INVALID
    if isinstance(value, str):
        return FieldValueState.PRESENT if value else FieldValueState.EMPTY
    if isinstance(value, (Mapping, Sequence)) and not isinstance(value, (str, bytes, bytearray)):
        return FieldValueState.PRESENT if len(value) else FieldValueState.EMPTY
    return FieldValueState.PRESENT


def _dynamic_entry_count(payload: Any, path: tuple[str, ...]) -> dict[str, Any]:
    values = list(_iter_path_values(payload, path))
    if len(values) != 1 or not isinstance(values[0], Mapping):
        return {"count": None, "truncated": False, "state": "missing_or_invalid"}
    count = len(values[0])
    return {
        "count": min(count, MAX_DYNAMIC_ENTRIES),
        "truncated": count > MAX_DYNAMIC_ENTRIES,
        "state": "present",
    }


def _source_date_relation(payload: Any, requested_date: str | None) -> str:
    if requested_date is None:
        return "unknown"
    relations: set[str] = set()
    for value in _calendar_dates(payload):
        try:
            source = date.fromisoformat(value)
        except ValueError:
            return "unknown"
        requested = date.fromisoformat(requested_date)
        relation = "same" if source == requested else "earlier" if source < requested else "later"
        relations.add(relation)
    return next(iter(relations)) if len(relations) == 1 else "unknown"


def _calendar_dates(payload: Any) -> tuple[str, ...]:
    result: list[str] = []
    stack = [payload]
    visited = 0
    while stack and visited < 256:
        current = stack.pop()
        visited += 1
        if isinstance(current, Mapping):
            for key, value in current.items():
                if key == "calendarDate" and isinstance(value, str):
                    result.append(value)
                elif isinstance(value, (Mapping, list, tuple)):
                    stack.append(value)
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            stack.extend(current[:MAX_DYNAMIC_ENTRIES])
    return tuple(result)


def _attribution(
    surface: str,
    states: Mapping[str, Mapping[str, int]],
    dynamic_counts: Mapping[str, Mapping[str, Any]],
) -> AttributionClass:
    present_identity = any(
        counts.get(FieldValueState.PRESENT.value, 0) > 0
        for label, counts in states.items()
        if label.endswith("deviceId") or label.endswith("unitId")
    )
    if surface in {"device_roster", "primary_training_device"}:
        return AttributionClass.ASSOCIATED_DEVICE if present_identity else AttributionClass.UNKNOWN
    if surface == "training_status" and any(
        value.get("count", 0) for value in dynamic_counts.values()
    ):
        return AttributionClass.ASSOCIATED_DEVICE
    if surface in {"activity_search_page", "activity_summary"}:
        return AttributionClass.ACTIVITY_RECORDER if present_identity else AttributionClass.UNKNOWN
    if present_identity:
        return AttributionClass.ASSOCIATED_DEVICE
    if surface in {
        "training_status",
        "training_readiness",
        "max_metrics_range",
        "max_metrics_single_day",
    } and any(
        counts.get(state, 0) > 0
        for counts in states.values()
        for state in (
            FieldValueState.PRESENT.value,
            FieldValueState.ZERO.value,
            FieldValueState.NONZERO.value,
        )
    ):
        return AttributionClass.ACCOUNT
    return AttributionClass.UNKNOWN


def _field_fingerprint(payload: Any, fields: Sequence[_FieldSpec]) -> tuple[Any, ...]:
    return tuple(
        (spec.label, tuple(_freeze(value) for value in _iter_path_values(payload, spec.path)))
        for spec in fields
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze(nested)) for key, nested in value.items()))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(nested) for nested in value[:MAX_DYNAMIC_ENTRIES])
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return type(value).__name__


def _compare_fingerprints(left: tuple[Any, ...] | None, right: tuple[Any, ...] | None) -> str:
    if left is None or right is None:
        return "unknown"
    return "same" if left == right else "different"


def _activity_ids(payload: Any) -> frozenset[str]:
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes, bytearray)):
        return frozenset()
    result: set[str] = set()
    for item in payload[:MAX_ACTIVITY_PAGE_SIZE]:
        if not isinstance(item, Mapping):
            continue
        value = item.get("activityId")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            result.add(str(value))
        elif isinstance(value, str) and value.strip().isdigit() and int(value) > 0:
            result.add(str(int(value)))
    return frozenset(result)


def _error_status(error: GarminSafeError) -> TrainingProbeStatus:
    if error.error_class == "authentication":
        return TrainingProbeStatus.REAUTH_REQUIRED
    if error.error_code == "rate_limited":
        return TrainingProbeStatus.RATE_LIMITED
    if error.error_code == "unsupported_or_not_found":
        return TrainingProbeStatus.UNSUPPORTED
    return TrainingProbeStatus.PROVIDER_ERROR


__all__ = [
    "GarminTrainingPhaseAProbe",
    "GarminTrainingProbeReport",
    "MAX_ACTIVITY_PAGE_SIZE",
    "MAX_ACTIVITY_SUMMARIES",
    "MAX_DATA_READS",
    "MAX_MAX_METRIC_RANGE_DAYS",
    "MAX_MAX_METRIC_RANGES",
    "MAX_TRAINING_DATES",
    "TRAINING_PROBE_CONTRACT_VERSION",
    "TrainingProbeRequest",
    "TrainingProbeStatus",
    "validate_training_probe_request",
]
