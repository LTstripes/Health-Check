"""Synthetic Garmin collection reconciliation and reprocess tests.

These tests use provider-shaped fixtures only. They do not read owner
credentials, session files, or live Garmin payloads.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from healthcheck import cli
from healthcheck.config import Settings
from healthcheck.db.models import GarminPayloadObservation, GarminSourceRecord, SyncStreamState
from healthcheck.garmin.auth import GarminAuthResult, GarminAuthStatus
from healthcheck.garmin.backfill import run_garmin_historical_backfill
from healthcheck.garmin.persistence import (
    PRE_RECONCILIATION_CONTRACT_VERSION,
    PROJECTION_CURRENT,
    PROJECTION_RETIRED,
    RECONCILIATION_CONTRACT_VERSION,
)
from healthcheck.garmin.reprocess import run_garmin_reprocess
from healthcheck.garmin.sync import (
    GarminIncrementalSync,
    GarminSyncStatus,
    run_garmin_incremental_sync,
)
from test_garmin_incremental_sync import FakeSyncClient, _engine_factory

AS_OF = date(2099, 1, 2)


def _hr(samples: list[Any], *, day: str = "2099-01-02") -> dict[str, Any]:
    return {
        "calendarDate": day,
        "heartRateValues": samples,
        "device": {"model": "Vivoactive 5"},
    }


def _activity(activity_id: Any, *, start: str = "2099-01-02T08:00:00Z") -> dict[str, Any]:
    return {
        "activityId": activity_id,
        "activityType": {"typeKey": "cycling"},
        "startTimeGMT": start,
        "duration": 3600,
        "device": {"model": "Vivoactive 5"},
    }


def _client(
    *, heart_rate: Any | None = None, activities: list[Any] | None = None
) -> FakeSyncClient:
    responses: dict[str, Any] = {}
    if heart_rate is not None:
        responses["get_heart_rates"] = heart_rate
    if activities is not None:
        responses["connectapi"] = activities
    return FakeSyncClient(responses=responses)


def _run(tmp_path: Path, client: FakeSyncClient, **kwargs: Any):
    settings = Settings(data_dir=tmp_path / "runtime")
    clock = kwargs.pop("clock", None)
    if clock is None:
        return run_garmin_incremental_sync(
            settings,
            client=client,
            auth_result=GarminAuthResult(
                status=GarminAuthStatus.AUTHENTICATED, session_reused=True
            ),
            as_of=kwargs.pop("as_of", AS_OF),
            trailing_window_days=kwargs.pop("trailing_window_days", 1),
            **kwargs,
        )
    return GarminIncrementalSync(
        settings,
        client=client,
        auth_result=GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED, session_reused=True),
        clock=clock,
    ).run(
        as_of=kwargs.pop("as_of", AS_OF),
        trailing_window_days=kwargs.pop("trailing_window_days", 1),
    )


def _hr_rows(session):
    return list(
        session.scalars(
            select(GarminSourceRecord).where(
                GarminSourceRecord.source_path.like("payload.heartRateValues%")
            )
        )
    )


def _activity_rows(session):
    return list(
        session.scalars(
            select(GarminSourceRecord).where(GarminSourceRecord.stream_code == "activity")
        )
    )


def test_reorder_and_insert_keep_stable_sample_identity(tmp_path: Path):
    first_samples = [
        ["2099-01-02T08:00:00Z", 60],
        ["2099-01-02T08:15:00Z", 72],
    ]
    first_report = _run(tmp_path, _client(heart_rate=_hr(first_samples)))
    assert first_report.status is GarminSyncStatus.SUCCEEDED
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            first = _hr_rows(session)
            first_keys = {
                row.idempotency_key
                for row in first
                if row.projection_status == PROJECTION_CURRENT
            }
            assert len(first_keys) == 2
    finally:
        engine.dispose()

    reordered = list(reversed(first_samples))
    reordered.insert(0, ["2099-01-02T07:45:00Z", 58])
    assert _run(tmp_path, _client(heart_rate=_hr(reordered))).status is GarminSyncStatus.SUCCEEDED
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            rows = _hr_rows(session)
            current = [row for row in rows if row.projection_status == PROJECTION_CURRENT]
            assert len(current) == 3
            current_keys = {row.idempotency_key for row in current}
            assert first_keys <= current_keys
            assert session.scalar(select(func.count(GarminSourceRecord.id)).where(
                GarminSourceRecord.surface_code == "heart_rate",
                GarminSourceRecord.projection_status == PROJECTION_RETIRED,
            )) == 0
    finally:
        engine.dispose()


def test_authoritative_remove_retires_absent_samples_partial_does_not(tmp_path: Path):
    samples = [
        ["2099-01-02T08:00:00Z", 60],
        ["2099-01-02T08:15:00Z", 72],
    ]
    assert _run(tmp_path, _client(heart_rate=_hr(samples))).status is GarminSyncStatus.SUCCEEDED
    failed = FakeSyncClient(
        responses={"get_heart_rates": _hr(samples[:1])},
        errors={"get_heart_rates": ConnectionError("synthetic-provider-outage")},
    )
    report = _run(tmp_path, failed)
    assert report.status is GarminSyncStatus.PARTIAL
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            current = [
                row
                for row in _hr_rows(session)
                if row.projection_status == PROJECTION_CURRENT
            ]
            assert len(current) == 2
    finally:
        engine.dispose()

    assert _run(tmp_path, _client(heart_rate=_hr(samples[:1]))).status is GarminSyncStatus.SUCCEEDED
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            rows = _hr_rows(session)
            current = [row for row in rows if row.projection_status == PROJECTION_CURRENT]
            retired = [row for row in rows if row.projection_status == PROJECTION_RETIRED]
            assert len(current) == 1
            assert len(retired) == 1
            assert retired[0].retire_reason == "authoritative_collection_replacement"
    finally:
        engine.dispose()


def test_value_and_timestamp_correction_and_stale_replay(tmp_path: Path):
    original = _hr([["2099-01-02T08:00:00Z", 60], ["2099-01-02T08:15:00Z", 72]])
    t1 = datetime(2099, 1, 2, 12, 0, tzinfo=UTC)
    t2 = datetime(2099, 1, 2, 13, 0, tzinfo=UTC)
    assert (
        _run(tmp_path, _client(heart_rate=original), clock=lambda: t1).status
        is GarminSyncStatus.SUCCEEDED
    )
    corrected_value = _hr([["2099-01-02T08:00:00Z", 88], ["2099-01-02T08:15:00Z", 72]])
    assert (
        _run(tmp_path, _client(heart_rate=corrected_value), clock=lambda: t2).status
        is GarminSyncStatus.SUCCEEDED
    )
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            current = [
                row
                for row in _hr_rows(session)
                if row.projection_status == PROJECTION_CURRENT
            ]
            assert len(current) == 2
            values = {
                restore_metric(session, row.id)
                for row in current
            }
            assert 88.0 in values
    finally:
        engine.dispose()

    stale = _run(tmp_path, _client(heart_rate=original), clock=lambda: t1)
    assert stale.status is GarminSyncStatus.SUCCEEDED
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            current = [
                row
                for row in _hr_rows(session)
                if row.projection_status == PROJECTION_CURRENT
            ]
            values = {restore_metric(session, row.id) for row in current}
            assert 88.0 in values
            assert 60.0 not in values
    finally:
        engine.dispose()

    shifted = _hr([["2099-01-02T08:05:00Z", 88], ["2099-01-02T08:15:00Z", 72]])
    assert (
        _run(
            tmp_path,
            _client(heart_rate=shifted),
            clock=lambda: datetime(2099, 1, 2, 14, 0, tzinfo=UTC),
        ).status
        is GarminSyncStatus.SUCCEEDED
    )
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            rows = _hr_rows(session)
            current = [row for row in rows if row.projection_status == PROJECTION_CURRENT]
            retired = [row for row in rows if row.projection_status == PROJECTION_RETIRED]
            assert len(current) == 2
            assert len(retired) == 1
    finally:
        engine.dispose()


def restore_metric(session, record_id: str) -> float | None:
    from healthcheck.db.models import GarminRecordMetric

    metric = session.scalar(
        select(GarminRecordMetric).where(
            GarminRecordMetric.record_id == record_id,
            GarminRecordMetric.metric_code == "heart_rate_bpm",
        )
    )
    return None if metric is None else metric.value_number


def test_activity_collection_retires_only_when_pages_complete(tmp_path: Path):
    first = [_activity(101), _activity(102, start="2099-01-02T10:00:00Z")]
    assert _run(tmp_path, _client(activities=first)).status is GarminSyncStatus.SUCCEEDED

    def _full_pages(_path: str, **kwargs: Any) -> list[dict[str, Any]]:
        start = int((kwargs.get("params") or {}).get("start") or 0)
        return [_activity(3000 + start + index) for index in range(20)]

    truncated = _run(tmp_path, FakeSyncClient(responses={"connectapi": _full_pages}))
    assert truncated.status in {GarminSyncStatus.SUCCEEDED, GarminSyncStatus.PARTIAL}
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            current_ids = {
                row.external_record_id
                for row in _activity_rows(session)
                if row.projection_status == PROJECTION_CURRENT
            }
            assert {"101", "102"} <= current_ids
    finally:
        engine.dispose()

    assert _run(tmp_path, _client(activities=[first[0]])).status is GarminSyncStatus.SUCCEEDED
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            rows = _activity_rows(session)
            current = [row for row in rows if row.projection_status == PROJECTION_CURRENT]
            retired = [row for row in rows if row.projection_status == PROJECTION_RETIRED]
            current_ids = {row.external_record_id for row in current}
            retired_ids = {row.external_record_id for row in retired}
            assert "101" in current_ids
            assert "102" in retired_ids
            assert "101" not in retired_ids
    finally:
        engine.dispose()


def test_reprocess_is_version_aware_and_backfill_skip_stays_default(tmp_path: Path):
    samples = [
        ["2099-01-02T08:00:00Z", 60],
        ["2099-01-02T08:15:00Z", 72],
    ]
    settings = Settings(data_dir=tmp_path / "runtime")
    auth = GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED, session_reused=True)
    first = run_garmin_historical_backfill(
        settings,
        client=_client(heart_rate=_hr(samples)),
        auth_result=auth,
        start=AS_OF,
        end=AS_OF,
        streams=["heart_rate"],
        chunk_days=1,
    )
    assert first.status is GarminSyncStatus.SUCCEEDED
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            for row in _hr_rows(session):
                row.reconciliation_contract_version = PRE_RECONCILIATION_CONTRACT_VERSION
            historical = list(
                session.scalars(
                    select(SyncStreamState).where(
                        SyncStreamState.stream_code.like("garmin_historical:%")
                    )
                )
            )
            incremental = list(
                session.scalars(
                    select(SyncStreamState).where(
                        ~SyncStreamState.stream_code.like("garmin_historical:%")
                    )
                )
            )
            assert historical
            session.commit()
            historical_cursors = [row.cursor for row in historical]
            incremental_ids = [row.id for row in incremental]
    finally:
        engine.dispose()

    skipped = run_garmin_historical_backfill(
        settings,
        client=_client(heart_rate=_hr(samples)),
        auth_result=auth,
        start=AS_OF,
        end=AS_OF,
        streams=["heart_rate"],
        chunk_days=1,
    )
    assert skipped.skipped_complete_count >= 1
    client = _client(heart_rate=_hr(samples))
    refreshed = run_garmin_historical_backfill(
        settings,
        client=client,
        auth_result=auth,
        start=AS_OF,
        end=AS_OF,
        streams=["heart_rate"],
        chunk_days=1,
        reprocess=True,
    )
    assert refreshed.status is GarminSyncStatus.SUCCEEDED
    assert client.calls
    report = run_garmin_reprocess(
        settings,
        start=AS_OF,
        end=AS_OF,
        streams=["heart_rate"],
    )
    assert report.status == "succeeded"
    assert report.as_dict()["reprocess"]["provider_requests"] == 0
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            current = [
                row
                for row in _hr_rows(session)
                if row.projection_status == PROJECTION_CURRENT
            ]
            assert current
            assert all(
                row.reconciliation_contract_version == RECONCILIATION_CONTRACT_VERSION
                for row in current
            )
            historical = list(
                session.scalars(
                    select(SyncStreamState).where(
                        SyncStreamState.stream_code.like("garmin_historical:%")
                    )
                )
            )
            incremental = list(
                session.scalars(
                    select(SyncStreamState).where(
                        ~SyncStreamState.stream_code.like("garmin_historical:%")
                    )
                )
            )
            assert [row.cursor for row in historical] == historical_cursors
            assert [row.id for row in incremental] == incremental_ids
            assert session.scalar(select(func.count(GarminPayloadObservation.id))) >= 1
    finally:
        engine.dispose()

    gaps = run_garmin_reprocess(
        settings,
        start=date(2098, 1, 1),
        end=date(2098, 1, 1),
        streams=["heart_rate"],
        dry_run=True,
    )
    assert any(
        item["reason"] == "outside_trailing_window_no_coverage"
        for item in gaps.as_dict()["history_gaps"]
    )


def test_cli_reprocess_rejects_sync_flags(tmp_path: Path, capsys):
    code = cli.main(
        [
            "garmin-reprocess",
            "--data-dir",
            str(tmp_path / "runtime"),
            "--date",
            "2099-01-02",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    payload = json.loads(captured.out)
    assert payload["error"]["error_code"] == "invalid_reprocess_request"
    args = cli.build_parser().parse_args(
        ["garmin-reprocess", "--start", "2099-01-01", "--end", "2099-01-02", "--dry-run"]
    )
    assert args.command == "garmin-reprocess"
