"""Synthetic Garmin incremental-sync tests.

These tests use provider-shaped fixtures only.  They do not read owner
credentials, session files, or live Garmin payloads.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
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
    RawArtifact,
    SyncRun,
    SyncStreamState,
)
from healthcheck.garmin.auth import GarminAuthResult, GarminAuthStatus
from healthcheck.garmin.contracts import load_synthetic_fixture
from healthcheck.garmin.normalization import (
    PROVIDER_SOURCE_KIND,
    garmin_source_identity,
    normalize_garmin_payload,
)
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore, serialize_garmin_payload
from healthcheck.garmin.sync import (
    DEFAULT_TRAILING_WINDOW_DAYS,
    MAX_SYNC_PROVIDER_REQUESTS,
    MAX_TRAILING_WINDOW_DAYS,
    PRODUCTION_SYNC_SURFACES,
    GarminIncrementalSync,
    GarminSyncStatus,
    compute_sync_window,
    run_garmin_incremental_sync,
    validate_trailing_window_days,
)
from healthcheck.runtime import resolve_runtime_paths
from healthcheck.source_freshness import SCOPE_BY_KEY, evaluate_scope
from healthcheck.source_freshness_read import read_facts

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "garmin"
AS_OF = date(2099, 1, 2)
FRESHNESS_NOW = datetime(2099, 1, 2, 12, tzinfo=UTC)


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
                {
                    "calendarDate": "2099-01-02",
                    "heartRateValues": [
                        ["2099-01-02T08:00:00Z", 0],
                        ["2099-01-02T08:15:00Z", 72],
                    ],
                },
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
                {
                    "calendarDate": "2099-01-02",
                    "avgStressLevel": 25,
                    "maxStressLevel": 80,
                    "stressValuesArray": [[0, 12], [60, 40]],
                },
                include_device=device,
                other_device=other,
            )
        if method == "get_body_battery":
            return [
                _with_device(
                    {
                        "calendarDate": "2099-01-02",
                        "charged": 40,
                        "drained": 55,
                        "bodyBatteryValuesArray": [[0, 64], [60, 70]],
                    },
                    include_device=device,
                    other_device=other,
                )
            ]
        if method == "get_spo2_data":
            return _with_device(
                {
                    "calendarDate": "2099-01-02",
                    "averageSpO2": 98,
                    "lastSevenDaysAvgSpO2": 97,
                    "spo2Values": [[0, 96], [60, 98]],
                },
                include_device=device,
                other_device=other,
            )
        if method == "get_respiration_data":
            return _with_device(
                {
                    "calendarDate": "2099-01-02",
                    "avgSleepRespirationValue": 15,
                    "respirationValues": [[0, 14], [60, 16]],
                },
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


def _run_freshness(
    tmp_path: Path, client: FakeSyncClient, *,
    at: datetime = FRESHNESS_NOW, trailing_window_days: int = 1,
):
    return GarminIncrementalSync(
        Settings(data_dir=tmp_path / "runtime"), client=client,
        auth_result=GarminAuthResult(
            status=GarminAuthStatus.AUTHENTICATED, session_reused=True,
        ),
        clock=lambda: at,
    ).run(as_of=AS_OF, trailing_window_days=trailing_window_days)


def _freshness_result(session, key: str, *, at: datetime = FRESHNESS_NOW):
    facts = read_facts(session, SCOPE_BY_KEY[key], evaluation_local_date=AS_OF)
    return evaluate_scope(SCOPE_BY_KEY[key], facts, evaluated_at_utc=at,
                          evaluation_local_date=AS_OF)


def test_freshness_accepts_proven_partial_garmin_daily_and_sleep_records(tmp_path: Path):
    client = FakeSyncClient(responses={
        "get_user_summary": {
            "calendarDate": "2099-01-02", "userActivitySummary": {},
        },
        "get_sleep_data": {
            "dailySleepDTO": {
                "calendarDate": "2099-01-02", "sleepTimeSeconds": 28_800,
            },
        },
    })
    report = _run_freshness(tmp_path, client)
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            for surface in ("daily_summary", "sleep", "resting_heart_rate", "hrv_status"):
                attempt = next(item for item in report.attempts if item.surface == surface)
                assert attempt.coverage_status == "present"
                checkpoint = session.scalar(select(SyncStreamState).where(
                    SyncStreamState.stream_code == surface,
                ))
                assert checkpoint is not None
                assert checkpoint.last_success_at is not None
                assert checkpoint.diagnostic_status == "present"
                coverage = session.scalar(select(CoverageInterval).where(
                    CoverageInterval.metric_code == surface,
                ))
                assert coverage is not None and coverage.status == "present"
                records = list(session.scalars(select(GarminSourceRecord).where(
                    GarminSourceRecord.surface_code == surface,
                    GarminSourceRecord.projection_status == "current",
                )))
                assert records and any(row.record_status == "partial" for row in records)
                assert _freshness_result(session, f"garmin:{surface}")["state"] == "fresh"
    finally:
        engine.dispose()


def test_freshness_counts_proven_partial_activity_in_complete_window(tmp_path: Path):
    activity = [{
        "activityId": "synthetic-partial-activity",
        "startTimeGMT": "2099-01-02T08:00:00Z",
        "duration": 3600,
    }]
    report = _run_freshness(
        tmp_path, FakeSyncClient(responses={"connectapi": activity}),
        trailing_window_days=7,
    )
    attempt = next(item for item in report.attempts if item.surface == "activities")
    assert attempt.coverage_status == "present"
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            records = list(session.scalars(select(GarminSourceRecord).where(
                GarminSourceRecord.stream_code == "activity",
                GarminSourceRecord.projection_status == "current",
            )))
            assert len(records) == 1
            assert records[0].record_status == "partial"
            coverage = session.scalar(select(CoverageInterval).where(
                CoverageInterval.metric_code == "activities",
            ))
            assert coverage is not None and coverage.status == "present"
            facts = read_facts(session, SCOPE_BY_KEY["garmin:activities"],
                               evaluation_local_date=AS_OF)
            assert (facts.coverage, facts.activity_count, facts.attribution_resolved) == (
                "complete", 1, True,
            )
            assert _freshness_result(session, "garmin:activities")["state"] == "fresh"
    finally:
        engine.dispose()


def test_freshness_does_not_accept_partial_record_without_surface_success(tmp_path: Path):
    payload = {
        "dailySleepDTO": {
            "calendarDate": "2099-01-02",
            "sleepScores": {"overall": {"value": 80}},
        },
    }
    report = _run_freshness(tmp_path, FakeSyncClient(responses={"get_sleep_data": payload}))
    attempt = next(item for item in report.attempts if item.surface == "sleep")
    assert attempt.coverage_status == "unknown"
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            record = session.scalar(select(GarminSourceRecord).where(
                GarminSourceRecord.surface_code == "sleep",
            ))
            assert record is not None and record.record_status == "partial"
            checkpoint = session.scalar(select(SyncStreamState).where(
                SyncStreamState.stream_code == "sleep",
            ))
            assert checkpoint is not None and checkpoint.last_success_at is None
            assert _freshness_result(session, "garmin:sleep")["reason_code"] == (
                "acquisition_incomplete"
            )
    finally:
        engine.dispose()


def test_freshness_maps_persisted_not_found_after_success(tmp_path: Path):
    _run_freshness(tmp_path, FakeSyncClient())
    failed_at = FRESHNESS_NOW + timedelta(hours=1)
    report = _run_freshness(
        tmp_path, FakeSyncClient(errors={"get_sleep_data": NotFoundError()}), at=failed_at,
    )
    attempt = next(item for item in report.attempts if item.surface == "sleep")
    assert (attempt.status, attempt.coverage_status) == (
        GarminSyncStatus.UNAVAILABLE, "unavailable",
    )
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            checkpoint = session.scalar(select(SyncStreamState).where(
                SyncStreamState.stream_code == "sleep",
            ))
            assert checkpoint is not None
            assert checkpoint.diagnostic_status == "unsupported_or_not_found"
            assert checkpoint.last_success_at is not None
            assert _freshness_result(session, "garmin:sleep", at=failed_at)["reason_code"] == (
                "required_stream_unavailable"
            )
    finally:
        engine.dispose()


def test_freshness_maps_persisted_missing_method_as_failure(tmp_path: Path):
    client = FakeSyncClient()
    client.get_sleep_data = None  # type: ignore[method-assign]
    report = _run_freshness(tmp_path, client)
    attempt = next(item for item in report.attempts if item.surface == "sleep")
    assert attempt.status is GarminSyncStatus.FAILED
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            checkpoint = session.scalar(select(SyncStreamState).where(
                SyncStreamState.stream_code == "sleep",
            ))
            assert checkpoint is not None
            assert checkpoint.diagnostic_status == "method_unavailable"
            assert _freshness_result(session, "garmin:sleep")["reason_code"] == "refresh_failed"
    finally:
        engine.dispose()


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
            assert source.source_kind == PROVIDER_SOURCE_KIND
            assert source.device_attributed is True
            assert session.get(PhysicalDevice, source.physical_device_id).model == "Vivoactive 5"
            def _values(capability: str) -> set:
                return {
                    item.value_number
                    for item in session.scalars(select(GarminRecordMetric))
                    if item.capability_code == capability and item.state == "value"
                }

            assert _values("heart_rate") >= {0, 72}
            assert _values("stress") >= {12, 25, 40}
            assert _values("body_battery") >= {64, 70}
            assert _values("spo2") >= {96, 98}
            assert _values("respiration") >= {14, 15, 16}
            assert 52 in _values("resting_heart_rate")
            assert 28800 in _values("sleep")
            hr_samples = list(
                session.scalars(
                    select(GarminSourceRecord).where(
                        GarminSourceRecord.source_path.like("payload.heartRateValues[%]")
                    )
                )
            )
            assert len(hr_samples) == 2
    finally:
        engine.dispose()


def test_identical_replay_does_not_duplicate_current_records(tmp_path: Path):
    client = FakeSyncClient()
    first = _run(tmp_path, client)
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            first_current = session.scalar(select(func.count(GarminSourceRecord.id)))
            first_observations = session.scalar(select(func.count(GarminPayloadObservation.id)))
    finally:
        engine.dispose()

    second = _run(tmp_path, FakeSyncClient())
    assert first.status is GarminSyncStatus.SUCCEEDED
    assert second.status is GarminSyncStatus.SUCCEEDED
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            current = session.scalar(select(func.count(GarminSourceRecord.id)))
            observations = session.scalar(select(func.count(GarminPayloadObservation.id)))
            runs = session.scalar(select(func.count(SyncRun.id)))
            assert current == first_current
            assert observations >= first_observations
            assert runs == 2
            keys = list(session.scalars(select(GarminSourceRecord.idempotency_key)))
            assert len(keys) == len(set(keys))
    finally:
        engine.dispose()


def test_overlapping_trailing_window_applies_late_correction(tmp_path: Path):
    original = raw_fixture("sleep")["payload"]
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
    client = FakeSyncClient(
        responses={
            "get_heart_rates": {
                "calendarDate": "2099-01-02",
                "device": {"model": "Vivoactive 5"},
                "heartRateValues": [["2099-01-02T08:00:00Z", 0]],
            },
            "get_stress_data": {
                "calendarDate": "2099-01-02",
                "device": {"model": "Vivoactive 5"},
                "stress": None,
            },
        }
    )
    report = _run(tmp_path, client)
    stress = next(item for item in report.attempts if item.surface == "stress")
    assert stress.status is GarminSyncStatus.PARTIAL
    assert stress.coverage_status == "unknown"
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            metrics = list(session.scalars(select(GarminRecordMetric)))
            by_code: dict[str, list] = {}
            for item in metrics:
                by_code.setdefault(item.metric_code, []).append(item)
            heart = next(item for item in by_code["heart_rate_bpm"] if item.state == "value")
            assert heart.value_number == 0
            stress_metric = next(item for item in by_code["stress_sample"] if item.state == "null")
            assert stress_metric.value_number is None
            missing = [item for item in metrics if item.state == "missing"]
            assert missing
            states = {item.stream_code: item for item in session.scalars(select(SyncStreamState))}
            assert states["heart_rate"].watermark is not None
            assert states["stress"].watermark is None
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


def test_expected_metric_missing_is_unknown_not_present(tmp_path: Path):
    client = FakeSyncClient(
        responses={
            "get_sleep_data": {
                "calendarDate": "2099-01-02",
                "device": {"model": "Vivoactive 5"},
                "dailySleepDTO": {"sleepScores": {"overall": {}}},
            }
        }
    )
    report = _run(tmp_path, client)
    sleep = next(item for item in report.attempts if item.surface == "sleep")
    assert sleep.status is GarminSyncStatus.PARTIAL
    assert sleep.coverage_status == "unknown"
    assert sleep.record_count >= 1
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            coverage = next(
                item
                for item in session.scalars(select(CoverageInterval))
                if item.metric_code == "sleep"
            )
            assert coverage.status == "unknown"
            state = next(
                item
                for item in session.scalars(select(SyncStreamState))
                if item.stream_code == "sleep"
            )
            assert state.watermark is None
            assert state.last_success_at is None
            assert state.last_attempt_at is not None
    finally:
        engine.dispose()


def test_reviewed_empty_sleep_shell_is_confirmed_empty(tmp_path: Path):
    report = _run(
        tmp_path,
        FakeSyncClient(responses={"get_sleep_data": _reviewed_empty_sleep()}),
    )
    sleep = next(item for item in report.attempts if item.surface == "sleep")
    assert sleep.coverage_status == "confirmed_empty"
    assert sleep.status is GarminSyncStatus.EMPTY
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            coverage = next(
                item
                for item in session.scalars(select(CoverageInterval))
                if item.metric_code == "sleep"
            )
            assert coverage.status == "confirmed_empty"
            state = next(
                item
                for item in session.scalars(select(SyncStreamState))
                if item.stream_code == "sleep"
            )
            assert state.last_success_at is not None
            values = [
                item.value_number
                for item in session.scalars(
                    select(GarminRecordMetric).where(
                        GarminRecordMetric.metric_code == "sleep_duration_seconds",
                        GarminRecordMetric.value_number.is_not(None),
                    )
                )
            ]
            assert values == []
    finally:
        engine.dispose()


def test_sleep_zero_duration_is_present_not_empty(tmp_path: Path):
    payload = _reviewed_empty_sleep()
    payload["dailySleepDTO"]["sleepTimeSeconds"] = 0
    report = _run(tmp_path, FakeSyncClient(responses={"get_sleep_data": payload}))
    sleep = next(item for item in report.attempts if item.surface == "sleep")
    assert sleep.coverage_status == "present"
    assert sleep.status is GarminSyncStatus.SUCCEEDED


def test_sleep_zero_nap_without_duration_stays_unknown(tmp_path: Path):
    payload = _reviewed_empty_sleep()
    payload["dailySleepDTO"]["napTimeSeconds"] = 0
    report = _run(tmp_path, FakeSyncClient(responses={"get_sleep_data": payload}))
    sleep = next(item for item in report.attempts if item.surface == "sleep")
    assert sleep.coverage_status == "unknown"
    assert sleep.status is GarminSyncStatus.PARTIAL


def test_sleep_null_duration_with_stages_stays_unknown(tmp_path: Path):
    payload = _reviewed_empty_sleep()
    payload["levels"] = [
        {
            "startTimeGMT": "2099-01-01T21:30:00Z",
            "endTimeGMT": "2099-01-01T23:00:00Z",
            "activityLevel": "deep",
        }
    ]
    report = _run(tmp_path, FakeSyncClient(responses={"get_sleep_data": payload}))
    sleep = next(item for item in report.attempts if item.surface == "sleep")
    assert sleep.coverage_status == "unknown"
    assert sleep.status is GarminSyncStatus.PARTIAL


def test_reviewed_empty_respiration_shell_is_confirmed_empty(tmp_path: Path):
    report = _run(
        tmp_path,
        FakeSyncClient(responses={"get_respiration_data": _reviewed_empty_respiration()}),
    )
    respiration = next(item for item in report.attempts if item.surface == "respiration")
    assert respiration.coverage_status == "confirmed_empty"
    assert respiration.status is GarminSyncStatus.EMPTY
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            coverage = next(
                item
                for item in session.scalars(select(CoverageInterval))
                if item.metric_code == "respiration"
            )
            assert coverage.status == "confirmed_empty"
            values = [
                item.value_number
                for item in session.scalars(
                    select(GarminRecordMetric).where(
                        GarminRecordMetric.metric_code == "respiration_bpm",
                        GarminRecordMetric.value_number.is_not(None),
                    )
                )
            ]
            assert values == []
    finally:
        engine.dispose()


def test_respiration_zero_scalar_is_present_not_empty(tmp_path: Path):
    payload = _reviewed_empty_respiration()
    payload["respiration"] = 0
    report = _run(tmp_path, FakeSyncClient(responses={"get_respiration_data": payload}))
    respiration = next(item for item in report.attempts if item.surface == "respiration")
    assert respiration.coverage_status == "present"
    assert respiration.status is GarminSyncStatus.SUCCEEDED


def test_respiration_missing_avg_stays_unknown(tmp_path: Path):
    report = _run(
        tmp_path,
        FakeSyncClient(
            responses={
                "get_respiration_data": {"calendarDate": "2099-01-02"},
            }
        ),
    )
    respiration = next(item for item in report.attempts if item.surface == "respiration")
    assert respiration.coverage_status == "unknown"
    assert respiration.status is GarminSyncStatus.PARTIAL


def test_respiration_unrecognized_series_stays_unknown(tmp_path: Path):
    payload = _reviewed_empty_respiration()
    payload["respirationValues"] = [{"unexpected": True}]
    report = _run(tmp_path, FakeSyncClient(responses={"get_respiration_data": payload}))
    respiration = next(item for item in report.attempts if item.surface == "respiration")
    assert respiration.coverage_status == "unknown"
    assert respiration.status is GarminSyncStatus.PARTIAL


def test_shape_drift_does_not_advance_successful_checkpoint(tmp_path: Path):
    client = FakeSyncClient(
        responses={
            "get_heart_rates": {
                "calendarDate": "2099-01-02",
                "device": {"model": "Vivoactive 5"},
                "heartRate": {"unexpected": True},
            }
        }
    )
    report = _run(tmp_path, client)
    heart = next(item for item in report.attempts if item.surface == "heart_rate")
    assert heart.status is GarminSyncStatus.PARTIAL
    assert heart.coverage_status == "unknown"
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            state = next(
                item
                for item in session.scalars(select(SyncStreamState))
                if item.stream_code == "heart_rate"
            )
            assert state.watermark is None
            coverage = next(
                item
                for item in session.scalars(select(CoverageInterval))
                if item.metric_code == "heart_rate"
            )
            assert coverage.status == "unknown"
    finally:
        engine.dispose()


def test_id_less_trailing_window_updates_one_current_projection(tmp_path: Path):
    original = raw_fixture("sleep")["payload"]
    assert "id" not in original and "recordId" not in original
    corrected = json.loads(json.dumps(original))
    corrected["dailySleepDTO"]["sleepTimeSeconds"] = 30000
    first = _run(tmp_path, FakeSyncClient(sleep_payloads=[original]))
    second = _run(tmp_path, FakeSyncClient(sleep_payloads=[corrected]))
    assert first.status is GarminSyncStatus.SUCCEEDED
    assert second.status is GarminSyncStatus.SUCCEEDED
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            sleep_records = list(
                session.scalars(
                    select(GarminSourceRecord).where(GarminSourceRecord.stream_code == "sleep")
                )
            )
            assert len(sleep_records) == 1
            duration = session.scalar(
                select(GarminRecordMetric).where(
                    GarminRecordMetric.record_id == sleep_records[0].id,
                    GarminRecordMetric.metric_code == "sleep_duration_seconds",
                )
            )
            assert duration is not None
            assert duration.value_number == 30000
            assert session.scalar(select(func.count(GarminPayloadObservation.id))) >= 2
    finally:
        engine.dispose()


def test_timeseries_sample_correction_reconciles_by_sample_identity(tmp_path: Path):
    first = {
        "calendarDate": "2099-01-02",
        "device": {"model": "Vivoactive 5"},
        "heartRateValues": [
            ["2099-01-02T08:00:00Z", 60],
            ["2099-01-02T08:15:00Z", 72],
        ],
    }
    second = {
        "calendarDate": "2099-01-02",
        "device": {"model": "Vivoactive 5"},
        "heartRateValues": [
            ["2099-01-02T08:00:00Z", 60],
            ["2099-01-02T08:15:00Z", 80],
        ],
    }
    assert _run(tmp_path, FakeSyncClient(responses={"get_heart_rates": first})).status is (
        GarminSyncStatus.SUCCEEDED
    )
    assert _run(tmp_path, FakeSyncClient(responses={"get_heart_rates": second})).status is (
        GarminSyncStatus.SUCCEEDED
    )
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            samples = list(
                session.scalars(
                    select(GarminSourceRecord).where(
                        GarminSourceRecord.stream_code == "intraday",
                        GarminSourceRecord.source_path.like("payload.heartRateValues[%]"),
                    )
                )
            )
            assert len(samples) == 2
            values = sorted(
                session.scalar(
                    select(GarminRecordMetric.value_number).where(
                        GarminRecordMetric.record_id == item.id,
                        GarminRecordMetric.metric_code == "heart_rate_bpm",
                    )
                )
                for item in samples
            )
            assert values == [60, 80]
    finally:
        engine.dispose()


def test_production_path_is_provider_kind_synthetic_fixtures_stay_synthetic(tmp_path: Path):
    report = _run(tmp_path, FakeSyncClient(include_device=False))
    assert report.status in {GarminSyncStatus.SUCCEEDED, GarminSyncStatus.PARTIAL}
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = resolve_runtime_paths(settings)
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            production_sources = list(session.scalars(select(GarminSource)))
            assert production_sources
            assert all(source.source_kind == PROVIDER_SOURCE_KIND for source in production_sources)
            assert all(source.device_attributed is False for source in production_sources)
            fixture = load_synthetic_fixture(FIXTURE_ROOT / "sleep.json")
            store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            result = normalize_garmin_payload(fixture)
            GarminPersistenceRepository(session, payload_store=store).persist_result(
                result,
                payload=fixture,
            )
            session.commit()
            kinds = {source.source_kind for source in session.scalars(select(GarminSource))}
            assert PROVIDER_SOURCE_KIND in kinds
            assert "synthetic" in kinds
            synthetic = next(
                source
                for source in session.scalars(select(GarminSource))
                if source.source_kind == "synthetic"
            )
            assert synthetic.device_attributed is True
    finally:
        engine.dispose()


def _production_body_battery(day: str = "2099-01-02") -> list[dict[str, Any]]:
    return [
        {
            "date": day,
            "charged": 40,
            "drained": 55,
            "startTimestampGMT": f"{day}T00:00:00.000",
            "bodyBatteryValueDescriptorDTOList": [
                {
                    "bodyBatteryValueDescriptorIndex": 0,
                    "bodyBatteryValueDescriptorKey": "millis",
                },
                {
                    "bodyBatteryValueDescriptorIndex": 1,
                    "bodyBatteryValueDescriptorKey": "charged",
                },
                {
                    "bodyBatteryValueDescriptorIndex": 2,
                    "bodyBatteryValueDescriptorKey": "bodyBatteryLevel",
                },
            ],
            "bodyBatteryValuesArray": [
                [1_735_804_800_000, False, 64],
                [1_735_804_860_000, True, 70],
            ],
        }
    ]


def _production_activity(day: str = "2099-01-02") -> list[dict[str, Any]]:
    return [
        {
            "activityId": 1987654321,
            "activityType": {"typeId": 2, "typeKey": "cycling"},
            "startTimeGMT": f"{day}T08:00:00.000",
            "duration": 3600.0,
            "manualActivity": False,
            "manufacturer": "GARMIN",
        }
    ]


def _null_heart_rate(day: str = "2099-01-02") -> dict[str, Any]:
    return {"calendarDate": day, "heartRateValues": None}


def _reviewed_empty_sleep(day: str = "2099-01-02") -> dict[str, Any]:
    return {
        "calendarDate": day,
        "dailySleepDTO": {
            "calendarDate": day,
            "sleepTimeSeconds": None,
            "napTimeSeconds": None,
        },
    }


def _reviewed_empty_respiration(day: str = "2099-01-02") -> dict[str, Any]:
    return {"calendarDate": day, "avgSleepRespirationValue": None}


def _body_battery_descriptors(*keys: str) -> list[dict[str, Any]]:
    return [
        {
            "bodyBatteryValueDescriptorIndex": index,
            "bodyBatteryValueDescriptorKey": key,
        }
        for index, key in enumerate(keys)
    ]


def _all_null_body_battery(day: str = "2099-01-02") -> list[dict[str, Any]]:
    return [
        {
            "calendarDate": day,
            "bodyBatteryValueDescriptorDTOList": _body_battery_descriptors(
                "millis", "bodyBatteryLevel"
            ),
            "bodyBatteryValuesArray": [
                [1_735_804_800_000 + offset, None] for offset in range(0, 6 * 60_000, 60_000)
            ],
        }
    ]


def _unrecognized_body_battery(day: str = "2099-01-02") -> list[dict[str, Any]]:
    return [
        {
            "calendarDate": day,
            "bodyBatteryValueDescriptorDTOList": _body_battery_descriptors("unexpected", "shell"),
            "bodyBatteryValuesArray": [
                [1_735_804_800_000, {"unexpected": True}],
                [1_735_804_860_000, {"unexpected": True}],
            ],
        }
    ]


def test_private_key_guard_allows_provider_fields_and_rejects_secrets() -> None:
    serialize_garmin_payload({"activities": _production_activity()})
    with pytest.raises(ValueError, match="private or credential-shaped"):
        serialize_garmin_payload({"access_token": "never-store-this"})
    with pytest.raises(ValueError, match="private or credential-shaped"):
        serialize_garmin_payload({"mfa": "never-store-this"})
    with pytest.raises(ValueError, match="private or credential-shaped"):
        serialize_garmin_payload({"refreshToken": "never-store-this"})


def test_explicit_empty_heart_rate_series_is_confirmed_empty(tmp_path: Path):
    report = _run(
        tmp_path,
        FakeSyncClient(
            responses={
                "get_heart_rates": {"calendarDate": "2099-01-02", "heartRateValues": []},
            }
        ),
    )
    heart = next(item for item in report.attempts if item.surface == "heart_rate")
    assert heart.coverage_status == "confirmed_empty"
    assert heart.status is GarminSyncStatus.EMPTY
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            coverage = next(
                item
                for item in session.scalars(select(CoverageInterval))
                if item.metric_code == "heart_rate"
            )
            assert coverage.status == "confirmed_empty"
            samples = list(
                session.scalars(
                    select(GarminSourceRecord).where(
                        GarminSourceRecord.source_path.like("payload.heartRateValues[%]")
                    )
                )
            )
            assert samples == []
    finally:
        engine.dispose()


def test_heart_rate_shape_drift_stays_unknown_not_empty(tmp_path: Path):
    report = _run(
        tmp_path,
        FakeSyncClient(
            responses={
                "get_heart_rates": {
                    "calendarDate": "2099-01-02",
                    "heartRateValues": [{"unexpected": True}],
                },
            }
        ),
    )
    heart = next(item for item in report.attempts if item.surface == "heart_rate")
    assert heart.coverage_status == "unknown"
    assert heart.status is GarminSyncStatus.PARTIAL


def test_null_heart_rate_series_is_confirmed_empty(tmp_path: Path):
    report = _run(
        tmp_path,
        FakeSyncClient(responses={"get_heart_rates": _null_heart_rate()}),
    )
    heart = next(item for item in report.attempts if item.surface == "heart_rate")
    assert heart.coverage_status == "confirmed_empty"
    assert heart.status is GarminSyncStatus.EMPTY
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            coverage = next(
                item
                for item in session.scalars(select(CoverageInterval))
                if item.metric_code == "heart_rate"
            )
            assert coverage.status == "confirmed_empty"
            samples = list(
                session.scalars(
                    select(GarminSourceRecord).where(
                        GarminSourceRecord.source_path.like("payload.heartRateValues[%]")
                    )
                )
            )
            assert samples == []
    finally:
        engine.dispose()


def test_null_heart_rate_with_scalar_alias_stays_present(tmp_path: Path):
    payload = _null_heart_rate()
    payload["heartRate"] = 72
    report = _run(tmp_path, FakeSyncClient(responses={"get_heart_rates": payload}))
    heart = next(item for item in report.attempts if item.surface == "heart_rate")
    assert heart.coverage_status == "present"
    assert heart.status is GarminSyncStatus.SUCCEEDED


def test_heart_rate_object_shell_stays_unknown(tmp_path: Path):
    report = _run(
        tmp_path,
        FakeSyncClient(
            responses={
                "get_heart_rates": {
                    "calendarDate": "2099-01-02",
                    "heartRateValues": {"unexpected": True},
                }
            }
        ),
    )
    heart = next(item for item in report.attempts if item.surface == "heart_rate")
    assert heart.coverage_status == "unknown"
    assert heart.status is GarminSyncStatus.PARTIAL


def test_body_battery_descriptor_series_is_present(tmp_path: Path):
    report = _run(
        tmp_path,
        FakeSyncClient(responses={"get_body_battery": _production_body_battery()}),
    )
    battery = next(item for item in report.attempts if item.surface == "body_battery")
    assert battery.coverage_status == "present"
    assert battery.status is GarminSyncStatus.SUCCEEDED
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            values = {
                item.value_number
                for item in session.scalars(
                    select(GarminRecordMetric).where(
                        GarminRecordMetric.metric_code == "body_battery"
                    )
                )
            }
            assert values >= {64, 70}
    finally:
        engine.dispose()


def test_body_battery_exact_duplicate_samples_coalesce_and_replay(tmp_path: Path):
    payload = _production_body_battery()
    samples = payload[0]["bodyBatteryValuesArray"]
    samples[1:1] = [list(samples[0]), list(samples[0])]
    original_payload = json.loads(json.dumps(payload))
    expected_raw = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    first = _run(
        tmp_path,
        FakeSyncClient(responses={"get_body_battery": payload}),
    )
    battery = next(item for item in first.attempts if item.surface == "body_battery")
    assert battery.status is GarminSyncStatus.SUCCEEDED
    assert battery.coverage_status == "present"
    assert payload == original_payload
    assert first.as_dict()["privacy"]["raw_values_emitted"] is False
    assert "bodyBatteryValuesArray" not in json.dumps(first.as_dict())

    paths = resolve_runtime_paths(Settings(data_dir=tmp_path / "runtime"))
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            records = list(
                session.scalars(
                    select(GarminSourceRecord).where(
                        GarminSourceRecord.source_path.like(
                            "payload.bodyBatteryValuesArray[%]"
                        )
                    )
                )
            )
            assert {item.source_path for item in records} == {
                "payload.bodyBatteryValuesArray[0]",
                "payload.bodyBatteryValuesArray[3]",
            }
            artifact = session.scalar(
                select(RawArtifact).where(RawArtifact.source_filename == "body_battery.json")
            )
            assert artifact is not None
            stored_raw = paths.root / "artifacts" / artifact.relative_storage_path
            assert stored_raw.read_bytes() == expected_raw

            unaffected_counts = {
                prefix: session.scalar(
                    select(func.count(GarminSourceRecord.id)).where(
                        GarminSourceRecord.source_path.like(f"payload.{prefix}[%]")
                    )
                )
                for prefix in (
                    "heartRateValues",
                    "stressValuesArray",
                    "spo2Values",
                    "respirationValues",
                )
            }
            assert unaffected_counts == {
                "heartRateValues": 2,
                "stressValuesArray": 2,
                "spo2Values": 2,
                "respirationValues": 2,
            }
    finally:
        engine.dispose()

    second = _run(
        tmp_path,
        FakeSyncClient(responses={"get_body_battery": payload}),
    )
    replay = next(item for item in second.attempts if item.surface == "body_battery")
    assert replay.status is GarminSyncStatus.SUCCEEDED
    assert replay.inserted_count == 0
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            assert (
                session.scalar(
                    select(func.count(GarminSourceRecord.id)).where(
                        GarminSourceRecord.source_path.like(
                            "payload.bodyBatteryValuesArray[%]"
                        )
                    )
                )
                == 2
            )
    finally:
        engine.dispose()


def test_body_battery_duplicate_timestamp_with_different_levels_fails_closed(
    tmp_path: Path,
):
    payload = _production_body_battery()
    first_sample = payload[0]["bodyBatteryValuesArray"][0]
    payload[0]["bodyBatteryValuesArray"].insert(
        1,
        [first_sample[0], first_sample[1], first_sample[2] + 1],
    )

    report = _run(
        tmp_path,
        FakeSyncClient(responses={"get_body_battery": payload}),
    )
    battery = next(item for item in report.attempts if item.surface == "body_battery")
    assert battery.status is GarminSyncStatus.FAILED
    assert battery.coverage_status == "failed"
    assert battery.failure_stage == "persistence"
    assert battery.error is not None
    assert battery.error.error_code == "invalid_input"
    assert report.as_dict()["privacy"]["raw_values_emitted"] is False


def test_body_battery_no_matching_day_is_unattributable(tmp_path: Path):
    report = _run(
        tmp_path,
        FakeSyncClient(
            responses={
                "get_body_battery": [
                    {
                        "date": "2099-01-01",
                        "bodyBatteryValuesArray": [[0, 64], [60, 70]],
                    }
                ]
            }
        ),
    )
    battery = next(item for item in report.attempts if item.surface == "body_battery")
    assert battery.coverage_status == "unknown"
    assert battery.status is GarminSyncStatus.PARTIAL
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            values = [
                item.value_number
                for item in session.scalars(
                    select(GarminRecordMetric).where(
                        GarminRecordMetric.metric_code == "body_battery",
                        GarminRecordMetric.value_number.is_not(None),
                    )
                )
            ]
            assert values == []
    finally:
        engine.dispose()


def test_body_battery_empty_list_is_confirmed_empty(tmp_path: Path):
    report = _run(tmp_path, FakeSyncClient(empty={"get_body_battery"}))
    battery = next(item for item in report.attempts if item.surface == "body_battery")
    assert battery.coverage_status == "confirmed_empty"
    assert battery.status is GarminSyncStatus.EMPTY


def test_body_battery_undated_item_is_unknown(tmp_path: Path):
    report = _run(
        tmp_path,
        FakeSyncClient(
            responses={
                "get_body_battery": [{"bodyBatteryValuesArray": [[0, 64], [60, 70]]}],
            }
        ),
    )
    battery = next(item for item in report.attempts if item.surface == "body_battery")
    assert battery.coverage_status == "unknown"
    assert battery.status is GarminSyncStatus.PARTIAL


def test_body_battery_all_null_levels_are_confirmed_empty(tmp_path: Path):
    report = _run(
        tmp_path,
        FakeSyncClient(responses={"get_body_battery": _all_null_body_battery()}),
    )
    battery = next(item for item in report.attempts if item.surface == "body_battery")
    assert battery.coverage_status == "confirmed_empty"
    assert battery.status is GarminSyncStatus.EMPTY
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            coverage = next(
                item
                for item in session.scalars(select(CoverageInterval))
                if item.metric_code == "body_battery"
            )
            assert coverage.status == "confirmed_empty"
            values = [
                item.value_number
                for item in session.scalars(
                    select(GarminRecordMetric).where(
                        GarminRecordMetric.metric_code == "body_battery",
                        GarminRecordMetric.value_number.is_not(None),
                    )
                )
            ]
            assert values == []
    finally:
        engine.dispose()


def test_body_battery_all_null_levels_do_not_use_another_day(tmp_path: Path):
    other_day = _production_body_battery("2099-01-01")[0]
    matching_day = _all_null_body_battery()[0]
    report = _run(
        tmp_path,
        FakeSyncClient(responses={"get_body_battery": [other_day, matching_day]}),
    )
    battery = next(item for item in report.attempts if item.surface == "body_battery")
    assert battery.coverage_status == "confirmed_empty"
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            values = [
                item.value_number
                for item in session.scalars(
                    select(GarminRecordMetric).where(
                        GarminRecordMetric.metric_code == "body_battery",
                        GarminRecordMetric.value_number.is_not(None),
                    )
                )
            ]
            assert values == []
    finally:
        engine.dispose()


def test_body_battery_mixed_null_and_level_is_present(tmp_path: Path):
    payload = _all_null_body_battery()
    payload[0]["bodyBatteryValuesArray"][-1][1] = 70
    report = _run(tmp_path, FakeSyncClient(responses={"get_body_battery": payload}))
    battery = next(item for item in report.attempts if item.surface == "body_battery")
    assert battery.coverage_status == "present"
    assert battery.status is GarminSyncStatus.SUCCEEDED
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            values = {
                item.value_number
                for item in session.scalars(
                    select(GarminRecordMetric).where(
                        GarminRecordMetric.metric_code == "body_battery"
                    )
                )
            }
            assert 70 in values
    finally:
        engine.dispose()


def test_body_battery_unrecognized_shape_stays_unknown(tmp_path: Path):
    report = _run(
        tmp_path,
        FakeSyncClient(responses={"get_body_battery": _unrecognized_body_battery()}),
    )
    battery = next(item for item in report.attempts if item.surface == "body_battery")
    assert battery.coverage_status == "unknown"
    assert battery.status is GarminSyncStatus.PARTIAL


def test_body_battery_all_null_without_descriptors_stays_unknown(tmp_path: Path):
    report = _run(
        tmp_path,
        FakeSyncClient(
            responses={
                "get_body_battery": [
                    {
                        "calendarDate": "2099-01-02",
                        "bodyBatteryValuesArray": [
                            [1_735_804_800_000, None],
                            [1_735_804_860_000, None],
                        ],
                    }
                ]
            }
        ),
    )
    battery = next(item for item in report.attempts if item.surface == "body_battery")
    assert battery.coverage_status == "unknown"
    assert battery.status is GarminSyncStatus.PARTIAL


def test_numeric_activity_id_and_provider_fields_persist(tmp_path: Path):
    report = _run(
        tmp_path,
        FakeSyncClient(responses={"connectapi": _production_activity()}),
    )
    activities = next(item for item in report.attempts if item.surface == "activities")
    assert activities.coverage_status == "present"
    assert activities.status is GarminSyncStatus.SUCCEEDED
    assert activities.failure_stage is None
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            records = list(
                session.scalars(
                    select(GarminSourceRecord).where(GarminSourceRecord.stream_code == "activity")
                )
            )
            assert any(item.external_record_id == "1987654321" for item in records)
    finally:
        engine.dispose()


def test_activity_failure_stage_is_sanitized_and_privacy_closed(tmp_path: Path):
    poisoned = _production_activity()
    poisoned[0]["access_token"] = "never-store-this"
    report = _run(tmp_path, FakeSyncClient(responses={"connectapi": poisoned}))
    activities = next(item for item in report.attempts if item.surface == "activities")
    dumped = json.dumps(report.as_dict())
    assert activities.status is GarminSyncStatus.FAILED
    assert activities.coverage_status == "failed"
    assert activities.failure_stage == "raw_payload_validation"
    assert activities.error is not None
    assert activities.error.error_class == "input"
    assert activities.error.error_code == "invalid_input"
    assert "never-store-this" not in dumped
    assert "access_token" not in dumped

    fetch_report = _run(
        tmp_path / "fetch",
        FakeSyncClient(errors={"get_heart_rates": ConnectionError("synthetic-provider-outage")}),
    )
    heart = next(item for item in fetch_report.attempts if item.surface == "heart_rate")
    assert heart.failure_stage == "fetch"
    assert "synthetic-provider-outage" not in json.dumps(fetch_report.as_dict())


def test_provider_source_kind_is_rejected_for_unknown_values():
    with pytest.raises(ValueError, match="synthetic or provider"):
        garmin_source_identity(source_kind="owner-live")
