"""Synthetic route/packet equivalence and desktop fixture exports for #347 B2."""

from __future__ import annotations

import os
import socket
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from healthcheck.analytics.period_summary import SLEEP_CODE, PeriodSummaryService
from healthcheck.config import Settings
from healthcheck.db.models import GarminRecordMetric, GarminSource, GoogleSource
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.web.ui_app import create_ui_app
from test_period_summary import END, START, _activity, _coverage
from test_sleep_account_cohort import _garmin, _google
from test_sleep_metrics import projection_database as projection_database


class MetricParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.cells = {}
        self.code = self.side = None
        self.in_article = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-statistics-metric" in attrs:
            self.code = attrs["data-statistics-metric"]
        if tag == "article":
            self.side = attrs["data-statistics-side"]
            self.in_article = True
            self.cells[self.code, self.side] = ""

    def handle_endtag(self, tag):
        if tag == "article":
            self.in_article = False

    def handle_data(self, data):
        if self.in_article:
            self.cells[self.code, self.side] += data


def seed(session, paths, case):
    if case == "missing":
        return
    _activity(session, paths, kind="cycling", distance=0 if case == "sparse" else 21000)
    _activity(session, paths, kind="tennis_v2", suffix="tennis", duration=3600)
    nights = 7 if case == "full" else 1
    for offset in range(nights):
        day = START + timedelta(days=offset)
        _garmin(session, paths, wake=day, attributed=True, seconds=28800)
        _google(session, paths, wake=day, main="true", nap="false", minutes="410")
    if case == "full":
        source = session.scalar(select(GarminSource))
        _coverage(session, source)
        _coverage(session, source, surface="sleep")
    if case == "sparse":
        metric = session.scalar(
            select(GarminRecordMetric).where(GarminRecordMetric.metric_code == "duration_seconds")
        )
        metric.state, metric.value_number = "null", None
        _google(session, paths, wake=END, nap="true", minutes="30")
    if case == "ambiguous":
        _activity(session, paths, attributed=False, suffix="other")
        _google(session, paths, source="synthetic-other-source", main="true", nap="false")
        # Same identity/wake date competing main sessions remain excluded after selection.
        _google(session, paths, name="synthetic-competing-main", main="true", nap="false")
    session.commit()


@pytest.fixture
def statistics_ui(projection_database, monkeypatch):
    session, paths = projection_database
    original_connect = socket.socket.connect

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        raise AssertionError("Statistics must not contact providers")

    def forbidden(*args, **kwargs):
        raise AssertionError("Statistics must not contact providers")

    monkeypatch.setattr(socket.socket, "connect", local_only)
    monkeypatch.setattr(requests.Session, "request", forbidden)
    app, _ = create_ui_app(
        Settings(data_dir=paths.root), photo_extractor=FakeImageMeasurementExtractor()
    )
    app.state.engine = session.bind
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        yield session, paths, client


@pytest.mark.parametrize("case", ["full", "sparse", "missing", "ambiguous"])
@pytest.mark.parametrize("days", [7, 30])
def test_route_matches_accepted_packet(statistics_ui, case, days):
    session, paths, client = statistics_ui
    seed(session, paths, case)
    packet = PeriodSummaryService(session).build(end_date=END, days=days)
    session.rollback()
    statements = []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(session.bind, "before_cursor_execute", capture)
    response = client.get("/statistics", params={"days": days, "end_date": str(END)})
    event.remove(session.bind, "before_cursor_execute", capture)
    assert statements and set(statements) <= {"SELECT", "BEGIN", "PRAGMA"}
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert 'href="/statistics" class="active" aria-current="page"' in response.text
    cells = MetricParser(response.text).cells
    assert len(cells) == 12
    for side in packet["sides"]:
        for code, cell in side["metrics"].items():
            text = cells[code, side["position"]]
            value = cell["aggregation"]["value"]
            if value is None:
                assert "Недоступно" in text
            elif isinstance(value, dict):
                for kind, count in value.items():
                    assert f"{kind}: {count}" in text
            else:
                assert str(value) in text
            assert f"Допустимо: {cell['aggregation']['eligible_count']}" in text
            assert f"без наблюдений {cell['missing_day_count']} дней" in text
            assert cell["source_unit"] in text and cell["unit"] in text
            assert cell["conversion"] in text
            assert cell["coverage"]["state"] in text
            for reason in cell["exclusions"]:
                assert f"{reason['reason_code']}: {reason['count']}" in text
    assert "Не собирается" in cells["activity_session_count", "right"]
    assert "Числовая разница недоступна" in response.text
    assert "Шаги и калории" in response.text
    if case == "ambiguous":
        assert "Выбери источник" in cells[SLEEP_CODE, "left"]
        assert "Выбери источник" in cells[SLEEP_CODE, "right"]
    export = os.environ.get("HEALTHCHECK_STATISTICS_FIXTURES_DIR")
    if export:
        directory = Path(export)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{case}-{days}.html").write_text(response.text, encoding="utf-8")


def test_explicit_independent_selection_and_period_persistence(statistics_ui):
    session, paths, client = statistics_ui
    seed(session, paths, "ambiguous")
    garmin = session.scalar(select(GarminSource).where(GarminSource.device_attributed.is_(True)))
    google = session.scalar(
        select(GoogleSource).where(GoogleSource.source_instance_id != "synthetic-other-source")
    )
    params = dict(
        days=30, end_date=str(END), garmin_source_id=garmin.id, google_source_id=google.id
    )
    response = client.get("/statistics", params=params)
    assert response.status_code == 200
    assert f'value="{garmin.id}" selected' in response.text
    assert f'value="{google.id}" selected' in response.text
    cells = MetricParser(response.text).cells
    assert "ambiguous_google_main: 2" in cells[SLEEP_CODE, "right"]
    assert "Недоступно" in cells[SLEEP_CODE, "right"]
    assert "28800.0" in cells[SLEEP_CODE, "left"]
    for days in (7, 30):
        assert client.get("/statistics", params={**params, "days": days}).status_code == 200
    export = os.environ.get("HEALTHCHECK_STATISTICS_FIXTURES_DIR")
    if export:
        Path(export, "ambiguous-selected-30.html").write_text(response.text, encoding="utf-8")


@pytest.mark.parametrize(
    "params",
    [
        {"days": 14},
        {"garmin_source_id": "unknown"},
        {"google_source_id": "unknown"},
        {"end_date": "bad"},
        {"end_date": "0001-01-01", "days": 30},
    ],
)
def test_invalid_selection_fails_closed(statistics_ui, params):
    _, _, client = statistics_ui
    response = client.get("/statistics", params=params)
    assert response.status_code in {400, 422}


def test_statistics_has_no_write_route(statistics_ui):
    _, _, client = statistics_ui
    assert (
        client.post(
            "/statistics", data={"days": 7}, headers={"Origin": "http://127.0.0.1:8120"}
        ).status_code
        == 405
    )


def test_missing_google_keeps_the_independent_empty_side(statistics_ui):
    session, paths, client = statistics_ui
    _activity(session, paths)
    _garmin(session, paths, wake=START, attributed=True)
    session.commit()
    response = client.get("/statistics", params={"end_date": str(END)})
    assert response.status_code == 200
    cells = MetricParser(response.text).cells
    assert "28800.0" in cells[SLEEP_CODE, "left"]
    assert "Источник отсутствует" in cells[SLEEP_CODE, "right"]
    assert "Недоступно" in cells[SLEEP_CODE, "right"]
    assert "Не собирается" in cells["activity_session_count", "right"]
