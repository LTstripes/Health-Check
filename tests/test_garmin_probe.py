"""Synthetic Garmin capability-probe tests."""

from __future__ import annotations

import inspect
import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from healthcheck.garmin.auth import GarminAuthResult, GarminAuthStatus
from healthcheck.garmin.probe import (
    MAX_PROVIDER_REQUESTS,
    GarminCapabilityProbe,
    GarminProbeStatus,
    _recovery_time_visibility,
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
        "get_body_battery",
        "get_body_battery_events",
        "get_spo2_data",
        "get_respiration_data",
        "get_max_metrics",
        "get_training_readiness",
        "get_training_status",
        "connectapi",
        "get_activities_by_date",
        "get_activity",
        "get_activity_details",
        "download_activity",
    }
    garmin_connect_activities = "/activitylist-service/activities/search/activities"

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
        self.retry_attempts = 3

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
        if method == "connectapi":
            return self._default_response("get_activities_by_date")
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
                "dailySleepDTO": {
                    "sleepTimeSeconds": 28800,
                    "napTimeSeconds": 0,
                    "deepSleepSeconds": 7200,
                    "lightSleepSeconds": 14400,
                    "remSleepSeconds": 6000,
                    "awakeSleepSeconds": 1200,
                    "sleepScores": {"overall": {"value": 80}},
                },
            }
        if method == "get_heart_rates":
            return {**self._device(), "heartRateValues": [0, 72], "value": SYNTHETIC_HEALTH_VALUE}
        if method == "get_rhr_day":
            return {
                **self._device(),
                "allMetrics": {
                    "metricsMap": {
                        "WELLNESS_RESTING_HEART_RATE": [{"value": 55}]
                    }
                },
            }
        if method == "get_hrv_data":
            return {
                **self._device(),
                "hrvSummary": {"weeklyAvg": 55, "status": "balanced"},
            }
        if method == "get_stress_data":
            return {
                **self._device(),
                "avgStressLevel": 20,
                "maxStressLevel": 30,
                "stressValuesArray": [[0, 20]],
            }
        if method == "get_body_battery":
            return [
                {
                    **self._device(),
                    "charged": 70,
                    "drained": 20,
                    "bodyBatteryValuesArray": [[0, 70]],
                }
            ]
        if method == "get_spo2_data":
            return {**self._device(), "averageSpO2": 98}
        if method == "get_respiration_data":
            return {**self._device(), "avgSleepRespirationValue": 15}
        if method == "get_max_metrics":
            return {
                **self._device(),
                "maxMetrics": {"vo2MaxRunning": 42},
            }
        if method == "get_training_readiness":
            return [
                {
                    **self._device(),
                    "score": 60,
                }
            ]
        if method == "get_training_status":
            return {**self._device(), "trainingStatus": "productive"}
        if method == "get_activities_by_date":
            return [
                {
                    **self._device(),
                    "activityId": SYNTHETIC_ACTIVITY_ID,
                    "activityName": "synthetic activity",
                    "activityType": {"typeKey": "cycling"},
                    "distance": 1000,
                    "duration": 60,
                }
            ]
        if method in {"get_activity", "get_activity_details"}:
            return {
                **self._device(),
                "aerobicTrainingEffect": 3.0,
                "activityTrainingLoad": 50,
                "distance": 1000,
                "duration": 60,
                "averageSpeed": 5,
                "averageHR": 120,
                "avgPower": 100,
            }
        if method == "download_activity":
            return b"synthetic FIT recoveryTimeSeconds and health payload"
        raise AssertionError(f"unexpected synthetic method: {method}")

    def get_user_summary(self, value: str) -> Any:
        return self._call("get_user_summary", value)

    def get_sleep_data(self, value: str) -> Any:
        return self._call("get_sleep_data", value)

    def get_body_battery(self, start: str, end: str | None = None) -> Any:
        return self._call("get_body_battery", start, end)

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

    def connectapi(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("connectapi", (path,), kwargs))
        if "get_activities_by_date" in self.errors:
            raise self.errors["get_activities_by_date"]
        if "get_activities_by_date" in self.responses:
            response = self.responses["get_activities_by_date"]
            return response(path, kwargs) if callable(response) else response
        return self._default_response("get_activities_by_date")

    def get_activity(self, activity_id: str) -> Any:
        return self._call("get_activity", activity_id)

    def get_activity_details(self, activity_id: str, **kwargs: Any) -> Any:
        return self._call("get_activity_details", activity_id, **kwargs)

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
    assert report.request_count == 15
    assert report.activity_selected is True
    assert all(
        item["status"] == "succeeded"
        for item in data["capabilities"]
        if item["code"] != "recovery_time"
    )
    assert _capability(report, "recovery_time")["status"] == GarminProbeStatus.NOT_RUN.value
    assert _capability(report, "recovery_time")["recovery_time_visibility"] == "not_evaluated"
    assert _capability(report, "recovery_time")["value_state"] == "unknown"
    assert all(
        "recovery_time_visibility" not in call
        for call in _capability(report, "recovery_time")["method_calls"]
    )
    assert _capability(report, "training_effect")["target_device_evidence"] is True
    assert _capability(report, "acute_training_load")["target_device_evidence"] is True
    assert _capability(report, "cycling_metrics")["target_device_evidence"] is True
    assert _capability(report, "naps")["field_state_counts"]
    assert sum(method == "connectapi" for method, _, _ in client.calls) == 1
    assert sum(method == "download_activity" for method, _, _ in client.calls) == 0
    activity_request = next(call for call in client.calls if call[0] == "connectapi")
    assert activity_request[2]["params"]["limit"] == "1"
    detail_request = next(call for call in client.calls if call[0] == "get_activity_details")
    assert detail_request[2] == {"maxchart": 1, "maxpoly": 0}
    assert client.retry_attempts == 3
    assert report.request_count <= MAX_PROVIDER_REQUESTS
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


def test_nested_sleep_contract_reports_typed_summary_leaves() -> None:
    report = GarminCapabilityProbe(FakeProbeClient()).run(("2026-09-05",))

    sleep = _capability(report, "sleep")
    score = _capability(report, "sleep_score")
    stages = _capability(report, "sleep_stages")

    assert "dailySleepDTO.sleepTimeSeconds" in sleep["field_paths"]
    assert sleep["value_state"] == "present"
    assert "dailySleepDTO.sleepScores.overall.value" in score["field_paths"]
    assert score["value_state"] == "present"
    assert "dailySleepDTO.deepSleepSeconds" in stages["field_paths"]
    assert stages["value_state"] == "present"


def test_successful_endpoint_without_nested_metric_leaf_is_missing_not_supported() -> None:
    client = FakeProbeClient(
        responses={"get_sleep_data": {"dailySleepDTO": {"providerAddedField": "synthetic"}}}
    )

    sleep = _capability(
        GarminCapabilityProbe(client).run(("2026-09-05",)), "sleep"
    )

    assert sleep["request_succeeded"] is True
    assert sleep["status"] == GarminProbeStatus.SUCCEEDED.value
    assert sleep["value_state"] == "missing"
    assert sleep["target_device_evidence"] is False


def test_training_readiness_score_is_account_evidence_without_target_attribution() -> None:
    client = FakeProbeClient(include_device=False)

    readiness = _capability(
        GarminCapabilityProbe(client).run(("2026-09-05",)), "training_readiness"
    )

    assert readiness["request_succeeded"] is True
    assert readiness["value_state"] == "present"
    assert readiness["device_attribution"] == "unattributed"
    assert readiness["target_device_evidence"] is False
    assert readiness["static_device_support"] == "not_supported"


def test_training_status_other_device_is_not_target_evidence() -> None:
    client = FakeProbeClient(
        responses={
            "get_training_status": {
                "device": {"model": "Forerunner 265"},
                "trainingStatus": "productive",
            }
        }
    )

    status = _capability(
        GarminCapabilityProbe(client).run(("2026-09-05",)), "training_status"
    )
    unified = _capability(
        GarminCapabilityProbe(FakeProbeClient(responses=client.responses)).run(("2026-09-05",)),
        "unified_training_status",
    )

    assert status["device_attribution"] == "other_device"
    assert status["target_device_evidence"] is False
    assert unified["device_attribution"] == "other_device"
    assert unified["target_device_evidence"] is False


def test_activity_typed_effect_and_load_paths_are_optional_metric_leaves() -> None:
    client = FakeProbeClient(
        responses={
            "get_activity": {"device": {"model": "Vivoactive 5"}, "distance": 1000},
            "get_activity_details": {"device": {"model": "Vivoactive 5"}, "distance": 1000},
        }
    )

    report = GarminCapabilityProbe(client).run(("2026-09-05",))

    effect = _capability(report, "training_effect")
    load = _capability(report, "acute_training_load")
    assert effect["request_succeeded"] is True
    assert effect["value_state"] == "missing"
    assert effect["target_device_evidence"] is False
    assert load["value_state"] == "missing"
    assert load["target_device_evidence"] is False


def test_empty_vo2_response_is_date_window_evidence_only() -> None:
    client = FakeProbeClient(responses={"get_max_metrics": {}})

    vo2 = _capability(
        GarminCapabilityProbe(client).run(("2026-09-05",)), "vo2_max"
    )

    assert vo2["request_succeeded"] is True
    assert vo2["status"] == GarminProbeStatus.EMPTY.value
    assert vo2["value_state"] == "empty"
    assert vo2["target_device_evidence"] is False


def test_mixed_target_and_other_device_markers_are_not_target_evidence() -> None:
    client = FakeProbeClient(
        responses={
            "get_activity": {
                "device": {"model": "Vivoactive 5"},
                "sourceDevice": {"model": "Forerunner 265"},
                "aerobicTrainingEffect": 3.0,
            },
            "get_activity_details": {
                "device": {"model": "Vivoactive 5"},
                "sourceDevice": {"model": "Forerunner 265"},
                "aerobicTrainingEffect": 3.0,
            },
        }
    )

    report = GarminCapabilityProbe(client).run(("2026-09-05",))

    effect = _capability(report, "training_effect")
    assert effect["device_attribution"] == "mixed"
    assert effect["target_device_evidence"] is False


def test_nonempty_metric_container_without_expected_leaf_is_unknown_evidence() -> None:
    client = FakeProbeClient(
        responses={
            "get_training_readiness": [
                {
                    "device": {"model": "Vivoactive 5"},
                    "trainingReadiness": {"providerAddedField": "synthetic"},
                }
            ]
        }
    )

    readiness = _capability(
        GarminCapabilityProbe(client).run(("2026-09-05",)), "training_readiness"
    )

    assert readiness["value_state"] == "missing"
    assert readiness["device_attribution"] == "target_device"
    assert readiness["target_device_evidence"] is False


def test_reauth_required_aborts_remaining_provider_calls() -> None:
    class ReauthRequiredError(Exception):
        status_code = 401

    client = FakeProbeClient(errors={"get_sleep_data": ReauthRequiredError()})

    report = GarminCapabilityProbe(client).run(("2026-09-05",))
    data = report.as_dict()

    assert report.abort_reason == "reauth_required"
    assert report.request_count == 2
    assert [method for method, _, _ in client.calls] == [
        "get_user_summary",
        "get_sleep_data",
    ]
    assert _capability(report, "sleep")["status"] == GarminProbeStatus.REAUTH_REQUIRED.value
    assert _capability(report, "heart_rate")["status"] == GarminProbeStatus.NOT_RUN.value
    assert _capability(report, "heart_rate")["not_run_reason"] == "reauth_required"
    assert data["probe"]["abort_reason"] == "reauth_required"


def test_pinned_details_signature_and_probe_no_route_request() -> None:
    from garminconnect import Garmin

    signature = inspect.signature(Garmin.get_activity_details)
    assert {"maxchart", "maxpoly"}.issubset(signature.parameters)
    discovery_source = inspect.getsource(Garmin.get_activities_by_date)
    assert "MAX_PAGINATED_REQUESTS" in discovery_source
    assert "range(MAX_PAGINATED_REQUESTS)" in discovery_source

    client = FakeProbeClient()
    GarminCapabilityProbe(client).run(("2026-09-05",))

    detail_calls = [call for call in client.calls if call[0] == "get_activity_details"]
    assert detail_calls == [
        (
            "get_activity_details",
            (str(SYNTHETIC_ACTIVITY_ID),),
            {"maxchart": 1, "maxpoly": 0},
        )
    ]
    discovery_calls = [call for call in client.calls if call[0] == "connectapi"]
    assert discovery_calls == [
        (
            "connectapi",
            (client.garmin_connect_activities,),
            {
                "params": {
                    "startDate": "2026-09-05",
                    "endDate": "2026-09-05",
                    "start": "0",
                    "limit": "1",
                }
            },
        )
    ]
    assert not any(
        "route" in method.casefold() or "polyline" in method.casefold()
        for method, _, _ in client.calls
    )


class ExplodingSequence(Sequence[Any]):
    def __init__(self, values: list[Any], allowed_items: int) -> None:
        self._values = values
        self._allowed_items = allowed_items

    def __len__(self) -> int:
        return len(self._values)

    def __getitem__(self, index: int) -> Any:
        return self._values[index]

    def __iter__(self):
        for index, value in enumerate(self._values):
            if index >= self._allowed_items:
                raise AssertionError("bounded helper traversed past its limit")
            yield value


def test_activity_discovery_and_redaction_traversal_are_bounded() -> None:
    activity = {
        "device": {"model": "Vivoactive 5"},
        "activityId": SYNTHETIC_ACTIVITY_ID,
        "activityType": "cycling",
        "distanceMeters": 1000,
    }
    client = FakeProbeClient(
        responses={
            "get_activities_by_date": ExplodingSequence([activity], allowed_items=1),
        }
    )

    report = GarminCapabilityProbe(client).run(("2026-09-05",))

    assert report.activity_selected is True
    assert report.request_count == 15


def test_two_day_probe_stays_inside_hard_provider_request_budget() -> None:
    client = FakeProbeClient()

    report = GarminCapabilityProbe(client).run(("2026-09-05", "2026-09-06"))

    assert report.request_count == 27
    assert report.request_count <= report.as_dict()["probe"]["max_provider_requests"]
    assert all(method != "get_activities_by_date" for method, _, _ in client.calls)
    assert client.retry_attempts == 3


def test_compressed_fit_bytes_remain_not_evaluated() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w") as archive:
        archive.writestr("activity.fit", b"recoveryTimeSeconds")

    assert _recovery_time_visibility(output.getvalue()) == "not_evaluated"
    assert _recovery_time_visibility({"recoveryTimeSeconds": 120}) == "not_evaluated"


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
