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
