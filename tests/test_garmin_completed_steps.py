"""Synthetic completed-day boundaries, acquisition proof and bounded completeness."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, insert, select

from healthcheck.db.models import GarminPayloadObservation, GarminRawPayload, IngestEvent, SyncRun
from healthcheck.db.repositories import repositories_for
from healthcheck.garmin import completed_steps_read as reader
from healthcheck.garmin.normalization import GarminSourceIdentity, normalize_garmin_payload
from healthcheck.garmin.observed_steps import SavedDailyStepsRepository
from healthcheck.garmin.observed_steps_read import read_observed_steps_window
from healthcheck.garmin.persistence import GarminPersistenceRepository
from test_garmin_observed_steps import saved_database as saved_database

DAY = date(2099, 1, 2)
BOUNDARY = datetime(2099, 1, 2, 21, tzinfo=UTC)
NOW = datetime(2099, 1, 4, 12, tzinfo=UTC)
ABSENT = object()


def acquire(
    session,
    store,
    count=17,
    *,
    at=BOUNDARY,
    day=DAY,
    run=None,
    status="succeeded",
    kind="garmin_incremental",
    account="synthetic-account",
    filename="daily_summary.json",
    extra=None,
):
    """Persist through the real normalizer/provenance spine; no provider calls."""
    payload = {"calendarDate": day.isoformat(), **(extra or {})}
    if count is not ABSENT:
        payload["totalSteps"] = count
    identity = GarminSourceIdentity(
        source_kind="provider",
        provider_code="garmin_connect",
        source_instance_id=account,
        device_attributed=False,
    )
    provider = repositories_for(session).providers.get_or_create(
        "garmin_connect", "Garmin Connect", "wearable"
    )
    if run is None:
        run = repositories_for(session).sync.create_run(provider_id=provider.id, stream_code=kind)
    normalized = normalize_garmin_payload(payload, stream="daily_health", source_identity=identity)
    saved = GarminPersistenceRepository(session, payload_store=store).persist_result(
        normalized,
        payload=payload,
        sync_run_id=run.id,
        source_filename=filename,
        received_at=at,
        source_window_start_utc=datetime(2099, 1, 2, tzinfo=UTC),
        source_window_end_utc=datetime(2099, 1, 3, tzinfo=UTC),
    )
    if status != "running":
        repositories_for(session).sync.finish_run(run.id, status=status)
    session.commit()
    return saved


def read(session, store, source_id, *, start=DAY, end=DAY, now=NOW):
    return reader.read_completed_steps_window(
        session,
        payload_store=store,
        source_id=source_id,
        start_date=start,
        end_date=end,
        evaluated_at=now,
    )


def append_unproven(session, observation, **changes):
    values = {
        column.name: getattr(observation, column.name)
        for column in GarminPayloadObservation.__table__.columns
    }
    values.update(
        id=str(uuid4()),
        observation_key="garmin-observation-v1:" + uuid4().hex,
        received_at=BOUNDARY + timedelta(hours=3),
    )
    values.update(changes)
    session.execute(insert(GarminPayloadObservation).values(**values))
    session.commit()


@pytest.mark.parametrize("delta,expected", [(-1, None), (0, 17), (1, 17)])
def test_moscow_boundary_exact_inclusive(saved_database, delta, expected):
    session, store = saved_database
    saved = acquire(session, store, at=BOUNDARY + timedelta(microseconds=delta))
    result = read(session, store, saved.source.id)
    assert result.cells[0].value == expected
    assert result.cells[0].completion_boundary_utc == BOUNDARY
    assert result.contract_version == "garmin-completed-day-steps-moscow-v1"
    assert result.cells[0].timezone == result.cells[0].finality == "unknown"


def test_moscow_today_future_and_snapshot_exclusion(saved_database):
    session, store = saved_database
    saved = acquire(session, store)
    acquire(session, store, 9, at=BOUNDARY + timedelta(hours=1))
    result = read(
        session,
        store,
        saved.source.id,
        start=DAY,
        end=DAY + timedelta(days=2),
        now=BOUNDARY + timedelta(minutes=1),
    )
    assert (result.start_date, result.end_date) == (DAY, DAY + timedelta(days=2))
    assert [cell.calendar_date for cell in result.cells] == [DAY]
    assert result.cells[0].value == 17
    assert (
        read(session, store, saved.source.id, now=BOUNDARY - timedelta(microseconds=1)).cells == ()
    )


def test_reacquisition_uses_actual_receipt_and_same_key_replay_keeps_old_time(saved_database):
    session, store = saved_database
    old = acquire(session, store, at=BOUNDARY - timedelta(hours=1))
    run = session.get(SyncRun, old.observation.sync_run_id)
    replay = acquire(session, store, run=run, at=BOUNDARY + timedelta(hours=1))
    assert replay.observation.id == old.observation.id
    assert read(session, store, old.source.id).cells[0].value is None
    new = acquire(session, store, at=BOUNDARY + timedelta(hours=2))
    assert new.raw_payload.id == old.raw_payload.id
    cell = read(session, store, old.source.id).cells[0]
    assert cell.value == 17 and cell.latest_received_at == BOUNDARY + timedelta(hours=2)
    assert cell.evidence[0].sync_run_id != old.raw_payload.sync_run_id


@pytest.mark.parametrize(
    "latest,expected_state,expected_value",
    [
        (3, "value", 3),
        (0, "value", 0),
        (ABSENT, "missing", None),
        (None, "null", None),
        (-1, "invalid", None),
        (True, "invalid", None),
        ("7", "invalid", None),
    ],
)
def test_newer_unprojected_lower_missing_or_invalid_never_falls_back(
    saved_database,
    latest,
    expected_state,
    expected_value,
):
    session, store = saved_database
    old = acquire(session, store, 100)
    SavedDailyStepsRepository(session, payload_store=store).project_day(old.source.id, DAY)
    session.commit()
    new = acquire(session, store, latest, at=BOUNDARY + timedelta(hours=1))
    cell = read(session, store, old.source.id).cells[0]
    assert (cell.state, cell.value) == (expected_state, expected_value)
    assert len(cell.evidence) == 2
    assert new.raw_payload.id in {item.raw_payload_id for item in cell.evidence}
    assert (
        read_observed_steps_window(session, source_id=old.source.id, start_date=DAY, end_date=DAY)
        .cells[0]
        .value
        == 100
    )


@pytest.mark.parametrize(
    "second,state,value", [(17, "value", 17), (9, "ambiguous", None), (ABSENT, "ambiguous", None)]
)
def test_complete_equal_timestamp_groups(saved_database, second, state, value):
    session, store = saved_database
    first = acquire(session, store, 17)
    acquire(session, store, second, extra={"extra": 1})
    cell = read(session, store, first.source.id).cells[0]
    assert (cell.state, cell.value, len(cell.evidence)) == (state, value, 2)


@pytest.mark.parametrize("status", ["partial", "failed", "running"])
def test_unproven_latest_run_blocks_older_value(saved_database, status):
    session, store = saved_database
    old = acquire(session, store)
    acquire(session, store, 9, at=BOUNDARY + timedelta(hours=1), status=status)
    cell = read(session, store, old.source.id).cells[0]
    assert (cell.state, cell.value, cell.reason) == (
        "unavailable",
        None,
        "latest_acquisition_unproven",
    )


@pytest.mark.parametrize("mismatch", ["run", "run_provider", "artifact", "event", "raw_source"])
def test_latest_wrong_links_are_unproven(saved_database, mismatch):
    session, store = saved_database
    old = acquire(session, store)
    new = acquire(session, store, 9, at=BOUNDARY + timedelta(hours=1))
    if mismatch == "run":
        append_unproven(session, new.observation, sync_run_id=old.observation.sync_run_id)
    elif mismatch == "artifact":
        append_unproven(session, new.observation, raw_artifact_id=old.raw_payload.raw_artifact_id)
    elif mismatch == "event":
        append_unproven(session, new.observation, ingest_event_id=old.observation.ingest_event_id)
    elif mismatch == "run_provider":
        provider = repositories_for(session).providers.get_or_create("other", "Other", "wearable")
        session.get(SyncRun, new.observation.sync_run_id).provider_id = provider.id
    else:
        other = acquire(session, store, account="other-account")
        values = {
            column.name: getattr(new.raw_payload, column.name)
            for column in GarminRawPayload.__table__.columns
        }
        values.update(id=str(uuid4()), garmin_source_id=other.source.id)
        session.execute(insert(GarminRawPayload).values(**values))
        append_unproven(session, new.observation, garmin_raw_payload_id=values["id"])
    session.commit()
    assert read(session, store, old.source.id).cells[0].value is None


def test_reprocess_and_other_filename_do_not_create_acquisitions(saved_database):
    session, store = saved_database
    old = acquire(session, store)
    acquire(session, store, 3, at=BOUNDARY + timedelta(hours=1), kind="garmin_reprocess")
    acquire(session, store, 9, at=BOUNDARY + timedelta(hours=2), filename="resting_heart_rate.json")
    assert read(session, store, old.source.id).cells[0].value == 17


def test_source_choice_and_returned_calendar_day_are_exact(saved_database):
    session, store = saved_database
    first = acquire(session, store)
    acquire(
        session,
        store,
        999,
        account="other-account",
        day=DAY + timedelta(days=1),
        at=BOUNDARY + timedelta(days=1),
    )
    assert read(session, store, None).source_id == first.source.id
    acquire(session, store, 8, account="other-account")
    ambiguous = read(session, store, None)
    assert ambiguous.reason == "source_selection_required" and ambiguous.cells == ()
    assert read(session, store, first.source.id).cells[0].value == 17


@pytest.mark.parametrize(
    "cap,reason",
    [
        ("MAX_PROVENANCE", "provenance_limit_exceeded"),
        ("MAX_CANDIDATES", "candidate_limit_exceeded"),
        ("MAX_ARTIFACTS", "artifact_limit_exceeded"),
    ],
)
@pytest.mark.parametrize("count", [1, 2, 3])
def test_cap_minus_exact_plus_one_fail_closed(saved_database, monkeypatch, cap, reason, count):
    session, store = saved_database
    monkeypatch.setattr(reader, cap, 2)
    for index in range(count):
        saved = acquire(session, store, index, at=BOUNDARY)
    result = read(session, store, saved.source.id)
    assert result.search_complete == (count <= 2)
    if count > 2:
        assert result.reason == reason and result.cells[0].value is None


@pytest.mark.parametrize(
    "cap,reason",
    [
        ("MAX_ARTIFACT_BYTES", "artifact_byte_limit_exceeded"),
        ("MAX_TOTAL_BYTES", "total_byte_limit_exceeded"),
        ("MAX_READ_SECONDS", "time_limit_exceeded"),
    ],
)
def test_byte_and_time_caps_do_not_return_old_value(saved_database, monkeypatch, cap, reason):
    session, store = saved_database
    saved = acquire(session, store)
    monkeypatch.setattr(reader, cap, 0)
    result = read(session, store, saved.source.id)
    assert not result.search_complete and result.reason == reason


def test_originals_read_once_no_writes_and_v1_ambiguity_unchanged(saved_database, monkeypatch):
    session, store = saved_database
    old = acquire(session, store, 100)
    acquire(session, store, 3, at=BOUNDARY + timedelta(hours=1))
    acquire(session, store, 3, at=BOUNDARY + timedelta(hours=2))
    SavedDailyStepsRepository(session, payload_store=store).project_day(old.source.id, DAY)
    session.commit()
    assert (
        read_observed_steps_window(session, source_id=old.source.id, start_date=DAY, end_date=DAY)
        .cells[0]
        .state
        == "ambiguous"
    )
    reads = []
    original = store.read
    monkeypatch.setattr(
        store, "read", lambda path, **kw: (reads.append(path), original(path, **kw))[1]
    )
    statements = []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(session.bind, "before_cursor_execute", capture)
    try:
        result = read(session, store, old.source.id, start=DAY, end=DAY + timedelta(days=1))
    finally:
        event.remove(session.bind, "before_cursor_execute", capture)
    assert result.cells[0].value == 3 and len(reads) == 2
    assert set(statements) <= {"SELECT", "BEGIN"}
    assert not session.new and not session.dirty and not session.deleted


def test_unreadable_unknown_day_fails_whole_search_closed(saved_database, monkeypatch):
    session, store = saved_database
    saved = acquire(session, store)

    def unreadable(*_args, **_kwargs):
        raise OSError("synthetic missing original")

    monkeypatch.setattr(store, "read", unreadable)
    assert read(session, store, saved.source.id).reason == "original_unreadable"


def test_missing_run_is_unproven(saved_database):
    session, store = saved_database
    saved = acquire(session, store)
    append_unproven(session, saved.observation, sync_run_id=None)
    assert read(session, store, saved.source.id).cells[0].value is None


def test_tied_proven_and_unproven_states_stay_ambiguous(saved_database):
    session, store = saved_database
    saved = acquire(session, store)
    append_unproven(session, saved.observation, sync_run_id=None, received_at=BOUNDARY)
    assert read(session, store, saved.source.id).cells[0].state == "ambiguous"


@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_exact_artifact_byte_boundary(saved_database, monkeypatch, delta):
    from healthcheck.db.models import RawArtifact

    session, store = saved_database
    saved = acquire(session, store, 2**53 + 1)
    artifact = session.get(RawArtifact, saved.raw_payload.raw_artifact_id)
    monkeypatch.setattr(reader, "MAX_ARTIFACT_BYTES", artifact.byte_size + delta)
    result = read(session, store, saved.source.id)
    assert result.search_complete == (delta >= 0)
    if delta >= 0:
        assert result.cells[0].value == 2**53 + 1


def test_original_integrity_failure_blocks_old_value(saved_database, monkeypatch):
    session, store = saved_database
    saved = acquire(session, store)
    original = store.read
    monkeypatch.setattr(store, "read", lambda path, **kw: original(path, **kw) + b" ")
    assert read(session, store, saved.source.id).reason == "original_integrity_mismatch"


def test_wrong_returned_day_never_substitutes_requested_day(saved_database):
    session, store = saved_database
    saved = acquire(session, store)
    acquire(session, store, 999, day=DAY - timedelta(days=1), at=BOUNDARY + timedelta(hours=2))
    assert read(session, store, saved.source.id).cells[0].value == 17


def test_actual_synthetic_surface_acquisition_path(tmp_path):
    from healthcheck.config import Settings
    from healthcheck.garmin.sync import GarminIncrementalSync
    from test_garmin_incremental_sync import _engine_factory, _steps_client

    report = GarminIncrementalSync(
        Settings(data_dir=tmp_path / "runtime"),
        client=_steps_client({"calendarDate": DAY.isoformat(), "totalSteps": 0}),
        clock=lambda: BOUNDARY,
    ).run(as_of=DAY, trailing_window_days=1)
    assert report.status.value == "succeeded"
    engine, factory = _engine_factory(tmp_path)
    from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore

    try:
        with factory() as session:
            obs = session.scalar(
                select(GarminPayloadObservation).where(
                    GarminPayloadObservation.source_filename == "daily_summary.json"
                )
            )
            store = ContentAddressedGarminPayloadStore(tmp_path / "runtime" / "artifacts")
            assert read(session, store, obs.garmin_source_id).cells[0].value == 0
            event_row = session.get(IngestEvent, obs.ingest_event_id)
            assert event_row.status == "committed"
    finally:
        engine.dispose()
