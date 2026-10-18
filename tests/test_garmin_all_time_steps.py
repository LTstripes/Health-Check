"""Synthetic all-history budget, day grain and statistics; no provider or Owner data."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, migrate_database
from healthcheck.db.models import RawArtifact
from healthcheck.db.repositories import repositories_for
from healthcheck.garmin import completed_steps_read as reader
from healthcheck.garmin.steps_statistics import summarize_completed_days
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.runtime import prepare_runtime
from test_garmin_completed_steps import ABSENT, BOUNDARY, DAY, NOW, acquire
from test_garmin_observed_steps import saved_database as saved_database


def read(session, store, source_id, **kwargs):
    return reader.read_completed_steps_all_time(
        session,
        payload_store=store,
        source_id=source_id,
        evaluated_at=kwargs.pop("evaluated_at", NOW),
        **kwargs,
    )


def test_unique_days_thresholds_all_records_and_calendar_streaks(saved_database):
    session, store = saved_database
    # 10000 counts for streaks, but not >10000. Null and absent calendar days break runs.
    values = {
        0: 0,
        1: 10000,
        2: 20000,
        3: None,
        4: 20001,
        5: 20001,
        7: 10000,
        8: 10001,
        9: ABSENT,
        10: True,
    }
    for offset, value in values.items():
        saved = acquire(
            session,
            store,
            value,
            day=DAY + timedelta(days=offset),
            at=BOUNDARY + timedelta(days=offset),
            receipt=True,
        )
    # Earlier higher value must not inflate sum or record; latest lower correction wins.
    acquire(session, store, 99999, day=DAY, at=BOUNDARY - timedelta(hours=1))
    result = read(session, store, saved.source.id, evaluated_at=NOW + timedelta(days=11))
    stats = result.statistics
    assert result.contract_version == reader.ALL_TIME_CONTRACT_VERSION
    assert result.budget_version == reader.ALL_TIME_BUDGET_VERSION
    assert stats.eligible_day_count == 7 and stats.total == 90003
    assert stats.mean == Decimal(90003) / 7
    assert stats.over_10000_day_count == 4 and stats.over_20000_day_count == 2
    assert stats.record_value == 20001
    assert stats.record_dates == (DAY + timedelta(days=4), DAY + timedelta(days=5))
    assert stats.longest_10000_streak == 2
    assert stats.longest_streak_ranges == tuple(
        (DAY + timedelta(days=i), DAY + timedelta(days=i + 1)) for i in (1, 4, 7)
    )
    assert stats.calendar_day_count == (result.end_date - DAY).days + 1
    assert stats.unobserved_day_count == stats.calendar_day_count - len(values)
    assert stats.state_counts == {"value": 7, "null": 1, "missing": 1, "invalid": 1}
    assert all(
        cell.coverage == cell.timezone == cell.finality == "unknown" for cell in result.cells
    )


@pytest.mark.parametrize(
    "latest,state",
    [
        (None, "null"),
        (ABSENT, "missing"),
        (True, "invalid"),
        (-1, "invalid"),
        (2**70, "value"),
        (0, "value"),
    ],
)
def test_latest_nonvalue_never_reveals_old_value(saved_database, latest, state):
    session, store = saved_database
    saved = acquire(session, store, 99999)
    acquire(session, store, 17, day=DAY - timedelta(days=1))
    acquire(session, store, latest, at=BOUNDARY + timedelta(hours=1))
    result = read(session, store, saved.source.id)
    assert result.cells[-1].state == state
    assert result.statistics.total == (17 + latest if state == "value" else 17)
    assert result.statistics.eligible_day_count == (2 if state == "value" else 1)
    assert result.statistics.record_value == (max(17, latest) if state == "value" else 17)


@pytest.mark.parametrize("proof,expected", [(False, None), (True, 3)])
def test_partial_receipt_rule_is_reused(saved_database, proof, expected):
    session, store = saved_database
    saved = acquire(session, store, 999)
    acquire(session, store, 3, at=BOUNDARY + timedelta(hours=1), status="partial", receipt=proof)
    result = read(session, store, saved.source.id)
    assert result.statistics.total == expected
    assert result.cells[0].value == expected


@pytest.mark.parametrize("other,expected", [(17, 17), (18, None), (None, None)])
def test_complete_latest_tie_groups_not_record_id_selection(saved_database, other, expected):
    session, store = saved_database
    saved = acquire(session, store, 17)
    acquire(session, store, other)
    result = read(session, store, saved.source.id)
    assert len(result.cells) == 1 and len(result.cells[0].evidence) == 2
    assert result.statistics.total == expected
    assert result.statistics.record_dates == ((DAY,) if expected is not None else ())


def test_reacquisition_opens_unique_original_once_and_keeps_provenance(saved_database, monkeypatch):
    session, store = saved_database
    first = acquire(session, store, 0, at=BOUNDARY - timedelta(microseconds=1))
    acquire(session, store, 0, at=BOUNDARY + timedelta(hours=1))
    paths = []
    original = store.read
    monkeypatch.setattr(
        store, "read", lambda path, **kw: (paths.append(path), original(path, **kw))[1]
    )
    monkeypatch.setattr(reader, "MAX_ALL_TIME_ARTIFACTS", 1)
    result = read(session, store, first.source.id)
    assert result.search_complete and result.artifacts_examined == len(paths) == 1
    assert result.provenance_examined == 2 and result.statistics.eligible_day_count == 1
    assert result.statistics.total == result.statistics.mean == result.statistics.record_value == 0
    assert result.statistics.longest_10000_streak == 0
    assert result.cells[0].latest_received_at == BOUNDARY + timedelta(hours=1)


def test_sparse_history_does_not_expand_calendar_or_pool_sources(saved_database):
    session, store = saved_database
    saved = acquire(session, store, 1, day=date(1, 1, 1))
    acquire(session, store, 10000, day=DAY)
    acquire(session, store, 999999, account="other-synthetic-account")
    result = read(session, store, saved.source.id)
    assert len(result.cells) == 2 and result.provenance_examined == 2
    assert result.statistics.total == 10001 and result.statistics.longest_10000_streak == 1
    assert result.statistics.calendar_day_count > 700000
    assert result.statistics.unobserved_day_count == result.statistics.calendar_day_count - 2


@pytest.mark.parametrize("delta,expected", [(-1, None), (0, 17), (1, 17)])
def test_exact_moscow_boundary_reused(saved_database, delta, expected):
    session, store = saved_database
    saved = acquire(session, store, 17, at=BOUNDARY + timedelta(microseconds=delta))
    result = read(session, store, saved.source.id)
    assert result.statistics.total == expected


def test_explicit_end_and_future_exclusion_are_honest(saved_database):
    session, store = saved_database
    for offset in (0, 1, 2, 100):
        saved = acquire(session, store, 10, day=DAY + timedelta(days=offset), at=BOUNDARY)
    historical = read(session, store, saved.source.id, end_date=DAY)
    assert historical.end_date == DAY and historical.requested_end_date == DAY
    assert historical.statistics.total == 10
    current = read(session, store, saved.source.id, end_date=date.max)
    assert current.end_date == date(2099, 1, 3)
    # Future days are excluded; a before-cutoff acquisition stays unavailable.
    assert [cell.calendar_date for cell in current.cells] == [DAY, DAY + timedelta(days=1)]
    assert current.statistics.total == 10 and current.statistics.eligible_day_count == 1


@pytest.mark.parametrize("source", [None, "missing"])
def test_explicit_source_required_without_reading_originals(saved_database, monkeypatch, source):
    session, store = saved_database
    acquire(session, store)
    monkeypatch.setattr(store, "read", lambda *a, **k: pytest.fail("unselected original read"))
    result = read(session, store, source)
    assert result.statistics is None and result.cells == ()
    assert result.reason == ("source_selection_required" if source is None else "source_not_found")


@pytest.mark.parametrize(
    "kw",
    [
        {"end_date": True},
        {"evaluated_at": datetime(2099, 1, 4)},
        {"end_date": datetime(2099, 1, 2, tzinfo=UTC)},
    ],
)
def test_bad_caller_rejected_before_sql(saved_database, monkeypatch, kw):
    session, store = saved_database
    monkeypatch.setattr(session, "get", lambda *a, **k: pytest.fail("invalid caller touched SQL"))
    with pytest.raises(ValueError):
        read(session, store, "anything", **kw)


@pytest.mark.parametrize("limit", ["MAX_ALL_TIME_ARTIFACTS", "MAX_CANDIDATES", "MAX_PROVENANCE"])
def test_cap_exhaustion_has_no_prefix_statistics(saved_database, monkeypatch, limit):
    session, store = saved_database
    for year in (2096, 2097, 2098):
        saved = acquire(session, store, 5, day=date(year, 1, 1))
    monkeypatch.setattr(reader, limit, 2)
    result = read(session, store, saved.source.id)
    assert not result.search_complete and result.statistics is None
    assert result.cells == () and result.start_date is None


@pytest.mark.parametrize("field", ["MAX_TOTAL_BYTES", "MAX_ARTIFACT_BYTES"])
@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_exact_byte_caps(saved_database, monkeypatch, field, delta):
    session, store = saved_database
    saved = acquire(session, store)
    artifact = session.get(RawArtifact, saved.raw_payload.raw_artifact_id)
    monkeypatch.setattr(reader, field, artifact.byte_size + delta)
    result = read(session, store, saved.source.id)
    assert result.search_complete == (delta >= 0)
    assert (result.statistics.total if result.statistics else None) == (17 if delta >= 0 else None)


def test_byte_budget_not_reset_between_years_and_actual_read_bounded(saved_database, monkeypatch):
    session, store = saved_database
    a = acquire(session, store, 3, day=date(2097, 1, 1))
    b = acquire(session, store, 5, day=date(2098, 1, 1))
    size_a = session.get(RawArtifact, a.raw_payload.raw_artifact_id).byte_size
    size_b = session.get(RawArtifact, b.raw_payload.raw_artifact_id).byte_size
    monkeypatch.setattr(reader, "MAX_TOTAL_BYTES", size_a + size_b - 1)
    result = read(session, store, a.source.id)
    assert not result.search_complete and result.statistics is None
    assert result.reason == "total_byte_limit_exceeded"


@pytest.mark.parametrize("elapsed,complete", [(5.0, True), (5.0001, False)])
def test_one_cooperative_deadline_including_original_read(
    saved_database, monkeypatch, elapsed, complete
):
    session, store = saved_database
    saved = acquire(session, store)
    clock = [0.0]
    monkeypatch.setattr(reader, "monotonic", lambda: clock[0])
    original = store.read

    def slow(*a, **kw):
        content = original(*a, **kw)
        clock[0] = elapsed
        return content

    monkeypatch.setattr(store, "read", slow)
    result = read(session, store, saved.source.id)
    assert result.search_complete == complete
    assert (result.statistics.total if result.statistics else None) == (17 if complete else None)


def test_summary_does_not_receive_a_fresh_time_budget(saved_database, monkeypatch):
    session, store = saved_database
    saved = acquire(session, store)
    clock = [0.0]
    monkeypatch.setattr(reader, "monotonic", lambda: clock[0])
    original = reader.summarize_completed_days

    def slow(history):
        result = original(history)
        clock[0] = 5.01
        return result

    monkeypatch.setattr(reader, "summarize_completed_days", slow)
    result = read(session, store, saved.source.id)
    assert not result.search_complete and result.statistics is None and result.cells == ()


def test_integrity_failure_and_unique_day_invariant_fail_closed(saved_database, monkeypatch):
    session, store = saved_database
    saved = acquire(session, store)
    good = read(session, store, saved.source.id)
    with pytest.raises(ValueError, match="duplicate"):
        summarize_completed_days(replace(good, cells=good.cells * 2))
    original = store.read
    monkeypatch.setattr(store, "read", lambda *a, **kw: original(*a, **kw) + b" ")
    bad = read(session, store, saved.source.id)
    assert not bad.search_complete and bad.statistics is None


def test_physical_snapshot_during_concurrent_correction_no_writes(saved_database):
    session, store = saved_database
    saved = acquire(session, store, 17)
    engine = session.bind
    session.rollback()
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    changed = False
    statements = []

    def concurrent(connection, cursor, statement, *args):
        nonlocal changed
        statements.append(statement.lstrip().split()[0].upper())
        if not changed and "FROM garmin_payload_observations" in statement:
            changed = True
            assert connection.connection.driver_connection.in_transaction
            with Session(engine) as writer:
                acquire(writer, store, 3, at=BOUNDARY + timedelta(hours=1))

    event.listen(engine, "before_cursor_execute", concurrent)
    try:
        before = read(session, store, saved.source.id)
    finally:
        event.remove(engine, "before_cursor_execute", concurrent)
    assert changed and before.statistics.total == 17
    session.rollback()
    assert read(session, store, saved.source.id).statistics.total == 3
    # Writer commands above are intentional; a separately captured read has no mutations.
    commands = []

    def capture(connection, cursor, statement, *args):
        commands.append(statement.lstrip().split()[0].upper())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        read(session, store, saved.source.id)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert not set(commands) & {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"}


@pytest.fixture(scope="module")
def bulk_history(tmp_path_factory):
    paths = prepare_runtime(
        Settings(data_dir=tmp_path_factory.mktemp("synthetic-all-time") / "profile")
    )
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    first = date(2080, 1, 1)
    received = datetime(2101, 1, 2, tzinfo=UTC)
    with Session(engine) as session:
        provider = repositories_for(session).providers.get_or_create(
            "garmin_connect", "Garmin", "wearable"
        )
        run = repositories_for(session).sync.create_run(
            provider_id=provider.id,
            stream_code="garmin_historical",
            requested_start=datetime(2080, 1, 1, tzinfo=UTC),
            requested_end=datetime(2101, 1, 1, tzinfo=UTC),
        )
        for i in range(4097):
            saved = acquire(
                session,
                store,
                i,
                day=first + timedelta(days=i),
                at=received + timedelta(seconds=i),
                run=run,
                status="running",
                receipt=True,
                commit=False,
            )
        source_id = saved.source.id
        repositories_for(session).sync.finish_run(run.id, status="succeeded")
        session.commit()
    yield engine, store, source_id, first, received
    engine.dispose()


@pytest.mark.parametrize("n", [4095, 4096, 4097])
def test_production_metadata_original_boundaries_without_clock_benchmark(
    bulk_history, monkeypatch, n
):
    engine, store, source_id, first, received = bulk_history
    # Deliberately isolate capacity semantics from elapsed-time tests above.
    monkeypatch.setattr(reader, "monotonic", lambda: 0.0)
    paths = []
    original = store.read
    monkeypatch.setattr(
        store, "read", lambda path, **kw: (paths.append(path), original(path, **kw))[1]
    )
    with Session(engine) as session:
        result = read(session, store, source_id, evaluated_at=received + timedelta(seconds=n - 1))
    assert reader.MAX_ARTIFACTS == 1000 and reader.MAX_ALL_TIME_ARTIFACTS == 4096
    if n <= 4096:
        assert result.search_complete
        assert (
            result.statistics.eligible_day_count == n
            and result.statistics.total == n * (n - 1) // 2
        )
        assert result.artifacts_examined == len(paths) == len(set(paths)) == n
        assert result.start_date == first and len(result.cells) == n
    else:
        assert not result.search_complete and result.reason == "provenance_limit_exceeded"
        assert result.statistics is None and not paths and result.cells == ()


def test_original_limit_does_not_change_window_entrypoint(bulk_history, monkeypatch):
    engine, store, source_id, first, received = bulk_history
    monkeypatch.setattr(reader, "monotonic", lambda: 0.0)
    with Session(engine) as session:
        result = reader.read_completed_steps_window(
            session,
            payload_store=store,
            source_id=source_id,
            start_date=first,
            end_date=first + timedelta(days=365),
            evaluated_at=received + timedelta(seconds=1100),
        )
        assert result.search_complete and result.artifacts_examined == 366
        assert result.contract_version == "garmin-completed-day-steps-moscow-v2"
        with pytest.raises(ValueError, match="366"):
            reader.read_completed_steps_window(
                session,
                payload_store=store,
                source_id=source_id,
                start_date=first,
                end_date=first + timedelta(days=366),
                evaluated_at=received,
            )


def test_accepted_large_integers_do_not_overflow_mean_or_display(saved_database):
    from healthcheck.web.statistics import format_steps_value

    session, store = saved_database
    huge = 10**400
    saved = acquire(session, store, huge)
    acquire(session, store, huge, day=DAY + timedelta(days=1), at=BOUNDARY + timedelta(days=1))
    history = read(session, store, saved.source.id)
    assert history.statistics.total == 2 * huge
    assert history.statistics.mean == Decimal(huge)
    assert history.statistics.record_dates == (DAY, DAY + timedelta(days=1))
    assert format_steps_value(history.statistics.mean).endswith(",0")
    assert format_steps_value(history.statistics.total).replace("\u202f", "") == str(2 * huge)


def test_all_time_metadata_delay_consumes_global_budget_before_originals(
    saved_database, monkeypatch
):
    session, store = saved_database
    saved = acquire(session, store, 17)
    source_id = saved.source.id
    clock = [0.0]
    monkeypatch.setattr(reader, "monotonic", lambda: clock[0])

    def slow_metadata(connection, cursor, statement, *args):
        if "FROM garmin_payload_observations" in statement:
            clock[0] = 5.001

    monkeypatch.setattr(store, "read", lambda *a, **k: pytest.fail("time guard ignored before I/O"))
    event.listen(session.bind, "before_cursor_execute", slow_metadata)
    try:
        result = read(session, store, source_id)
    finally:
        event.remove(session.bind, "before_cursor_execute", slow_metadata)
    assert not result.search_complete and result.statistics is None
    assert result.reason == "time_limit_exceeded" and result.artifacts_examined == 0


def test_all_time_default_end_uses_moscow_date_at_utc_date_boundary(saved_database):
    session, store = saved_database
    day = date(2099, 1, 4)
    saved = acquire(session, store, 10000, day=day, at=reader.completion_boundary(day))
    # Jan 4 UTC is already Jan 5 in Moscow; completed day is Jan 4, not Jan 3.
    result = read(
        session, store, saved.source.id, evaluated_at=datetime(2099, 1, 4, 22, tzinfo=UTC)
    )
    assert result.end_date == day and result.start_date == day
    assert result.statistics.total == 10000 and result.statistics.over_10000_day_count == 0
    assert result.statistics.longest_10000_streak == 1
