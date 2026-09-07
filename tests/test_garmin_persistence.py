"""Offline R02 Garmin persistence, migration, and replay contract tests."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import func, inspect, select

from healthcheck.config import Settings
from healthcheck.db.engine import (
    _alembic_config,
    create_session_factory,
    create_sqlite_engine,
    database_readiness,
    migrate_database,
)
from healthcheck.db.models import (
    CoverageInterval,
    GarminActivityRecord,
    GarminDailyRecord,
    GarminFitRecord,
    GarminIntradayRecord,
    GarminPayloadObservation,
    GarminRawPayload,
    GarminRecordMetric,
    GarminSleepRecord,
    GarminSleepStageInterval,
    GarminSource,
    GarminSourceRecord,
    IngestBatch,
    IngestEvent,
    PhysicalDevice,
    RawArtifact,
    SyncStreamState,
)
from healthcheck.db.repositories import repositories_for, restore_stored_utc
from healthcheck.garmin.contracts import GarminCapabilityFixture, load_synthetic_fixture
from healthcheck.garmin.normalization import (
    GarminSourceIdentity,
    normalize_garmin_payload,
)
from healthcheck.garmin.persistence import (
    GARMIN_COVERAGE_RULE_VERSION,
    GarminPersistenceRepository,
)
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore, serialize_garmin_payload
from healthcheck.runtime import prepare_runtime

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "garmin"


@pytest.fixture
def persistence_database(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            yield paths, session, ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    finally:
        engine.dispose()


def fixture(name: str):
    return load_synthetic_fixture(FIXTURE_ROOT / f"{name}.json")


def raw_fixture(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / f"{name}.json").read_text(encoding="utf-8"))


def persist(
    session,
    store,
    name: str,
    *,
    received_at: datetime | None = None,
    payload=None,
):
    value = fixture(name) if payload is None else payload
    result = normalize_garmin_payload(value)
    raw = (FIXTURE_ROOT / f"{name}.json").read_bytes() if payload is None else value
    source_contract_version = (
        value.contract_version if isinstance(value, GarminCapabilityFixture) else None
    )
    repository = GarminPersistenceRepository(session, payload_store=store)
    return repository.persist_result(
        result,
        payload=raw,
        received_at=received_at,
        source_contract_version=source_contract_version,
    )


def test_sleep_persistence_keeps_raw_typed_temporal_and_provenance(persistence_database):
    _paths, session, store = persistence_database
    received_at = datetime(2099, 1, 3, 12, 0, tzinfo=UTC)
    outcome = persist(session, store, "sleep", received_at=received_at)
    session.commit()

    assert outcome.inserted_count == 1
    assert outcome.updated_count == 0
    assert outcome.replayed is False
    source = session.get(GarminSource, outcome.source.id)
    assert source is not None
    assert source.provider_code == "garmin_connect"
    assert source.device_attributed is True
    assert source.device_code == "garmin_vivoactive_5"
    assert session.get(PhysicalDevice, source.physical_device_id).model == "Vivoactive 5"

    raw_payload = session.get(GarminRawPayload, outcome.raw_payload.id)
    assert raw_payload is not None
    assert raw_payload.stream_code == "sleep"
    assert raw_payload.parse_status == "ok"
    assert raw_payload.record_count == 1
    assert raw_payload.source_contract_version == "r02-garmin-capability-fixture-v1"
    artifact = session.get(RawArtifact, raw_payload.raw_artifact_id)
    assert artifact is not None
    assert store.read(artifact.relative_storage_path) == (FIXTURE_ROOT / "sleep.json").read_bytes()

    (record,) = outcome.records
    typed = session.get(GarminSleepRecord, record.id)
    assert typed is not None
    assert typed.wake_date == date(2099, 1, 2)
    metrics = {
        item.metric_code: item
        for item in session.scalars(
            select(GarminRecordMetric).where(GarminRecordMetric.record_id == record.id)
        )
    }
    assert metrics["sleep_duration_seconds"].value_number == 28800
    assert metrics["sleep_score"].value_number == 82
    assert metrics["nap_duration_seconds"].value_number == 900
    assert metrics["sleep_stages"].collection_json is not None
    stages = list(
        session.scalars(
            select(GarminSleepStageInterval).where(
                GarminSleepStageInterval.sleep_record_id == record.id
            )
        )
    )
    assert len(stages) == 2
    assert restore_stored_utc(stages[0].start_at_utc) == datetime(2099, 1, 1, 21, 30, tzinfo=UTC)
    assert stages[0].activity_level == "deep"

    event = session.get(IngestEvent, outcome.ingest_event_id)
    assert event is not None
    assert event.status == "committed"
    batch = session.get(IngestBatch, outcome.ingest_batch_id)
    assert batch is not None
    assert batch.batch_kind == "provider_sync"
    assert batch.status == "committed"
    assert batch.committed_count == 1


def test_each_garmin_stream_has_a_separate_typed_projection(persistence_database):
    _paths, session, store = persistence_database
    outcomes = [
        persist(session, store, name)
        for name in ("daily_health", "sleep", "activity", "intraday", "original_fit")
    ]
    session.commit()

    assert session.scalar(select(func.count(GarminSourceRecord.id))) == 5
    assert session.scalar(select(func.count(GarminDailyRecord.record_id))) == 1
    assert session.scalar(select(func.count(GarminSleepRecord.record_id))) == 1
    assert session.scalar(select(func.count(GarminActivityRecord.record_id))) == 1
    assert session.scalar(select(func.count(GarminIntradayRecord.record_id))) == 1
    assert session.scalar(select(func.count(GarminFitRecord.record_id))) == 1
    intraday = next(item for item in outcomes if item.raw_payload.stream_code == "intraday")
    zero = session.scalar(
        select(GarminRecordMetric).where(
            GarminRecordMetric.record_id == intraday.records[0].id,
            GarminRecordMetric.metric_code == "heart_rate_bpm",
        )
    )
    stress = session.scalar(
        select(GarminRecordMetric).where(
            GarminRecordMetric.record_id == intraday.records[0].id,
            GarminRecordMetric.metric_code == "stress_sample",
        )
    )
    assert zero is not None and zero.state == "value" and zero.value_number == 0
    assert stress is not None and stress.state == "null"


def test_exact_replay_is_idempotent_but_refreshed_payload_updates_current_projection(
    persistence_database,
):
    _paths, session, store = persistence_database
    first_payload = raw_fixture("activity")
    first = persist(session, store, "activity", payload=first_payload)
    session.commit()

    replay = persist(session, store, "activity", payload=first_payload)
    assert replay.replayed is True
    assert replay.inserted_count == 0
    assert replay.updated_count == 0
    session.commit()
    assert session.scalar(select(func.count(GarminRawPayload.id))) == 1
    assert session.scalar(select(func.count(GarminPayloadObservation.id))) == 1
    assert session.scalar(select(func.count(GarminSourceRecord.id))) == 1

    refreshed_payload = raw_fixture("activity")
    refreshed_payload["fixture_id"] = "synthetic-vivoactive-5-cycling-refreshed"
    refreshed_payload["payload"]["activities"][0]["duration"] = 9999
    refreshed = persist(session, store, "activity", payload=refreshed_payload)
    assert refreshed.replayed is False
    assert refreshed.inserted_count == 0
    assert refreshed.updated_count == 1
    session.commit()

    assert session.scalar(select(func.count(GarminRawPayload.id))) == 2
    assert session.scalar(select(func.count(GarminPayloadObservation.id))) == 2
    assert session.scalar(select(func.count(RawArtifact.id))) == 2
    record = session.get(GarminSourceRecord, first.records[0].id)
    assert record is not None
    assert record.raw_payload_id == refreshed.raw_payload.id
    duration = session.scalar(
        select(GarminRecordMetric).where(
            GarminRecordMetric.record_id == record.id,
            GarminRecordMetric.metric_code == "duration_seconds",
        )
    )
    assert duration is not None and duration.value_number == 9999
    assert store.read(
        session.get(RawArtifact, first.raw_payload.raw_artifact_id).relative_storage_path
    ) == serialize_garmin_payload(first_payload)


@pytest.mark.parametrize(
    ("offset_text", "expected_offset_minutes"),
    (("+23:59", 1439), ("-23:59", -1439)),
)
def test_accepted_boundary_utc_offset_round_trips_through_persistence(
    persistence_database, offset_text, expected_offset_minutes
):
    _paths, session, store = persistence_database
    source = GarminSourceIdentity(
        source_kind="synthetic",
        provider_code="garmin_connect",
        device_attributed=True,
        device_code="garmin_vivoactive_5",
        device_model="Vivoactive 5",
        source_instance_id=f"synthetic-offset-{expected_offset_minutes}",
    )
    payload = {
        "calendarDate": "2099-01-02",
        "startTimeLocal": f"2099-01-02T08:00:00{offset_text}",
        "restingHeartRate": 52,
    }
    result = normalize_garmin_payload(payload, stream="daily_health", source_identity=source)
    assert result.records[0].temporal.source_utc_offset_minutes == expected_offset_minutes

    outcome = GarminPersistenceRepository(session, payload_store=store).persist_result(
        result,
        payload=payload,
        source_identity=source,
        stream_code="daily_health",
        create_ingest_event=False,
    )
    session.commit()
    session.expire_all()

    record = session.get(GarminSourceRecord, outcome.records[0].id)
    assert record is not None
    assert record.source_utc_offset_minutes == expected_offset_minutes


def test_identical_bytes_keep_each_window_sync_and_normalization_observation(
    persistence_database,
):
    _paths, session, store = persistence_database
    fixture_value = fixture("activity")
    payload = (FIXTURE_ROOT / "activity.json").read_bytes()
    result_v1 = normalize_garmin_payload(fixture_value)
    repository = GarminPersistenceRepository(session, payload_store=store)
    source = repository.sources.get_or_create(result_v1.source)
    provenance = repositories_for(session)
    first_run = provenance.sync.create_run(
        provider_id=source.provider_id,
        acquisition_source_id=source.acquisition_source_id,
        stream_code="activity",
        requested_start=datetime(2099, 1, 1, tzinfo=UTC),
        requested_end=datetime(2099, 1, 3, tzinfo=UTC),
    )
    second_run = provenance.sync.create_run(
        provider_id=source.provider_id,
        acquisition_source_id=source.acquisition_source_id,
        stream_code="activity",
        requested_start=datetime(2099, 1, 2, tzinfo=UTC),
        requested_end=datetime(2099, 1, 4, tzinfo=UTC),
    )

    first = repository.persist_result(
        result_v1,
        payload=payload,
        source_filename="activity-window-1.json",
        received_at=datetime(2099, 1, 3, 12, tzinfo=UTC),
        source_window_start_utc=datetime(2099, 1, 1, tzinfo=UTC),
        source_window_end_utc=datetime(2099, 1, 3, tzinfo=UTC),
        sync_run_id=first_run.id,
    )
    session.commit()

    result_v2 = replace(result_v1, contract_version="r02-garmin-normalization-contract-v2")
    second = repository.persist_result(
        result_v2,
        payload=payload,
        source_filename="activity-window-2.json",
        received_at=datetime(2099, 1, 4, 12, tzinfo=UTC),
        source_window_start_utc=datetime(2099, 1, 2, tzinfo=UTC),
        source_window_end_utc=datetime(2099, 1, 4, tzinfo=UTC),
        sync_run_id=second_run.id,
    )
    session.commit()

    replay = repository.persist_result(
        result_v1,
        payload=payload,
        source_filename="activity-window-1.json",
        received_at=datetime(2099, 1, 5, 12, tzinfo=UTC),
        source_window_start_utc=datetime(2099, 1, 1, tzinfo=UTC),
        source_window_end_utc=datetime(2099, 1, 3, tzinfo=UTC),
        sync_run_id=first_run.id,
    )
    assert replay.replayed is True
    assert replay.inserted_count == 0
    assert replay.updated_count == 0
    session.commit()
    session.expire_all()

    observations = list(
        session.scalars(
            select(GarminPayloadObservation).order_by(
                GarminPayloadObservation.received_at, GarminPayloadObservation.id
            )
        )
    )
    assert len(observations) == 2
    assert {item.garmin_raw_payload_id for item in observations} == {first.raw_payload.id}
    assert {item.raw_artifact_id for item in observations} == {first.raw_payload.raw_artifact_id}
    assert [item.sync_run_id for item in observations] == [first_run.id, second_run.id]
    assert [item.source_filename for item in observations] == [
        "activity-window-1.json",
        "activity-window-2.json",
    ]
    assert [item.normalization_contract_version for item in observations] == [
        result_v1.contract_version,
        result_v2.contract_version,
    ]
    assert [
        (
            restore_stored_utc(item.source_window_start_utc),
            restore_stored_utc(item.source_window_end_utc),
        )
        for item in observations
    ] == [
        (datetime(2099, 1, 1, tzinfo=UTC), datetime(2099, 1, 3, tzinfo=UTC)),
        (datetime(2099, 1, 2, tzinfo=UTC), datetime(2099, 1, 4, tzinfo=UTC)),
    ]
    assert observations[0].ingest_event_id == first.ingest_event_id
    assert observations[1].ingest_event_id == second.ingest_event_id
    assert observations[0].ingest_event_id != observations[1].ingest_event_id
    assert session.scalar(select(func.count(GarminRawPayload.id))) == 1
    assert session.scalar(select(func.count(RawArtifact.id))) == 1

    current = session.get(GarminSourceRecord, first.records[0].id)
    assert current is not None
    assert current.ingest_event_id == second.ingest_event_id
    assert current.normalization_contract_version == result_v2.contract_version


@pytest.mark.parametrize(
    ("label", "value", "expected_state", "expected_number"),
    (
        ("zero", 0, "value", 0),
        ("missing", None, "missing", None),
        ("null", None, "null", None),
    ),
)
def test_missing_null_and_zero_are_persisted_as_distinct_states(
    persistence_database, label, value, expected_state, expected_number
):
    _paths, session, store = persistence_database
    payload = raw_fixture("daily_health")["payload"]
    if label == "missing":
        del payload["allMetrics"]["metricsMap"]["WELLNESS_RESTING_HEART_RATE"]
    else:
        payload["allMetrics"]["metricsMap"]["WELLNESS_RESTING_HEART_RATE"][0]["value"] = value
    source = GarminSourceIdentity(
        source_kind="synthetic",
        provider_code="garmin_connect",
        device_attributed=True,
        device_code="garmin_vivoactive_5",
        device_model="Vivoactive 5",
        source_instance_id=f"synthetic-{label}-source",
    )
    result = normalize_garmin_payload(payload, stream="daily_health", source_identity=source)
    repository = GarminPersistenceRepository(session, payload_store=store)
    outcome = repository.persist_result(
        result,
        payload=payload,
        source_identity=source,
        stream_code="daily_health",
        create_ingest_event=False,
    )
    session.commit()

    metric = session.scalar(
        select(GarminRecordMetric).where(
            GarminRecordMetric.record_id == outcome.records[0].id,
            GarminRecordMetric.metric_code == "resting_heart_rate_bpm",
        )
    )
    assert metric is not None
    assert metric.state == expected_state
    assert metric.value_number == expected_number


def test_local_only_temporal_evidence_survives_sqlite_roundtrip(persistence_database):
    _paths, session, store = persistence_database
    source = GarminSourceIdentity(
        source_kind="synthetic",
        provider_code="garmin_connect",
        device_attributed=True,
        device_code="garmin_vivoactive_5",
        device_model="Vivoactive 5",
        source_instance_id="synthetic-local-time-source",
    )
    result = normalize_garmin_payload(
        {
            "calendarDate": "2099-01-02",
            "startTimeLocal": "2099-01-02T08:15:00",
            "restingHeartRate": 52,
        },
        stream="daily_health",
        source_identity=source,
    )
    outcome = GarminPersistenceRepository(session, payload_store=store).persist_result(
        result, payload=result.as_dict(), source_identity=source, stream_code="daily_health"
    )
    session.commit()
    session.expire_all()

    record = session.get(GarminSourceRecord, outcome.records[0].id)
    assert record is not None
    assert record.temporal_precision == "local"
    assert record.source_timestamp_utc is None
    assert record.local_wall_time == "2099-01-02T08:15:00"
    assert record.source_local_timestamp == "2099-01-02T08:15:00"
    assert record.source_timezone is None


def test_coverage_and_freshness_reuse_r01_tables_without_zeroing_unknown_counts(
    persistence_database,
):
    _paths, session, store = persistence_database
    outcome = persist(session, store, "daily_health")
    repository = GarminPersistenceRepository(session, payload_store=store)
    attempted_at = datetime(2099, 1, 4, 12, tzinfo=UTC)
    interval = repository.coverage.record(
        outcome.source,
        stream_code="daily_health",
        metric_code="resting_heart_rate_bpm",
        interval_start=datetime(2099, 1, 2, tzinfo=UTC),
        interval_end=datetime(2099, 1, 3, tzinfo=UTC),
        resolution="day",
        status="confirmed_empty",
        observed_count=None,
        expected_count=None,
        attempted_at=attempted_at,
        watermark=datetime(2099, 1, 2, tzinfo=UTC),
        trailing_window_days=3,
    )
    session.commit()
    state = repository.coverage.get_state(outcome.source, "daily_health")

    assert interval.status == "confirmed_empty"
    assert interval.observed_count is None
    assert interval.expected_count is None
    assert state is not None
    assert state.trailing_window_days == 3
    assert restore_stored_utc(state.last_attempt_at) == attempted_at
    assert restore_stored_utc(state.last_success_at) == attempted_at
    assert state.watermark is not None
    assert session.scalar(select(func.count(CoverageInterval.id))) == 1
    assert session.scalar(select(func.count(SyncStreamState.id))) == 1
    assert GARMIN_COVERAGE_RULE_VERSION == "garmin-coverage-v1"

    repository.coverage.record(
        outcome.source,
        stream_code="daily_health",
        metric_code="resting_heart_rate_bpm",
        interval_start=datetime(2099, 1, 3, tzinfo=UTC),
        interval_end=datetime(2099, 1, 4, tzinfo=UTC),
        resolution="day",
        status="failed",
        diagnostic_reason="synthetic timeout",
        attempted_at=datetime(2099, 1, 3, 12, tzinfo=UTC),
        watermark=datetime(2099, 1, 1, tzinfo=UTC),
    )
    session.commit()
    state = repository.coverage.get_state(outcome.source, "daily_health")
    assert state is not None
    assert restore_stored_utc(state.last_attempt_at) == attempted_at
    assert restore_stored_utc(state.last_success_at) == attempted_at
    assert restore_stored_utc(state.watermark) == datetime(2099, 1, 2, tzinfo=UTC)
    assert session.scalar(select(func.count(CoverageInterval.id))) == 2


def test_invalid_result_retains_raw_failure_but_creates_no_typed_record(persistence_database):
    _paths, session, store = persistence_database
    source = GarminSourceIdentity(
        source_kind="synthetic",
        provider_code="garmin_connect",
        device_attributed=False,
        source_instance_id="synthetic-invalid-source",
    )
    result = normalize_garmin_payload({"source_kind": "owner-live", "payload": {}})
    repository = GarminPersistenceRepository(session, payload_store=store)
    outcome = repository.persist_result(
        result,
        payload={"synthetic": "invalid-envelope"},
        source_identity=source,
        stream_code="daily_health",
    )
    session.commit()

    assert outcome.records == ()
    assert outcome.raw_payload.parse_status == "invalid"
    assert session.scalar(select(func.count(GarminSourceRecord.id))) == 0
    batch = session.get(IngestBatch, outcome.ingest_batch_id)
    event = session.get(IngestEvent, outcome.ingest_event_id)
    assert batch is not None and batch.status == "failed"
    assert event is not None and event.status == "failed"


def test_garmin_raw_and_source_rows_are_append_only(persistence_database):
    _paths, session, store = persistence_database
    outcome = persist(session, store, "daily_health")
    session.commit()
    raw_payload = session.get(GarminRawPayload, outcome.raw_payload.id)
    observation = session.get(GarminPayloadObservation, outcome.observation.id)
    source = session.get(GarminSource, outcome.source.id)
    assert raw_payload is not None and observation is not None and source is not None

    with pytest.raises(Exception):
        with session.begin_nested():
            raw_payload.parse_status = "invalid"
            session.flush()
    with pytest.raises(Exception):
        with session.begin_nested():
            session.delete(source)
            session.flush()
    with pytest.raises(Exception):
        with session.begin_nested():
            observation.source_filename = "changed.json"
            session.flush()
    with pytest.raises(Exception):
        with session.begin_nested():
            session.delete(observation)
            session.flush()
    session.rollback()

    session.refresh(raw_payload)
    session.refresh(observation)
    session.refresh(source)
    assert raw_payload.parse_status == "ok"
    assert observation.source_filename is None
    assert source.provider_code == "garmin_connect"


def test_garmin_migration_downgrade_and_upgrade_are_linear(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    config = _alembic_config(paths)
    command.upgrade(config, "head")
    assert (
        database_readiness(paths)["migration_revision"]
        == "0008_garmin_observation_reconciliation_version"
    )

    engine = create_sqlite_engine(paths)
    try:
        assert "garmin_sources" in inspect(engine).get_table_names()
        assert "garmin_payload_observations" in inspect(engine).get_table_names()
        command.downgrade(config, "0004_naive_minute_wall_clock")
        assert database_readiness(paths)["migration_revision"] == "0004_naive_minute_wall_clock"
        assert "garmin_sources" not in inspect(engine).get_table_names()
        assert "garmin_payload_observations" not in inspect(engine).get_table_names()
        command.upgrade(config, "head")
        assert (
            database_readiness(paths)["migration_revision"]
            == "0008_garmin_observation_reconciliation_version"
        )
        assert "garmin_sleep_stage_intervals" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_observation_migration_backfills_legacy_raw_payload_provenance(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    config = _alembic_config(paths)
    command.upgrade(config, "0005_garmin_persistence_contract")
    engine = create_sqlite_engine(paths)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            source_identity = GarminSourceIdentity(
                source_kind="synthetic",
                provider_code="garmin_connect",
                device_attributed=False,
                source_instance_id="synthetic-legacy-observation-source",
            )
            repository = GarminPersistenceRepository(session)
            source = repository.sources.get_or_create(source_identity)
            artifact = repositories_for(session).raw_artifacts.get_or_create(
                content_hash="a" * 64,
                kind="garmin_payload",
                media_type="application/json",
                byte_size=16,
                relative_storage_path="garmin/aa/" + "a" * 64 + ".json",
                source_filename="legacy-window.json",
            )
            raw_payload = GarminRawPayload(
                garmin_source_id=source.id,
                raw_artifact_id=artifact.id,
                stream_code="daily_health",
                content_hash="a" * 64,
                payload_format="json",
                normalization_contract_version="r02-garmin-normalization-contract-v1",
                parse_status="ok",
                record_count=0,
                source_window_start_utc=datetime(2099, 1, 1, tzinfo=UTC),
                source_window_end_utc=datetime(2099, 1, 2, tzinfo=UTC),
                received_at=datetime(2099, 1, 3, tzinfo=UTC),
            )
            session.add(raw_payload)
            session.commit()

        command.upgrade(config, "head")
        with factory() as session:
            observation = session.scalar(select(GarminPayloadObservation))
            assert observation is not None
            assert observation.garmin_raw_payload_id == raw_payload.id
            assert observation.raw_artifact_id == artifact.id
            assert observation.source_filename == "legacy-window.json"
            assert observation.sync_run_id is None
            assert observation.normalization_contract_version == (
                "r02-garmin-normalization-contract-v1"
            )
            assert observation.observation_key.startswith("garmin-observation-v1:")
    finally:
        engine.dispose()
