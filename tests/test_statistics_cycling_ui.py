"""Synthetic production-route checks for the bounded #347 cycling UI slice."""

import os
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import event, select

from healthcheck.analytics import period_summary_read as bounded
from healthcheck.analytics.cycling_source_discovery import (
    METRIC_CODE,
    CyclingSourceDiscoveryService,
)
from healthcheck.analytics.period_summary import PeriodSummaryService
from healthcheck.db.models import GarminRecordMetric, GarminSource, GarminSourceRecord
from healthcheck.web.statistics import format_statistics_value, statistics_cycling_cell
from test_cycling_source_discovery import extra_source
from test_period_summary import END, _activity, _coverage
from test_statistics_ui import MetricParser, SourceFormParser
from test_statistics_ui import projection_database as projection_database
from test_statistics_ui import statistics_ui as statistics_ui

PERIODS = ["7", "30", "trailing365", "calendar_year", "year_to_date"]


def params(period="7", end=END):
    return {"period": period, "end_date": str(end), "calendar_year": end.year}


def window(period):
    if period in {"7", "30"}:
        return {"end_date": END, "days": int(period)}
    if period == "calendar_year":
        return {"period_type": period, "calendar_year": END.year}
    return {"period_type": period, "end_date": END}


def export(response, name):
    folder = os.environ.get("HEALTHCHECK_STATISTICS_FIXTURES_DIR")
    if folder:
        path = Path(folder)
        path.mkdir(parents=True, exist_ok=True)
        (path / f"cycling-{name}.html").write_text(response.text, encoding="utf-8")


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("distance", [0, 12345.6])
def test_exact_unique_metric_source_and_packet_preservation(statistics_ui, period, distance):
    session, paths, client = statistics_ui
    _activity(session, paths, day=END, distance=distance)
    source = session.scalar(select(GarminSource))
    # Device metadata and other metric identities are not distance availability.
    for _ in range(4):
        extra_source(session, source)
    session.commit()
    packet = PeriodSummaryService(session).build(**window(period), sleep_source_selection=True)
    before = deepcopy(packet)
    discovered = CyclingSourceDiscoveryService(session).discover(**window(period))
    cell = statistics_cycling_cell(session, packet, window=window(period), explicit=None)
    assert packet == before
    chosen = next(o for o in discovered["providers"][0]["options"]
                  if o["source_identity"]["source_id"] == source.id)
    for key, value in chosen["summary"].items():
        assert cell[key] == value
    assert cell["source_identity"]["source_id"] == source.id
    assert cell["cycling_selection"]["state"] == "unique_eligible_source"
    assert cell["coverage"]["complete"] is False
    session.rollback()
    statements = []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(session.bind, "before_cursor_execute", capture)
    try:
        response = client.get("/statistics", params=params(period))
    finally:
        event.remove(session.bind, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert statements and set(statements) <= {"SELECT", "BEGIN", "PRAGMA"}
    parsed = MetricParser(response.text)
    assert parsed.values[METRIC_CODE, "left"].strip() == format_statistics_value(
        METRIC_CODE, distance)
    assert "automatic" in parsed.details[METRIC_CODE, "left"]
    assert "Автоматически для этого периода" not in parsed.cells[METRIC_CODE, "left"]
    assert source.id in parsed.details[METRIC_CODE, "left"]
    assert (METRIC_CODE, "right") not in parsed.cells
    assert SourceFormParser(response.text).selected["garmin_source_id"] == ""
    # Only cycling gets a metric source. Provider-wide activities stay unselected.
    assert parsed.values["activity_session_count", "left"].strip() == "Недоступно"
    link = response.text.split('data-session-drilldown="cycling_distance_meters"')[0]
    link = link.rsplit('href="', 1)[1].split('"', 1)[0].replace("&amp;", "&")
    query = parse_qs(urlsplit(link).query, keep_blank_values=True)
    assert query["garmin_source_id"] == [source.id]
    assert query["origin_garmin_source_id"] == [""]
    sessions = client.get(link)
    assert sessions.status_code == 200
    back = sessions.text.split('data-statistics-return')[0].rsplit('href="', 1)[1].split('"')[0]
    assert parse_qs(urlsplit(back.replace("&amp;", "&")).query,
                    keep_blank_values=True)["garmin_source_id"] == [""]
    export(response, f"unique-{period}-{'zero' if distance == 0 else 'value'}")


@pytest.mark.parametrize("case", ["multiple", "conflict", "missing", "subtype", "empty"])
@pytest.mark.parametrize("period", ["7", "trailing365"])
def test_no_silent_winner_or_missing_zero(statistics_ui, case, period):
    session, paths, client = statistics_ui
    if case != "empty":
        _activity(session, paths, day=END, kind="road_biking" if case == "subtype" else "cycling",
                  count=2 if case == "conflict" else 1)
        rows = list(session.scalars(select(GarminSourceRecord)))
        if case == "conflict":
            rows[1].external_record_id = rows[0].external_record_id
            # An independent usable value must not conceal duplicate-current ambiguity.
            _activity(session, paths, day=END, suffix="independent", distance=17)
        if case == "missing":
            metric = session.scalar(select(GarminRecordMetric).where(
                GarminRecordMetric.metric_code == "distance_meters"))
            metric.state, metric.value_number = "null", None
            _coverage(session, session.scalar(select(GarminSource)), status="confirmed_empty")
        if case == "multiple":
            _activity(session, paths, day=END, attributed=False, suffix="other", distance=0)
    session.commit()
    response = client.get("/statistics", params=params(period))
    assert response.status_code == 200
    parsed = MetricParser(response.text)
    text = parsed.cells[METRIC_CODE, "left"]
    assert parsed.values[METRIC_CODE, "left"].strip() == "Недоступно"
    assert "Допустимо: 0" not in text
    assert 'data-session-drilldown="cycling_distance_meters"' not in response.text
    assert ("Выберите Garmin-источник выше" in text) == (case in {"multiple", "conflict"})
    if case == "conflict":
        assert "duplicate_current_identity: 2" in parsed.details[METRIC_CODE, "left"]
    assert (METRIC_CODE, "right") not in parsed.cells
    export(response, f"{case}-{period}")


@pytest.mark.parametrize("period", PERIODS)
def test_existing_explicit_override_never_falls_back(statistics_ui, monkeypatch, period):
    session, paths, client = statistics_ui
    _activity(session, paths, day=END)
    first = session.scalar(select(GarminSource))
    empty = extra_source(session, first)
    session.commit()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Explicit override must retain its existing source read")

    monkeypatch.setattr(CyclingSourceDiscoveryService, "discover", forbidden)
    for chosen in (first, empty):
        response = client.get("/statistics", params={**params(period),
                                                     "garmin_source_id": chosen.id})
        assert response.status_code == 200
        parsed = MetricParser(response.text)
        expected = 21000 if chosen == first else None
        assert parsed.values[METRIC_CODE, "left"].strip() == format_statistics_value(
            METRIC_CODE, expected)
        assert SourceFormParser(response.text).selected["garmin_source_id"] == chosen.id
        assert "explicit" in parsed.details[METRIC_CODE, "left"]
        assert "Выбран явно" not in parsed.cells[METRIC_CODE, "left"]
        export(response, f"explicit-{'value' if chosen == first else 'empty'}-{period}")


@pytest.mark.parametrize("cap", ["MAX_PERIOD_SOURCES", "MAX_PERIOD_RECORDS", "MAX_METRIC_ROWS",
                                 "MAX_COVERAGE_ROWS", "MAX_METADATA_ROWS"])
@pytest.mark.parametrize("period", ["7", "trailing365"])
def test_capped_search_publishes_no_prefix_or_zero(statistics_ui, monkeypatch, cap, period):
    session, paths, client = statistics_ui
    _activity(session, paths, day=END, count=2)
    source = session.scalar(select(GarminSource))
    extra_source(session, source)
    _coverage(session, source)
    _coverage(session, source, status="failed")
    session.commit()
    monkeypatch.setattr(bounded, cap, 0 if cap == "MAX_METADATA_ROWS" else 1)
    response = client.get("/statistics", params=params(period))
    assert response.status_code == 200
    parsed = MetricParser(response.text)
    text = parsed.cells[METRIC_CODE, "left"]
    assert parsed.values[METRIC_CODE, "left"].strip() == "Недоступно"
    assert "Поиск велодистанции не завершён" in text
    assert "Допустимо:" not in text
    assert "без наблюдений 0" not in text
    assert "Не завершён:" in parsed.details[METRIC_CODE, "left"]
    assert (METRIC_CODE, "right") not in parsed.cells
    export(response, f"capped-{period}")


def test_period_change_rechecks_auto_and_preserves_explicit(statistics_ui):
    session, paths, client = statistics_ui
    end = END + timedelta(days=31)
    _activity(session, paths, day=end, distance=11000)
    first = session.scalar(select(GarminSource))
    _activity(session, paths, day=end - timedelta(days=20), attributed=False, distance=22000)
    session.commit()
    for period in PERIODS:
        response = client.get("/statistics", params=params(period, end))
        assert response.status_code == 200
        parsed = MetricParser(response.text)
        assert parsed.values[METRIC_CODE, "left"].strip() == (
            "11 км" if period == "7" else "Недоступно")
        assert SourceFormParser(response.text).selected["garmin_source_id"] == ""
        export(response, f"window-{period}")
        explicit = client.get("/statistics", params={**params(period, end),
                                                     "garmin_source_id": first.id})
        assert explicit.status_code == 200
        assert MetricParser(explicit.text).values[METRIC_CODE, "left"].strip() == "11 км"
        assert SourceFormParser(explicit.text).selected["garmin_source_id"] == first.id
        export(explicit, f"window-explicit-{period}")


@pytest.mark.parametrize("period", ["7", "trailing365"])
def test_late_deadline_discards_a_successful_candidate(statistics_ui, monkeypatch, period):
    session, paths, client = statistics_ui
    _activity(session, paths, day=END)
    extra_source(session, session.scalar(select(GarminSource)))
    session.commit()
    original = PeriodSummaryService._activities
    calls = []

    def fail_second(service, source, *args):
        calls.append(source.id)
        if len(calls) == 2:
            raise bounded.IncompletePeriodRead("time_budget_exceeded")
        return original(service, source, *args)

    monkeypatch.setattr(PeriodSummaryService, "_activities", fail_second)
    response = client.get("/statistics", params=params(period))
    assert response.status_code == 200 and len(calls) == 2
    parsed = MetricParser(response.text)
    assert parsed.values[METRIC_CODE, "left"].strip() == "Недоступно"
    assert "time_budget_exceeded" in parsed.details[METRIC_CODE, "left"]
    assert "допустимых сессий" not in parsed.details[METRIC_CODE, "left"]


def test_explicit_conflict_retains_accepted_exclusions(statistics_ui):
    session, paths, client = statistics_ui
    _activity(session, paths, day=END, count=2)
    rows = list(session.scalars(select(GarminSourceRecord)))
    rows[1].external_record_id = rows[0].external_record_id
    _activity(session, paths, day=END, suffix="usable", distance=17000)
    source = session.scalar(select(GarminSource))
    session.commit()
    response = client.get("/statistics", params={**params(), "garmin_source_id": source.id})
    assert response.status_code == 200
    parsed = MetricParser(response.text)
    assert parsed.values[METRIC_CODE, "left"].strip() == "17 км"
    assert "duplicate_current_identity: 2" in parsed.details[METRIC_CODE, "left"]


def test_explicit_annual_read_keeps_existing_caps(statistics_ui, monkeypatch):
    session, paths, client = statistics_ui
    _activity(session, paths, day=END, count=2)
    source = session.scalar(select(GarminSource))
    session.commit()
    monkeypatch.setattr(bounded, "MAX_PERIOD_RECORDS", 1)
    response = client.get("/statistics", params={**params("trailing365"),
                                                 "garmin_source_id": source.id})
    assert response.status_code == 200
    parsed = MetricParser(response.text)
    assert parsed.values[METRIC_CODE, "left"].strip() == "Недоступно"
    assert "candidate_record_limit_exceeded" in parsed.details[METRIC_CODE, "left"]
    assert SourceFormParser(response.text).selected["garmin_source_id"] == source.id


@pytest.mark.parametrize("multiple", [False, True])
def test_completed_discovery_supplies_labels_after_summary_deadline(
    statistics_ui, monkeypatch, multiple,
):
    session, paths, client = statistics_ui
    _activity(session, paths, day=END)
    if multiple:
        _activity(session, paths, day=END, attributed=False, suffix="second")
    source_ids = list(session.scalars(select(GarminSource.id)))
    session.commit()
    original_enter = bounded.PeriodReadBudget.__enter__
    original_rows = bounded.PeriodReadBudget.rows
    budgets = []

    def enter(budget):
        budgets.append(budget)
        return original_enter(budget)

    def rows(budget, *args, **kwargs):
        if budget is budgets[0]:
            raise bounded.IncompletePeriodRead("time_budget_exceeded")
        return original_rows(budget, *args, **kwargs)

    monkeypatch.setattr(bounded.PeriodReadBudget, "__enter__", enter)
    monkeypatch.setattr(bounded.PeriodReadBudget, "rows", rows)
    response = client.get("/statistics", params=params("trailing365"))
    assert response.status_code == 200
    parsed = MetricParser(response.text)
    text = parsed.cells[METRIC_CODE, "left"]
    assert "data-cycling-source" not in text
    assert "Источник / поле" in parsed.details[METRIC_CODE, "left"]
    assert parsed.values[METRIC_CODE, "left"].strip() == ("Недоступно" if multiple else "21 км")
    # Other cells keep the first budget's failure; successful cycling identities
    # support a labelled selector but do not rewrite that shared packet.
    assert "Поиск сохранённых данных не завершён" in parsed.cells["activity_session_count", "left"]
    provider_header = response.text.split('<header data-statistics-side="left">')[1].split(
        "</header>")[0]
    for source_id in source_ids:
        assert f'<option value="{source_id}">Garmin' in provider_header
    assert SourceFormParser(response.text).selected["garmin_source_id"] == ""
    export(response, f"summary-deadline-{'multiple' if multiple else 'unique'}")
