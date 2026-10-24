"""Synthetic acceptance cases for saved account-level Steps, without provider calls."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import event, func, insert, select
from sqlalchemy.exc import InvalidRequestError

from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
from healthcheck.db.models import (
    GarminDailyRecord,
    GarminDailySummaryDateProof,
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


@pytest.mark.parametrize("count", [4096, 4097])
def test_projector_observation_cap_precedes_artifact_reads_and_writes(
    saved_database, monkeypatch, count
):
    session, store = saved_database
    saved = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 0})
    duplicate_provenance(session, saved, count)
    reads = []
    original = store.read

    def read(path, **kwargs):
        reads.append(kwargs["max_bytes"])
        return original(path, **kwargs)

    monkeypatch.setattr(store, "read", read)
    if count == 4096:
        assert project(session, store, saved.source.id).value == 0
        artifact = session.get(RawArtifact, saved.raw_payload.raw_artifact_id)
        assert reads == [artifact.byte_size]
    else:
        with pytest.raises(SavedStepsEvidenceError, match="observation bound"):
            project(session, store, saved.source.id)
        assert reads == []
        assert session.scalar(select(func.count(GarminRecordMetric.id))) == 0


def test_corrupt_actual_file_cannot_bypass_byte_cap_with_small_metadata(
    saved_database, monkeypatch
):
    from pathlib import Path
    from unittest.mock import MagicMock

    session, store = saved_database
    saved = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 0})
    artifact = session.get(RawArtifact, saved.raw_payload.raw_artifact_id)
    path = store._resolve(artifact.relative_storage_path)
    path.write_bytes(b"x" * (2 * 1024 * 1024))
    original_open = Path.open
    read_sizes = []

    def bounded_open(selected, *args, **kwargs):
        handle = original_open(selected, *args, **kwargs)
        if selected != path:
            return handle
        wrapper = MagicMock(wraps=handle)
        wrapper.__enter__.return_value = wrapper
        wrapper.__exit__.side_effect = lambda *_: handle.close()

        def read(size=-1):
            read_sizes.append(size)
            assert size == artifact.byte_size + 1
            return handle.read(size)

        wrapper.read.side_effect = read
        return wrapper

    monkeypatch.setattr(Path, "open", bounded_open)
    with pytest.raises(SavedStepsEvidenceError, match="unreadable"):
        project(session, store, saved.source.id)
    assert read_sizes == [artifact.byte_size + 1]
    assert session.scalar(select(func.count(GarminRecordMetric.id))) == 0


@pytest.mark.parametrize("start,end", [
    (DAY, DAY - timedelta(days=1)), (DAY - timedelta(days=14), DAY), (RECEIVED, DAY)
])
def test_saved_refresh_window_validation_precedes_database_reads(saved_database, start, end):
    session, store = saved_database
    with pytest.raises(ValueError):
        SavedDailyStepsRepository(session, payload_store=store).project_saved_summary(
            "source", "observation", start_date=start, end_date=end
        )
    assert not session.in_transaction()


def test_saved_refresh_rejects_acquisition_source_mismatch(saved_database):
    session, store = saved_database
    saved = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 0})
    with pytest.raises(SavedStepsEvidenceError, match="acquisition mismatch"):
        SavedDailyStepsRepository(session, payload_store=store).project_saved_summary(
            "another-source", saved.observation.id, start_date=DAY, end_date=DAY
        )
    assert session.scalar(select(func.count(GarminRecordMetric.id))) == 0


@pytest.mark.parametrize("value", [0, 1001, True, 1.5])
def test_saved_date_bootstrap_rejects_invalid_batch_before_reads(saved_database, value):
    session, store = saved_database
    with pytest.raises(ValueError):
        SavedDailyStepsRepository(session, payload_store=store).index_saved_summary_dates(
            "source", max_artifacts=value
        )
    assert not session.in_transaction()


def test_saved_date_bootstrap_is_explicit_and_does_not_project_or_commit(saved_database):
    from healthcheck.garmin.observed_steps import DATE_PROOF_VERSION

    session, store = saved_database
    saved = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 0})
    source_id, raw_id = saved.source.id, saved.raw_payload.id
    session.commit()
    repository = SavedDailyStepsRepository(session, payload_store=store)
    batch = repository.index_saved_summary_dates(source_id)
    assert batch.input_after_raw_id is None and batch.proposed_after_raw_id == raw_id
    assert batch.inserted_proofs == batch.examined_raws == batch.inspected_observations == 1
    assert batch.exhausted_after_cursor and batch.stop_reason == "suffix_exhausted"
    assert not batch.unproven
    proof = session.get(GarminDailySummaryDateProof, raw_id)
    assert (proof.contract_version, proof.original_calendar_date) == (DATE_PROOF_VERSION, DAY)
    assert session.scalar(select(func.count(GarminSourceRecord.id))) == 0
    session.rollback()
    assert session.get(GarminDailySummaryDateProof, raw_id) is None
    # A cursor from an uncommitted batch must not be used to skip this original.
    repeated = repository.index_saved_summary_dates(source_id)
    assert repeated.inserted_proofs == 1
    session.commit()
    assert repository.index_saved_summary_dates(source_id).examined_raws == 0


def test_saved_date_bootstrap_advances_past_invalid_and_unreadable_without_proof(saved_database):
    session, store = saved_database
    bad_json = save(session, store, b"{synthetic-malformed")
    unsupported = save(session, store, {"date": DAY.isoformat(), "totalSteps": 4})
    unreadable = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 5})
    good = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 7})
    artifact = session.get(RawArtifact, unreadable.raw_payload.raw_artifact_id)
    missing_path = store._resolve(artifact.relative_storage_path)
    original = missing_path.read_bytes()
    missing_path.unlink()
    source_id = good.source.id
    unknown_ids = {item.raw_payload.id for item in (bad_json, unsupported, unreadable)}
    repository = SavedDailyStepsRepository(session, payload_store=store)
    cursor, encountered = None, set()
    for _ in range(4):
        batch = repository.index_saved_summary_dates(
            source_id, after_raw_id=cursor, max_artifacts=1
        )
        encountered.update(item.raw_payload_id for item in batch.unproven)
        session.commit()
        assert batch.proposed_after_raw_id != cursor
        cursor = batch.proposed_after_raw_id
    assert encountered == unknown_ids
    assert session.scalar(select(func.count(GarminDailySummaryDateProof.raw_payload_id))) == 1
    assert repository.index_saved_summary_dates(source_id, after_raw_id=cursor).examined_raws == 0
    # An exhausted suffix does not certify the unknown rows or remove them from projection.
    with pytest.raises(SavedStepsEvidenceError, match="unreadable"):
        project(session, store, source_id)
    missing_path.write_bytes(original)
    result = project(session, store, source_id)
    assert result.state == "ambiguous" and {item.value for item in result.evidence} == {5, 7}
    assert {item.raw_payload_id for item in result.excluded_artifacts} == {
        bad_json.raw_payload.id, unsupported.raw_payload.id,
    }


def test_saved_date_bootstrap_does_not_starve_after_oversized_observation_group(saved_database):
    session, store = saved_database
    entries = [save(session, store, {"calendarDate": DAY.isoformat(), "extra": i})
               for i in range(2)]
    entries.sort(key=lambda item: item.raw_payload.id)
    duplicate_provenance(session, entries[0], 4097)
    repository = SavedDailyStepsRepository(session, payload_store=store)
    first = repository.index_saved_summary_dates(entries[0].source.id)
    assert first.examined_raws == 1 and first.inspected_observations == 4097
    assert first.inserted_proofs == 0 and first.unproven[0].reason == "observation_bound"
    assert first.proposed_after_raw_id == entries[0].raw_payload.id
    session.commit()
    second = repository.index_saved_summary_dates(
        entries[0].source.id, after_raw_id=first.proposed_after_raw_id
    )
    assert second.inserted_proofs == 1 and second.exhausted_after_cursor
    session.commit()
    with pytest.raises(SavedStepsEvidenceError, match="observation bound"):
        project(session, store, entries[0].source.id)


def test_saved_date_bootstrap_total_physical_allowance_stops_before_next_read(
    saved_database, monkeypatch
):
    from healthcheck.garmin import observed_steps as implementation

    session, store = saved_database
    entries = [save(session, store, {"calendarDate": DAY.isoformat(), "extra": i})
               for i in range(2)]
    entries.sort(key=lambda item: item.raw_payload.id)
    artifact = session.get(RawArtifact, entries[0].raw_payload.raw_artifact_id)
    allowance = artifact.byte_size + 1
    monkeypatch.setattr(implementation, "MAX_TOTAL_READ_BYTES", allowance)
    repository = SavedDailyStepsRepository(session, payload_store=store)
    batch = repository.index_saved_summary_dates(entries[0].source.id)
    assert batch.read_allowance_bytes == allowance and batch.inserted_proofs == 1
    assert batch.stop_reason == "byte_batch_bound" and not batch.exhausted_after_cursor
    assert batch.proposed_after_raw_id == entries[0].raw_payload.id
    session.commit()
    next_batch = repository.index_saved_summary_dates(
        entries[0].source.id, after_raw_id=batch.proposed_after_raw_id
    )
    assert next_batch.inserted_proofs == 1


@pytest.mark.parametrize("failure", ["interrupt", "flush", "deadline"])
def test_saved_date_bootstrap_fatal_failure_rolls_back_batch_and_reuses_input(
    saved_database, monkeypatch, failure
):
    from healthcheck.garmin import observed_steps as implementation

    session, store = saved_database
    saved = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 7})
    source_id, raw_id = saved.source.id, saved.raw_payload.id
    session.commit()
    repository = SavedDailyStepsRepository(session, payload_store=store)
    original_read, original_flush = store.read, session.flush
    with monkeypatch.context() as patch:
        if failure == "interrupt":
            def interrupted(*_args, **_kwargs):
                raise KeyboardInterrupt("synthetic interruption")
            patch.setattr(store, "read", interrupted)
            expected = KeyboardInterrupt
        elif failure == "flush":
            def failed_flush(*_args, **_kwargs):
                original_flush()
                raise RuntimeError("synthetic post-flush failure")
            patch.setattr(session, "flush", failed_flush)
            expected = RuntimeError
        else:
            def expired(*args, **kwargs):
                result = original_read(*args, **kwargs)
                repository._active_budget.deadline = 0
                return result
            patch.setattr(store, "read", expired)
            expected = implementation.SavedStepsBudgetError
        with pytest.raises(expected):
            repository.index_saved_summary_dates(source_id)
    assert not session.in_transaction()
    assert session.get(GarminDailySummaryDateProof, raw_id) is None
    assert repository.index_saved_summary_dates(source_id).inserted_proofs == 1


@pytest.mark.parametrize("surface", ["candidates", "observations"])
def test_saved_steps_sql_budget_covers_both_metadata_enumerations_and_restores_connection(
    saved_database, monkeypatch, surface
):
    from healthcheck.garmin import observed_steps as implementation

    session, store = saved_database
    saved = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 7})
    duplicate_provenance(session, saved, 512)
    source_id, raw_id = saved.source.id, saved.raw_payload.id
    session.commit()
    repository = SavedDailyStepsRepository(session, payload_store=store)
    driver = session.connection().connection.driver_connection
    original_timeout = driver.execute("PRAGMA busy_timeout").fetchone()[0]
    reads = []
    monkeypatch.setattr(store, "read", lambda *_args, **_kwargs: reads.append(True))
    monkeypatch.setattr(implementation, "MAX_SQL_STEPS", 1000)
    if surface == "observations":
        from sqlalchemy import literal
        monkeypatch.setattr(repository, "_raw_candidates", lambda *_args, **_kwargs: select(
            literal(raw_id)
        ))
    with pytest.raises(implementation.SavedStepsBudgetError, match="SQL work bound"):
        repository.project_day(source_id, DAY)
    assert not reads
    assert driver.execute("PRAGMA busy_timeout").fetchone()[0] == original_timeout
    # This statement would be interrupted if the expired callback leaked.
    assert driver.execute(
        "WITH RECURSIVE x(n) AS (VALUES(1) UNION ALL SELECT n+1 FROM x WHERE n<2000) "
        "SELECT sum(n) FROM x"
    ).fetchone()[0] == 2001000
    session.rollback()
    assert session.scalar(select(func.count(GarminDailySummaryDateProof.raw_payload_id))) == 0


def test_saved_date_proof_never_hides_bad_observation_artifact_link(saved_database):
    from healthcheck.garmin.observed_steps import DATE_PROOF_VERSION

    session, store = saved_database
    old = save(session, store, {"calendarDate": "2090-01-01", "totalSteps": 3})
    other = save(session, store, {"calendarDate": "2090-01-02", "totalSteps": 4})
    SavedDailyStepsRepository(session, payload_store=store).index_saved_summary_dates(old.source.id)
    session.commit()
    fields = {column.name: getattr(old.observation, column.name)
              for column in GarminPayloadObservation.__table__.columns}
    session.execute(insert(GarminPayloadObservation).values(**(fields | {
        "id": "523-contradictory-observation", "observation_key": "523" * 22,
        "raw_artifact_id": other.raw_payload.raw_artifact_id,
    })))
    proof = session.get(GarminDailySummaryDateProof, old.raw_payload.id)
    assert proof.contract_version == DATE_PROOF_VERSION
    with pytest.raises(SavedStepsEvidenceError, match="provenance mismatch"):
        project(session, store, old.source.id)
    assert session.scalar(select(func.count(GarminRecordMetric.id))) == 0


def test_unknown_date_proof_version_is_retained_and_fails_closed(saved_database):
    session, store = saved_database
    saved = save(session, store, {"calendarDate": "2090-01-01", "totalSteps": 3})
    session.add(GarminDailySummaryDateProof(
        raw_payload_id=saved.raw_payload.id, contract_version="unrecognized",
        original_calendar_date=date(2090, 1, 1),
    ))
    session.flush()
    with pytest.raises(SavedStepsEvidenceError, match="date proof mismatch"):
        project(session, store, saved.source.id)


def test_saved_date_index_migration_is_empty_and_preserves_legacy(tmp_path):
    from alembic import command
    from sqlalchemy import inspect

    from healthcheck.db.engine import _alembic_config

    paths = prepare_runtime(Settings(data_dir=tmp_path / "synthetic-migration-runtime"))
    config = _alembic_config(paths)
    command.upgrade(config, "0018_google_offline_steps")
    engine = create_sqlite_engine(paths)
    try:
        with create_session_factory(engine)() as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            saved = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 9})
            identity = saved.raw_payload.id, saved.observation.id, saved.raw_payload.content_hash
            session.commit()
        command.upgrade(config, "head")
        with create_session_factory(engine)() as session:
            assert session.scalar(select(func.count(
                GarminDailySummaryDateProof.raw_payload_id
            ))) == 0
            assert session.get(GarminRawPayload, identity[0]).content_hash == identity[2]
            assert session.get(GarminPayloadObservation, identity[1]) is not None
        foreign = inspect(engine).get_foreign_keys(GarminDailySummaryDateProof.__tablename__)
        assert len(foreign) == 1 and foreign[0]["referred_table"] == "garmin_raw_payloads"
        assert foreign[0]["options"]["ondelete"] == "RESTRICT"
        with engine.connect() as connection:
            assert not list(connection.exec_driver_sql("PRAGMA foreign_key_check"))
        command.downgrade(config, "0018_google_offline_steps")
        assert GarminDailySummaryDateProof.__tablename__ not in inspect(engine).get_table_names()
        command.upgrade(config, "head")
    finally:
        engine.dispose()


@pytest.mark.parametrize("action", ["update", "delete", "duplicate", "foreign", "date", "version"])
def test_saved_date_proof_schema_rejects_mutation_and_invalid_values(saved_database, action):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from healthcheck.garmin.observed_steps import DATE_PROOF_VERSION

    session, store = saved_database
    saved = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 7})
    repository = SavedDailyStepsRepository(session, payload_store=store)
    repository.index_saved_summary_dates(saved.source.id)
    session.commit()
    second = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 9})
    table = GarminDailySummaryDateProof.__tablename__
    with pytest.raises(IntegrityError), session.begin_nested():
        if action == "update":
            session.execute(text(f"UPDATE {table} SET contract_version='changed'"))
        elif action == "delete":
            session.execute(text(f"DELETE FROM {table}"))
        else:
            raw_id = saved.raw_payload.id if action == "duplicate" else "missing-raw"
            if action in {"date", "version"}:
                # The raw exists, so these fail their own CHECK rather than just FK.
                raw_id = second.raw_payload.id
            session.execute(text(
                f"INSERT INTO {table}(raw_payload_id,contract_version,original_calendar_date) "
                "VALUES (:raw,:version,:day)"
            ), {"raw": raw_id, "version": "" if action == "version" else DATE_PROOF_VERSION,
                "day": "2099-02-31" if action == "date" else DAY.isoformat()})



def test_final_saved_steps_budget_failure_rolls_back_proof_and_projection_savepoint(
    saved_database, monkeypatch
):
    from healthcheck.garmin.observed_steps import SavedStepsBudgetError

    session, store = saved_database
    saved = save(session, store, {"calendarDate": DAY.isoformat(), "totalSteps": 7})
    source_id, raw_id, observation_id = (
        saved.source.id, saved.raw_payload.id, saved.observation.id
    )
    session.commit()
    repository = SavedDailyStepsRepository(session, payload_store=store)
    original_upsert = repository.records.upsert

    def upsert_then_expire(**kwargs):
        result = original_upsert(**kwargs)
        repository._active_budget.deadline = 0
        return result

    monkeypatch.setattr(repository.records, "upsert", upsert_then_expire)
    with pytest.raises(SavedStepsBudgetError, match="work bound"):
        repository.project_day(source_id, DAY)
    # Even a caller that catches the service error and commits cannot publish
    # derived rows from the failed operation. Pre-existing raw evidence survives.
    session.commit()
    assert session.get(GarminDailySummaryDateProof, raw_id) is None
    assert session.scalar(select(func.count(GarminRecordMetric.id))) == 0
    assert session.scalar(select(func.count(GarminSourceRecord.id))) == 0
    assert session.get(GarminRawPayload, raw_id) is not None
    assert session.get(GarminPayloadObservation, observation_id) is not None
