"""Synthetic #393 period arithmetic, source semantics and bounded completeness."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from fractions import Fraction

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import InvalidRequestError, OperationalError

from healthcheck import saved_rhr_period as module
from healthcheck.db.models import GarminRecordMetric
from healthcheck.garmin.persistence import GarminSourceRepository
from healthcheck.google.persistence import GoogleSourceRepository
from healthcheck.saved_rhr_period import SavedRhrPeriodQuery, read_saved_rhr_period
from test_google_daily_vitals import _family_identity
from test_saved_values import (
    DAY,
    GARMIN_IDENTITY,
    NOW,
    _copy,
    _query,
    _read,
    _seed,
)
from test_saved_values import (
    saved_engine as saved_engine,
)
from test_saved_values import (
    stored as stored,
)


def _period(stored, *, days=7, **kwargs):
    query = _query(stored)
    values = dict(provider_code=query.provider_code, metric_code=query.metric_code,
                  source_id=query.source_id, requested_start_date=DAY - timedelta(days=days - 1),
                  requested_end_date=DAY, evaluated_at_utc=NOW, evaluation_local_date=DAY)
    values.update(kwargs)
    stored[0].flush()
    return read_saved_rhr_period(stored[0], SavedRhrPeriodQuery(**values))


@pytest.mark.parametrize("days", [1, 7, 30, 90, 365, 400])
def test_exact_period_reads_all_distinct_days_beyond_latest_reader_caps(stored, days):
    for offset in range(days):
        _seed(stored, day=DAY - timedelta(days=offset), value=50 + offset % 3,
              external=f"synthetic-period-{offset}")
    result = _period(stored, days=days)
    mean = Fraction(sum(50 + offset % 3 for offset in range(days)), days)
    assert result["eligible_day_count"] == days and result["excluded_day_count"] == 0
    assert result["mean_exact"]["numerator"] == str(mean.numerator)
    assert result["mean_exact"]["denominator"] == str(mean.denominator)
    assert result["search"]["complete"] and result["search"]["groups_examined"] == days
    assert len(result["observations"]) == days
    assert result["observations"][0]["source_local_date"] == (
        DAY - timedelta(days=days - 1)).isoformat()
    # Last-value contract is still a single observation, not this period DTO.
    latest = _read(stored, mode="explicit_period",
                   requested_start_date=DAY - timedelta(days=days - 1))
    assert latest.observation.value == 50 and latest.search.groups_examined == 1


@pytest.mark.parametrize("values,display,numerator,denominator", [
    ([60, 61], 61, "121", "2"), ([60.49, 60.5], 60, "12099", "200"),
    ([60.4, 60.6], 61, "121", "2"), ([60.1, 60.2, 60.3], 60, "301", "5"),
    ([0], 0, "0", "1"), ([61.5], 62, "123", "2"),
    ([0, 61], 31, "61", "2"), ([60, 60, 61], 60, "181", "3"),
    ([-1.5], -2, "-3", "2"), ([-0.5], -1, "-1", "2"),
    ([-1.49], -1, "-149", "100"), ([-1.51], -2, "-151", "100"),
    ([-1.49, -1.5], -1, "-299", "200"), ([-0.4, -0.6], -1, "-1", "2"),
    ([1.5], 2, "3", "2"),
])
def test_final_only_rounding_exact_fraction_and_sparse_denominator(
    stored, values, display, numerator, denominator,
):
    for index, value in enumerate(values):
        _seed(stored, day=DAY - timedelta(days=index * 2), value=value,
              external=f"synthetic-sparse-{index}")
    result = _period(stored)
    assert result["mean_display"] == display
    assert result["mean_exact"]["numerator"] == numerator
    assert result["mean_exact"]["denominator"] == denominator
    assert result["eligible_day_count"] == len(values)
    assert result["excluded_day_count"] == 7 - len(values)
    assert result["acquisition_coverage_state"] == "unknown"
    assert result["origin_state"] == "unknown" and result["snapshot_as_of"] is None


def test_negative_tie_is_reachable_from_saved_observation(stored):
    record, metric = _seed(stored, value=-1.5)
    assert metric.state == "value" and metric.value_number == -1.5
    latest = _read(stored)
    assert latest.state == "exact" and latest.observation.record_id == record.id
    assert latest.observation.value == -1.5
    result = _period(stored, days=1)
    assert result["state"] == "observed" and result["eligible_day_count"] == 1
    assert result["observations"][0]["value"] == -1.5
    assert result["mean_exact"]["numerator"] == "-3"
    assert result["mean_exact"]["denominator"] == "2"
    assert result["mean_display"] == -2


@pytest.mark.parametrize("case", [
    "missing", "null", "invalid", "wrong_unit", "nonfinite", "retired", "future_stamp",
    "future_day", "conflict", "partial", "corrected", "undated", "outside", "no_row",
])
def test_excludes_whole_ineligible_day_without_latest_substitution(stored, case):
    _seed(stored, day=DAY - timedelta(days=3), value=50, external="synthetic-old")
    record, metric = _seed(stored, value=70)
    if case in {"missing", "null", "invalid"}:
        metric.state, metric.value_number = case, None
    elif case == "wrong_unit":
        metric.unit = "ms"
    elif case == "nonfinite":
        metric.value_number = float("inf")
    elif case == "retired":
        record.projection_status, record.retired_at, record.retire_reason = "retired", NOW, "test"
    elif case == "future_stamp":
        record.source_timestamp_utc = NOW + timedelta(seconds=1)
    elif case == "future_day":
        record.source_local_date = DAY + timedelta(days=1)
    elif case == "conflict":
        _copy(stored, record, metric)
    elif case == "partial":
        record.record_status = "partial"
    elif case == "corrected":
        metric.value_number = 60
    elif case == "undated":
        record.source_local_date = None
    elif case == "outside":
        record.source_local_date = DAY - timedelta(days=7)
    elif case == "no_row":
        stored[0].delete(metric)
    result = _period(stored, requested_end_date=DAY + timedelta(days=1))
    count = 2 if case in {"partial", "corrected"} else 1
    assert result["eligible_day_count"] == count
    assert result["mean_display"] == (
        60 if case == "partial" else 55 if case == "corrected" else 50)
    assert result["excluded_day_count"] == 8 - count
    assert len([e for e in result["exclusions"] if e["source_local_date"]]) == 8 - count
    if case == "conflict":
        assert any(e["reason"] == "ambiguous_same_date_records" and e["candidate_count"] == 2
                   for e in result["exclusions"])
    if case == "undated":
        assert any(e["source_local_date"] is None and e["candidate_count"] is None
                   for e in result["exclusions"])


@pytest.mark.parametrize("stamps,expected_count,expected_mean", [
    ((None, None), 0, None), ((NOW, NOW), 0, None),
    ((NOW - timedelta(hours=1), NOW), 1, 80),
    ((NOW, NOW - timedelta(hours=1)), 1, 50),
    ((None, NOW), 0, None),
])
@pytest.mark.parametrize("stored", ["garmin_connect"], indirect=True)
def test_garmin_same_day_revision_is_one_value_or_ambiguous(stored, stamps, expected_count,
                                                         expected_mean):
    record, metric = _seed(stored, value=50)
    record.source_timestamp_utc = stamps[0]
    duplicate = _copy(stored, record, metric, source_timestamp_utc=stamps[1],
                      surface_code="resting_heart_rate")
    stored[0].flush()
    for row in stored[0].scalars(select(GarminRecordMetric).where(
        GarminRecordMetric.record_id == duplicate.id,
    )):
        row.value_number = 80
    result = _period(stored)
    assert result["eligible_day_count"] == expected_count
    assert result["mean_display"] == expected_mean


def test_zero_eligible_has_no_number_and_does_not_prove_never_collected(stored):
    result = _period(stored)
    assert result["state"] == "no_eligible_in_period"
    assert result["eligible_day_count"] == 0 and result["excluded_day_count"] == 7
    assert result["mean_display"] is None and result["mean_exact"] is None
    assert result["observations"] == [] and result["last_observation"] is None


def test_401_does_not_read_or_silently_truncate(stored, monkeypatch):
    def forbid(*_args, **_kwargs):
        raise AssertionError("too-long period must not query storage")
    monkeypatch.setattr(stored[0], "scalars", forbid)
    monkeypatch.setattr(stored[0], "get", forbid)
    result = _period(stored, days=401)
    assert result["state"] == "period_too_long"
    assert result["query"]["requested_start_date"] == (DAY - timedelta(days=400)).isoformat()
    assert result["requested_day_count"] == 401
    assert result["mean_display"] is None and result["eligible_day_count"] is None


@pytest.mark.parametrize("cap,expected", [(1, "period_record_cap"), (2, None)])
def test_period_cap_plus_one_blocks_the_mean_of_a_valid_prefix(stored, cap, expected):
    _seed(stored, value=60)
    _seed(stored, day=DAY - timedelta(days=1), value=80, external="synthetic-cap-old")
    result = _period(stored, max_candidate_records=cap)
    assert result["reason"] == expected
    assert result["mean_display"] == (None if expected else 70)
    assert result["search"]["records_examined"] == 2
    assert result["search"]["complete"] == (expected is None)


def test_group_cap_blocks_whole_period_even_after_an_eligible_newer_day(stored):
    record, metric = _seed(stored, day=DAY - timedelta(days=1), value=60)
    _copy(stored, record, metric)
    _seed(stored, value=80, external="synthetic-new")
    result = _period(stored, max_records_per_day=1)
    assert result["reason"] == "candidate_group_cap" and result["mean_display"] is None
    assert result["eligible_day_count"] is None and result["observations"] == []
    assert not result["search"]["complete"]


def test_exact_source_selection_inventory_and_no_pooling(stored, monkeypatch):
    _seed(stored, value=60)
    if stored[2].provider_code == "google_health":
        GoogleSourceRepository(stored[0]).get_or_create(_family_identity())
    else:
        GarminSourceRepository(stored[0]).get_or_create(replace(
            GARMIN_IDENTITY, source_instance_id="synthetic-second-period-source"))
    selected = _period(stored)
    ambiguous = _period(stored, source_id=None)
    assert selected["mean_display"] == 60
    assert selected["source_identity"]["source_id"] == stored[2].id
    assert ambiguous["reason"] == "source_selection_required" and ambiguous["mean_display"] is None
    assert len(ambiguous["available_sources"]) == 2
    assert _period(stored, source_id="nonexistent")["reason"] == "source_not_found"
    monkeypatch.setattr(module, "MAX_SOURCE_IDENTITIES", 1)
    capped = _period(stored, source_id=None)
    assert capped["reason"] == "source_inventory_cap" and capped["available_sources"] == []


@pytest.mark.parametrize("stored", ["google_health"], indirect=True)
def test_source_civil_day_never_reconstructed_from_utc_and_date_precision_required(stored):
    record, _ = _seed(stored, value=60)
    record.source_timestamp_utc = datetime(2099, 1, 2, 23, 30, tzinfo=UTC)
    result = _period(stored, days=1)
    assert result["observations"][0]["source_local_date"] == "2099-01-03"
    record.temporal_precision = "instant"
    result = _period(stored, days=1)
    assert result["mean_display"] is None and result["eligible_day_count"] == 0


def test_inclusive_custom_boundaries_and_clocks(stored):
    start, end = date(2098, 12, 31), date(2099, 1, 1)
    for day in [start - timedelta(days=1), start, end, end + timedelta(days=1)]:
        _seed(stored, day=day, value=60 if day in {start, end} else 90,
              external=f"synthetic-boundary-{day}")
    result = _period(stored, requested_start_date=start, requested_end_date=end)
    assert result["mean_display"] == 60 and result["eligible_day_count"] == 2
    assert result["requested_day_count"] == 2


def test_pending_writes_rejected_and_reader_is_read_only(stored):
    _, metric = _seed(stored)
    query = _query(stored)
    period = SavedRhrPeriodQuery(query.provider_code, query.metric_code, DAY, DAY, NOW, DAY,
                                source_id=query.source_id)
    metric.value_number = 63
    with pytest.raises(InvalidRequestError, match="pending"):
        read_saved_rhr_period(stored[0], period)
    stored[0].flush()
    statements = []
    def capture(_c, _cur, sql, *_args):
        statements.append(sql)
    event.listen(stored[0].bind, "before_cursor_execute", capture)
    try:
        assert read_saved_rhr_period(stored[0], period)["mean_display"] == 63
    finally:
        event.remove(stored[0].bind, "before_cursor_execute", capture)
    assert all(sql.lstrip().upper().startswith(("SELECT", "BEGIN")) for sql in statements)
    model, scope = module._record_scope(period, stored[2].id)
    statement = select(model).where(
        *scope, model.projection_status == "current", model.source_local_date >= DAY,
        model.source_local_date <= DAY,
    ).order_by(model.source_local_date.desc()).limit(period.max_candidate_records + 1)
    sql = str(statement.compile(stored[0].bind, compile_kwargs={"literal_binds": True}))
    plan = stored[0].execute(text("EXPLAIN QUERY PLAN " + sql)).all()
    assert any("source_records_stream_date" in str(row) for row in plan)
    assert not any("TEMP B-TREE" in str(row) for row in plan)


@pytest.mark.parametrize("changes", [
    {"max_candidate_records": 4097}, {"max_candidate_records": True},
    {"max_records_per_day": 257}, {"max_records_per_day": 0},
    {"evaluated_at_utc": NOW.replace(tzinfo=None)},
    {"metric_code": "unapproved-metric"}, {"source_id": " "},
    {"requested_start_date": DAY + timedelta(days=1)},
])
def test_period_validation_does_not_reinterpret_inputs(stored, changes):
    with pytest.raises(ValueError):
        _period(stored, **changes)


def test_read_failure_after_partial_projection_never_publishes_mean(stored, monkeypatch):
    _seed(stored)
    _seed(stored, day=DAY - timedelta(days=1), external="synthetic-failure-old")
    original = module._project_group
    calls = 0
    def fail_later(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OperationalError("synthetic", {}, RuntimeError("synthetic"))
        return original(*args)
    monkeypatch.setattr(module, "_project_group", fail_later)
    result = _period(stored)
    assert result["reason"] == "saved_value_read_failed"
    assert result["mean_display"] is None and result["observations"] == []
    assert result["eligible_day_count"] is None and not result["search"]["complete"]
