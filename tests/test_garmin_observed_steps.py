"""Synthetic acceptance cases for saved account-level Steps, without provider calls."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import event, func, insert, select
from sqlalchemy.exc import InvalidRequestError

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
from healthcheck.garmin.observed_steps_read import read_observed_steps_window
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


def materialize(session, store, day=DAY, count=17, identity=None, extra=None):
    payload = {"calendarDate": day.isoformat()}
    if count is not ABSENT:
        payload["totalSteps"] = count
    if extra is not None:
        payload["extra"] = extra
    saved = save(session, store, payload, identity=identity)
    result = SavedDailyStepsRepository(session, payload_store=store).project_day(
        saved.source.id, day
    )
    return saved, result


def read_steps(session, source_id, start=DAY, end=DAY):
    return read_observed_steps_window(session, source_id=source_id, start_date=start, end_date=end)


def test_window_daily_states_exact_counts_and_provenance(saved_database):
    session, store = saved_database
    counts = [0, 2**53 + 1, ABSENT, None, True, 17, None]
    for index, count in enumerate(counts):
        saved, _ = materialize(session, store, DAY + timedelta(days=index), count)
    materialize(session, store, DAY + timedelta(days=5), 19)
    materialize(session, store, DAY + timedelta(days=6), ABSENT)
    result = read_steps(session, saved.source.id, end=DAY + timedelta(days=7))
    assert [cell.state for cell in result.cells] == [
        "value",
        "value",
        "missing",
        "null",
        "invalid",
        "ambiguous",
        "unavailable",
        "projection_unavailable",
    ]
    assert [cell.value for cell in result.cells] == [
        0,
        2**53 + 1,
        None,
        None,
        None,
        None,
        None,
        None,
    ]
    assert result.cells[-1].reason == "not_evidenced"
    assert result.search_complete
    for index, cell in enumerate(result.cells):
        assert cell.calendar_date == DAY + timedelta(days=index)
        assert cell.source_id == saved.source.id
        assert (cell.coverage, cell.device, cell.timezone, cell.finality) == ("unknown",) * 4
        for evidence in cell.evidence:
            assert evidence.observation_ids
            assert evidence.raw_artifact_id
            assert evidence.content_hash
            assert evidence.metric_row_id
            assert evidence.normalization_version == CONTRACT_VERSION
    assert {item.value for item in result.cells[5].evidence} == {17, 19}
    assert {item.metric_state for item in result.cells[6].evidence} == {"missing", "null"}


def test_window_same_count_and_nonvalues_keep_all_evidence(saved_database):
    session, store = saved_database
    saved, _ = materialize(session, store, count=17, extra=1)
    for count, extra in [(17, 2), (None, 3), (ABSENT, 4), (False, 5)]:
        materialize(session, store, count=count, extra=extra)
    result = read_steps(session, saved.source.id)
    assert (result.cells[0].state, result.cells[0].value) == ("value", 17)
    assert len(result.cells[0].evidence) == 5


def test_window_exact_source_dates_and_no_latest_or_auto_selection(saved_database):
    session, store = saved_database
    saved, _ = materialize(session, store, DAY - timedelta(days=1), 100)
    materialize(session, store, DAY + timedelta(days=1), 200)
    other, _ = materialize(session, store, DAY, 999, source("other-account"))
    assert read_steps(session, saved.source.id).cells[0].state == "projection_unavailable"
    assert read_steps(session, other.source.id).cells[0].value == 999
    assert (
        read_steps(session, saved.source.id, DAY - timedelta(days=1), DAY + timedelta(days=1))
        .cells[0]
        .value
        == 100
    )
    for source_id in [None, "", " "]:
        with pytest.raises(ValueError, match="explicit exact"):
            read_steps(session, source_id)
    unknown = read_steps(session, "nonexistent-source")
    assert unknown.reason == "source_not_found"
    assert unknown.cells[0].value is None


@pytest.mark.parametrize("materialized", [False, True])
def test_window_no_projection_is_not_missing_and_read_does_not_write(
    saved_database, monkeypatch, materialized
):
    session, store = saved_database
    saved = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 7})
    if materialized:
        project(session, store, saved.source.id)
    session.commit()
    session.connection().exec_driver_sql("PRAGMA query_only = ON")
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    def forbidden(*_args, **_kwargs):
        pytest.fail("reader called materialization or transaction mutation")

    monkeypatch.setattr(SavedDailyStepsRepository, "project_day", forbidden)
    monkeypatch.setattr(session, "commit", forbidden)
    event.listen(session.bind, "before_cursor_execute", capture)
    try:
        result = read_steps(session, saved.source.id)
    finally:
        event.remove(session.bind, "before_cursor_execute", capture)
    if materialized:
        assert (result.cells[0].state, result.cells[0].value) == ("value", 7)
    else:
        assert (result.cells[0].state, result.cells[0].reason) == (
            "projection_unavailable",
            "not_evidenced",
        )
    assert all(sql.lstrip().upper().startswith(("SELECT", "BEGIN")) for sql in statements)
    assert not (session.new or session.dirty or session.deleted)
    assert session.scalar(select(func.count(GarminRecordMetric.id))) == int(materialized)


@pytest.mark.parametrize("days", [1, 7, 30, 365, 366])
def test_window_inclusive_supported_bounds(saved_database, days):
    session, store = saved_database
    saved, _ = materialize(session, store, count=0)
    result = read_steps(session, saved.source.id, end=DAY + timedelta(days=days - 1))
    assert len(result.cells) == days
    assert result.cells[0].value == 0
    assert result.cells[-1].calendar_date == DAY + timedelta(days=days - 1)


def test_window_rejects_367_reversed_and_instant_dates_before_reads(saved_database):
    session, _store = saved_database
    for start, end in [
        (DAY, DAY + timedelta(days=366)),
        (DAY, DAY - timedelta(days=1)),
        (RECEIVED, DAY),
    ]:
        with pytest.raises(ValueError):
            read_steps(session, "explicit", start, end)
    assert not session.in_transaction()


def duplicate_candidates(session, result, count):
    record = session.get(GarminSourceRecord, result.evidence[0].record_id)
    metric = session.scalar(
        select(GarminRecordMetric).where(GarminRecordMetric.record_id == record.id)
    )
    records, metrics = [], []
    for index in range(1, count):
        record_id = f"{record.id[:8]}-candidate-{index:06}"
        records.append(
            {
                column.name: getattr(record, column.name)
                for column in GarminSourceRecord.__table__.columns
            }
            | {"id": record_id, "idempotency_key": f"synthetic-{index:064}"}
        )
        metrics.append(
            {
                column.name: getattr(metric, column.name)
                for column in GarminRecordMetric.__table__.columns
            }
            | {"id": f"{record.id[:8]}-metric-{index:06}", "record_id": record_id}
        )
    session.execute(insert(GarminSourceRecord), records)
    session.execute(insert(GarminRecordMetric), metrics)


def duplicate_provenance(session, saved, count):
    rows = [
        {
            column.name: getattr(saved.observation, column.name)
            for column in GarminPayloadObservation.__table__.columns
        }
        | {"id": f"synthetic-observation-{index:06}", "observation_key": f"{index:064}"}
        for index in range(1, count)
    ]
    session.execute(insert(GarminPayloadObservation), rows)


@pytest.mark.parametrize("kind", ["candidate", "provenance"])
@pytest.mark.parametrize("count", [4095, 4096, 4097])
def test_window_independent_cap_boundaries(saved_database, kind, count):
    session, store = saved_database
    saved, projected = materialize(session, store, count=0)
    if kind == "candidate":
        duplicate_candidates(session, projected, count)
    else:
        duplicate_provenance(session, saved, count)
    result = read_steps(session, saved.source.id)
    cell = result.cells[0]
    assert (cell.state, cell.value) == (
        ("value", 0) if count <= 4096 else ("search_incomplete", None)
    )
    assert result.search_complete == (count <= 4096)
    assert (
        result.candidates_examined if kind == "candidate" else result.provenance_examined
    ) == count
    if kind == "candidate" and count <= 4096:
        assert result.provenance_examined == 1  # raw references do not multiply acquisitions
    if kind == "provenance":
        assert result.candidates_examined == 1


@pytest.mark.parametrize("kind", ["candidate", "provenance"])
def test_window_incomplete_later_group_preserves_independently_complete_cell(saved_database, kind):
    session, store = saved_database
    saved, _ = materialize(session, store, count=2**53 + 1)
    later, projected = materialize(session, store, DAY + timedelta(days=1), 900)
    if kind == "candidate":
        duplicate_candidates(session, projected, 4097)
    else:
        duplicate_provenance(session, later, 4097)
    result = read_steps(session, saved.source.id, end=DAY + timedelta(days=2))
    assert result.cells[0].value == 2**53 + 1
    assert result.cells[0].search_complete
    assert (result.cells[1].state, result.cells[1].value) == ("search_incomplete", None)
    assert result.cells[1].reason == f"{kind}_limit_exceeded"
    assert result.cells[2].state == (
        "search_incomplete" if kind == "candidate" else "projection_unavailable"
    )


def test_window_metric_row_absence_is_incomplete_not_leaf_missing(saved_database):
    session, store = saved_database
    saved, projected = materialize(session, store)
    metric = session.scalar(
        select(GarminRecordMetric).where(
            GarminRecordMetric.record_id == projected.evidence[0].record_id
        )
    )
    session.delete(metric)
    session.flush()
    result = read_steps(session, saved.source.id)
    assert (result.cells[0].state, result.cells[0].value, result.cells[0].reason) == (
        "search_incomplete",
        None,
        "metric_row_not_evidenced",
    )


def test_window_pending_writes_are_rejected(saved_database):
    session, store = saved_database
    saved, _ = materialize(session, store)
    saved.source.source_kind = "pending-change"
    with pytest.raises(InvalidRequestError, match="pending"):
        read_steps(session, saved.source.id)


@pytest.mark.parametrize("text", ["00", "-1", "17.0", "17e0", " 17", "+17", None])
def test_window_never_coerces_invalid_integer_storage(saved_database, text):
    session, store = saved_database
    saved, projected = materialize(session, store)
    metric = session.scalar(
        select(GarminRecordMetric).where(
            GarminRecordMetric.record_id == projected.evidence[0].record_id
        )
    )
    metric.value_text = text
    session.flush()
    result = read_steps(session, saved.source.id)
    assert (result.cells[0].state, result.cells[0].value) == ("invalid", None)


def test_window_history_not_hidden_by_current_filter(saved_database):
    session, store = saved_database
    saved, projected = materialize(session, store)
    record = session.get(GarminSourceRecord, projected.evidence[0].record_id)
    record.projection_status = "retired"
    record.retired_at = RECEIVED
    record.retire_reason = "synthetic-retirement"
    session.flush()
    result = read_steps(session, saved.source.id)
    assert result.candidates_examined == 1
    assert (result.cells[0].state, result.cells[0].value) == ("search_incomplete", None)
    assert result.cells[0].evidence[0].projection_status == "retired"


def test_window_provenance_mismatch_fails_day_closed(saved_database):
    session, store = saved_database
    saved, _ = materialize(session, store)
    other, _ = materialize(session, store, DAY + timedelta(days=1), 19)
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
    result = read_steps(session, saved.source.id, end=DAY + timedelta(days=1))
    assert (result.cells[0].state, result.cells[0].value) == ("search_incomplete", None)
    assert result.cells[0].reason == "provenance_mismatch"
    assert result.cells[1].value == 19


def test_window_absence_requires_evidenced_leaf_absence(saved_database):
    session, store = saved_database
    saved, projected = materialize(session, store, count=ABSENT)
    metric = session.scalar(
        select(GarminRecordMetric).where(
            GarminRecordMetric.record_id == projected.evidence[0].record_id
        )
    )
    metric.reason = None
    session.flush()
    result = read_steps(session, saved.source.id)
    assert (result.cells[0].state, result.cells[0].reason) == (
        "search_incomplete",
        "leaf_absence_not_evidenced",
    )


def test_window_caps_exclude_other_sources_and_outside_dates(saved_database):
    session, store = saved_database
    saved, _ = materialize(session, store)
    _, outside = materialize(session, store, DAY - timedelta(days=1), 100)
    duplicate_candidates(session, outside, 4097)
    _, other = materialize(session, store, DAY, 900, source("other-account"))
    duplicate_candidates(session, other, 4097)
    result = read_steps(session, saved.source.id)
    assert result.search_complete
    assert (result.candidates_examined, result.provenance_examined) == (1, 1)
    assert result.cells[0].value == 17


def test_window_compound_reads_share_snapshot_across_new_projection(saved_database, monkeypatch):
    session, store = saved_database
    saved, _ = materialize(session, store)
    source_id = saved.source.id
    session.commit()
    original_get = session.get
    committed = []

    def read_then_materialize(model, identity, **kwargs):
        row = original_get(model, identity, **kwargs)
        if not committed:
            with create_session_factory(session.bind)() as writer:
                materialize(writer, store, count=19)
                writer.commit()
            committed.append(True)
        return row

    monkeypatch.setattr(session, "get", read_then_materialize)
    result = read_steps(session, source_id)
    assert committed == [True]
    assert result.cells[0].value == 17  # the concurrent materialization is outside this snapshot
    session.rollback()
    assert read_steps(session, source_id).cells[0].state == "ambiguous"
