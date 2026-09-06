"""Synthetic Garmin historical-backfill tests.

These tests use provider-shaped fixtures only.  They do not read owner
credentials, session files, or live Garmin payloads.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from healthcheck import cli
from healthcheck.config import Settings
from healthcheck.db.models import (
    CoverageInterval,
    GarminPayloadObservation,
    GarminRecordMetric,
    GarminSourceRecord,
    SyncRun,
    SyncStreamState,
)
from healthcheck.garmin.auth import GarminAuthResult, GarminAuthStatus
from healthcheck.garmin.backfill import (
    BACKFILL_CONTRACT_VERSION,
    DEFAULT_BACKFILL_CHUNK_DAYS,
    HISTORICAL_CHECKPOINT_NAMESPACE,
    HISTORICAL_RUN_STREAM,
    MAX_BACKFILL_CHUNK_DAYS,
    MAX_BACKFILL_SPAN_DAYS,
    plan_garmin_historical_backfill,
    run_garmin_historical_backfill,
    validate_backfill_chunk_days,
    validate_backfill_range,
)
from healthcheck.garmin.sync import (
    DEFAULT_TRAILING_WINDOW_DAYS,
    INCREMENTAL_RUN_STREAM,
    PRODUCTION_SYNC_SURFACES,
    GarminSyncStatus,
    compute_sync_window,
    run_garmin_incremental_sync,
)
from test_garmin_incremental_sync import (
    AuthenticationError,
    FakeSyncClient,
    _engine_factory,
    raw_fixture,
)
from test_garmin_incremental_sync import (
    _run as _run_incremental,
)

START = date(2098, 12, 20)
END = date(2098, 12, 22)


def _relabel(payload: Any, day: str) -> Any:
    if payload is None:
        return None
    return json.loads(json.dumps(payload).replace("2099-01-02", day))


class DatedFakeSyncClient(FakeSyncClient):
    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        payload = super()._call(method, *args, **kwargs)
        if method == "connectapi":
            params = kwargs.get("params") or {}
            day = params.get("startDate")
            return _relabel(payload, day) if isinstance(day, str) else payload
        if args and isinstance(args[0], str) and len(args[0]) == 10:
            return _relabel(payload, args[0])
        return payload


def _run_backfill(tmp_path: Path, client: FakeSyncClient, **kwargs: Any):
    settings = Settings(data_dir=tmp_path / "runtime")
    return run_garmin_historical_backfill(
        settings,
        client=client,
        auth_result=GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED, session_reused=True),
        start=kwargs.pop("start", START),
        end=kwargs.pop("end", END),
        streams=kwargs.pop("streams", ["sleep"]),
        chunk_days=kwargs.pop("chunk_days", 1),
        dry_run=kwargs.pop("dry_run", False),
        **kwargs,
    )


def test_explicit_range_is_required_and_bounded():
    with pytest.raises(ValueError, match="explicit"):
        validate_backfill_range(None, END)
    with pytest.raises(ValueError, match="precede"):
        validate_backfill_range(END, START)
    with pytest.raises(ValueError, match="at most"):
        validate_backfill_range(date(2000, 1, 1), date(2011, 1, 1))
    start, end = validate_backfill_range("2098-12-31", "2099-01-01")
    assert start == date(2098, 12, 31)
    assert end == date(2099, 1, 1)
    assert MAX_BACKFILL_SPAN_DAYS == 3660
    assert DEFAULT_BACKFILL_CHUNK_DAYS == 7
    assert MAX_BACKFILL_CHUNK_DAYS == 14
    with pytest.raises(ValueError):
        validate_backfill_chunk_days(0)
    with pytest.raises(ValueError):
        validate_backfill_chunk_days(99)


def test_dry_run_reports_chunk_and_request_shape_without_fetch(tmp_path: Path):
    client = DatedFakeSyncClient()
    report = _run_backfill(tmp_path, client, dry_run=True, streams=["sleep", "activities"])
    payload = report.as_dict()
    assert report.status is GarminSyncStatus.NOT_RUN
    assert payload["contract_version"] == BACKFILL_CONTRACT_VERSION
    assert payload["backfill"]["dry_run"] is True
    assert payload["backfill"]["historical_backfill"] is True
    assert payload["backfill"]["gps_or_fit_downloaded"] is False
    assert payload["backfill"]["incremental_trailing_window_unchanged"] is True
    assert payload["backfill"]["streams"] == ["sleep", "activities"]
    assert payload["backfill"]["chunk_count"] == 3
    assert payload["chunks"][0]["request_shape"]["per_day_methods"] == ["get_sleep_data"]
    assert payload["chunks"][0]["request_shape"]["range_methods"] == ["connectapi"]
    assert client.calls == []
    assert payload["privacy"]["raw_values_emitted"] is False
    assert payload["privacy"]["tokens_emitted"] is False
    dumped = json.dumps(payload)
    assert "28800" not in dumped
    assert "token" not in dumped.lower() or payload["privacy"]["tokens_emitted"] is False


def test_multi_chunk_synthetic_backfill_persists_each_day(tmp_path: Path):
    report = _run_backfill(tmp_path, DatedFakeSyncClient())
    assert report.status is GarminSyncStatus.SUCCEEDED
    assert report.request_count == 3
    assert report.remaining_chunk_count == 0
    days = {item.day for item in report.attempts if item.surface == "sleep"}
    assert days == {"2098-12-20", "2098-12-21", "2098-12-22"}
    assert all(item.method != "download_activity" for item in report.attempts)
    assert all(item.method != "get_activities_by_date" for item in report.attempts)

    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            runs = list(session.scalars(select(SyncRun)))
            assert any(run.stream_code == HISTORICAL_RUN_STREAM for run in runs)
            assert all(run.stream_code != INCREMENTAL_RUN_STREAM for run in runs)
            sleep_records = list(
                session.scalars(
                    select(GarminSourceRecord).where(GarminSourceRecord.stream_code == "sleep")
                )
            )
            assert len(sleep_records) == 3
            states = {item.stream_code: item for item in session.scalars(select(SyncStreamState))}
            assert f"{HISTORICAL_CHECKPOINT_NAMESPACE}:sleep" in states
            assert "sleep" not in states
            assert states[HISTORICAL_RUN_STREAM].cursor == "2098-12-22"
            coverage_days = {
                item.interval_start.date().isoformat()
                for item in session.scalars(select(CoverageInterval))
                if item.metric_code == "sleep" and item.status == "present"
            }
            assert coverage_days == {"2098-12-20", "2098-12-21", "2098-12-22"}
    finally:
        engine.dispose()


def test_interruption_resume_skips_successful_chunks(tmp_path: Path):
    interrupted = _run_backfill(tmp_path, DatedFakeSyncClient(), max_provider_requests=1)
    assert interrupted.abort_reason == "request_budget_exhausted"
    assert interrupted.status is GarminSyncStatus.PARTIAL
    assert interrupted.request_count == 1
    assert interrupted.remaining_chunk_count == 2
    assert interrupted.remaining_day_count == 2
    first_success = next(
        item
        for item in interrupted.attempts
        if item.surface == "sleep" and item.status is GarminSyncStatus.SUCCEEDED
    )
    assert first_success.day == "2098-12-20"

    resumed_client = DatedFakeSyncClient()
    resumed = _run_backfill(tmp_path, resumed_client)
    assert resumed.status is GarminSyncStatus.SUCCEEDED
    assert resumed.remaining_chunk_count == 0
    assert resumed.remaining_day_count == 0
    skipped = [item for item in resumed.attempts if item.skipped]
    assert any(item.day == "2098-12-20" and item.skipped for item in skipped)
    fetched_days = [
        args[0]
        for method, args, _kwargs in resumed_client.calls
        if method == "get_sleep_data"
    ]
    assert "2098-12-20" not in fetched_days
    assert "2098-12-21" in fetched_days
    assert "2098-12-22" in fetched_days

    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            sleep_records = list(
                session.scalars(
                    select(GarminSourceRecord).where(GarminSourceRecord.stream_code == "sleep")
                )
            )
            assert len(sleep_records) == 3
            failed_or_missing = [
                item
                for item in session.scalars(select(CoverageInterval))
                if item.metric_code == "sleep" and item.status == "failed"
            ]
            assert not failed_or_missing
    finally:
        engine.dispose()


def test_repeated_low_budget_resumptions_keep_exact_remaining_work(tmp_path: Path):
    for expected_remaining in (2, 1):
        report = _run_backfill(tmp_path, DatedFakeSyncClient(), max_provider_requests=1)
        assert report.status is GarminSyncStatus.PARTIAL
        assert report.abort_reason == "request_budget_exhausted"
        assert report.remaining_chunk_count == expected_remaining
        assert report.remaining_day_count == expected_remaining
        payload = report.as_dict()["backfill"]
        assert payload["remaining_chunk_count"] == expected_remaining
        assert payload["remaining_day_count"] == expected_remaining
        assert payload["remaining_chunk_count"] > 0
        assert payload["remaining_day_count"] > 0

    final = _run_backfill(tmp_path, DatedFakeSyncClient(), max_provider_requests=1)
    assert final.status is GarminSyncStatus.SUCCEEDED
    assert final.abort_reason is None
    assert final.remaining_chunk_count == 0
    assert final.remaining_day_count == 0

    only_chunk = _run_backfill(
        tmp_path,
        DatedFakeSyncClient(),
        start=date(2098, 11, 1),
        end=date(2098, 11, 2),
        chunk_days=7,
        max_provider_requests=1,
    )
    assert only_chunk.status is GarminSyncStatus.PARTIAL
    assert only_chunk.abort_reason == "request_budget_exhausted"
    assert only_chunk.chunks[0].day_count == 2
    assert only_chunk.remaining_chunk_count == 1
    assert only_chunk.remaining_day_count == 2


def test_overlapping_rerun_is_idempotent(tmp_path: Path):
    first = _run_backfill(tmp_path, DatedFakeSyncClient())
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            first_records = session.scalar(select(func.count(GarminSourceRecord.id)))
            first_observations = session.scalar(select(func.count(GarminPayloadObservation.id)))
    finally:
        engine.dispose()

    second_client = DatedFakeSyncClient()
    second = _run_backfill(tmp_path, second_client)
    assert first.status is GarminSyncStatus.SUCCEEDED
    assert second.status is GarminSyncStatus.SUCCEEDED
    assert second.skipped_complete_count == 3
    assert second_client.calls == []
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            assert session.scalar(select(func.count(GarminSourceRecord.id))) == first_records
            observations = session.scalar(select(func.count(GarminPayloadObservation.id)))
            assert observations == first_observations
            keys = list(session.scalars(select(GarminSourceRecord.idempotency_key)))
            assert len(keys) == len(set(keys))
    finally:
        engine.dispose()


def test_empty_partial_and_failed_coverage_are_distinct(tmp_path: Path):
    empty = _run_backfill(
        tmp_path,
        DatedFakeSyncClient(empty={"get_sleep_data"}),
        start=START,
        end=START,
    )
    sleep = next(item for item in empty.attempts if item.surface == "sleep")
    assert sleep.status is GarminSyncStatus.EMPTY
    assert sleep.coverage_status == "confirmed_empty"

    failed = _run_backfill(
        tmp_path,
        DatedFakeSyncClient(errors={"get_sleep_data": ConnectionError("synthetic-outage")}),
        start=date(2098, 12, 21),
        end=date(2098, 12, 21),
    )
    failed_sleep = next(item for item in failed.attempts if item.surface == "sleep")
    assert failed_sleep.status is GarminSyncStatus.FAILED
    assert "synthetic-outage" not in json.dumps(failed.as_dict())

    partial = _run_backfill(
        tmp_path,
        DatedFakeSyncClient(
            responses={
                "get_sleep_data": {
                    "calendarDate": "2098-12-22",
                    "device": {"model": "Vivoactive 5"},
                    "dailySleepDTO": {"sleepScores": {"overall": {}}},
                }
            }
        ),
        start=END,
        end=END,
    )
    partial_sleep = next(item for item in partial.attempts if item.surface == "sleep")
    assert partial_sleep.status is GarminSyncStatus.PARTIAL
    assert partial_sleep.coverage_status == "unknown"

    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            by_day = {
                item.interval_start.date().isoformat(): item.status
                for item in session.scalars(select(CoverageInterval))
                if item.metric_code == "sleep"
            }
            assert by_day["2098-12-20"] == "confirmed_empty"
            assert by_day["2098-12-21"] == "failed"
            assert by_day["2098-12-22"] == "unknown"
            failed_row = next(
                item
                for item in session.scalars(select(CoverageInterval))
                if item.metric_code == "sleep" and item.status == "failed"
            )
            assert failed_row.observed_count is None
            states = {item.stream_code: item for item in session.scalars(select(SyncStreamState))}
            historical_sleep = states[f"{HISTORICAL_CHECKPOINT_NAMESPACE}:sleep"]
            assert historical_sleep.cursor == "2098-12-20"
            assert "sleep" not in states
    finally:
        engine.dispose()

    retry_client = DatedFakeSyncClient()
    retry = _run_backfill(tmp_path, retry_client, start=START, end=END)
    fetched = [
        args[0] for method, args, _kwargs in retry_client.calls if method == "get_sleep_data"
    ]
    assert "2098-12-20" not in fetched
    assert "2098-12-21" in fetched
    assert "2098-12-22" in fetched
    assert retry.status is GarminSyncStatus.SUCCEEDED


def test_boundary_dates_use_the_same_utc_day_bounds_as_incremental(tmp_path: Path):
    report = _run_backfill(
        tmp_path,
        DatedFakeSyncClient(),
        start="2098-12-31",
        end="2099-01-01",
        chunk_days=1,
    )
    assert report.status is GarminSyncStatus.SUCCEEDED
    assert {item.day for item in report.attempts} == {"2098-12-31", "2099-01-01"}
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            intervals = [
                item
                for item in session.scalars(select(CoverageInterval))
                if item.metric_code == "sleep"
            ]
            dates = sorted(item.interval_start.date() for item in intervals)
            assert dates == [date(2098, 12, 31), date(2099, 1, 1)]
            assert all(
                item.interval_start.hour == 0 and item.interval_end.hour == 0
                for item in intervals
            )
    finally:
        engine.dispose()


def test_backfill_does_not_change_incremental_trailing_window(tmp_path: Path):
    incremental = _run_incremental(tmp_path, FakeSyncClient())
    assert incremental.status is GarminSyncStatus.SUCCEEDED
    assert incremental.as_dict()["sync"]["historical_backfill"] is False
    start, end = compute_sync_window(date(2099, 1, 2), DEFAULT_TRAILING_WINDOW_DAYS)
    assert start == date(2098, 12, 27)
    assert end == date(2099, 1, 2)

    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            before = {
                item.stream_code: (
                    item.cursor,
                    item.trailing_window_days,
                    item.watermark,
                    item.last_success_at,
                )
                for item in session.scalars(select(SyncStreamState))
            }
            incremental_sleep = before["sleep"]
    finally:
        engine.dispose()

    backfill = _run_backfill(tmp_path, DatedFakeSyncClient())
    assert backfill.status is GarminSyncStatus.SUCCEEDED

    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            after = {
                item.stream_code: item
                for item in session.scalars(select(SyncStreamState))
            }
            assert after["sleep"].cursor == incremental_sleep[0]
            assert after["sleep"].trailing_window_days == incremental_sleep[1]
            assert after["sleep"].watermark == incremental_sleep[2]
            assert after["sleep"].last_success_at == incremental_sleep[3]
            assert after["sleep"].trailing_window_days == 1
            assert f"{HISTORICAL_CHECKPOINT_NAMESPACE}:sleep" in after
    finally:
        engine.dispose()

    follow_client = FakeSyncClient()
    follow = run_garmin_incremental_sync(
        Settings(data_dir=tmp_path / "runtime"),
        client=follow_client,
        auth_result=GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED, session_reused=True),
        as_of=date(2099, 1, 2),
        trailing_window_days=1,
    )
    assert follow.status is GarminSyncStatus.SUCCEEDED
    assert follow.as_dict()["sync"]["historical_backfill"] is False
    assert follow.window_start == "2099-01-02"
    assert follow.window_end == "2099-01-02"
    summary_dates = [
        args[0]
        for method, args, _kwargs in follow_client.calls
        if method == "get_user_summary"
    ]
    assert summary_dates == ["2099-01-02"]
    assert "2098-12-20" not in summary_dates


def test_backfill_then_incremental_still_reconciles_trailing_window(tmp_path: Path):
    _run_backfill(
        tmp_path,
        DatedFakeSyncClient(),
        start=date(2099, 1, 2),
        end=date(2099, 1, 2),
        streams=["sleep"],
    )
    original = json.loads(json.dumps(raw_fixture("sleep")["payload"]))
    corrected = json.loads(json.dumps(original))
    corrected["dailySleepDTO"]["sleepTimeSeconds"] = 30000
    follow = _run_incremental(tmp_path, FakeSyncClient(sleep_payloads=[corrected]))
    assert follow.status is GarminSyncStatus.SUCCEEDED
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


def test_unknown_stream_and_forbidden_expansion_are_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="accepted production surface"):
        _run_backfill(tmp_path, DatedFakeSyncClient(), streams=["training_readiness"])
    codes = [item.code for item in PRODUCTION_SYNC_SURFACES]
    assert "training_readiness" not in codes
    plan = plan_garmin_historical_backfill(
        start=START,
        end=END,
        streams=["sleep"],
        chunk_days=1,
    )
    dumped = json.dumps(plan.as_dict())
    assert "download_activity" not in dumped
    assert "get_activities_by_date" not in dumped


def test_cli_dry_run_and_invalid_input(tmp_path: Path, capsys):
    code = cli.main(
        [
            "garmin-backfill",
            "--data-dir",
            str(tmp_path / "runtime"),
            "--start",
            "2098-12-20",
            "--end",
            "2098-12-22",
            "--stream",
            "sleep",
            "--chunk-days",
            "1",
            "--dry-run",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["backfill"]["dry_run"] is True
    assert payload["backfill"]["chunk_count"] == 3
    assert payload["auth"]["status"] == "not_attempted"

    invalid = cli.main(
        [
            "garmin-backfill",
            "--data-dir",
            str(tmp_path / "runtime"),
            "--date",
            "2098-12-20",
        ]
    )
    invalid_out = capsys.readouterr()
    assert invalid == 2
    error = json.loads(invalid_out.out)
    assert error["error"]["error_code"] == "invalid_backfill_request"

    window = cli.main(
        [
            "garmin-backfill",
            "--data-dir",
            str(tmp_path / "runtime"),
            "--start",
            "2098-12-20",
            "--end",
            "2098-12-22",
            "--trailing-window-days",
            "7",
        ]
    )
    window_out = capsys.readouterr()
    assert window == 2
    assert json.loads(window_out.out)["error"]["error_code"] == "invalid_backfill_request"


def test_reauth_aborts_without_unbounded_crawl(tmp_path: Path):
    report = _run_backfill(
        tmp_path,
        DatedFakeSyncClient(errors={"get_sleep_data": AuthenticationError()}),
        start=START,
        end=END,
        chunk_days=1,
    )
    assert report.status is GarminSyncStatus.REAUTH_REQUIRED
    executed = [
        item for item in report.attempts if item.status is not GarminSyncStatus.NOT_RUN
    ]
    assert len(executed) == 1
    assert report.request_count == 1
