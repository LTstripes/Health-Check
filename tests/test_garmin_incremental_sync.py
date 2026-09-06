"""Synthetic Garmin incremental-sync tests.

These tests use provider-shaped fixtures only.  They do not read owner
credentials, session files, or live Garmin payloads.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from healthcheck import cli
from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine
from healthcheck.db.models import (
    CoverageInterval,
    GarminPayloadObservation,
    GarminRecordMetric,
    GarminSource,
    GarminSourceRecord,
    PhysicalDevice,
    SyncRun,
    SyncStreamState,
)
from healthcheck.garmin.auth import GarminAuthResult, GarminAuthStatus
from healthcheck.garmin.sync import (
    DEFAULT_TRAILING_WINDOW_DAYS,
    MAX_SYNC_PROVIDER_REQUESTS,
    MAX_TRAILING_WINDOW_DAYS,
    PRODUCTION_SYNC_SURFACES,
    GarminSyncStatus,
    compute_sync_window,
    run_garmin_incremental_sync,
    validate_trailing_window_days,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "garmin"
AS_OF = date(2099, 1, 2)


class NotFoundError(Exception):
    status_code = 404


class AuthenticationError(Exception):
    status_code = 401


def raw_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / f"{name}.json").read_text(encoding="utf-8"))


def _with_device(
    payload: Mapping[str, Any], *, include_device: bool, other_device: bool
) -> dict[str, Any]:
    value = dict(payload)
    if include_device:
        model = "Forerunner 265" if other_device else "Vivoactive 5"
        value["device"] = {"model": model}
    return value


class FakeSyncClient:
    garmin_connect_activities = "/activitylist-service/activities/search/activities"

    def __init__(
        self,
        *,
        responses: Mapping[str, Any] | None = None,
        errors: Mapping[str, BaseException] | None = None,
        empty: set[str] | None = None,
        include_device: bool = True,
        other_device: bool = False,
        sleep_payloads: list[Any] | None = None,
    ) -> None:
        self.responses = dict(responses or {})
        self.errors = dict(errors or {})
        self.empty = set(empty or ())
        self.include_device = include_device
        self.other_device = other_device
        self.sleep_payloads = list(sleep_payloads or [])
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.retry_attempts = 3
        self._sleep_index = 0

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((method, args, kwargs))
        if method in self.errors:
            raise self.errors[method]
        if method in self.empty:
            return {} if method != "get_body_battery" else []
        if method in self.responses:
            response = self.responses[method]
            return response(*args, **kwargs) if callable(response) else response
        return self._default(method)

    def _default(self, method: str) -> Any:
        device = self.include_device
        other = self.other_device
        if method == "get_user_summary":
            return _with_device(
                {"calendarDate": "2099-01-02", "userActivitySummary": {"totalKilocalories": 12}},
                include_device=device,
                other_device=other,
            )
        if method == "get_sleep_data":
            if self.sleep_payloads:
                payload = self.sleep_payloads[min(self._sleep_index, len(self.sleep_payloads) - 1)]
                self._sleep_index += 1
                return _with_device(payload, include_device=device, other_device=other)
            return _with_device(
                raw_fixture("sleep")["payload"],
                include_device=device,
                other_device=other,
            )
        if method == "get_heart_rates":
            return _with_device(
                {"calendarDate": "2099-01-02", "heartRate": 0, "timestamp": "2099-01-02T08:15:00Z"},
                include_device=device,
                other_device=other,
            )
        if method == "get_rhr_day":
            return _with_device(
                {
                    "calendarDate": "2099-01-02",
                    "allMetrics": {"metricsMap": {"WELLNESS_RESTING_HEART_RATE": [{"value": 52}]}},
                },
                include_device=device,
                other_device=other,
            )
        if method == "get_hrv_data":
            return _with_device(
                {
                    "calendarDate": "2099-01-02",
                    "hrvSummary": {"weeklyAvg": 55, "status": "balanced"},
                },
                include_device=device,
                other_device=other,
            )
        if method == "get_stress_data":
            return _with_device(
                {"calendarDate": "2099-01-02", "stress": None},
                include_device=device,
                other_device=other,
            )
        if method == "get_body_battery":
            return [
                _with_device(
                    {"calendarDate": "2099-01-02", "bodyBattery": 64},
                    include_device=device,
                    other_device=other,
                )
            ]
        if method == "get_spo2_data":
            return _with_device(
                {"calendarDate": "2099-01-02", "spo2": 98},
                include_device=device,
                other_device=other,
            )
        if method == "get_respiration_data":
            return _with_device(
                {"calendarDate": "2099-01-02", "respiration": 15},
                include_device=device,
                other_device=other,
            )
        if method == "connectapi":
            activities = raw_fixture("activity")["payload"]["activities"]
            return [
                _with_device(item, include_device=device, other_device=other) for item in activities
            ]
        raise AssertionError(f"unexpected Garmin method {method}")

    def get_user_summary(self, cdate: str) -> Any:
        return self._call("get_user_summary", cdate)

    def get_sleep_data(self, cdate: str) -> Any:
        return self._call("get_sleep_data", cdate)

    def get_heart_rates(self, cdate: str) -> Any:
        return self._call("get_heart_rates", cdate)

    def get_rhr_day(self, cdate: str) -> Any:
        return self._call("get_rhr_day", cdate)

    def get_hrv_data(self, cdate: str) -> Any:
        return self._call("get_hrv_data", cdate)

    def get_stress_data(self, cdate: str) -> Any:
        return self._call("get_stress_data", cdate)

    def get_body_battery(self, startdate: str, enddate: str | None = None) -> Any:
        return self._call("get_body_battery", startdate, enddate)

    def get_spo2_data(self, cdate: str) -> Any:
        return self._call("get_spo2_data", cdate)

    def get_respiration_data(self, cdate: str) -> Any:
        return self._call("get_respiration_data", cdate)

    def connectapi(self, path: str, **kwargs: Any) -> Any:
        return self._call("connectapi", path, **kwargs)

    def get_activities_by_date(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("get_activities_by_date", *args, **kwargs)

    def download_activity(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("download_activity", *args, **kwargs)

    def get_activity(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("get_activity", *args, **kwargs)

    def get_activity_details(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("get_activity_details", *args, **kwargs)

    def get_training_readiness(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("get_training_readiness", *args, **kwargs)

    def get_training_status(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("get_training_status", *args, **kwargs)

    def get_max_metrics(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("get_max_metrics", *args, **kwargs)


def _run(tmp_path: Path, client: FakeSyncClient, **kwargs: Any):
    settings = Settings(data_dir=tmp_path / "runtime")
    return run_garmin_incremental_sync(
        settings,
        client=client,
        auth_result=GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED, session_reused=True),
        as_of=kwargs.pop("as_of", AS_OF),
        trailing_window_days=kwargs.pop("trailing_window_days", 1),
        **kwargs,
    )


def _engine_factory(tmp_path: Path):
    from healthcheck.runtime import resolve_runtime_paths

    paths = resolve_runtime_paths(Settings(data_dir=tmp_path / "runtime"))
    engine = create_sqlite_engine(paths)
    return engine, create_session_factory(engine)


def test_trailing_window_is_bounded_and_first_run_is_not_backfill():
    start, end = compute_sync_window(date(2099, 1, 10), 7)
    assert start == date(2099, 1, 4)
    assert end == date(2099, 1, 10)
    assert DEFAULT_TRAILING_WINDOW_DAYS == 7
    assert MAX_TRAILING_WINDOW_DAYS == 14
    with pytest.raises(ValueError):
        validate_trailing_window_days(30)
    with pytest.raises(ValueError):
        validate_trailing_window_days(0)


def test_first_run_persists_streams_coverage_and_checkpoints(tmp_path: Path):
    client = FakeSyncClient()
    report = _run(tmp_path, client)

    assert report.status is GarminSyncStatus.SUCCEEDED
    payload = report.as_dict()
    assert payload["sync"]["historical_backfill"] is False
    assert payload["sync"]["gps_or_fit_downloaded"] is False
    assert report.as_dict()["privacy"]["raw_values_emitted"] is False
    methods = [name for name, _args, _kwargs in client.calls]
    assert "get_sleep_data" in methods
    assert "get_user_summary" in methods
    assert "connectapi" in methods
    assert "get_activities_by_date" not in methods
    assert "download_activity" not in methods
    assert "get_training_readiness" not in methods
    assert "get_training_status" not in methods
    assert "get_max_metrics" not in methods
    assert client.retry_attempts == 3

    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            assert session.scalar(select(func.count(SyncRun.id))) == 1
            assert session.scalar(select(func.count(GarminSourceRecord.id))) >= 1
            assert session.scalar(select(func.count(CoverageInterval.id))) >= 1
            states = list(session.scalars(select(SyncStreamState)))
            codes = {item.stream_code for item in states}
            assert "sleep" in codes
            assert "resting_heart_rate" in codes
            assert "activities" in codes
            sleep_state = next(item for item in states if item.stream_code == "sleep")
            assert sleep_state.cursor == "2099-01-02"
            assert sleep_state.trailing_window_days == 1
            assert sleep_state.last_success_at is not None
            source = session.scalar(select(GarminSource))
            assert source is not None
            assert source.device_attributed is True
            assert session.get(PhysicalDevice, source.physical_device_id).model == "Vivoactive 5"
    finally:
        engine.dispose()


def test_identical_replay_does_not_duplicate_current_records(tmp_path: Path):
    client = FakeSyncClient()
    first = _run(tmp_path, client)
    second = _run(tmp_path, FakeSyncClient())

    assert first.status is GarminSyncStatus.SUCCEEDED
    assert second.status is GarminSyncStatus.SUCCEEDED
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            current = session.scalar(select(func.count(GarminSourceRecord.id)))
            observations = session.scalar(select(func.count(GarminPayloadObservation.id)))
            runs = session.scalar(select(func.count(SyncRun.id)))
            assert current >= 1
            assert observations == current * 2 or observations > current
            assert runs == 2
            keys = list(session.scalars(select(GarminSourceRecord.idempotency_key)))
            assert len(keys) == len(set(keys))
    finally:
        engine.dispose()


def test_overlapping_trailing_window_applies_late_correction(tmp_path: Path):
    original = raw_fixture("sleep")["payload"]
    original = {**original, "id": "synthetic-sleep-night-2099-01-02"}
    corrected = json.loads(json.dumps(original))
    corrected["dailySleepDTO"]["sleepScores"]["overall"]["value"] = 90
    first_client = FakeSyncClient(sleep_payloads=[original])
    assert _run(tmp_path, first_client).status is GarminSyncStatus.SUCCEEDED
    second_client = FakeSyncClient(sleep_payloads=[corrected])
    assert _run(tmp_path, second_client).status is GarminSyncStatus.SUCCEEDED

    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            sleep_records = list(
                session.scalars(
                    select(GarminSourceRecord).where(GarminSourceRecord.stream_code == "sleep")
                )
            )
            assert len(sleep_records) == 1
            metrics = {
                item.metric_code: item
                for item in session.scalars(
                    select(GarminRecordMetric).where(
                        GarminRecordMetric.record_id == sleep_records[0].id
                    )
                )
            }
            assert metrics["sleep_score"].value_number == 90
            assert session.scalar(select(func.count(GarminPayloadObservation.id))) >= 2
    finally:
        engine.dispose()


def test_partial_failure_preserves_successful_checkpoint(tmp_path: Path):
    client = FakeSyncClient(errors={"get_hrv_data": ConnectionError("synthetic-provider-outage")})
    report = _run(tmp_path, client)
    assert report.status is GarminSyncStatus.PARTIAL
    hrv = next(item for item in report.attempts if item.surface == "hrv_status")
    sleep = next(item for item in report.attempts if item.surface == "sleep")
    assert hrv.status is GarminSyncStatus.FAILED
    assert hrv.error is not None
    assert "synthetic-provider-outage" not in json.dumps(report.as_dict())
    assert sleep.status is GarminSyncStatus.SUCCEEDED

    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            states = {item.stream_code: item for item in session.scalars(select(SyncStreamState))}
            assert states["sleep"].last_success_at is not None
            assert states["hrv_status"].last_success_at is None
            assert states["hrv_status"].watermark is None
            assert states["hrv_status"].last_attempt_at is not None
            failed_coverage = [
                item
                for item in session.scalars(select(CoverageInterval))
                if item.metric_code == "hrv_status"
            ]
            assert failed_coverage
            assert failed_coverage[0].status == "failed"
            assert failed_coverage[0].observed_count is None
    finally:
        engine.dispose()


def test_empty_payload_is_confirmed_empty_and_not_zero(tmp_path: Path):
    report = _run(tmp_path, FakeSyncClient(empty={"get_sleep_data"}))
    sleep = next(item for item in report.attempts if item.surface == "sleep")
    assert sleep.status is GarminSyncStatus.EMPTY
    assert sleep.coverage_status == "confirmed_empty"
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            coverage = next(
                item
                for item in session.scalars(select(CoverageInterval))
                if item.metric_code == "sleep"
            )
            assert coverage.status == "confirmed_empty"
            assert coverage.expected_count is None
            state = next(
                item
                for item in session.scalars(select(SyncStreamState))
                if item.stream_code == "sleep"
            )
            assert state.last_success_at is not None
            assert state.cursor == "2099-01-02"
    finally:
        engine.dispose()


def test_not_found_does_not_advance_watermark(tmp_path: Path):
    report = _run(tmp_path, FakeSyncClient(errors={"get_spo2_data": NotFoundError()}))
    spo2 = next(item for item in report.attempts if item.surface == "spo2")
    assert spo2.status is GarminSyncStatus.UNAVAILABLE
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            state = next(
                item
                for item in session.scalars(select(SyncStreamState))
                if item.stream_code == "spo2"
            )
            assert state.watermark is None
            assert state.last_success_at is None
            coverage = next(
                item
                for item in session.scalars(select(CoverageInterval))
                if item.metric_code == "spo2"
            )
            assert coverage.status == "unavailable"
            assert coverage.observed_count is None
    finally:
        engine.dispose()


def test_restart_resume_retries_failed_surface_without_losing_success(tmp_path: Path):
    failed = _run(tmp_path, FakeSyncClient(errors={"get_hrv_data": ConnectionError("synthetic")}))
    assert failed.status is GarminSyncStatus.PARTIAL
    resumed = _run(tmp_path, FakeSyncClient())
    assert resumed.status is GarminSyncStatus.SUCCEEDED
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            states = {item.stream_code: item for item in session.scalars(select(SyncStreamState))}
            assert states["sleep"].last_success_at is not None
            assert states["hrv_status"].last_success_at is not None
            assert states["hrv_status"].cursor == "2099-01-02"
    finally:
        engine.dispose()


def test_missing_null_and_zero_stay_distinct(tmp_path: Path):
    report = _run(tmp_path, FakeSyncClient())
    assert report.status is GarminSyncStatus.SUCCEEDED
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            metrics = list(session.scalars(select(GarminRecordMetric)))
            by_code = {}
            for item in metrics:
                by_code.setdefault(item.metric_code, []).append(item)
            heart = next(
                item for item in by_code["heart_rate_bpm"] if item.state == "value"
            )
            assert heart.value_number == 0
            stress = next(item for item in by_code["stress"] if item.state == "null")
            assert stress.value_number is None
            missing = [item for item in metrics if item.state == "missing"]
            assert missing
    finally:
        engine.dispose()


def test_method_presence_is_not_vivoactive_attribution(tmp_path: Path):
    report = _run(tmp_path, FakeSyncClient(include_device=False))
    assert report.status in {GarminSyncStatus.SUCCEEDED, GarminSyncStatus.PARTIAL}
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            sources = list(session.scalars(select(GarminSource)))
            assert sources
            assert all(source.device_attributed is False for source in sources)
            assert all(source.physical_device_id is None for source in sources)
            assert session.scalar(select(func.count(PhysicalDevice.id))) == 0
    finally:
        engine.dispose()


def test_other_device_is_not_promoted_to_vivoactive(tmp_path: Path):
    report = _run(tmp_path, FakeSyncClient(other_device=True))
    assert all(
        item.device_attribution != "target_device"
        for item in report.attempts
        if item.status is not GarminSyncStatus.NOT_RUN
    )
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            sources = list(session.scalars(select(GarminSource)))
            assert sources
            assert all(source.device_code != "garmin_vivoactive_5" for source in sources)
    finally:
        engine.dispose()


def test_request_budget_stops_without_unbounded_loops(tmp_path: Path):
    client = FakeSyncClient()
    report = _run(tmp_path, client, max_provider_requests=1)
    assert report.abort_reason == "request_budget_exhausted"
    assert report.request_count == 1
    assert any(item.status is GarminSyncStatus.NOT_RUN for item in report.attempts)
    assert report.request_count < MAX_SYNC_PROVIDER_REQUESTS
    assert "get_activities_by_date" not in [name for name, _a, _k in client.calls]


def test_reauth_aborts_remaining_surfaces(tmp_path: Path):
    client = FakeSyncClient(errors={"get_user_summary": AuthenticationError()})
    report = _run(tmp_path, client)
    assert report.status is GarminSyncStatus.REAUTH_REQUIRED
    assert report.abort_reason == "reauth_required"
    executed = [
        item.surface
        for item in report.attempts
        if item.status is not GarminSyncStatus.NOT_RUN
    ]
    assert executed == ["daily_summary"]
    assert any(item.not_run_reason == "reauth_required" for item in report.attempts)


def test_cli_garmin_sync_rejects_invalid_window_and_exposes_command(tmp_path: Path, capsys):
    args = cli.build_parser().parse_args(
        ["garmin-sync", "--data-dir", str(tmp_path / "runtime"), "--trailing-window-days", "99"]
    )
    assert args.command == "garmin-sync"
    code = cli.main(
        [
            "garmin-sync",
            "--data-dir",
            str(tmp_path / "runtime"),
            "--date",
            "2099-01-02",
            "--trailing-window-days",
            "99",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    payload = json.loads(captured.out)
    assert payload["error"]["error_code"] == "invalid_sync_request"
    assert "token" not in captured.out.lower() or payload["privacy"]["tokens_emitted"] is False


def test_sync_surfaces_are_the_accepted_first_wave_only():
    codes = [item.code for item in PRODUCTION_SYNC_SURFACES]
    assert codes == [
        "daily_summary",
        "sleep",
        "heart_rate",
        "resting_heart_rate",
        "hrv_status",
        "stress",
        "body_battery",
        "spo2",
        "respiration",
        "activities",
    ]
    assert all(item.method != "download_activity" for item in PRODUCTION_SYNC_SURFACES)
    assert all(item.method != "get_activities_by_date" for item in PRODUCTION_SYNC_SURFACES)
