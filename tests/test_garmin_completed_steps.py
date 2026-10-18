"""Synthetic completed-day boundaries, acquisition proof and bounded completeness."""

from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, insert, select

from healthcheck.db.models import (
    GarminDailySummaryAcquisitionReceipt as Receipt,
)
from healthcheck.db.models import (
    GarminPayloadObservation,
    GarminRawPayload,
    IngestEvent,
    RawArtifact,
    SyncRun,
)
from healthcheck.db.repositories import repositories_for
from healthcheck.garmin import completed_steps_read as reader
from healthcheck.garmin.daily_summary_acquisition import (
    RECEIPT_VERSION,
    record_daily_summary_acquisition,
)
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
    receipt=False,
    commit=True,
    window_day=None,
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
    start = datetime.combine(window_day or (day if receipt else DAY), time(), UTC)
    end = start + timedelta(days=1)
    if run is None:
        run = repositories_for(session).sync.create_run(
            provider_id=provider.id,
            stream_code=kind,
            requested_start=start if receipt or window_day else None,
            requested_end=end if receipt or window_day else None,
        )
    normalized = normalize_garmin_payload(payload, stream="daily_health", source_identity=identity)
    saved = GarminPersistenceRepository(session, payload_store=store).persist_result(
        normalized,
        payload=payload,
        sync_run_id=run.id,
        source_filename=filename,
        received_at=at,
        source_window_start_utc=start,
        source_window_end_utc=end,
    )
    if receipt:
        artifact = session.get(RawArtifact, saved.raw_payload.raw_artifact_id)
        assert (
            record_daily_summary_acquisition(
                session,
                saved,
                original_bytes=store.read(artifact.relative_storage_path),
                requested_date=day,
                surface="daily_summary",
                method="get_user_summary",
                fetch_complete=True,
                request_count=1,
            )
            is not None
        )
    if status != "running":
        repositories_for(session).sync.finish_run(run.id, status=status)
    if commit:
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
    assert result.contract_version == "garmin-completed-day-steps-moscow-v2"
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


def add_synthetic_receipt(session, observation_id, day):
    """Deliberately bypass the writer for adversarial synthetic index fixtures."""
    session.add(
        Receipt(
            observation_id=observation_id,
            contract_version=RECEIPT_VERSION,
            surface="daily_summary",
            method="get_user_summary",
            requested_date=day,
            original_calendar_date=day,
        )
    )
    session.commit()


def test_year_window_reads_only_indexed_year_from_over_1000_originals(saved_database, monkeypatch):
    session, store = saved_database
    first = date(2096, 1, 1)
    received = datetime(2101, 1, 2, tzinfo=UTC)
    provider = repositories_for(session).providers.get_or_create(
        "garmin_connect", "Garmin Connect", "wearable"
    )
    run = repositories_for(session).sync.create_run(
        provider_id=provider.id,
        stream_code="garmin_historical",
        requested_start=datetime(2096, 1, 1, tzinfo=UTC),
        requested_end=datetime(2101, 1, 1, tzinfo=UTC),
    )
    for offset in range(1100):
        saved = acquire(
            session,
            store,
            offset,
            day=first + timedelta(days=offset),
            at=received,
            run=run,
            status="running",
            receipt=True,
            commit=False,
        )
    repositories_for(session).sync.finish_run(run.id, status="succeeded")
    session.commit()
    paths = []
    original = store.read
    monkeypatch.setattr(
        store, "read", lambda path, **kw: (paths.append(path), original(path, **kw))[1]
    )
    for year in (2096, 2097, 2098):
        paths.clear()
        start, end = date(year, 1, 1), date(year, 12, 31)
        length = (end - start).days + 1
        result = read(session, store, saved.source.id, start=start, end=end, now=received)
        assert result.search_complete
        assert result.candidates_examined == result.provenance_examined == 1100
        assert result.artifacts_examined == len(paths) == length
        assert [cell.value for cell in result.cells] == [
            (start - first).days + offset for offset in range(length)
        ]
        assert all(
            cell.evidence[0].acquisition_proof == "daily_summary_receipt" for cell in result.cells
        )


def test_year_edges_and_all_reacquisitions_preserve_latest_and_ties(saved_database):
    session, store = saved_database
    days = [date(2098, 12, 31), date(2099, 1, 1), date(2099, 12, 31), date(2100, 1, 1)]
    at = datetime(2100, 1, 3, tzinfo=UTC)
    for day in days:
        saved = acquire(session, store, 100, day=day, at=at, receipt=True)
    acquire(session, store, 7, day=days[1], at=at + timedelta(hours=1), receipt=True)
    acquire(session, store, None, day=days[2], at=at + timedelta(hours=1), receipt=True)
    acquire(session, store, 5, day=days[2], at=at + timedelta(hours=1), receipt=True)
    result = read(
        session, store, saved.source.id, start=days[1], end=days[2], now=at + timedelta(days=1)
    )
    assert result.search_complete and result.artifacts_examined == 5
    assert result.cells[0].value == 7 and len(result.cells[0].evidence) == 2
    assert result.cells[-1].state == "ambiguous" and len(result.cells[-1].evidence) == 3


@pytest.mark.parametrize("receipt_day", [None, DAY + timedelta(days=1)])
def test_missing_or_mismatched_index_retains_actual_legacy_returned_day(
    saved_database, receipt_day
):
    session, store = saved_database
    saved = acquire(session, store, 31)
    if receipt_day:
        add_synthetic_receipt(session, saved.observation.id, receipt_day)
    result = read(session, store, saved.source.id)
    assert result.search_complete and result.artifacts_examined == 1
    assert result.cells[0].value == (None if receipt_day else 31)
    if receipt_day:
        assert result.cells[0].evidence[0].reason == "acquisition_receipt_mismatch"


@pytest.mark.parametrize("tied", [False, True])
def test_valid_index_never_hides_same_raw_unproven_competitor(saved_database, tied):
    session, store = saved_database
    outside = DAY + timedelta(days=1)
    saved = acquire(session, store, 33, day=outside, at=NOW, receipt=True)
    append_unproven(
        session, saved.observation, received_at=NOW if tied else NOW + timedelta(hours=1)
    )
    result = read(
        session, store, saved.source.id, start=outside, end=outside, now=NOW + timedelta(days=1)
    )
    assert result.artifacts_examined == 1 and len(result.cells[0].evidence) == 2
    assert result.cells[0].state == ("ambiguous" if tied else "unavailable")
    # Even outside the window, the unindexed competitor forces original reading.
    result = read(session, store, saved.source.id, now=NOW + timedelta(days=1))
    assert result.search_complete and result.artifacts_examined == 1


def test_conflicting_valid_index_days_for_same_raw_force_original_verification(saved_database):
    session, store = saved_database
    saved = acquire(session, store, receipt=True)
    other = DAY + timedelta(days=1)
    forged = acquire(session, store, window_day=other, at=BOUNDARY + timedelta(hours=1))
    assert forged.raw_payload.id == saved.raw_payload.id
    add_synthetic_receipt(session, forged.observation.id, other)
    # Both metadata spines/indexes pass individually, but disagree for one raw.
    result = read(
        session, store, saved.source.id, start=DAY - timedelta(days=1), end=DAY - timedelta(days=1)
    )
    assert result.search_complete and result.artifacts_examined == 1
    result = read(session, store, saved.source.id)
    assert result.cells[0].value is None and len(result.cells[0].evidence) == 2
    assert result.cells[0].evidence[-1].reason == "acquisition_receipt_mismatch"


@pytest.mark.parametrize(
    "cap,reason",
    [
        ("MAX_PROVENANCE", "provenance_limit_exceeded"),
        ("MAX_CANDIDATES", "candidate_limit_exceeded"),
    ],
)
def test_outside_indexed_history_still_counts_toward_metadata_caps(
    saved_database, monkeypatch, cap, reason
):
    session, store = saved_database
    for offset in range(3):
        saved = acquire(session, store, day=DAY + timedelta(days=offset + 1), at=NOW, receipt=True)
    monkeypatch.setattr(reader, cap, 2)
    result = read(session, store, saved.source.id)
    assert not result.search_complete and result.reason == reason
    assert result.artifacts_examined == 0


def test_unknown_legacy_day_still_fails_closed_beside_outside_index(saved_database, monkeypatch):
    session, store = saved_database
    acquire(session, store, day=DAY + timedelta(days=1), at=NOW, receipt=True)
    legacy = acquire(session, store, 44, day=DAY - timedelta(days=1))

    def unreadable(*_args, **_kwargs):
        raise OSError("synthetic missing original")

    monkeypatch.setattr(store, "read", unreadable)
    result = read(session, store, legacy.source.id)
    assert not result.search_complete and result.reason == "original_unreadable"


@pytest.mark.parametrize("mismatch", ["status", "provider", "window"])
def test_outside_index_with_tampered_run_cannot_hide_actual_inrange_day(saved_database, mismatch):
    session, store = saved_database
    outside = DAY + timedelta(days=1)
    saved = acquire(session, store, window_day=outside)
    add_synthetic_receipt(session, saved.observation.id, outside)
    run = session.get(SyncRun, saved.observation.sync_run_id)
    if mismatch == "status":
        run.status = "failed"
    elif mismatch == "provider":
        run.provider_id = (
            repositories_for(session)
            .providers.get_or_create("synthetic_other", "Synthetic Other", "wearable")
            .id
        )
    else:
        run.requested_end = datetime.combine(DAY, time(), UTC)
    session.commit()
    result = read(session, store, saved.source.id)
    assert result.search_complete and result.artifacts_examined == 1
    assert result.cells[0].value is None and len(result.cells[0].evidence) == 1
    assert not result.cells[0].evidence[0].acquisition_proven


@pytest.mark.parametrize("failure", ["missing", "hash"])
def test_indexed_selected_original_still_requires_bytes_and_integrity(
    saved_database, monkeypatch, failure
):
    session, store = saved_database
    saved = acquire(session, store, receipt=True)
    original = store.read

    def broken(path, **kwargs):
        if failure == "missing":
            raise OSError("synthetic missing selected original")
        return original(path, **kwargs) + b" "

    monkeypatch.setattr(store, "read", broken)
    result = read(session, store, saved.source.id)
    assert not result.search_complete
    assert result.reason == (
        "original_unreadable" if failure == "missing" else "original_integrity_mismatch"
    )


def test_automatic_source_choice_uses_retained_actual_inrange_evidence(saved_database):
    session, store = saved_database
    acquire(session, store, day=DAY - timedelta(days=1), receipt=True, account="other")
    selected = acquire(session, store, receipt=True)
    result = read(session, store, None)
    assert result.search_complete and result.source_id == selected.source.id
    assert result.artifacts_examined == 1 and len(result.source_choices) == 1
