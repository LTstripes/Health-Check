"""Synthetic backend entry-point checks; no Owner profile, providers or UI."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.exc import InvalidRequestError

from healthcheck.analytics import period_summary_read as bounded
from healthcheck.analytics.cycling_source_discovery import (
    METRIC_CODE,
    CyclingSourceDiscoveryService,
)
from healthcheck.analytics.period_summary import PeriodSummaryService
from healthcheck.db.engine import session_scope
from healthcheck.db.models import GarminRecordMetric, GarminSource, GarminSourceRecord
from test_period_summary import END, START, _activity, _coverage
from test_sleep_account_cohort import _garmin, _google
from test_sleep_metrics import projection_database as projection_database


def discover(session, **window):
    return CyclingSourceDiscoveryService(session).discover(
        **(window or {"end_date": END, "days": 7}))


def garmin(packet):
    return packet["providers"][0]


def option(packet):
    return garmin(packet)["options"][0]


def reasons(cell):
    return {item["reason_code"]: item["count"] for item in cell["exclusions"]}


def extra_source(session, original):
    source = GarminSource(
        provider_id=original.provider_id, acquisition_source_id=original.acquisition_source_id,
        provider_code="garmin_connect", source_kind="synthetic",
        source_instance_id="synthetic-" + uuid4().hex,
    )
    session.add(source)
    session.flush()
    return source


def test_no_sources_and_google_not_collected_are_distinct(projection_database):
    session, paths = projection_database
    _google(session, paths, END)
    session.commit()
    packet = discover(session)
    assert packet["contract_version"] == "cycling-distance-source-discovery-v1"
    assert packet["selection_policy"] == "caller_owned_no_automatic_selection"
    assert packet["metric"] == {
        "canonical_metric_code": METRIC_CODE, "source_metric_code": "distance_meters",
        "unit": "meters", "conversion": "identity_v1", "activity_types": ["cycling"],
        "date_basis": "persisted_source_local_date",
    }
    left, right = packet["providers"]
    assert left["state"] == "source_missing"
    assert left["source_count"] == left["eligible_source_count"] == 0
    assert left["search"] == {"complete": True, "reason": None}
    assert right["state"] == "not_collected"
    assert right["eligible_source_count"] is None
    assert right["options"] == []
    assert packet["freshness"]["state"] == "unknown"


@pytest.mark.parametrize("window,start,end", [
    ({"end_date": END, "days": 7}, START, END),
    ({"end_date": END, "days": 30}, END - timedelta(days=29), END),
    ({"period_type": "calendar_year", "calendar_year": 2096},
     date(2096, 1, 1), date(2096, 12, 31)),
    ({"period_type": "trailing365", "end_date": END}, END - timedelta(days=364), END),
    ({"period_type": "year_to_date", "end_date": END}, date(END.year, 1, 1), END),
])
def test_windows_boundaries_and_public_summary_equivalence(projection_database, window, start, end):
    session, paths = projection_database
    _activity(session, paths, day=start, count=105, distance=2)
    _activity(session, paths, day=end, suffix="end", distance=0)
    _activity(session, paths, day=start - timedelta(days=1), suffix="before", distance=999)
    _activity(session, paths, day=end + timedelta(days=1), suffix="after", distance=999)
    _activity(session, paths, day=end, kind="road_biking", distance=999)
    session.commit()
    packet = discover(session, **window)
    result = option(packet)
    source_id = result["source_identity"]["source_id"]
    expected = PeriodSummaryService(session).build(**window, garmin_source_id=source_id)
    cell = expected["sides"][0]["metrics"][METRIC_CODE]
    assert result["summary"] == {**{k: cell[k] for k in result["summary"] if k != "search"},
                                 "search": {"complete": True, "reason": None}}
    assert result["summary"]["aggregation"]["value"] == 210
    assert result["summary"]["aggregation"]["eligible_count"] == 106
    assert result["summary"]["availability_counts"]["zero"] == 1
    assert result["summary"]["effective_dates"] == {"min_observed": str(start),
                                                  "max_observed": str(end)}
    assert packet["requested_window"]["inclusive_days"] == (end - start).days + 1
    assert garmin(packet)["state"] == "unique_eligible_source"
    assert "selected_source_id" not in garmin(packet)


@pytest.mark.parametrize("case", [
    "empty", "other_type", "sleep_only", "outside", "zero", "partial",
])
def test_metadata_and_other_metrics_do_not_prove_distance(projection_database, case):
    session, paths = projection_database
    if case == "sleep_only":
        _garmin(session, paths, END)
    else:
        _activity(session, paths, day=START - timedelta(days=1) if case == "outside" else START,
                  kind="tennis" if case == "other_type" else "cycling", distance=0)
    if case in {"empty", "partial"}:
        row = session.scalar(select(GarminSourceRecord))
        if case == "empty":
            row.garmin_source_id = extra_source(session, session.scalar(select(GarminSource))).id
        else:
            row.record_status = "partial"
    session.commit()
    packet = discover(session)
    result = (next(o for o in garmin(packet)["options"]
                   if not o["summary"]["observed_count"]) if case == "empty" else option(packet))
    cell = result["summary"]
    eligible = case in {"zero", "partial"}
    assert result["eligibility"]["has_eligible_values"] is eligible
    assert cell["aggregation"]["value"] == (0 if eligible else None)
    assert cell["availability_counts"]["zero"] == int(eligible)
    assert cell["availability_counts"]["partial"] == int(case == "partial")


@pytest.mark.parametrize("case,reason", [
    ("missing", "metric_missing"), ("null", "metric_null"), ("invalid", "metric_invalid"),
    ("wrong_unit", "metric_unit_mismatch"), ("negative", "negative_activity_summary"),
    ("infinite", "non_finite_value"),
    ("record_invalid", "record_invalid"), ("missing_type", "activity_type_missing"),
])
def test_ineligible_fields_retain_exact_counts_and_reasons(projection_database, case, reason):
    session, paths = projection_database
    _activity(session, paths)
    metric = session.scalar(select(GarminRecordMetric).where(
        GarminRecordMetric.metric_code == "distance_meters"))
    if case == "wrong_unit":
        metric.unit = "km"
    elif case in {"negative", "infinite"}:
        metric.value_number = -1 if case == "negative" else float("inf")
    elif case in {"missing", "null", "invalid"}:
        metric.state, metric.value_number = case, None
    elif case == "record_invalid":
        session.scalar(select(GarminSourceRecord)).record_status = "invalid"
    else:
        session.scalar(select(GarminSourceRecord)).activity_type = None
    session.commit()
    packet = discover(session)
    result = option(packet)
    assert result["eligibility"]["state"] == "no_eligible_values"
    assert reason in result["eligibility"]["reason_codes"]
    assert result["summary"]["aggregation"]["eligible_count"] == 0
    assert result["summary"]["aggregation"]["excluded_count"] == 1
    assert result["summary"]["aggregation"]["value"] is None
    assert reasons(result["summary"])[reason] == 1


@pytest.mark.parametrize("competitor", ["eligible", "zero", "ambiguous", "missing", "outside"])
def test_sources_stay_separate_and_competition_never_chooses(projection_database, competitor):
    session, paths = projection_database
    _activity(session, paths, distance=11)
    _activity(session, paths, attributed=False, suffix="second",
              day=START - timedelta(days=1) if competitor == "outside" else START,
              distance=0 if competitor == "zero" else 22,
              count=2 if competitor == "ambiguous" else 1)
    second = session.scalar(select(GarminSource).where(GarminSource.device_attributed.is_(False)))
    records = list(session.scalars(select(GarminSourceRecord).where(
        GarminSourceRecord.garmin_source_id == second.id)))
    if competitor == "ambiguous":
        records[1].external_record_id = records[0].external_record_id
    if competitor == "missing":
        metric = session.scalar(select(GarminRecordMetric).where(
            GarminRecordMetric.record_id == records[0].id,
            GarminRecordMetric.metric_code == "distance_meters"))
        metric.state, metric.value_number = "null", None
    session.commit()
    packet = discover(session)
    provider = garmin(packet)
    assert provider["source_count"] == 2
    assert len(provider["options"]) == 2
    assert provider["eligible_source_count"] == (2 if competitor in {"eligible", "zero"} else 1)
    assert provider["state"] == (
        "ambiguous_records" if competitor == "ambiguous" else
        "multiple_eligible_sources" if competitor in {"eligible", "zero"} else
        "unique_eligible_source")
    second_option = next(o for o in provider["options"]
                         if o["source_identity"]["source_id"] == second.id)
    assert second_option["eligibility"]["ambiguous_record_count"] == (
        2 if competitor == "ambiguous" else 0)
    assert "selected_source_id" not in provider
    assert "aggregation" not in provider


def test_ambiguity_with_usable_record_and_retirement_history(projection_database):
    session, paths = projection_database
    _activity(session, paths, count=2, distance=11)
    _activity(session, paths, suffix="independent", distance=7)
    rows = list(session.scalars(select(GarminSourceRecord)))
    rows[1].external_record_id = rows[0].external_record_id
    session.commit()
    packet = discover(session)
    assert garmin(packet)["state"] == "ambiguous_records"
    assert option(packet)["eligibility"]["has_eligible_values"] is True
    assert option(packet)["summary"]["aggregation"]["value"] == 7
    session.rollback()
    rows[0].projection_status = "retired"
    rows[0].retired_at = datetime(2099, 1, 9, tzinfo=UTC)
    rows[0].retire_reason = "authoritative_collection_replacement"
    session.commit()
    packet = discover(session)
    assert garmin(packet)["state"] == "unique_eligible_source"
    assert option(packet)["summary"]["aggregation"]["value"] == 18
    assert option(packet)["summary"]["availability_counts"]["retired"] == 1
    assert reasons(option(packet)["summary"])["retired:authoritative_collection_replacement"] == 1


@pytest.mark.parametrize("status", ["present", "confirmed_empty", "failed"])
def test_search_completeness_is_not_acquisition_completeness(projection_database, status):
    session, paths = projection_database
    _activity(session, paths)
    source = session.scalar(select(GarminSource))
    _coverage(session, source, status=status)
    session.commit()
    packet = discover(session)
    assert garmin(packet)["search"]["complete"] is True
    coverage = option(packet)["summary"]["coverage"]
    assert coverage["complete"] is (status == "present")
    assert coverage["state"] == {"present": "present", "confirmed_empty": "contradictory",
                                 "failed": "unavailable"}[status]
    session.rollback()
    extra_source(session, source)
    session.commit()
    packet = discover(session)
    assert all(o["summary"]["coverage"]["complete"] is False for o in garmin(packet)["options"])


def test_empty_distance_with_complete_coverage_is_null(projection_database):
    session, paths = projection_database
    _activity(session, paths, day=START - timedelta(days=1))
    _coverage(session, session.scalar(select(GarminSource)), status="confirmed_empty")
    session.commit()
    cell = option(discover(session))["summary"]
    assert cell["aggregation"]["value"] is None
    assert cell["aggregation"]["eligible_count"] == 0
    assert cell["availability_counts"]["zero"] == 0
    assert cell["coverage"]["complete"] is True
    assert cell["coverage"]["state"] == "confirmed_empty"


@pytest.mark.parametrize("cap,reason", [
    ("MAX_PERIOD_SOURCES", "source_inventory_limit_exceeded"),
    ("MAX_PERIOD_RECORDS", "candidate_record_limit_exceeded"),
    ("MAX_METRIC_ROWS", "ancillary_row_limit_exceeded"),
    ("MAX_COVERAGE_ROWS", "coverage_interval_limit_exceeded"),
    ("MAX_METADATA_ROWS", "ancillary_row_limit_exceeded"),
])
def test_overflow_suppresses_entire_discovery(projection_database, monkeypatch, cap, reason):
    session, paths = projection_database
    _activity(session, paths, count=2)
    source = session.scalar(select(GarminSource))
    extra_source(session, source)
    _coverage(session, source)
    _coverage(session, source, status="confirmed_empty")
    session.commit()
    monkeypatch.setattr(bounded, cap, 0 if cap == "MAX_METADATA_ROWS" else 1)
    provider = garmin(discover(session))
    assert provider["state"] == "search_incomplete"
    assert provider["search"] == {"complete": False, "reason": reason}
    assert provider["options"] == []
    assert provider["source_count"] is provider["eligible_source_count"] is None
    assert provider["ambiguous_source_count"] is None


def test_late_incomplete_search_never_returns_successful_prefix(projection_database, monkeypatch):
    session, paths = projection_database
    _activity(session, paths)
    source = session.scalar(select(GarminSource))
    extra_source(session, source)
    session.commit()
    original = PeriodSummaryService._activities
    called = []

    def fail_second(service, *args):
        called.append(args[0].id)
        if len(called) == 2:
            raise bounded.IncompletePeriodRead("time_budget_exceeded")
        return original(service, *args)

    monkeypatch.setattr(PeriodSummaryService, "_activities", fail_second)
    provider = garmin(discover(session))
    assert len(called) == 2
    assert provider["state"] == "search_incomplete"
    assert provider["options"] == []


def test_budget_restores_connection_policy_and_session_is_reusable(
    projection_database, monkeypatch,
):
    session, paths = projection_database
    _activity(session, paths)
    session.commit()
    driver = session.connection().connection.driver_connection
    before = driver.execute("PRAGMA busy_timeout").fetchone()[0]
    monkeypatch.setattr(bounded, "READ_BUDGET_SECONDS", -1)
    assert garmin(discover(session))["search"]["reason"] == "time_budget_exceeded"
    assert driver.execute("PRAGMA busy_timeout").fetchone()[0] == before
    monkeypatch.setattr(bounded, "READ_BUDGET_SECONDS", 2)
    assert garmin(discover(session))["state"] == "unique_eligible_source"


@pytest.mark.parametrize("window", [
    {}, {"end_date": END, "days": True}, {"end_date": END, "days": 8},
    {"end_date": date.max, "days": 7}, {"end_date": date.min, "days": 7},
    {"end_date": datetime(2099, 1, 8), "days": 7},
    {"period_type": "calendar_year", "calendar_year": True},
    {"period_type": "calendar_year", "calendar_year": 9999},
    {"period_type": "year_to_date", "end_date": END, "days": 7},
    {"period_type": "custom", "end_date": END},
])
def test_invalid_requests_fail_before_database_access(projection_database, window):
    session, _ = projection_database
    statements = []
    def listener(*args):
        statements.append(args[2])
    event.listen(session.bind, "before_cursor_execute", listener)
    try:
        with pytest.raises(ValueError):
            CyclingSourceDiscoveryService(session).discover(**window)
        assert statements == []
    finally:
        event.remove(session.bind, "before_cursor_execute", listener)


def test_pending_changes_rejected_without_flush(projection_database):
    session, paths = projection_database
    _activity(session, paths)
    session.commit()
    row = session.scalar(select(GarminSourceRecord))
    row.record_status = "invalid"
    with pytest.raises(InvalidRequestError, match="no pending"):
        discover(session)
    assert row in session.dirty


def test_read_only_queries_and_one_snapshot_without_unrelated_reads(projection_database):
    session, paths = projection_database
    _activity(session, paths)
    _google(session, paths, END)
    session.commit()
    session.expire_all()
    statements = []
    def listener(*args):
        statements.append(args[2].lower())
    event.listen(session.bind, "before_cursor_execute", listener)
    try:
        packet = discover(session)
        assert packet["providers"][0]["search"]["complete"]
        assert sum(s == "begin" for s in statements) == 1
        assert all(s.startswith(("begin", "select")) for s in statements)
        assert not any(any(name in s for name in (
            "google_", "garmin_sleep", "context_", "garmin_raw_payloads")) for s in statements)
        assert not session.new and not session.dirty and not session.deleted
        assert session.connection().connection.driver_connection.in_transaction
    finally:
        event.remove(session.bind, "before_cursor_execute", listener)


def test_discovery_is_coherent_across_separate_wal_writer(projection_database, monkeypatch):
    session, paths = projection_database
    _activity(session, paths, distance=11)
    session.commit()
    original = PeriodSummaryService._activities
    commits = []

    def write_after_inventory(service, *args):
        with session_scope(session.bind) as writer:
            writer.execute(update(GarminRecordMetric).where(
                GarminRecordMetric.metric_code == "distance_meters").values(value_number=22))
        commits.append(True)
        return original(service, *args)

    monkeypatch.setattr(PeriodSummaryService, "_activities", write_after_inventory)
    packet = discover(session)
    assert commits == [True]
    assert option(packet)["summary"]["aggregation"]["value"] == 11
    session.rollback()
    monkeypatch.setattr(PeriodSummaryService, "_activities", original)
    assert option(discover(session))["summary"]["aggregation"]["value"] == 22


def test_repeated_payload_is_one_saved_session(projection_database):
    session, paths = projection_database
    _activity(session, paths, distance=11)
    _activity(session, paths, distance=11)
    session.commit()
    cell = option(discover(session))["summary"]
    assert cell["aggregation"]["value"] == 11
    assert cell["aggregation"]["eligible_count"] == 1
    assert cell["availability_counts"]["candidate"] == 1


def test_wrong_provider_metadata_does_not_enter_inventory(projection_database):
    session, paths = projection_database
    _activity(session, paths)
    source = session.scalar(select(GarminSource))
    session.add(GarminSource(
        provider_id=source.provider_id, acquisition_source_id=source.acquisition_source_id,
        source_kind="synthetic", provider_code="unrelated_provider",
        source_instance_id="synthetic-other-provider"))
    session.commit()
    assert garmin(discover(session))["source_count"] == 1
