"""Bounded synthetic annual contracts; no providers or Owner runtime."""

import sqlite3
from datetime import UTC, date, datetime, timedelta
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import event, insert, select, update

from healthcheck.analytics import period_summary_read as bounded
from healthcheck.analytics.period_summary import SLEEP_CODE, PeriodSummaryService
from healthcheck.analytics.sleep_metrics import _load_google_sleep_record_side
from healthcheck.analytics.sleep_pairing import ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS
from healthcheck.db.models import (
    CoverageInterval,
    GarminPayloadObservation,
    GarminRecordMetric,
    GarminSleepRecord,
    GarminSource,
    GarminSourceRecord,
    GoogleNormalizationAttempt,
    GoogleRecordMetric,
    GoogleRecordSourceEvidence,
    GoogleSleepRecord,
    GoogleSource,
    GoogleSourceRecord,
)
from test_period_summary import _activity, _coverage
from test_sleep_account_cohort import _garmin, _google
from test_sleep_metrics import projection_database as projection_database

END = date(2096, 12, 31)
START = date(2096, 1, 1)


def annual(session, **kwargs):
    return PeriodSummaryService(session).build(
        period_type="calendar_year", calendar_year=2096, **kwargs
    )


def cell(packet, code=SLEEP_CODE, side=0):
    return packet["sides"][side]["metrics"][code]


def clone_rows(session, model, stream, count, *, daily=False, children=()):
    """Bulk typed fixture rows with unique identities, reusing synthetic evidence."""
    table = model.__table__
    original = dict(
        session.execute(select(table).where(table.c.stream_code == stream)).mappings().one()
    )
    snapshots = [
        (
            m.__table__,
            list(
                session.execute(
                    select(m.__table__).where(m.__table__.c.record_id == original["id"])
                ).mappings()
            ),
        )
        for m in children
    ]
    rows, descendants = [], {t.name: [] for t, _ in snapshots}
    for offset in range(1, count):
        identity = str(uuid4())
        row = dict(original, id=identity, idempotency_key=identity, external_record_id=identity)
        if "record_identity_key" in row:
            row["record_identity_key"] = identity
        if daily:
            row["source_local_date"] = original["source_local_date"] + timedelta(days=offset)
        rows.append(row)
        for t, values in snapshots:
            for value in values:
                child = dict(value, record_id=identity)
                if "id" in child:
                    child["id"] = str(uuid4())
                if daily and "wake_date" in child:
                    child["wake_date"] += timedelta(days=offset)
                descendants[t.name].append(child)
    if rows:
        session.execute(insert(table), rows)
    for t, _ in snapshots:
        if descendants[t.name]:
            session.execute(insert(t), descendants[t.name])
    session.commit()


@pytest.mark.parametrize(
    "selection,start,end,count",
    [
        ({"period_type": "trailing365", "end_date": END}, date(2096, 1, 2), END, 365),
        ({"period_type": "calendar_year", "calendar_year": 2096}, START, END, 366),
        (
            {"period_type": "calendar_year", "calendar_year": 2095},
            date(2095, 1, 1),
            date(2095, 12, 31),
            365,
        ),
        (
            {"period_type": "year_to_date", "end_date": date(2096, 2, 29)},
            START,
            date(2096, 2, 29),
            60,
        ),
    ],
)
def test_boundaries_keep_requested_sparse_source_specific_dates(
    projection_database,
    selection,
    start,
    end,
    count,
):
    session, paths = projection_database
    for day in (start - timedelta(days=1), start, end, end + timedelta(days=1)):
        _garmin(session, paths, day, seconds=0 if day == start else 3600)
    _google(session, paths, start, main="true", nap="false", minutes="0")
    session.commit()
    packet = PeriodSummaryService(session).build(**selection)
    assert packet["requested_window"] == {
        "start_date": str(start),
        "end_date": str(end),
        "inclusive_days": count,
        "period_type": selection["period_type"],
    }
    left, right = cell(packet), cell(packet, side=1)
    assert left["aggregation"]["value"] == 1800
    assert left["aggregation"]["eligible_count"] == 2
    assert left["aggregation"]["denominator"] == "eligible_saved_nights"
    assert left["availability_counts"]["zero"] == 1
    assert left["missing_day_count"] == count - 2
    assert right["aggregation"]["value"] == 0
    assert right["effective_dates"] == {"min_observed": str(start), "max_observed": str(start)}
    assert right["source_unit"] == "min" and right["conversion"] == "minutes_times_60_v1"
    assert not right["coverage"]["complete"]
    assert packet["deltas"][SLEEP_CODE]["value"] is None


@pytest.mark.parametrize(
    "selection",
    [
        {"period_type": "all_history", "end_date": END},
        {"period_type": "calendar_year", "calendar_year": True},
        {"period_type": "calendar_year", "calendar_year": 9999},
        {"period_type": "calendar_year", "calendar_year": 2096, "end_date": END},
        {"period_type": "trailing365", "end_date": END, "days": 365},
        {"period_type": "trailing365", "end_date": date.min},
        {"period_type": "year_to_date", "end_date": date.max},
        {"period_type": "year_to_date", "end_date": END, "calendar_year": 2095},
    ],
)
def test_invalid_requests_fail_before_reads(projection_database, selection):
    session, _ = projection_database
    statements = []

    def capture(*args):
        statements.append(args[2])

    event.listen(session.get_bind(), "before_cursor_execute", capture)
    try:
        with pytest.raises((ValueError, OverflowError)):
            PeriodSummaryService(session).build(**selection)
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", capture)
    assert statements == []


def test_empty_annual_search_is_not_zero_or_never_collected(projection_database):
    session, paths = projection_database
    _google(session, paths, date(2095, 12, 31), main="true", nap="false")
    session.commit()
    packet = annual(session)
    right = cell(packet, side=1)
    assert right["state"] == "no_eligible_values"
    assert right["aggregation"]["value"] is None
    assert right["effective_dates"] == {"min_observed": None, "max_observed": None}
    assert right["missing_day_count"] == 366
    assert right["coverage"]["state"] == "unestablished"


def test_annual_matches_legacy_fields_with_corrections_roles_and_date_only(projection_database):
    session, paths = projection_database
    for day, name, main, nap, minutes in (
        (END, "main", "true", "false", "0"),
        (END, "nap", "false", "true", "60"),
        (END, "uncertain", "missing", "missing", "120"),
        (END - timedelta(days=1), "retired", "true", "false", "60"),
        (END - timedelta(days=1), "corrected", "true", "false", "120"),
        (END - timedelta(days=2), "conflict-one", "true", "false", "60"),
        (END - timedelta(days=2), "conflict-missing-scalar", "true", "false", "120"),
    ):
        _google(session, paths, day, name=name, main=main, nap=nap, minutes=minutes)
    records = list(
        session.scalars(
            select(GoogleSourceRecord).order_by(
                GoogleSourceRecord.created_at, GoogleSourceRecord.id
            )
        )
    )
    retired = next(r for r in records if r.external_record_id == "retired")
    retired.projection_status = "retired"
    retired.retired_at = datetime(2097, 1, 1, tzinfo=UTC)
    retired.retire_reason = "superseded_logical_session"
    missing = next(r for r in records if r.external_record_id == "conflict-missing-scalar")
    metric = session.scalar(
        select(GoogleRecordMetric).where(
            GoogleRecordMetric.record_id == missing.id,
            GoogleRecordMetric.metric_code == "sleep_summary_minutes_asleep",
        )
    )
    metric.state, metric.value_text, metric.value_number = "null", None, None
    for r in records:
        r.temporal_precision, r.source_timestamp_utc = "date", None
        r.source_local_date = END - timedelta(days=3)
    session.commit()
    before = cell(PeriodSummaryService(session).build(end_date=END, days=7), side=1)
    after = cell(annual(session), side=1)
    for field in (
        "aggregation",
        "observed_count",
        "observed_day_count",
        "availability_counts",
        "effective_dates",
        "exclusions",
        "snapshot_evidence",
    ):
        assert after[field] == before[field]
    assert after["aggregation"]["eligible_count"] == 2
    assert after["aggregation"]["value"] == 3600
    assert after["availability_counts"]["retired"] == 1
    assert {e["reason_code"] for e in after["exclusions"]} >= {
        "google_nap_only",
        "google_explicit_main_preferred",
        "ambiguous_google_main",
    }


@pytest.mark.parametrize("count", [4095, 4096, 4097])
def test_actual_activity_capacity_boundaries_preserve_independent_sleep(projection_database, count):
    session, paths = projection_database
    _activity(session, paths, day=START, attributed=False, distance=2)
    clone_rows(session, GarminSourceRecord, "activity", count, children=(GarminRecordMetric,))
    _garmin(session, paths, END)
    session.commit()
    packet = annual(session)
    activity = cell(packet, "activity_session_count")
    if count <= 4096:
        assert activity["aggregation"]["value"] == count
        assert cell(packet, "cycling_distance_meters")["aggregation"]["value"] == count * 2
    else:
        assert_incomplete(activity, "candidate_record_limit_exceeded")
    assert cell(packet)["aggregation"]["value"] == 28800


def assert_incomplete(value, reason):
    assert value["state"] == "search_incomplete"
    assert value["search"] == {"complete": False, "reason": reason}
    assert value["aggregation"]["value"] is None
    assert value["aggregation"]["denominator"] is None
    assert value["aggregation"]["eligible_count"] is None
    assert value["missing_dates"] is None and value["missing_day_count"] is None
    assert not value["coverage"]["complete"]


@pytest.mark.parametrize("count", [199, 200, 201])
def test_actual_night_group_boundaries_never_select_prefix(projection_database, count):
    session, paths = projection_database
    _garmin(session, paths, START)
    clone_rows(
        session,
        GarminSourceRecord,
        "sleep",
        count,
        children=(GarminSleepRecord, GarminRecordMetric),
    )
    _garmin(session, paths, END, seconds=3600)
    _google(session, paths, END, main="true", nap="false", minutes="60")
    session.commit()
    packet = annual(session)
    if count <= 200:
        assert cell(packet)["aggregation"]["eligible_count"] == 1
        assert cell(packet)["aggregation"]["value"] == 3600
    else:
        assert_incomplete(cell(packet), "night_group_limit_exceeded")
        assert packet["deltas"][SLEEP_CODE]["value"] is None
    assert cell(packet, side=1)["aggregation"]["value"] == 3600


def test_coverage_overflow_is_incomplete_without_erasing_other_provider(
    projection_database,
    monkeypatch,
):
    session, paths = projection_database
    _garmin(session, paths, END)
    _google(session, paths, END, main="true", nap="false")
    source = session.scalar(select(GarminSource))
    _coverage(session, source, surface="sleep")
    for row in session.scalars(select(CoverageInterval)):
        row.interval_start = datetime(2096, 1, 1, tzinfo=UTC)
        row.interval_end = datetime(2097, 1, 1, tzinfo=UTC)
    session.flush()
    row = dict(session.execute(select(CoverageInterval.__table__)).mappings().one())
    session.execute(insert(CoverageInterval), [dict(row, id=str(uuid4()))])
    session.commit()
    monkeypatch.setattr(bounded, "MAX_COVERAGE_ROWS", 1)
    packet = annual(session)
    assert_incomplete(cell(packet), "coverage_interval_limit_exceeded")
    assert cell(packet, side=1)["aggregation"]["value"] == 24600


def test_ancillary_observation_overflow_is_not_a_partial_mean(projection_database, monkeypatch):
    session, paths = projection_database
    _garmin(session, paths, END)
    template = dict(session.execute(select(GarminPayloadObservation.__table__)).mappings().one())
    session.execute(
        insert(GarminPayloadObservation),
        [dict(template, id=str(uuid4()), observation_key=str(uuid4()))],
    )
    _google(session, paths, END, main="true", nap="false")
    session.commit()
    monkeypatch.setattr(bounded, "MAX_METADATA_ROWS", 1)
    packet = annual(session)
    assert_incomplete(cell(packet), "ancillary_row_limit_exceeded")
    assert cell(packet, side=1)["aggregation"]["value"] == 24600


def test_cpu_timeout_preserves_complete_activity_and_cleans_guard(projection_database, monkeypatch):
    session, paths = projection_database
    _activity(session, paths, day=START, attributed=False)
    _garmin(session, paths, END)
    session.commit()
    clock = [0.0]
    monkeypatch.setattr(bounded, "monotonic", lambda: clock[0])
    original = bounded.PeriodReadBudget.night

    def expire(self, *args):
        clock[0] = 3.0
        return original(self, *args)

    monkeypatch.setattr(bounded.PeriodReadBudget, "night", expire)
    packet = annual(session)
    assert cell(packet, "activity_session_count")["aggregation"]["value"] == 1
    assert_incomplete(cell(packet), "time_budget_exceeded")
    # The expired handler must be removed even on failure; caller owns its transaction.
    assert (
        session.connection()
        .exec_driver_sql(
            "WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<10000) "
            "SELECT max(x) FROM n"
        )
        .scalar()
        == 10000
    )
    assert not session.new and not session.dirty and not session.deleted


def test_sqlite_interruption_becomes_incomplete_and_handler_is_removed(
    projection_database,
    monkeypatch,
):
    session, _ = projection_database
    clock = [0.0]
    monkeypatch.setattr(bounded, "monotonic", lambda: clock[0])

    def expire(conn, cursor, statement, parameters, context, executemany):
        if "garmin_sources" in statement:
            clock[0] = 3.0
            return (
                "WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL "
                "SELECT x+1 FROM n WHERE x<10000) SELECT max(x) FROM n", (),
            )
        return statement, parameters

    errors = []

    def capture_error(context):
        errors.append(getattr(context.original_exception, "sqlite_errorcode", None))

    event.listen(session.get_bind(), "before_cursor_execute", expire, retval=True)
    event.listen(session.get_bind(), "handle_error", capture_error)
    try:
        packet = annual(session)
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", expire)
        event.remove(session.get_bind(), "handle_error", capture_error)
    assert errors == [9]
    assert_incomplete(cell(packet), "time_budget_exceeded")
    assert_incomplete(cell(packet, side=1), "time_budget_exceeded")
    assert session.connection().exec_driver_sql("SELECT 42").scalar() == 42


def test_full_leap_year_fits_budget_and_queries_grow_by_batches(projection_database):
    session, paths = projection_database
    _garmin(session, paths, START)
    _google(session, paths, START, main="true", nap="false", minutes="60")
    clone_rows(
        session,
        GarminSourceRecord,
        "sleep",
        366,
        daily=True,
        children=(GarminSleepRecord, GarminRecordMetric),
    )
    clone_rows(
        session,
        GoogleSourceRecord,
        "sleep",
        366,
        daily=True,
        children=(GoogleSleepRecord, GoogleRecordMetric, GoogleRecordSourceEvidence),
    )
    statements = []

    def capture(*args):
        if args[2].lstrip().upper().startswith("SELECT"):
            statements.append(args[2])

    event.listen(session.get_bind(), "before_cursor_execute", capture)
    counts = []
    try:
        for end, expected in ((START, 1), (START + timedelta(days=30), 31), (END, 366)):
            statements.clear()
            started = perf_counter()
            packet = PeriodSummaryService(session).build(period_type="year_to_date", end_date=end)
            elapsed = perf_counter() - started
            for side, mean in ((0, 28800), (1, 3600)):
                value = cell(packet, side=side)
                assert value["aggregation"]["value"] == mean
                assert value["aggregation"]["eligible_count"] == expected
                assert value["missing_day_count"] == 0
                assert not value["coverage"]["complete"]
            counts.append(len(statements))
            print(
                f"annual synthetic {expected} nights/provider: "
                f"{len(statements)} SQL, {elapsed:.3f}s"
            )
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", capture)
    assert counts[0] == counts[1]
    assert counts[2] <= counts[1] + 12
    assert counts[2] < 50


def test_exact_source_selection_and_missing_wake_do_not_pool(projection_database):
    session, paths = projection_database
    _google(session, paths, START, source="synthetic-one", main="true", nap="false")
    _google(session, paths, END, source="synthetic-two", main="true", nap="false")
    # Locate by typed wake date because source-local date may differ.
    typed = session.scalar(select(GoogleSleepRecord).where(GoogleSleepRecord.wake_date == END))
    record = session.get(GoogleSourceRecord, typed.record_id)
    typed.wake_date = None
    record.source_local_date = END
    session.commit()
    assert annual(session)["sides"][1]["state"] == "selection_required"
    packet = annual(session, google_source_id=record.google_source_id)
    value = cell(packet, side=1)
    assert packet["sides"][1]["source_identity"]["source_id"] == record.google_source_id
    assert value["aggregation"]["value"] is None
    assert value["observed_count"] == 1
    assert {r["reason_code"] for r in value["exclusions"]} == {"wake_date_missing"}


@pytest.mark.parametrize("ancillary", ["metrics", "normalization_attempts"])
def test_google_ancillary_caps_keep_independent_garmin(projection_database, monkeypatch, ancillary):
    session, paths = projection_database
    _garmin(session, paths, END)
    _google(session, paths, END, main="true", nap="false")
    if ancillary == "normalization_attempts":
        row = dict(session.execute(select(GoogleNormalizationAttempt.__table__)).mappings().one())
        session.execute(insert(GoogleNormalizationAttempt), [
            dict(row, id=str(uuid4()), attempt_key=str(uuid4())),
        ])
        monkeypatch.setattr(bounded, "MAX_METADATA_ROWS", 1)
    else:
        monkeypatch.setattr(bounded, "MAX_METRIC_ROWS", 3)
    session.commit()
    packet = annual(session)
    assert_incomplete(cell(packet, side=1), "ancillary_row_limit_exceeded")
    assert cell(packet)["aggregation"]["value"] == 28800


def test_source_inventory_overflow_retains_requested_identity(projection_database, monkeypatch):
    session, paths = projection_database
    _garmin(session, paths, END)
    _google(session, paths, END, source="synthetic-one")
    _google(session, paths, END, source="synthetic-two")
    selected = session.scalar(select(GoogleSourceRecord.google_source_id))
    session.commit()
    monkeypatch.setattr(bounded, "MAX_PERIOD_SOURCES", 1)
    packet = annual(session, google_source_id=selected)
    assert_incomplete(cell(packet, side=1), "source_inventory_limit_exceeded")
    assert packet["sides"][1]["requested_source_id"] == selected
    assert cell(packet)["aggregation"]["value"] == 28800


def test_timeout_between_activity_cells_preserves_completed_cells(projection_database, monkeypatch):
    session, paths = projection_database
    _activity(session, paths, day=START, attributed=False)
    session.commit()
    clock, reads = [0.0], [0]
    monkeypatch.setattr(bounded, "monotonic", lambda: clock[0])
    original = bounded.PeriodReadBudget.snapshot_evidence
    def expire(self, records, **kwargs):
        if records:
            reads[0] += 1
            if reads[0] == 3:
                clock[0] = 3.0
        return original(self, records, **kwargs)
    monkeypatch.setattr(bounded.PeriodReadBudget, "snapshot_evidence", expire)
    packet = annual(session)
    assert cell(packet, "activity_session_count")["aggregation"]["value"] == 1
    assert cell(packet, "activity_type_counts")["aggregation"]["value"] == {"cycling": 1}
    assert_incomplete(cell(packet, "cycling_distance_meters"), "time_budget_exceeded")


def test_sqlite_lock_wait_obeys_budget_and_restores_busy_timeout(projection_database):
    session, paths = projection_database
    connection = session.connection()
    # WAL permits readers during BEGIN EXCLUSIVE; use a disposable rollback-journal
    # fixture to exercise an actual blocking read, without touching Owner storage.
    assert connection.exec_driver_sql("PRAGMA journal_mode=DELETE").scalar() == "delete"
    previous = connection.exec_driver_sql("PRAGMA busy_timeout").scalar()
    other = sqlite3.connect(paths.database)
    try:
        other.execute("BEGIN EXCLUSIVE")
        packet = annual(session)
    finally:
        other.rollback()
        other.close()
    assert_incomplete(cell(packet), "time_budget_exceeded")
    assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == previous
    assert connection.exec_driver_sql("SELECT 42").scalar() == 42


def test_annual_sources_share_snapshot_and_next_read_sees_correction(projection_database):
    session, paths = projection_database
    _garmin(session, paths, END)
    _google(session, paths, END, main="true", nap="false", minutes="60")
    session.commit()
    changed = [False]
    engine = session.get_bind()

    def correct(conn, cursor, statement, *args):
        if not changed[0] and "google_source_records" in statement:
            changed[0] = True
            with engine.begin() as writer:
                writer.execute(update(GoogleRecordMetric).where(
                    GoogleRecordMetric.metric_code == "sleep_summary_minutes_asleep"
                ).values(value_number=120, value_text="120"))

    event.listen(engine, "before_cursor_execute", correct)
    try:
        packet = annual(session)
    finally:
        event.remove(engine, "before_cursor_execute", correct)
    assert changed[0]
    assert cell(packet, side=1)["aggregation"]["value"] == 3600
    session.rollback()
    assert cell(annual(session), side=1)["aggregation"]["value"] == 7200


def test_batched_evidence_matches_original_normalization_and_locator(projection_database):
    session, paths = projection_database
    _google(session, paths, END, main="true", nap="false")
    session.commit()
    record = session.scalar(select(GoogleSourceRecord))
    source = session.scalar(select(GoogleSource))
    previous = _load_google_sleep_record_side(
        session, record.id, cohort=ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS,
    )
    with bounded.PeriodReadBudget(session) as reader:
        current = reader.sleep_sessions(source, [record])[record.id]
    assert current.evidence.as_dict() == previous.evidence.as_dict()
