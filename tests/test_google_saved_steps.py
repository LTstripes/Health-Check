"""Saved Google Steps through production persistence and actual Statistics GET."""

from datetime import date, timedelta

import pytest
from sqlalchemy import event, select

from healthcheck.db.models import GoogleRecordInterval, GoogleRecordMetric
from healthcheck.google.contracts import FAMILY_ALL_SOURCES, INT64_MAX
from healthcheck.google.steps_read import read_saved_steps_window
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from test_google_steps_countsum import MISSING, NOW, civil, payload, persist
from test_google_steps_countsum import database as database
from test_sleep_account_cohort import _google
from test_statistics_ui import projection_database as projection_database
from test_statistics_ui import statistics_ui as statistics_ui

END = date(2099, 1, 3)


def read(session, *, days=7, source=None, end=END):
    return read_saved_steps_window(
        session,
        start_date=end - timedelta(days=days - 1),
        end_date=end,
        source_id=source,
    )


def cell(result, day=date(2099, 1, 2)):
    return next(c for c in result["cells"] if c["calendar_date"] == day)


@pytest.mark.parametrize("days", [7, 30])
@pytest.mark.parametrize(
    "value,state,expected",
    [
        ("0", "value", 0),
        (str(INT64_MAX), "value", INT64_MAX),
        (str(2**53 + 1), "value", 2**53 + 1),
        (MISSING, "missing", None),
        (None, "null", None),
        ("1.5", "invalid", None),
    ],
)
def test_typed_integer_states_and_honest_coverage(database, days, value, state, expected):
    _, session, _ = database
    persist(database, payload(value))
    result = read(session, days=days)
    assert len(result["cells"]) == days
    assert (cell(result)["state"], cell(result)["value"]) == (state, expected)
    if expected is not None:
        assert type(cell(result)["value"]) is int
    assert all(result[k] == "unknown" for k in ("coverage", "pagination", "timezone", "finality"))
    assert "total" not in result and "average" not in result
    assert cell(result, END)["state"] == "no_observation"
    assert result["search_complete"]


@pytest.mark.parametrize(
    "value,state", [("0", "value"), (None, "null"), (MISSING, "missing"), ("1.5", "invalid")]
)
def test_current_lower_or_nonvalue_correction_never_restores_old_number(database, value, state):
    _, session, _ = database
    persist(database, payload("999"))
    persist(database, payload(value), epoch=1)
    persist(database, payload("999"), epoch=-1)
    got = cell(read(session))
    assert got["state"] == state
    assert got["value"] == (0 if value == "0" else None)


def test_conflict_barrier_and_later_resolution(database):
    _, session, _ = database
    persist(database, payload("111"))
    persist(database, payload("222"))
    assert cell(read(session))["state"] == "invalid"
    assert cell(read(session))["value"] is None
    session.commit()
    persist(database, payload("111"), epoch=-1)
    assert cell(read(session))["value"] is None
    session.commit()
    persist(database, payload("0"), epoch=1)
    assert cell(read(session))["value"] == 0


def test_equivalent_civil_encodings_remain_ambiguous_no_sum(database):
    _, session, _ = database
    persist(database, payload("17"))
    raw = payload("17")
    del raw["rollupDataPoints"][0]["civilStartTime"]["time"]
    persist(database, raw, epoch=1)
    assert cell(read(session))["state"] == "ambiguous"
    assert cell(read(session))["value"] is None


@pytest.mark.parametrize("kind", ["partial", "nanoseconds", "multi_day", "overlap_before_window"])
def test_non_daily_intervals_block_every_intersected_date(database, kind):
    _, session, _ = database
    raw = payload("10")
    point = raw["rollupDataPoints"][0]
    if kind == "partial":
        point["civilStartTime"]["time"]["hours"] = 12
    elif kind == "nanoseconds":
        point["civilStartTime"]["time"]["nanos"] = 1
    elif kind == "multi_day":
        point["civilEndTime"] = civil(4)
    else:
        point["civilStartTime"] = civil(1)
        point["civilEndTime"] = civil(4)
    persist(database, raw)
    result = read(session, end=date(2099, 1, 8) if kind == "overlap_before_window" else END)
    assert cell(result)["state"] == "unavailable"
    assert cell(result)["value"] is None
    if kind in {"multi_day", "overlap_before_window"}:
        assert cell(result, END)["state"] == "unavailable"


def test_partial_plus_daily_is_ambiguous_not_preferred_or_summed(database):
    _, session, _ = database
    persist(database, payload("100"))
    raw = payload("8")
    raw["rollupDataPoints"][0]["civilStartTime"]["time"]["hours"] = 12
    persist(database, raw, epoch=1)
    assert cell(read(session))["state"] == "ambiguous"


def test_exact_family_selection_no_pooling_or_explicit_fallback(database):
    _, session, _ = database
    _, first = persist(database, payload("5"))
    _, second = persist(database, payload("700"), family=FAMILY_ALL_SOURCES)
    result = read(session)
    assert result["reason"] == "source_selection_required" and not result["cells"]
    assert cell(read(session, source=first.source.id))["value"] == 5
    assert cell(read(session, source=second.source.id))["value"] == 700
    assert read(session, source="unknown-source")["reason"] == "source_not_evidenced"


def test_empty_source_and_window_are_not_zero_or_never_collected(database):
    _, session, _ = database
    assert read(session)["reason"] == "no_saved_source"
    persist(database, payload("0"))
    result = read(session, end=END + timedelta(days=40))
    assert all(c["state"] == "no_observation" and c["value"] is None for c in result["cells"])
    assert result["search_complete"]


def test_retired_rows_do_not_resurrect(database):
    _, session, _ = database
    _, got = persist(database, payload("900"))
    got.records[0].projection_status = "retired"
    got.records[0].retired_at = NOW
    session.commit()
    assert cell(read(session))["state"] == "no_observation"


@pytest.mark.parametrize("mutation", ["metric", "record_key", "interval", "provenance"])
def test_tampered_projection_fails_closed(database, mutation):
    _, session, _ = database
    _, got = persist(database, payload("999"))
    row = got.records[0]
    if mutation == "metric":
        session.scalar(select(GoogleRecordMetric)).value_number = 999.0
    elif mutation == "record_key":
        row.record_identity_key = "forged-record-key"
    elif mutation == "interval":
        session.scalar(select(GoogleRecordInterval)).start_local_wall_time = "2099-01-02T01:00:00"
    else:
        _, other = persist(database, payload("1"), family=FAMILY_ALL_SOURCES)
        row.observation_id = other.observation.id
    session.commit()
    result = read(session, source=got.source.id)
    assert not result["cells"] or all(c["value"] is None for c in result["cells"])


@pytest.mark.parametrize(
    "budget",
    ["MAX_RECORDS", "MAX_CHILDREN", "MAX_SOURCES", "MAX_TEXT_BYTES", "COOPERATIVE_SECONDS"],
)
def test_caps_withhold_all_values_not_prefix(database, monkeypatch, budget):
    _, session, _ = database
    persist(database, payload("5"))
    monkeypatch.setattr("healthcheck.google.steps_read." + budget, 0)
    result = read(session)
    assert not result["search_complete"] and not result["cells"]


def test_large_child_text_is_rejected_before_materialization(database):
    _, session, _ = database
    persist(database, payload("5"))
    session.scalar(select(GoogleRecordInterval)).start_temporal_json = "x" * 5000
    session.commit()
    result = read(session)
    assert result["reason"] == "text_budget_exceeded" and not result["cells"]


@pytest.mark.parametrize("span", [0, 1, 6, 8, 29, 31, 365])
def test_unsupported_reader_windows_rejected(database, span):
    _, session, _ = database
    with pytest.raises(ValueError):
        read_saved_steps_window(session, start_date=END - timedelta(days=span - 1), end_date=END)


def test_reader_uses_snapshot_without_dml(database):
    _, session, _ = database
    persist(database, payload("0"))
    statements = []
    engine = session.get_bind()

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split()[0].upper())

    event.listen(engine, "before_cursor_execute", observe)
    try:
        assert cell(read(session))["value"] == 0
        assert not session.new and not session.dirty and not session.deleted
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert not set(statements) & {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER"}


@pytest.mark.parametrize("days", [7, 30])
def test_actual_statistics_route_exact_integer_dates_and_unknowns(statistics_ui, days):
    session, paths, client = statistics_ui
    bundle = (paths, session, ContentAddressedGooglePayloadStore(paths.root / "artifacts"))
    _, got = persist(bundle, payload(str(INT64_MAX)))
    response = client.get(
        "/statistics",
        params={
            "days": days,
            "end_date": END.isoformat(),
            "google_steps_source_id": got.source.id,
        },
    )
    assert response.status_code == 200
    html = response.text.split("data-google-steps>", 1)[1]
    assert str(INT64_MAX) in html
    assert 'data-google-steps-date="2099-01-02" data-google-steps-state="value"' in html
    assert "покрытие неизвестно" in html
    assert "Поле шагов отсутствует" not in html
    assert f'name="google_steps_source_id" value="{got.source.id}"' in response.text


def test_route_independent_steps_selector_and_unsupported_periods(statistics_ui):
    session, paths, client = statistics_ui
    bundle = (paths, session, ContentAddressedGooglePayloadStore(paths.root / "artifacts"))
    _, got = persist(bundle, payload("13"))
    other = _google(session, paths, wake=END, source="synthetic-independent-sleep")
    session.commit()
    response = client.get(
        "/statistics",
        params={
            "days": 7,
            "end_date": END.isoformat(),
            "google_source_id": other.source.id,
            "google_steps_source_id": got.source.id,
        },
    )
    assert response.status_code == 200 and ">13</td>" in response.text
    for params in [{"period": "30", "steps_period": "all_time"}, {"period": "trailing365"}]:
        response = client.get("/statistics", params=params)
        assert response.status_code == 200
        assert 'data-google-steps-reason="unsupported_window"' in response.text
