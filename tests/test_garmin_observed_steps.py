"""Synthetic acceptance cases for saved account-level Steps, without provider calls."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
from healthcheck.db.models import (
    GarminDailyRecord,
    GarminPayloadObservation,
    GarminRawPayload,
    GarminRecordMetric,
    GarminSourceRecord,
    RawArtifact,
)
from healthcheck.garmin.capabilities import GarminStream
from healthcheck.garmin.normalization import (
    GarminNormalizationResult,
    GarminParseStatus,
    GarminSourceIdentity,
    normalize_garmin_payload,
)
from healthcheck.garmin.observed_steps import (
    CONTRACT_VERSION,
    METRIC_CODE,
    SavedDailyStepsRepository,
    SavedStepsEvidenceError,
)
from healthcheck.garmin.persistence import GarminCollectionScope, GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.runtime import prepare_runtime

DAY = date(2099, 1, 2)
RECEIVED = datetime(2099, 1, 3, 12, tzinfo=UTC)
ABSENT = object()


@pytest.fixture
def saved_database(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "synthetic-runtime"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    try:
        with create_session_factory(engine)() as session:
            yield session, ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    finally:
        engine.dispose()


def source(name="synthetic-account", *, device=False):
    return GarminSourceIdentity(
        source_kind="synthetic",
        provider_code="garmin_connect",
        device_attributed=device,
        device_code="synthetic-watch" if device else None,
        device_model="Synthetic watch" if device else None,
        source_instance_id=name,
    )


def save(
    session,
    store,
    payload,
    *,
    identity=None,
    received=RECEIVED,
    filename="daily_summary.json",
    scope=None,
    normalizer=False,
):
    identity = identity or source()
    result = (
        normalize_garmin_payload(payload, stream="daily_health", source_identity=identity)
        if normalizer
        else GarminNormalizationResult(
            status=GarminParseStatus.OK,
            stream=GarminStream.DAILY_HEALTH,
            source=identity,
        )
    )
    outcome = GarminPersistenceRepository(session, payload_store=store).persist_result(
        result,
        payload=payload,
        source_filename=filename,
        received_at=received,
        collection_scope=scope,
        source_window_start_utc=datetime(2099, 1, 1, tzinfo=UTC),
        source_window_end_utc=datetime(2099, 1, 2, tzinfo=UTC),
    )
    session.flush()
    return outcome


def project(session, store, source_id, **kwargs):
    return SavedDailyStepsRepository(session, payload_store=store).project_day(
        source_id, DAY, **kwargs
    )


@pytest.mark.parametrize(
    "count,state,value",
    [
        (0, "value", 0),
        (4321, "value", 4321),
        (2**53 + 1, "value", 2**53 + 1),
        (None, "null", None),
        (ABSENT, "missing", None),
        (True, "invalid", None),
        (False, "invalid", None),
        (-1, "invalid", None),
        (1.5, "invalid", None),
        (3.0, "invalid", None),
        ("123", "invalid", None),
        ([], "invalid", None),
        ({}, "invalid", None),
    ],
)
def test_presence_exact_integer_and_immutable_provenance(saved_database, count, state, value):
    session, store = saved_database
    payload = {"calendarDate": DAY.isoformat()}
    if count is not ABSENT:
        payload["totalSteps"] = count
    saved = save(session, store, payload, identity=source(device=True))
    before = (saved.raw_payload.content_hash, saved.observation.normalization_contract_version)
    result = project(session, store, saved.source.id)
    session.commit()
    assert (result.state, result.value) == (state, value)
    assert (result.unit, result.attribution) == ("steps", "account")
    assert (result.coverage, result.device, result.timezone, result.finality) == ("unknown",) * 4
    (evidence,) = result.evidence
    assert evidence.observation_ids == (saved.observation.id,)
    assert evidence.raw_payload_id == saved.raw_payload.id
    assert evidence.raw_artifact_id == saved.raw_payload.raw_artifact_id
    record = session.get(GarminSourceRecord, evidence.record_id)
    assert record.raw_payload_id == saved.raw_payload.id
    assert record.ingest_event_id == saved.observation.ingest_event_id
    assert record.normalization_contract_version == CONTRACT_VERSION
    assert record.source_local_date == DAY
    assert record.temporal_precision == "date"
    assert record.source_timestamp_utc is None
    assert record.source_timezone is None
    assert record.source_utc_offset_minutes is None
    assert session.get(GarminDailyRecord, record.id).calendar_date == DAY
    metric = session.scalar(
        select(GarminRecordMetric).where(
            GarminRecordMetric.record_id == record.id, GarminRecordMetric.metric_code == METRIC_CODE
        )
    )
    assert (metric.state, metric.value_number, metric.value_text) == (
        state,
        None,
        str(value) if state == "value" else None,
    )
    assert metric.unit == "steps"
    assert metric.source_device_attributed is False
    assert metric.capability_status == "unverified"
    if state == "missing":
        assert metric.reason == "field_absent_in_payload"
    assert before == (
        saved.raw_payload.content_hash,
        saved.observation.normalization_contract_version,
    )


def test_identical_acquisitions_share_one_record_and_retain_all_observations(saved_database):
    session, store = saved_database
    payload = {"calendarDate": DAY.isoformat(), "totalSteps": 0}
    first = save(session, store, payload)
    initial = project(session, store, first.source.id)
    later = save(session, store, payload, received=RECEIVED + timedelta(hours=1))
    repeated = project(session, store, first.source.id)
    assert repeated.value == 0
    assert len(repeated.evidence) == 1
    assert repeated.evidence[0].record_id == initial.evidence[0].record_id
    assert set(repeated.evidence[0].observation_ids) == {first.observation.id, later.observation.id}
    assert session.get(GarminSourceRecord, repeated.evidence[0].record_id).ingest_event_id == (
        first.observation.ingest_event_id
    )


@pytest.mark.parametrize("counts", [(0, 99), (99, 0)])
@pytest.mark.parametrize("late_first", [True, False])
def test_divergent_same_day_is_ambiguous_in_any_acquisition_or_projection_order(
    saved_database, counts, late_first
):
    session, store = saved_database
    first = save(
        session,
        store,
        {"calendarDate": DAY.isoformat(), "totalSteps": counts[0]},
        received=RECEIVED + timedelta(hours=int(late_first)),
    )
    project(session, store, first.source.id)
    save(
        session,
        store,
        {"calendarDate": DAY.isoformat(), "totalSteps": counts[1]},
        received=RECEIVED + timedelta(hours=int(not late_first)),
    )
    result = project(session, store, first.source.id)
    assert (result.state, result.value, result.reason) == (
        "ambiguous",
        None,
        "divergent_saved_observations",
    )
    assert {item.value for item in result.evidence} == {0, 99}
    assert len({item.record_id for item in result.evidence}) == 2


def test_same_count_different_artifacts_not_added_and_nonvalues_stay_visible(saved_database):
    session, store = saved_database
    first = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 17, "extra": 1})
    for payload in [
        {"calendarDate": DAY.isoformat(), "totalSteps": 17, "extra": 2},
        {"calendarDate": DAY.isoformat(), "totalSteps": None},
        {"calendarDate": DAY.isoformat()},
        {"calendarDate": DAY.isoformat(), "totalSteps": True},
    ]:
        save(session, store, payload)
    result = project(session, store, first.source.id)
    assert (result.state, result.value) == ("value", 17)
    assert len(result.evidence) == 5
    assert {item.state.value for item in result.evidence} == {"value", "missing", "null", "invalid"}


def test_sources_days_and_surfaces_are_never_fused_or_inferred(saved_database):
    session, store = saved_database
    first = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 7})
    other = save(
        session,
        store,
        {"calendarDate": DAY.isoformat(), "totalSteps": 11},
        identity=source("second-synthetic-account"),
    )
    save(session, store, {"calendarDate": "2099-01-01", "totalSteps": 100})
    save(
        session,
        store,
        {"calendarDate": DAY.isoformat(), "totalSteps": 999},
        filename="activity.json",
    )
    assert project(session, store, first.source.id).value == 7
    assert project(session, store, other.source.id).value == 11
    absent = save(
        session,
        store,
        {"calendarDate": DAY.isoformat(), "distance": 1000, "activities": [{"steps": 999}]},
        identity=source("third"),
    )
    assert project(session, store, absent.source.id).state == "missing"
    empty = save(
        session, store, {"calendarDate": "2099-01-01", "totalSteps": 0}, identity=source("fourth")
    )
    result = project(session, store, empty.source.id)
    assert (result.state, result.value, result.evidence) == ("unavailable", None, ())
    assert result.coverage == "unknown"


@pytest.mark.parametrize(
    "day",
    [None, "20990102", "2099-1-02", "2099-02-30", "2099-01-02T00:00:00Z", " 2099-01-02", 20990102],
)
def test_unsupported_calendar_date_does_not_use_acquisition_window(saved_database, day):
    session, store = saved_database
    saved = save(session, store, {"calendarDate": day, "totalSteps": 7})
    result = project(session, store, saved.source.id)
    assert (result.state, result.value) == ("unavailable", None)
    assert result.excluded_artifacts[0].reason == "unsupported_calendar_date"
    assert result.excluded_artifacts[0].observation_ids == (saved.observation.id,)
    assert not result.evidence


@pytest.mark.parametrize(
    "payload,reason",
    [
        (b'{"calendarDate":"2099-01-02","totalSteps":1,"totalSteps":2}', "invalid_json"),
        (b'{"calendarDate":"2099-01-02","totalSteps":NaN}', "invalid_json"),
        (b"{bad json", "invalid_json"),
        (b'[{"calendarDate":"2099-01-02","totalSteps":7}]', "unsupported_payload_shape"),
        (b'{"payload":{"calendarDate":"2099-01-02","totalSteps":7}}', "unsupported_calendar_date"),
    ],
)
def test_unaccepted_shape_and_json_are_explicit_exclusions(saved_database, payload, reason):
    session, store = saved_database
    saved = save(session, store, payload)
    result = project(session, store, saved.source.id)
    assert (result.state, result.value) == ("unavailable", None)
    assert result.excluded_artifacts[0].reason == reason


def test_bounds_and_integrity_fail_closed_before_projection_writes(saved_database):
    session, store = saved_database
    first = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 7})
    save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 8})
    with pytest.raises(SavedStepsEvidenceError, match="artifact bound"):
        project(session, store, first.source.id, max_artifacts=1)
    with pytest.raises(SavedStepsEvidenceError, match="byte bound"):
        project(session, store, first.source.id, max_artifact_bytes=1)
    artifact = session.get(RawArtifact, first.raw_payload.raw_artifact_id)
    store._resolve(artifact.relative_storage_path).write_bytes(b"synthetic corruption")
    with pytest.raises(SavedStepsEvidenceError, match="integrity mismatch"):
        project(session, store, first.source.id)
    assert session.scalar(select(func.count(GarminRecordMetric.id))) == 0


def test_regular_daily_summary_replacement_cannot_retire_steps_evidence(saved_database):
    session, store = saved_database
    scope = GarminCollectionScope("daily_summary", "daily_health", "day_singleton", DAY, DAY, True)
    first = save(
        session,
        store,
        {"calendarDate": DAY.isoformat(), "totalSteps": 7},
        scope=scope,
        normalizer=True,
    )
    initial = project(session, store, first.source.id)
    save(
        session,
        store,
        {"calendarDate": DAY.isoformat(), "totalSteps": 9},
        received=RECEIVED + timedelta(hours=1),
        scope=scope,
        normalizer=True,
    )
    result = project(session, store, first.source.id)
    assert result.state == "ambiguous"
    assert {item.value for item in result.evidence} == {7, 9}
    assert (
        session.get(GarminSourceRecord, initial.evidence[0].record_id).projection_status
        == "current"
    )
    assert session.scalar(select(func.count(GarminPayloadObservation.id))) == 2
    assert session.scalar(select(func.count(GarminRawPayload.id))) == 2


def test_committed_saved_bytes_project_without_implicitly_committing_the_caller(saved_database):
    session, store = saved_database
    saved = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 0})
    session.commit()
    result = project(session, store, saved.source.id)
    record_id = result.evidence[0].record_id
    assert session.get(GarminSourceRecord, record_id) is not None
    session.rollback()
    assert session.get(GarminSourceRecord, record_id) is None
    assert session.scalar(select(func.count(GarminRawPayload.id))) == 1
    assert session.scalar(select(func.count(GarminPayloadObservation.id))) == 1


def test_mixed_nonvalues_are_unavailable_without_inventing_collection_status(saved_database):
    session, store = saved_database
    saved = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": None})
    save(session, store, {"calendarDate": DAY.isoformat()})
    result = project(session, store, saved.source.id)
    assert (result.state, result.value, result.coverage) == ("unavailable", None, "unknown")
    assert {item.state.value for item in result.evidence} == {"missing", "null"}


def test_untrusted_timezone_and_timestamp_do_not_reinterpret_returned_day(saved_database):
    session, store = saved_database
    saved = save(
        session,
        store,
        {
            "calendarDate": DAY.isoformat(),
            "totalSteps": 0,
            "timestamp": "2099-01-01T23:30:00-05:00",
            "timeZone": "America/New_York",
        },
    )
    result = project(session, store, saved.source.id)
    assert (result.calendar_date, result.value, result.timezone) == (DAY, 0, "unknown")
    record = session.get(GarminSourceRecord, result.evidence[0].record_id)
    assert record.source_timestamp_utc is None
    assert record.source_timezone is None


def test_observation_artifact_mismatch_fails_closed(saved_database):
    session, store = saved_database
    saved = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 7})
    other = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 9})
    # Insert a malformed synthetic provenance link; the append-only trigger
    # correctly forbids mutating an acquisition that is already saved.
    bad_observation = GarminPayloadObservation(
        **{
            column.name: getattr(saved.observation, column.name)
            for column in GarminPayloadObservation.__table__.columns
            if column.name not in {"id", "raw_artifact_id", "observation_key"}
        },
        raw_artifact_id=other.observation.raw_artifact_id,
        observation_key="f" * 64,
    )
    session.add(bad_observation)
    session.flush()
    with pytest.raises(SavedStepsEvidenceError, match="provenance mismatch"):
        project(session, store, saved.source.id)
    assert session.scalar(select(func.count(GarminRecordMetric.id))) == 0


def test_unreadable_saved_bytes_fail_closed(saved_database):
    session, store = saved_database
    saved = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 7})
    artifact = session.get(RawArtifact, saved.raw_payload.raw_artifact_id)
    store._resolve(artifact.relative_storage_path).unlink()
    with pytest.raises(SavedStepsEvidenceError, match="unreadable"):
        project(session, store, saved.source.id)
    assert session.scalar(select(func.count(GarminRecordMetric.id))) == 0
