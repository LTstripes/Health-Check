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
from healthcheck.db.models import (
    GarminPayloadObservation,
    GarminRecordMetric,
    GarminSource,
    GarminSourceRecord,
    SyncStreamState,
)
from healthcheck.garmin.auth import GarminAuthResult, GarminAuthStatus
from healthcheck.garmin.backfill import run_garmin_historical_backfill
from healthcheck.garmin.normalization import GarminSourceIdentity, normalize_garmin_payload
from healthcheck.garmin.persistence import (
    PRE_RECONCILIATION_CONTRACT_VERSION,
    PROJECTION_CURRENT,
    PROJECTION_RETIRED,
    RECONCILIATION_CONTRACT_VERSION,
    GarminPersistenceRepository,
)
from healthcheck.garmin.reprocess import _reconstruct_fetch_complete, run_garmin_reprocess
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.garmin.sync import (
    ACTIVITY_PAGE_SIZE,
    PRODUCTION_SYNC_SURFACES,
    GarminIncrementalSync,
    GarminSyncStatus,
    _collection_scope,
    _day_bounds,
    _normalize_provider_payload,
    _prepare_normalization_result,
    run_garmin_incremental_sync,
)
from healthcheck.runtime import resolve_runtime_paths
from test_garmin_incremental_sync import FakeSyncClient, _engine_factory

AS_OF = date(2099, 1, 2)


def _hr(samples: list[Any], *, day: str = "2099-01-02") -> dict[str, Any]:
    return {
        "calendarDate": day,
        "heartRateValues": samples,
        "device": {"model": "Vivoactive 5"},
    }


def _activity(
    activity_id: Any,
    *,
    start: str = "2099-01-02T08:00:00Z",
    duration: int = 3600,
) -> dict[str, Any]:
    return {
        "activityId": activity_id,
        "activityType": {"typeKey": "cycling"},
        "startTimeGMT": start,
        "duration": duration,
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


def test_offline_reprocess_applies_newest_observation_not_oldest(tmp_path: Path):
    t1 = datetime(2099, 1, 2, 12, 0, tzinfo=UTC)
    t2 = datetime(2099, 1, 2, 13, 0, tzinfo=UTC)
    original = _hr([["2099-01-02T08:00:00Z", 60], ["2099-01-02T08:15:00Z", 72]])
    corrected = _hr([["2099-01-02T08:00:00Z", 88], ["2099-01-02T08:15:00Z", 72]])
    assert (
        _run(tmp_path, _client(heart_rate=original), clock=lambda: t1).status
        is GarminSyncStatus.SUCCEEDED
    )
    assert (
        _run(tmp_path, _client(heart_rate=corrected), clock=lambda: t2).status
        is GarminSyncStatus.SUCCEEDED
    )
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            for row in _hr_rows(session):
                row.reconciliation_contract_version = PRE_RECONCILIATION_CONTRACT_VERSION
            before = session.scalar(select(func.count(GarminPayloadObservation.id)))
            session.commit()
    finally:
        engine.dispose()

    settings = Settings(data_dir=tmp_path / "runtime")
    first = run_garmin_reprocess(settings, start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert first.status == "succeeded"
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            values = {
                restore_metric(session, row.id)
                for row in _hr_rows(session)
                if row.projection_status == PROJECTION_CURRENT
            }
            assert 88.0 in values
            assert 60.0 not in values
            after_first = session.scalar(select(func.count(GarminPayloadObservation.id)))
    finally:
        engine.dispose()

    second = run_garmin_reprocess(settings, start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert second.status == "succeeded"
    assert second.processed_count == 0
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            values = {
                restore_metric(session, row.id)
                for row in _hr_rows(session)
                if row.projection_status == PROJECTION_CURRENT
            }
            assert 88.0 in values
            assert 60.0 not in values
            after_second = session.scalar(select(func.count(GarminPayloadObservation.id)))
            assert after_second == after_first
            assert after_first >= before
    finally:
        engine.dispose()


def test_offline_reprocess_does_not_promote_truncated_activities(tmp_path: Path):
    first = [_activity(101), _activity(102, start="2099-01-02T10:00:00Z")]
    assert _run(tmp_path, _client(activities=first)).status is GarminSyncStatus.SUCCEEDED
    truncated = [_activity(101)] + [
        _activity(4000 + index, start="2099-01-02T09:00:00Z")
        for index in range(ACTIVITY_PAGE_SIZE - 1)
    ]
    assert len(truncated) == ACTIVITY_PAGE_SIZE
    _persist_activity_payload(tmp_path, truncated, complete=False)
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            for row in _activity_rows(session):
                row.reconciliation_contract_version = PRE_RECONCILIATION_CONTRACT_VERSION
            session.commit()
            current_ids = {
                row.external_record_id
                for row in _activity_rows(session)
                if row.projection_status == PROJECTION_CURRENT
            }
            assert "102" in current_ids
    finally:
        engine.dispose()

    report = run_garmin_reprocess(
        Settings(data_dir=tmp_path / "runtime"),
        start=AS_OF,
        end=AS_OF,
        streams=["activities"],
    )
    assert report.status == "succeeded"
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            current_ids = {
                row.external_record_id
                for row in _activity_rows(session)
                if row.projection_status == PROJECTION_CURRENT
            }
            retired_ids = {
                row.external_record_id
                for row in _activity_rows(session)
                if row.projection_status == PROJECTION_RETIRED
            }
            assert "102" in current_ids
            assert "102" not in retired_ids
    finally:
        engine.dispose()


def test_offline_reprocess_skips_already_current_empty_collection(tmp_path: Path):
    assert _run(tmp_path, _client(activities=[])).status in {
        GarminSyncStatus.SUCCEEDED,
        GarminSyncStatus.EMPTY,
        GarminSyncStatus.PARTIAL,
    }
    settings = Settings(data_dir=tmp_path / "runtime")
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            before = session.scalar(
                select(func.count(GarminPayloadObservation.id)).where(
                    GarminPayloadObservation.source_filename == "activities.json"
                )
            )
            assert before >= 1
            assert not [
                row
                for row in _activity_rows(session)
                if row.projection_status == PROJECTION_CURRENT
            ]
    finally:
        engine.dispose()

    first = run_garmin_reprocess(settings, start=AS_OF, end=AS_OF, streams=["activities"])
    second = run_garmin_reprocess(settings, start=AS_OF, end=AS_OF, streams=["activities"])
    assert first.processed_count == 0
    assert second.processed_count == 0
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            after = session.scalar(
                select(func.count(GarminPayloadObservation.id)).where(
                    GarminPayloadObservation.source_filename == "activities.json"
                )
            )
            assert after == before
    finally:
        engine.dispose()


def test_reprocess_reconstructs_activity_completeness_fail_closed() -> None:
    activities = next(item for item in PRODUCTION_SYNC_SURFACES if item.code == "activities")
    heart_rate = next(item for item in PRODUCTION_SYNC_SURFACES if item.code == "heart_rate")
    assert _reconstruct_fetch_complete(heart_rate, {}) is True
    assert _reconstruct_fetch_complete(activities, []) is True
    assert _reconstruct_fetch_complete(activities, [_activity(1)]) is True
    assert (
        _reconstruct_fetch_complete(
            activities, [_activity(index) for index in range(ACTIVITY_PAGE_SIZE)]
        )
        is False
    )
    assert _reconstruct_fetch_complete(activities, {"not": "a-list"}) is False


def _persist_activity_payload(
    tmp_path: Path,
    activities: list[Any],
    *,
    complete: bool,
    received_at: datetime | None = None,
    window_start: date | None = None,
    window_end: date | None = None,
) -> None:
    paths = resolve_runtime_paths(Settings(data_dir=tmp_path / "runtime"))
    engine, factory = _engine_factory(tmp_path)
    surface = next(item for item in PRODUCTION_SYNC_SURFACES if item.code == "activities")
    scope_start = window_start or AS_OF
    scope_end = window_end or AS_OF
    try:
        with factory() as session:
            source_id = session.scalar(
                select(GarminSourceRecord.garmin_source_id).where(
                    GarminSourceRecord.stream_code == "activity"
                )
            )
            source_row = session.get(GarminSource, source_id)
            assert source_row is not None
            identity = GarminSourceIdentity(
                source_kind=source_row.source_kind,
                provider_code=source_row.provider_code,
                device_attributed=source_row.device_attributed,
                device_code=source_row.device_code,
                device_model=source_row.device_model,
                source_instance_id=source_row.source_instance_id,
            )
            normalized = _normalize_provider_payload(surface, activities, day=None)
            result = normalize_garmin_payload(
                normalized, stream=surface.stream, source_identity=identity
            )
            result = _prepare_normalization_result(surface, activities, result, day=None)
            bounds_start, _ = _day_bounds(scope_start)
            _, bounds_end = _day_bounds(scope_end)
            GarminPersistenceRepository(
                session,
                payload_store=ContentAddressedGarminPayloadStore(paths.root / "artifacts"),
            ).persist_result(
                result,
                payload={"activities": activities},
                stream_code=surface.stream,
                source_identity=identity,
                received_at=received_at or datetime(2099, 1, 2, 15, 0, tzinfo=UTC),
                source_window_start_utc=bounds_start,
                source_window_end_utc=bounds_end,
                source_filename="activities.json",
                collection_scope=_collection_scope(
                    surface,
                    day=None,
                    window_start=scope_start,
                    window_end=scope_end,
                    fetch_complete=complete,
                    coverage_status="present",
                ),
            )
            session.commit()
    finally:
        engine.dispose()


def test_stale_older_collection_cannot_add_unseen_extra_member(tmp_path: Path):
    """Sync/backfill whole-collection stale must not insert an unseen extra identity."""

    day = date(2099, 1, 2)
    assert _run(
        tmp_path,
        _client(activities=[_activity(101, start="2099-01-02T08:00:00Z", duration=3600)]),
        clock=lambda: datetime(2099, 1, 2, 18, 0, tzinfo=UTC),
    ).status is GarminSyncStatus.SUCCEEDED

    _persist_activity_payload(
        tmp_path,
        [
            _activity(101, start="2099-01-02T08:00:00Z", duration=1800),
            _activity(102, start="2099-01-02T12:00:00Z", duration=2400),
        ],
        complete=True,
        received_at=datetime(2099, 1, 2, 10, 0, tzinfo=UTC),
        window_start=day,
        window_end=day,
    )

    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            current = {
                row.external_record_id: row
                for row in _activity_rows(session)
                if row.projection_status == PROJECTION_CURRENT
            }
            assert "101" in current
            assert "102" not in current
            assert _activity_duration(session, current["101"].id) == 3600.0
            assert all(row.external_record_id != "102" for row in _activity_rows(session))
    finally:
        engine.dispose()


def test_offline_reprocess_overlapping_activity_windows_keep_newer_correction(
    tmp_path: Path,
):
    day_one = date(2099, 1, 1)
    day_two = date(2099, 1, 2)
    assert _run(
        tmp_path,
        _client(activities=[_activity(101, start="2099-01-02T08:00:00Z")]),
        clock=lambda: datetime(2099, 1, 1, 10, 0, tzinfo=UTC),
    ).status is GarminSyncStatus.SUCCEEDED
    _persist_activity_payload(
        tmp_path,
        [
            _activity(101, start="2099-01-01T08:00:00Z", duration=3600),
            _activity(102, start="2099-01-02T10:00:00Z", duration=3600),
        ],
        complete=True,
        received_at=datetime(2099, 1, 1, 12, 0, tzinfo=UTC),
        window_start=day_one,
        window_end=date(2099, 1, 3),
    )
    _persist_activity_payload(
        tmp_path,
        [_activity(102, start="2099-01-02T10:00:00Z", duration=9999)],
        complete=True,
        received_at=datetime(2099, 1, 2, 16, 0, tzinfo=UTC),
        window_start=day_two,
        window_end=day_two,
    )
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            for row in _activity_rows(session):
                row.reconciliation_contract_version = PRE_RECONCILIATION_CONTRACT_VERSION
            session.commit()
    finally:
        engine.dispose()

    report = run_garmin_reprocess(
        Settings(data_dir=tmp_path / "runtime"),
        start=day_one,
        end=day_two,
        streams=["activities"],
    )
    assert report.status == "succeeded"
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            current = {
                row.external_record_id: row
                for row in _activity_rows(session)
                if row.projection_status == PROJECTION_CURRENT
            }
            assert "102" in current
            assert _activity_duration(session, current["102"].id) == 9999.0
    finally:
        engine.dispose()


def test_offline_reprocess_bounded_resume_converges_overlapping_activity_windows(
    tmp_path: Path,
):
    day_one = date(2099, 1, 1)
    day_two = date(2099, 1, 2)
    day_three = date(2099, 1, 3)
    assert _run(
        tmp_path,
        _client(activities=[_activity(101, start="2099-01-02T08:00:00Z")]),
        clock=lambda: datetime(2099, 1, 1, 10, 0, tzinfo=UTC),
    ).status is GarminSyncStatus.SUCCEEDED
    _persist_activity_payload(
        tmp_path,
        [
            _activity(101, start="2099-01-01T08:00:00Z", duration=3600),
            _activity(102, start="2099-01-02T10:00:00Z", duration=3600),
            _activity(103, start="2099-01-03T08:00:00Z", duration=1200),
        ],
        complete=True,
        received_at=datetime(2099, 1, 1, 12, 0, tzinfo=UTC),
        window_start=day_one,
        window_end=day_three,
    )
    _persist_activity_payload(
        tmp_path,
        [_activity(102, start="2099-01-02T10:00:00Z", duration=9999)],
        complete=True,
        received_at=datetime(2099, 1, 2, 16, 0, tzinfo=UTC),
        window_start=day_two,
        window_end=day_two,
    )
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            for row in _activity_rows(session):
                row.reconciliation_contract_version = PRE_RECONCILIATION_CONTRACT_VERSION
            outside = next(
                row for row in _activity_rows(session) if row.external_record_id == "103"
            )
            outside_snapshot = (
                outside.id,
                outside.projection_status,
                PRE_RECONCILIATION_CONTRACT_VERSION,
                _activity_duration(session, outside.id),
            )
            session.commit()
    finally:
        engine.dispose()

    settings = Settings(data_dir=tmp_path / "runtime")
    first = run_garmin_reprocess(
        settings,
        start=day_one,
        end=day_two,
        streams=["activities"],
        max_observations=1,
    )
    assert first.status == "partial"
    assert first.remaining_observation_count >= 1

    last = first
    for _ in range(4):
        last = run_garmin_reprocess(
            settings,
            start=day_one,
            end=day_two,
            streams=["activities"],
            max_observations=1,
        )
        if last.remaining_observation_count == 0:
            break
    assert last.remaining_observation_count == 0

    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            current = {
                row.external_record_id: row
                for row in _activity_rows(session)
                if row.projection_status == PROJECTION_CURRENT
            }
            assert current["101"].reconciliation_contract_version == (
                RECONCILIATION_CONTRACT_VERSION
            )
            assert current["102"].reconciliation_contract_version == (
                RECONCILIATION_CONTRACT_VERSION
            )
            assert _activity_duration(session, current["102"].id) == 9999.0
            outside = session.get(GarminSourceRecord, outside_snapshot[0])
            assert outside is not None
            assert outside.projection_status == outside_snapshot[1]
            assert outside.reconciliation_contract_version == outside_snapshot[2]
            assert _activity_duration(session, outside.id) == outside_snapshot[3]
    finally:
        engine.dispose()

    again = run_garmin_reprocess(
        settings,
        start=day_one,
        end=day_two,
        streams=["activities"],
        max_observations=1,
    )
    assert again.processed_count == 0
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            current = {
                row.external_record_id: row
                for row in _activity_rows(session)
                if row.projection_status == PROJECTION_CURRENT
            }
            assert _activity_duration(session, current["102"].id) == 9999.0
            assert current["101"].reconciliation_contract_version == (
                RECONCILIATION_CONTRACT_VERSION
            )
            outside = session.get(GarminSourceRecord, outside_snapshot[0])
            assert outside is not None
            assert outside.reconciliation_contract_version == PRE_RECONCILIATION_CONTRACT_VERSION
            assert _activity_duration(session, outside.id) == 1200.0
    finally:
        engine.dispose()


def test_offline_reprocess_does_not_mutate_outside_requested_activity_range(
    tmp_path: Path,
):
    day_one = date(2099, 1, 1)
    day_two = date(2099, 1, 2)
    bootstrap = _run(
        tmp_path,
        _client(activities=[_activity(101, start="2099-01-01T08:00:00Z")]),
        as_of=day_one,
        clock=lambda: datetime(2099, 1, 1, 10, 0, tzinfo=UTC),
    )
    assert bootstrap.status in {GarminSyncStatus.SUCCEEDED, GarminSyncStatus.PARTIAL}
    _persist_activity_payload(
        tmp_path,
        [
            _activity(101, start="2099-01-01T08:00:00Z", duration=3600),
            _activity(102, start="2099-01-02T10:00:00Z", duration=4800),
        ],
        complete=True,
        received_at=datetime(2099, 1, 2, 12, 0, tzinfo=UTC),
        window_start=day_one,
        window_end=day_two,
    )
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            outside = next(
                row
                for row in _activity_rows(session)
                if row.external_record_id == "101"
            )
            snapshot = (
                outside.id,
                outside.projection_status,
                outside.reconciliation_contract_version,
                outside.updated_at,
                _activity_duration(session, outside.id),
            )
            for row in _activity_rows(session):
                row.reconciliation_contract_version = PRE_RECONCILIATION_CONTRACT_VERSION
            session.commit()
            snapshot = (
                snapshot[0],
                snapshot[1],
                PRE_RECONCILIATION_CONTRACT_VERSION,
                session.get(GarminSourceRecord, snapshot[0]).updated_at,
                snapshot[4],
            )
    finally:
        engine.dispose()

    report = run_garmin_reprocess(
        Settings(data_dir=tmp_path / "runtime"),
        start=day_two,
        end=day_two,
        streams=["activities"],
    )
    assert report.status == "succeeded"
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            outside = session.get(GarminSourceRecord, snapshot[0])
            assert outside is not None
            assert outside.projection_status == snapshot[1]
            assert outside.reconciliation_contract_version == snapshot[2]
            assert outside.updated_at == snapshot[3]
            assert _activity_duration(session, outside.id) == snapshot[4]
            inside = next(
                row
                for row in _activity_rows(session)
                if row.external_record_id == "102"
                and row.projection_status == PROJECTION_CURRENT
            )
            assert inside.reconciliation_contract_version == RECONCILIATION_CONTRACT_VERSION
    finally:
        engine.dispose()


def _activity_duration(session, record_id: str) -> float | None:
    metric = session.scalar(
        select(GarminRecordMetric).where(
            GarminRecordMetric.record_id == record_id,
            GarminRecordMetric.metric_code == "duration_seconds",
        )
    )
    return None if metric is None else metric.value_number


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
