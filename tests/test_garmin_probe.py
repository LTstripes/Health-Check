"""Synthetic Garmin capability-probe tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from healthcheck.garmin.auth import GarminAuthResult, GarminAuthStatus
from healthcheck.garmin.probe import (
    GarminCapabilityProbe,
    GarminProbeStatus,
    validate_probe_dates,
)

SYNTHETIC_HEALTH_VALUE = "synthetic-health-value-not-exported"
SYNTHETIC_ACTIVITY_ID = 987654321


class NotFoundError(Exception):
    status_code = 404


class FakeProbeClient:
    class ActivityDownloadFormat:
        ORIGINAL = "synthetic-original-fit"

    _METHODS = {
        "get_user_summary",
        "get_sleep_data",
        "get_heart_rates",
        "get_rhr_day",
        "get_hrv_data",
        "get_stress_data",
        "get_body_battery_events",
        "get_spo2_data",
        "get_respiration_data",
        "get_max_metrics",
        "get_training_readiness",
        "get_training_status",
        "get_activities_by_date",
        "get_activity",
        "get_activity_details",
        "download_activity",
    }

    def __init__(
        self,
        *,
        responses: Mapping[str, Any] | None = None,
        errors: Mapping[str, BaseException] | None = None,
        missing: set[str] | None = None,
        include_device: bool = True,
    ) -> None:
        self.responses = dict(responses or {})
        self.errors = dict(errors or {})
        self.missing = set(missing or ())
        self.include_device = include_device
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattribute__(self, name: str) -> Any:
        if name in object.__getattribute__(self, "missing"):
            return None
        return object.__getattribute__(self, name)

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((method, args, kwargs))
        if method in self.errors:
            raise self.errors[method]
        if method in self.responses:
            response = self.responses[method]
            return response(*args, **kwargs) if callable(response) else response
        return self._default_response(method)

    def _device(self) -> dict[str, object]:
        return {"device": {"model": "Vivoactive 5"}} if self.include_device else {}

    def _default_response(self, method: str) -> Any:
        if method == "get_user_summary":
            return {
                **self._device(),
                "calendarDate": "2026-09-05",
                "userActivitySummary": {"steps": 123},
                "value": SYNTHETIC_HEALTH_VALUE,
            }
        if method == "get_sleep_data":
            return {
                **self._device(),
                "sleepTimeSeconds": 28800,
                "sleepScore": 80,
                "levels": [{"startGMT": "synthetic"}],
                "napTimeSeconds": 0,
            }
        if method == "get_heart_rates":
            return {**self._device(), "heartRateValues": [0, 72], "value": SYNTHETIC_HEALTH_VALUE}
        if method == "get_rhr_day":
            return {**self._device(), "restingHeartRate": 55}
        if method == "get_hrv_data":
            return {**self._device(), "hrvStatus": {"status": "balanced"}}
        if method == "get_stress_data":
            return {**self._device(), "stressValues": [20, 30]}
        if method == "get_body_battery_events":
            return [{**self._device(), "bodyBatteryLevel": 70}]
        if method == "get_spo2_data":
            return {**self._device(), "spo2Values": [98]}
        if method == "get_respiration_data":
            return {**self._device(), "respirationValues": [15]}
        if method == "get_max_metrics":
            return {**self._device(), "vo2Max": 42}
        if method == "get_training_readiness":
            return [{**self._device(), "trainingReadiness": {"score": 60}, "score": 60}]
        if method == "get_training_status":
            return {**self._device(), "trainingStatus": "productive"}
        if method == "get_activities_by_date":
            return [
                {
                    **self._device(),
                    "activityId": SYNTHETIC_ACTIVITY_ID,
                    "activityName": "synthetic activity",
                }
            ]
        if method in {"get_activity", "get_activity_details"}:
            return {
                **self._device(),
                "trainingEffect": 3.0,
                "trainingLoad": 50,
                "recoveryTimeSeconds": 120,
                "distance": 1000,
                "value": SYNTHETIC_HEALTH_VALUE,
            }
        if method == "download_activity":
            return b"synthetic FIT recoveryTimeSeconds and health payload"
        raise AssertionError(f"unexpected synthetic method: {method}")

    def get_user_summary(self, value: str) -> Any:
        return self._call("get_user_summary", value)

    def get_sleep_data(self, value: str) -> Any:
        return self._call("get_sleep_data", value)

    def get_heart_rates(self, value: str) -> Any:
        return self._call("get_heart_rates", value)

    def get_rhr_day(self, value: str) -> Any:
        return self._call("get_rhr_day", value)

    def get_hrv_data(self, value: str) -> Any:
        return self._call("get_hrv_data", value)

    def get_stress_data(self, value: str) -> Any:
        return self._call("get_stress_data", value)

    def get_body_battery_events(self, value: str) -> Any:
        return self._call("get_body_battery_events", value)

    def get_spo2_data(self, value: str) -> Any:
        return self._call("get_spo2_data", value)

    def get_respiration_data(self, value: str) -> Any:
        return self._call("get_respiration_data", value)

    def get_max_metrics(self, value: str) -> Any:
        return self._call("get_max_metrics", value)

    def get_training_readiness(self, value: str) -> Any:
        return self._call("get_training_readiness", value)

    def get_training_status(self, value: str) -> Any:
        return self._call("get_training_status", value)

    def get_activities_by_date(self, start: str, end: str) -> Any:
        return self._call("get_activities_by_date", start, end)

    def get_activity(self, activity_id: str) -> Any:
        return self._call("get_activity", activity_id)

    def get_activity_details(self, activity_id: str) -> Any:
        return self._call("get_activity_details", activity_id)

    def download_activity(self, activity_id: str, *, dl_fmt: Any) -> Any:
        return self._call("download_activity", activity_id, dl_fmt=dl_fmt)


def _capability(report: Any, code: str) -> dict[str, Any]:
    return next(item for item in report.as_dict()["capabilities"] if item["code"] == code)


def test_successful_probe_is_small_deterministic_and_value_free() -> None:
    client = FakeProbeClient()
    auth = GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED)

    report = GarminCapabilityProbe(client).run(("2026-09-05",), auth_result=auth)
    data = report.as_dict()
    serialized = report.to_json()

    codes = [item["code"] for item in data["capabilities"]]
    assert len(codes) == len(set(codes)) == 23
    assert report.request_count == 16
    assert report.activity_selected is True
    assert all(item["status"] == "succeeded" for item in data["capabilities"])
    assert _capability(report, "recovery_time")["recovery_time_visibility"] == "observed"
    assert _capability(report, "training_effect")["target_device_evidence"] is True
    assert _capability(report, "acute_training_load")["target_device_evidence"] is True
    assert _capability(report, "naps")["field_state_counts"]
    assert sum(method == "get_activities_by_date" for method, _, _ in client.calls) == 1
    assert sum(method == "download_activity" for method, _, _ in client.calls) == 1
    assert SYNTHETIC_HEALTH_VALUE not in serialized
    assert str(SYNTHETIC_ACTIVITY_ID) not in serialized
    assert "synthetic activity" not in serialized
    assert "activityId" not in serialized
    assert data["privacy"] == {
        "health_timestamps_emitted": False,
        "private_identifiers_emitted": False,
        "raw_values_emitted": False,
        "tokens_emitted": False,
    }
    assert data["application"] == {"name": "Garmin Connect", "version": "unknown"}


def test_probe_distinguishes_empty_null_shape_drift_unsupported_and_missing_method() -> None:
    client = FakeProbeClient(
        responses={
            "get_sleep_data": {},
            "get_hrv_data": None,
            "get_heart_rates": ["shape-drift"],
        },
        errors={"get_spo2_data": NotFoundError("synthetic private response")},
        missing={"get_training_readiness"},
    )

    report = GarminCapabilityProbe(client).run(("2026-09-05",))
    data = report.as_dict()

    assert _capability(report, "sleep")["status"] == GarminProbeStatus.EMPTY.value
    assert _capability(report, "sleep_score")["value_state"] == "empty"
    assert _capability(report, "hrv_status")["status"] == GarminProbeStatus.NULL.value
    assert _capability(report, "heart_rate")["status"] == GarminProbeStatus.SHAPE_DRIFT.value
    assert (
        _capability(report, "intraday_time_series")["status"] == GarminProbeStatus.SHAPE_DRIFT.value
    )
    assert _capability(report, "spo2")["status"] == GarminProbeStatus.UNSUPPORTED.value
    readiness = _capability(report, "training_readiness")
    assert readiness["method_callable"] is False
    assert readiness["status"] == GarminProbeStatus.METHOD_UNAVAILABLE.value
    assert readiness["request_succeeded"] is False
    assert readiness["errors"] == []
    serialized = json.dumps(data, sort_keys=True)
    assert "synthetic private response" not in serialized
    assert "shape-drift" not in serialized


def test_method_presence_without_device_attribution_never_becomes_target_evidence() -> None:
    report = GarminCapabilityProbe(FakeProbeClient(include_device=False)).run(("2026-09-05",))

    activity = _capability(report, "activities")
    effect = _capability(report, "training_effect")
    assert activity["method_callable"] is True
    assert activity["request_succeeded"] is True
    assert activity["value_state"] == "present"
    assert activity["device_attribution"] == "unattributed"
    assert activity["target_device_evidence"] is False
    assert effect["device_attribution"] == "unattributed"
    assert effect["target_device_evidence"] is False


def test_target_marker_does_not_promote_null_capability_field() -> None:
    client = FakeProbeClient(
        responses={
            "get_training_readiness": [
                {
                    "device": {"model": "Vivoactive 5"},
                    "trainingReadiness": None,
                    "score": None,
                }
            ]
        }
    )

    readiness = _capability(
        GarminCapabilityProbe(client).run(("2026-09-05",)), "training_readiness"
    )

    assert readiness["value_state"] == "null"
    assert readiness["device_attribution"] == "target_device"
    assert readiness["target_device_evidence"] is False


def test_empty_activity_window_does_not_probe_details_or_fit() -> None:
    client = FakeProbeClient(responses={"get_activities_by_date": []})

    report = GarminCapabilityProbe(client).run(("2026-09-05",))

    assert report.activity_requested is True
    assert report.activity_selected is False
    assert _capability(report, "activity_details")["status"] == GarminProbeStatus.NOT_RUN.value
    assert _capability(report, "recovery_time")["status"] == GarminProbeStatus.NOT_RUN.value
    assert _capability(report, "training_effect")["status"] == GarminProbeStatus.NOT_RUN.value
    assert not any(
        method in {"get_activity", "get_activity_details", "download_activity"}
        for method, _, _ in client.calls
    )


def test_failed_auth_prevents_any_capability_request() -> None:
    client = FakeProbeClient()
    auth = GarminAuthResult(status=GarminAuthStatus.REAUTH_REQUIRED)

    report = GarminCapabilityProbe(client).run(("2026-09-05",), auth_result=auth)

    assert client.calls == []
    assert report.request_count == 0
    assert all(item.status is GarminProbeStatus.NOT_RUN for item in report.capabilities)


@pytest.mark.parametrize(
    "values",
    [
        None,
        (),
        ("2026-09-05", "2026-09-05"),
        ("2026-09-05", "2026-09-07"),
        ("2026-02-30",),
        ("2026/09/05",),
    ],
)
def test_probe_date_window_is_strict_and_small(values: tuple[str, ...] | None) -> None:
    with pytest.raises(ValueError):
        validate_probe_dates(values)


def test_probe_date_window_is_sorted_and_adjacent() -> None:
    assert validate_probe_dates(("2026-09-06", "2026-09-05")) == (
        "2026-09-05",
        "2026-09-06",
    )
