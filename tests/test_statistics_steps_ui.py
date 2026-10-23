"""Completed-day Steps through the real Statistics route; external synthetic data."""

import os
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.garmin.completed_steps_read import read_completed_steps_window
from healthcheck.garmin.observed_steps import SavedDailyStepsRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.web.owner_presentation import owner_date
from test_garmin_completed_steps import ABSENT, BOUNDARY, DAY, NOW, acquire
from test_statistics_ui import projection_database as projection_database
from test_statistics_ui import statistics_ui as statistics_ui


class StepsParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.states, self.values = {}, {}
        self.day = None
        self.in_value = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr" and "data-steps-date" in attrs:
            self.day = attrs["data-steps-date"]
            self.states[self.day] = attrs["data-steps-state"]
            self.values[self.day] = ""
        if tag == "td" and attrs.get("class") == "statistics-steps-value":
            self.in_value = True

    def handle_endtag(self, tag):
        if tag == "td":
            self.in_value = False
        if tag == "tr":
            self.day = None

    def handle_data(self, text):
        if self.day and self.in_value:
            self.values[self.day] += text


def steps_html(response):
    return response.text.split('<section class="statistics-steps"', 1)[1].split("</section>", 1)[0]


def export(response, name):
    root = os.environ.get("HEALTHCHECK_STATISTICS_FIXTURES_DIR")
    if root:
        directory = Path(root)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"steps-{name}.html").write_text(response.text, encoding="utf-8")


def seed_steps(session, paths):
    store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    for index, count in enumerate([17, 0, None, ABSENT, True, 7]):
        saved = acquire(
            session,
            store,
            count,
            day=DAY + timedelta(days=index),
            at=BOUNDARY + timedelta(days=index),
        )
    acquire(
        session, store, 3, day=DAY + timedelta(days=5), at=BOUNDARY + timedelta(days=5, hours=1)
    )
    return saved.source.id


@pytest.fixture(autouse=True)
def deterministic_steps_clock(monkeypatch):
    monkeypatch.setattr(
        "healthcheck.web.statistics.steps_evaluation_instant", lambda: NOW + timedelta(days=7)
    )


def test_future_partial_receipt_through_real_statistics_get(statistics_ui, monkeypatch):
    from sqlalchemy import select

    from healthcheck.db.models import GarminPayloadObservation
    from test_garmin_daily_summary_acquisition import fetch

    session, paths, client = statistics_ui
    session.commit()
    report = fetch(paths.root, count=17)
    assert report.status.value == "partial"
    session.expire_all()
    source_id = session.scalar(select(GarminPayloadObservation.garmin_source_id).where(
        GarminPayloadObservation.sync_run_id == report.sync_run_id,
        GarminPayloadObservation.source_filename == "daily_summary.json",
    ))
    session.commit()
    statements = []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(session.bind, "before_cursor_execute", capture)
    try:
        response = client.get("/statistics", params={
            "period": "7", "end_date": DAY.isoformat(), "garmin_source_id": source_id,
        })
    finally:
        event.remove(session.bind, "before_cursor_execute", capture)
    assert response.status_code == 200
    parser = StepsParser(steps_html(response))
    assert parser.states[DAY.isoformat()] == "value"
    assert parser.values[DAY.isoformat()].strip() == "17"
    assert set(statements) <= {"SELECT", "BEGIN"}


@pytest.mark.parametrize("period", ["7", "30", "calendar_year", "trailing365", "year_to_date"])
def test_steps_reader_preserves_explicit_period_and_result(statistics_ui, monkeypatch, period):
    session, paths, client = statistics_ui
    first = seed_steps(session, paths)
    captured = []

    def capture(read_session, **kwargs):
        result = read_completed_steps_window(read_session, **kwargs)
        captured.append((kwargs, result))
        return result

    monkeypatch.setattr("healthcheck.web.statistics.read_completed_steps_window", capture)
    end = DAY + timedelta(days=8)
    response = client.get(
        "/statistics",
        params={
            "period": period,
            "end_date": str(end),
            "calendar_year": 2099,
            "garmin_source_id": first,
        },
    )
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    selection, result = captured[0]
    assert selection["source_id"] == first
    assert result.end_date == (end if period != "calendar_year" else DAY.replace(month=12, day=31))
    parser = StepsParser(response.text)
    assert parser.states == {str(cell.calendar_date): cell.state for cell in result.cells}
    assert parser.values == {
        str(cell.calendar_date): str(cell.value) if cell.value is not None else "Недоступно"
        for cell in result.cells
    }
    section = steps_html(response)
    assert "unknown / unknown / unknown / unknown" in section
    assert "Europe/Moscow" in section and "garmin-completed-day-steps-moscow-v2" in section
    assert "statistics-denominator" not in section and "statistics-comparison" not in section
    for cell in result.cells:
        for evidence in cell.evidence:
            assert evidence.observation_id in section and evidence.content_hash in section
    export(response, f"completed-{period}")


def test_default_targets_yesterday_and_does_not_shift_explicit_window(statistics_ui, monkeypatch):
    session, paths, client = statistics_ui
    source = seed_steps(session, paths)
    monkeypatch.setattr("healthcheck.web.statistics.steps_evaluation_instant", lambda: BOUNDARY)
    response = client.get("/statistics", params={"garmin_source_id": source})
    parser = StepsParser(response.text)
    assert max(parser.states) == str(DAY) and len(parser.states) == 7
    assert parser.values[str(DAY)] == "17"
    historical = client.get(
        "/statistics",
        params={"end_date": str(DAY - timedelta(days=10)), "garmin_source_id": source},
    )
    assert max(StepsParser(historical.text).states) == str(DAY - timedelta(days=10))


def test_sole_source_defaults_but_multiple_sources_require_honest_choice(statistics_ui):
    session, paths, client = statistics_ui
    store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    first = acquire(session, store, 0)
    response = client.get("/statistics", params={"end_date": str(DAY)})
    assert StepsParser(response.text).values[str(DAY)] == "0"
    second = acquire(session, store, 999, account="other-account")
    response = client.get("/statistics", params={"end_date": str(DAY)})
    assert 'data-steps-selection="required"' in response.text
    assert not StepsParser(response.text).states
    explicit = client.get(
        "/statistics", params={"end_date": str(DAY), "garmin_source_id": first.source.id}
    )
    assert StepsParser(explicit.text).values[str(DAY)] == "0"
    assert second.source.id not in steps_html(explicit)


def test_current_future_days_omitted_and_source_range_never_guessed(statistics_ui, monkeypatch):
    session, paths, client = statistics_ui
    source = seed_steps(session, paths)
    monkeypatch.setattr("healthcheck.web.statistics.steps_evaluation_instant", lambda: BOUNDARY)
    response = client.get(
        "/statistics", params={"end_date": str(DAY + timedelta(days=1)), "garmin_source_id": source}
    )
    assert max(StepsParser(response.text).states) == str(DAY)
    assert owner_date(DAY) in steps_html(response)
    missing = client.get("/statistics", params={"garmin_source_id": "missing-source"})
    assert missing.status_code == 400  # Existing Statistics exact-source validation.


def test_steps_ui_no_writes_or_projection(statistics_ui, monkeypatch):
    session, paths, client = statistics_ui
    first = seed_steps(session, paths)
    statements = []

    def forbidden(*_args, **_kwargs):
        pytest.fail("GET attempted Steps materialization")

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lstrip().split()[0].upper())

    monkeypatch.setattr(SavedDailyStepsRepository, "project_day", forbidden)
    event.listen(session.bind, "before_cursor_execute", capture)
    try:
        response = client.get(
            "/statistics", params={"end_date": "2099-02-08", "garmin_source_id": first}
        )
    finally:
        event.remove(session.bind, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert not StepsParser(response.text).states  # Explicit future range has no completed days.
    assert set(statements) <= {"SELECT", "BEGIN", "PRAGMA"}


def test_reader_failure_keeps_html_error_contract(statistics_ui, monkeypatch):
    _, _, client = statistics_ui

    def fail(*_args, **_kwargs):
        raise SQLAlchemyError("synthetic Steps failure")

    monkeypatch.setattr("healthcheck.web.statistics.read_completed_steps_window", fail)
    response = client.get("/statistics")
    assert response.status_code == 500 and 'role="alert"' in response.text
    assert "synthetic Steps failure" not in response.text


def test_browser_period_captures_share_one_exact_source(statistics_ui):
    session, paths, client = statistics_ui
    source_id = seed_steps(session, paths)
    for period in ("7", "30"):
        response = client.get(
            "/statistics",
            params={
                "period": period,
                "end_date": "2099-01-10",
                "calendar_year": 2099,
                "garmin_source_id": source_id,
            },
        )
        assert response.status_code == 200
        assert source_id in steps_html(response)
        export(response, f"completed-{period}")


def test_all_time_stats_real_route_and_google_unsupported_window(statistics_ui, monkeypatch):
    from healthcheck.web import statistics as module

    session, paths, client = statistics_ui
    source_id = seed_steps(session, paths)
    calls = []
    monkeypatch.setattr(
        module, "steps_evaluation_instant", lambda: (calls.append(1), NOW + timedelta(days=7))[1]
    )
    monkeypatch.setattr(
        module, "read_completed_steps_window", lambda *a, **k: pytest.fail("window loop")
    )
    response = client.get(
        "/statistics", params={"steps_period": "all_time", "garmin_source_id": source_id}
    )
    assert response.status_code == 200 and len(calls) == 1
    history = response.context["steps"]
    assert history.statistics.total == 20 and history.statistics.eligible_day_count == 3
    html = steps_html(response)
    assert 'data-steps-provider="google" data-steps-history-state="unsupported_window"' in html
    assert 'data-steps-stat="total">20<' in html
    assert 'data-steps-stat="mean">6,7<' in html
    assert "Полный поиск сохранённых данных не доказывает полную историю аккаунта" in html
    assert "snapshot" in html and source_id in html
    assert history.statistics.state_counts == {"value": 3, "null": 1, "missing": 1, "invalid": 1}
    assert "statistics-steps-panels--compact" not in html
    assert html.count('data-steps-provider="google"') == 1
    assert "data-google-steps>" not in html  # Existing all-time pair owns this explanation.
    assert '<div class="statistics-pair statistics-steps-history">' in html


@pytest.mark.parametrize("period", ["7", "30", "trailing365", "calendar_year", "year_to_date"])
def test_compact_grid_only_applies_to_7_30_window(statistics_ui, period):
    session, paths, client = statistics_ui
    source_id = seed_steps(session, paths)
    response = client.get("/statistics", params={
        "period": period, "end_date": str(DAY + timedelta(days=6)),
        "calendar_year": 2099, "garmin_source_id": source_id,
    })
    assert response.status_code == 200
    html = steps_html(response)
    assert ("statistics-steps-panels--compact" in html) == (period in {"7", "30"})
    # Long windows retain full-width daily tables and their one unsupported Google view.
    assert html.count("data-google-steps>") == 1


def test_all_time_fullwidth_view_matches_exact_read_api_packet(statistics_ui):
    from healthcheck.garmin.completed_steps_read import read_completed_steps_all_time

    session, paths, client = statistics_ui
    source_id = seed_steps(session, paths)
    response = client.get("/statistics", params={
        "steps_period": "all_time", "end_date": str(DAY + timedelta(days=6)),
        "garmin_source_id": source_id,
    })
    assert response.status_code == 200
    actual = response.context["steps"]
    # This is the existing Python read API, not an invented HTTP endpoint/mock.
    expected = read_completed_steps_all_time(
        session, payload_store=ContentAddressedGarminPayloadStore(paths.root / "artifacts"),
        source_id=source_id, evaluated_at=actual.evaluated_at,
        end_date=DAY + timedelta(days=6),
    )
    assert actual == expected
    assert actual.source_id == source_id and actual.statistics.total == 20
    assert actual.statistics.eligible_day_count == 3
    html = steps_html(response)
    assert "statistics-steps-panels--compact" not in html
    assert html.count('data-steps-provider="garmin"') == 1
    assert html.count('data-steps-provider="google"') == 1
    assert 'data-steps-stat="total">20<' in html


def test_all_time_explicit_end_does_not_change_other_windows(statistics_ui):
    session, paths, client = statistics_ui
    source_id = seed_steps(session, paths)
    response = client.get(
        "/statistics",
        params={
            "period": "calendar_year",
            "calendar_year": 2099,
            "end_date": DAY.isoformat(),
            "steps_period": "all_time",
            "garmin_source_id": source_id,
        },
    )
    assert response.status_code == 200
    assert response.context["steps"].end_date == DAY
    assert response.context["steps"].statistics.total == 17
    assert response.context["packet"]["requested_window"]["end_date"] == "2099-12-31"


@pytest.mark.parametrize("mode", ["omitted", "window"])
def test_window_mode_compatibility_remains_v2(statistics_ui, mode):
    session, paths, client = statistics_ui
    source_id = seed_steps(session, paths)
    params = {"end_date": DAY.isoformat(), "garmin_source_id": source_id}
    if mode == "window":
        params["steps_period"] = "window"
    response = client.get("/statistics", params=params)
    assert response.status_code == 200
    assert response.context["steps"].contract_version == "garmin-completed-day-steps-moscow-v2"
    assert 'data-steps-stat="total"' not in steps_html(response)
    assert StepsParser(response.text).values[DAY.isoformat()] == "17"


def test_all_time_incomplete_no_numeric_prefix_and_recovery(statistics_ui, monkeypatch):
    from healthcheck.garmin import completed_steps_read as reader

    session, paths, client = statistics_ui
    source_id = seed_steps(session, paths)
    params = {"steps_period": "all_time", "garmin_source_id": source_id}
    monkeypatch.setattr(reader, "MAX_ALL_TIME_ARTIFACTS", 1)
    response = client.get("/statistics", params=params)
    assert response.status_code == 200
    assert response.context["steps"].statistics is None
    assert 'data-steps-history-state="search_incomplete"' in response.text
    assert 'data-steps-stat="total"' not in response.text
    monkeypatch.setattr(reader, "MAX_ALL_TIME_ARTIFACTS", 4096)
    assert client.get("/statistics", params=params).context["steps"].statistics.total == 20


def test_all_time_requires_explicit_account_and_invalid_mode_is_sanitized(
    statistics_ui, monkeypatch
):
    session, paths, client = statistics_ui
    source_id = seed_steps(session, paths)
    response = client.get("/statistics", params={"steps_period": "all_time"})
    assert (
        response.status_code == 200
        and response.context["steps"].reason == "source_selection_required"
    )
    assert 'value="' + source_id + '"' in response.text
    assert "не оценена без точного источника" in steps_html(response)
    response = client.get("/statistics", params={"steps_period": "synthetic-secret-invalid"})
    assert response.status_code == 400 and "synthetic-secret-invalid" not in response.text


def test_all_time_mean_rendering_does_not_inherit_ambient_rounding():
    from decimal import ROUND_DOWN, Decimal, localcontext

    from healthcheck.web.statistics import format_steps_value
    with localcontext() as context:
        context.rounding = ROUND_DOWN
        assert format_steps_value(Decimal("0.15")) == "0,2"
        assert format_steps_value(0) == "0"


def test_compact_steps_real_route_preserves_cells_and_exact_observed_day_summary(statistics_ui):
    session, paths, client = statistics_ui
    source = seed_steps(session, paths)
    response = client.get('/statistics', params={
        'period': '7', 'end_date': str(DAY + timedelta(days=6)), 'garmin_source_id': source,
    })
    assert response.status_code == 200
    html = steps_html(response)
    # Latest correction 7→3, explicit zero included; null/missing/invalid excluded.
    assert 'data-steps-total>20</dd>' in html and 'data-steps-mean>6.7</dd>' in html
    assert '3 из 7 дней с данными' not in html
    assert 'data-steps-cursor hidden' in html and 'Выберите день' in html
    assert ('<details class="statistics-details steps-daily-details">'
            '<summary>Дни и подробности Garmin</summary>') in html
    assert 'data-steps-chart="garmin"' in html
    primary = html.split('<details class="owner-info">', 1)[0]
    assert 'только завершённые дни по МСК' not in primary
    assert 'garmin-completed-steps-summary-v1' in html
    assert StepsParser(html).values[str(DAY + timedelta(days=5))].strip() == '3'
    assert '/static/statistics_steps.js' in response.text
