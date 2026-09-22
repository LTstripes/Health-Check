"""Synthetic-only regressions for the Garmin Training Phase A probe."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from healthcheck import cli
from healthcheck.config import Settings
from healthcheck.garmin.auth import GarminAuthResult, GarminAuthStatus
from healthcheck.garmin.training_probe import (
    MAX_ACTIVITY_PAGE_SIZE,
    MAX_DATA_READS,
    GarminTrainingPhaseAProbe,
    TrainingProbeStatus,
    validate_training_probe_request,
)


class _RateLimitError(Exception):
    status_code = 429


class _AuthenticationError(Exception):
    status_code = 401


class _ProviderUnavailableError(Exception):
    status_code = 503


class FakeTrainingClient:
    garmin_connect_activities = "/activitylist-service/activities/search/activities"

    def __init__(self, *, errors: dict[str, Exception] | None = None) -> None:
        self.retry_attempts = 3
        self.errors = errors or {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))
        if name in self.errors:
            raise self.errors[name]

    def get_devices(self) -> list[dict[str, Any]]:
        self._record("get_devices")
        return [
            {
                "deviceId": 987654321,
                "unitId": "private-unit-id",
                "productDisplayName": "Private Watch Name",
                "deviceTypePk": 42,
            },
            {
                "deviceId": 987654322,
                "unitId": "other-private-unit-id",
                "productDisplayName": "Private Bike Computer",
                "deviceTypePk": 43,
            },
        ]

    def get_primary_training_device(self) -> dict[str, Any]:
        self._record("get_primary_training_device")
        return {
            "deviceId": 987654321,
            "unitId": "private-unit-id",
            "productDisplayName": "Private Watch Name",
            "primaryTrainingDevice": True,
            "priorityOrder": 1,
        }

    def get_training_status(self, requested_date: str) -> dict[str, Any]:
        self._record("get_training_status", requested_date)
        return {
            "mostRecentTrainingStatus": {
                "latestTrainingStatusData": {
                    "dynamic-private-device-key": {
                        "calendarDate": requested_date,
                        "deviceId": 987654321,
                        "trainingStatus": 0,
                        "trainingStatusFeedbackPhrase": "PRIVATE_STATUS_PHRASE",
                        "weeklyTrainingLoad": 222.25,
                        "fitnessTrend": "not-a-number",
                        "primaryTrainingDevice": True,
                        "acuteTrainingLoadDTO": {
                            "dailyTrainingLoadAcute": 0,
                            "dailyTrainingLoadChronic": None,
                            "acwrPercent": 101,
                            "dailyAcuteChronicWorkloadRatio": "invalid-private-value",
                            "acwrStatus": "PRIVATE_ACWR_STATUS",
                        },
                    }
                }
            },
            "mostRecentTrainingLoadBalance": {
                "metricsTrainingLoadBalanceDTOMap": {
                    "dynamic-private-device-key": {
                        "monthlyLoadAerobicLow": 100,
                        "monthlyLoadAerobicHigh": 200,
                        "monthlyLoadAnaerobic": 300,
                        "monthlyLoadAerobicLowTargetMin": 90,
                        "monthlyLoadAerobicLowTargetMax": 110,
                    }
                }
            },
            "mostRecentVO2Max": {
                "generic": {"vo2MaxValue": 51.7},
                "cycling": {"vo2MaxValue": None},
            },
        }

    def get_training_readiness(self, requested_date: str) -> list[dict[str, Any]]:
        self._record("get_training_readiness", requested_date)
        return [
            {
                "calendarDate": requested_date,
                "timestamp": f"{requested_date}T06:00:00.0",
                "timestampLocal": f"{requested_date}T09:00:00.0",
                "deviceId": 987654321,
                "score": 0,
                "level": "PRIVATE_LEVEL",
                "recoveryTime": 0,
                "recoveryTimeFactorPercent": 100,
                "recoveryTimeFactorFeedback": "PRIVATE_FEEDBACK",
                "recoveryTimeChangePhrase": "PRIVATE_CHANGE",
                "acuteLoad": 0,
                "acwrFactorPercent": 99,
                "acwrFactorFeedback": "PRIVATE_ACWR_FEEDBACK",
                "inputContext": "PRIVATE_CONTEXT",
                "primaryActivityTracker": True,
                "validSleep": True,
            },
            {
                "calendarDate": requested_date,
                "timestamp": f"{requested_date}T12:00:00.0",
                "timestampLocal": f"{requested_date}T15:00:00.0",
                "deviceId": 987654321,
                "score": 73,
                "level": "PRIVATE_LEVEL_2",
                "recoveryTime": None,
                "recoveryTimeChangePhrase": None,
                "inputContext": "PRIVATE_CONTEXT_2",
                "primaryActivityTracker": True,
                "validSleep": True,
            },
        ]

    def get_max_metrics_range(self, start: str, end: str) -> dict[str, Any]:
        self._record("get_max_metrics_range", start, end)
        return {
            "maxMetrics": {"vo2MaxRunning": 0, "vo2MaxCycling": None},
            "generic": {"vo2MaxValue": 55.5},
        }

    def get_max_metrics(self, requested_date: str) -> dict[str, Any]:
        self._record("get_max_metrics", requested_date)
        return {
            "calendarDate": requested_date,
            "maxMetrics": {"vo2MaxRunning": 0, "vo2MaxCycling": None},
            "generic": {"vo2MaxValue": 55.5},
        }

    def connectapi(self, endpoint: str, *, params: dict[str, str]) -> list[dict[str, Any]]:
        self._record("connectapi", endpoint, params=params)
        return [
            {
                "activityId": 7001,
                "activityName": "PRIVATE_RIDE_NAME",
                "activityType": {"typeKey": "PRIVATE_ACTIVITY_TYPE"},
                "startTimeLocal": "2026-09-03T08:15:00.0",
                "startTimeGMT": "2026-09-03T05:15:00.0",
                "deviceId": 987654322,
                "aerobicTrainingEffect": 0,
                "anaerobicTrainingEffect": 2.5,
                "activityTrainingLoad": 111,
                "trainingEffectLabel": "PRIVATE_EFFECT",
            },
            {"activityId": "7002", "deviceId": 987654322},
            {"activityId": 7003, "deviceId": 987654322},
        ]

    def get_activity(self, activity_id: str) -> dict[str, Any]:
        self._record("get_activity", activity_id)
        return {
            "activityId": int(activity_id),
            "activityName": f"PRIVATE_ACTIVITY_{activity_id}",
            "activityType": {"typeKey": "PRIVATE_TYPE"},
            "startTimeLocal": "2026-09-03T08:15:00.0",
            "startTimeGMT": "2026-09-03T05:15:00.0",
            "deviceId": 987654322,
            "aerobicTrainingEffect": 3.1,
            "anaerobicTrainingEffect": 0,
            "activityTrainingLoad": 144,
            "trainingEffectLabel": "PRIVATE_SUMMARY_EFFECT",
        }


def _maximal_request():
    return validate_training_probe_request(
        ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"),
        (("2026-09-01", "2026-09-07"), ("2026-08-01", "2026-08-07")),
        "2026-09-01",
        "2026-09-01",
        "2026-09-07",
        ("7001", "7002", "7003"),
        "2026-09-02",
    )


def _observation(report: dict[str, Any], surface: str, role: str) -> dict[str, Any]:
    return next(
        item
        for item in report["observations"]
        if item["surface"] == surface and item["request_role"] == role
    )


def test_maximal_probe_uses_exact_bounded_reads_and_emits_no_private_values() -> None:
    client = FakeTrainingClient()

    report = GarminTrainingPhaseAProbe(client).run(_maximal_request()).as_dict()

    assert report["status"] == TrainingProbeStatus.COMPLETED.value
    assert report["sample_incomplete"] is False
    assert report["request_budget"] == {
        "max_data_reads": MAX_DATA_READS,
        "data_reads": MAX_DATA_READS,
        "provider_retries_disabled": True,
        "automatic_expansion": False,
    }
    assert client.retry_attempts == 3
    assert [name for name, _, _ in client.calls].count("connectapi") == 1
    activity_call = next(call for call in client.calls if call[0] == "connectapi")
    assert activity_call[2]["params"] == {
        "startDate": "2026-09-01",
        "endDate": "2026-09-07",
        "start": "0",
        "limit": str(MAX_ACTIVITY_PAGE_SIZE),
    }
    assert [args[0] for name, args, _ in client.calls if name == "get_activity"] == [
        "7001",
        "7002",
        "7003",
    ]
    assert report["consistency"]["repeat"] == {
        "training_status": "same",
        "training_readiness": "same",
    }
    assert report["consistency"]["single_vs_range"] == [
        {"range_index": 1, "disposition": "different"},
        {"range_index": 2, "disposition": "not_comparable"},
    ]

    encoded = json.dumps(report, sort_keys=True)
    for private_value in (
        "2026-09-01",
        "2026-09-02",
        "2026-09-03",
        "2026-09-04",
        "987654321",
        "987654322",
        "7001",
        "7002",
        "7003",
        "dynamic-private-device-key",
        "private-unit-id",
        "Private Watch Name",
        "PRIVATE_STATUS_PHRASE",
        "PRIVATE_LEVEL",
        "PRIVATE_CONTEXT",
        "PRIVATE_RIDE_NAME",
        "invalid-private-value",
    ):
        assert private_value not in encoded


def test_probe_preserves_missing_null_zero_nonzero_invalid_and_dynamic_key_counts() -> None:
    report = GarminTrainingPhaseAProbe(FakeTrainingClient()).run(_maximal_request()).as_dict()
    status = _observation(report, "training_status", "training_date_1")
    readiness = _observation(report, "training_readiness", "training_date_1")

    fields = status["field_state_counts"]
    assert fields[
        "status.latestTrainingStatusData.<device>.acuteTrainingLoadDTO.dailyTrainingLoadAcute"
    ] == {"zero": 1}
    assert fields[
        "status.latestTrainingStatusData.<device>.acuteTrainingLoadDTO.dailyTrainingLoadChronic"
    ] == {"null": 1}
    assert fields["status.latestTrainingStatusData.<device>.acuteTrainingLoadDTO.acwrPercent"] == {
        "nonzero": 1
    }
    assert fields[
        "status.latestTrainingStatusData.<device>.acuteTrainingLoadDTO.dailyAcuteChronicWorkloadRatio"
    ] == {"invalid": 1}
    assert fields["status.loadBalance.<device>.monthlyLoadAerobicHighTargetMin"] == {"missing": 1}
    assert status["dynamic_entry_counts"] == {
        "latest_training_status_device_count": {
            "count": 1,
            "truncated": False,
            "state": "present",
        },
        "load_balance_device_count": {
            "count": 1,
            "truncated": False,
            "state": "present",
        },
    }
    assert status["dynamic_keys_redacted"] is True
    assert status["source_date_relation"] == "same"
    assert status["metric_producer_proven"] is False
    assert readiness["snapshot_cardinality"] == 2
    assert readiness["field_state_counts"]["readiness[].score"] == {
        "nonzero": 1,
        "zero": 1,
    }
    assert readiness["field_state_counts"]["readiness[].recoveryTime"] == {
        "null": 1,
        "zero": 1,
    }


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"dates": ()}, "one to four"),
        (
            {
                "dates": (
                    "2026-09-01",
                    "2026-09-02",
                    "2026-09-03",
                    "2026-09-04",
                    "2026-09-05",
                )
            },
            "one to four",
        ),
        (
            {
                "max_ranges": (
                    ("2026-09-01", "2026-09-02"),
                    ("2026-08-01", "2026-08-02"),
                    ("2026-07-01", "2026-07-02"),
                )
            },
            "at most two",
        ),
        ({"max_ranges": (("2026-09-01", "2026-09-08"),)}, "too wide"),
        ({"activity_ids": ("1", "2", "3", "4")}, "at most three"),
        ({"repeat_date": "2026-08-31"}, "repeat date"),
    ],
)
def test_request_validation_rejects_automatic_expansion(
    override: dict[str, Any], message: str
) -> None:
    values: dict[str, Any] = {
        "dates": ("2026-09-01",),
        "max_ranges": (("2026-09-01", "2026-09-07"),),
        "max_date": "2026-09-01",
        "activity_start": "2026-09-01",
        "activity_end": "2026-09-07",
        "activity_ids": ("1",),
        "repeat_date": None,
    }
    values.update(override)
    with pytest.raises(ValueError, match=message):
        validate_training_probe_request(**values)


def test_rate_limit_aborts_without_leaking_provider_error_or_expanding_sample() -> None:
    client = FakeTrainingClient(
        errors={"get_training_status": _RateLimitError("PRIVATE_PROVIDER_BODY")}
    )

    report = GarminTrainingPhaseAProbe(client).run(_maximal_request()).as_dict()

    assert report["status"] == TrainingProbeStatus.RATE_LIMITED.value
    assert report["sample_incomplete"] is True
    assert report["abort_reason"] == "rate_limited"
    assert report["request_budget"]["data_reads"] == 3
    assert [name for name, _, _ in client.calls] == [
        "get_devices",
        "get_primary_training_device",
        "get_training_status",
    ]
    assert "PRIVATE_PROVIDER_BODY" not in json.dumps(report)
    failure = _observation(report, "training_status", "training_date_1")
    assert failure["error"] == {
        "error_class": "provider",
        "error_code": "rate_limited",
        "http_status": 429,
    }


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_abort", "expected_error"),
    [
        (
            _AuthenticationError("PRIVATE_AUTH_BODY"),
            TrainingProbeStatus.REAUTH_REQUIRED.value,
            "reauth_required",
            {
                "error_class": "authentication",
                "error_code": "authentication_failed",
                "http_status": 401,
            },
        ),
        (
            _ProviderUnavailableError("PRIVATE_PROVIDER_BODY"),
            TrainingProbeStatus.FAILED.value,
            "provider_unavailable",
            {
                "error_class": "provider",
                "error_code": "provider_unavailable",
                "http_status": 503,
            },
        ),
    ],
)
def test_auth_and_provider_failures_abort_safely_without_private_text(
    error: Exception,
    expected_status: str,
    expected_abort: str,
    expected_error: dict[str, Any],
) -> None:
    client = FakeTrainingClient(errors={"get_devices": error})

    report = GarminTrainingPhaseAProbe(client).run(_maximal_request()).as_dict()

    assert report["status"] == expected_status
    assert report["sample_incomplete"] is True
    assert report["abort_reason"] == expected_abort
    assert report["request_budget"]["data_reads"] == 1
    assert [name for name, _, _ in client.calls] == ["get_devices"]
    assert report["observations"][0]["error"] == expected_error
    assert "PRIVATE_AUTH_BODY" not in json.dumps(report)
    assert "PRIVATE_PROVIDER_BODY" not in json.dumps(report)


def test_shape_drift_is_explicit_and_does_not_leak_the_requested_date() -> None:
    class ShapeDriftClient(FakeTrainingClient):
        def get_training_readiness(self, requested_date: str) -> dict[str, Any]:
            self._record("get_training_readiness", requested_date)
            return {"calendarDate": requested_date, "private": "PRIVATE_RAW_VALUE"}

    request = validate_training_probe_request(
        ("2026-09-01",),
        (),
        "2026-09-01",
        "2026-09-01",
        "2026-09-07",
    )

    report = GarminTrainingPhaseAProbe(ShapeDriftClient()).run(request).as_dict()

    assert report["status"] == TrainingProbeStatus.PARTIAL.value
    assert report["shape_drift"] is True
    readiness = _observation(report, "training_readiness", "training_date_1")
    assert readiness["status"] == TrainingProbeStatus.SHAPE_DRIFT.value
    assert "2026-09-01" not in json.dumps(report)
    assert "PRIVATE_RAW_VALUE" not in json.dumps(report)


def test_activity_ids_must_come_from_the_single_bounded_page() -> None:
    request = validate_training_probe_request(
        ("2026-09-01",),
        (),
        "2026-09-01",
        "2026-09-01",
        "2026-09-07",
        ("999999",),
    )
    client = FakeTrainingClient()

    report = GarminTrainingPhaseAProbe(client).run(request).as_dict()

    assert report["status"] == TrainingProbeStatus.PARTIAL.value
    assert report["activity_selection"] == {
        "requested_count": 1,
        "matched_count": 0,
        "unmatched_count": 1,
    }
    assert [name for name, _, _ in client.calls].count("connectapi") == 1
    assert "get_activity" not in [name for name, _, _ in client.calls]
    assert "999999" not in json.dumps(report)


def test_cli_uses_existing_session_without_database_or_checkpoint_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeTrainingClient()
    runtime = tmp_path / "runtime"

    class FakeAuthService:
        def __init__(self, settings: Settings, *, is_cn: bool = False) -> None:
            assert settings.data_dir == runtime
            assert is_cn is False

        def load_existing(self) -> tuple[FakeTrainingClient, GarminAuthResult]:
            return client, GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED)

    monkeypatch.setattr(cli, "GarminAuthService", FakeAuthService)
    monkeypatch.setattr(
        cli,
        "prepare_runtime",
        lambda _settings: pytest.fail("training probe must not prepare a database runtime"),
    )

    result = cli.main(
        [
            "garmin-training-phase-a",
            "--data-dir",
            str(runtime),
            "--date",
            "2026-09-01",
            "--max-range",
            "2026-09-01",
            "2026-09-07",
            "--max-date",
            "2026-09-01",
            "--activity-start",
            "2026-09-01",
            "--activity-end",
            "2026-09-07",
            "--activity-id",
            "7001",
        ]
    )

    assert result == 0
    output = capsys.readouterr().out
    assert '"status": "completed"' in output
    assert "2026-09-01" not in output
    assert "7001" not in output
    assert "healthcheck.db" not in output
    assert not runtime.exists()


def test_missing_session_is_safe_and_makes_no_provider_reads() -> None:
    request = validate_training_probe_request(
        ("2026-09-01",),
        (),
        "2026-09-01",
        "2026-09-01",
        "2026-09-07",
    )
    report = (
        GarminTrainingPhaseAProbe(None)
        .run(
            request,
            auth_result=GarminAuthResult(status=GarminAuthStatus.REAUTH_REQUIRED),
        )
        .as_dict()
    )

    assert report["status"] == TrainingProbeStatus.REAUTH_REQUIRED.value
    assert report["request_budget"]["data_reads"] == 0
    assert report["observations"] == []
    assert report["privacy"]["database_or_checkpoint_writes"] is False
