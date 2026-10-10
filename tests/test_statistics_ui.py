"""Synthetic route/packet equivalence and desktop fixture exports for #347 B2."""

from __future__ import annotations

import os
import socket
from copy import deepcopy
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
from healthcheck.web.statistics import format_statistics_value
from healthcheck.web.ui_app import create_ui_app
from test_period_summary import END, START, _activity, _coverage
from test_sleep_account_cohort import _garmin, _google
from test_sleep_metrics import projection_database as projection_database


class MetricParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.cells = {}
        self.values = {}
        self.details = {}
        self.code = self.side = None
        self.in_article = False
        self.in_value = self.in_details = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-statistics-metric" in attrs:
            self.code = attrs["data-statistics-metric"]
        if tag == "article":
            self.side = attrs["data-statistics-side"]
            self.in_article = True
            self.cells[self.code, self.side] = ""
            self.values[self.code, self.side] = ""
            self.details[self.code, self.side] = ""
        if tag == "div" and attrs.get("class") == "statistics-value":
            self.in_value = True
        if tag == "details" and self.in_article:
            self.in_details = True

    def handle_endtag(self, tag):
        if tag == "article":
            self.in_article = False
        if tag == "div":
            self.in_value = False
        if tag == "details":
            self.in_details = False

    def handle_data(self, data):
        if self.in_article:
            self.cells[self.code, self.side] += data
            if self.in_value:
                self.values[self.code, self.side] += data
            if self.in_details:
                self.details[self.code, self.side] += data


def seed(session, paths, case):
    if case == "missing":
        return
    _activity(
        session,
        paths,
        kind="cycling",
        distance=0 if case == "sparse" else 12345.6 if case == "fractional" else 21000,
    )
    _activity(
        session,
        paths,
        kind="tennis_v2",
        suffix="tennis",
        duration=3661.25 if case == "fractional" else 0 if case == "zero" else 3600,
    )
    nights = 7 if case == "full" else 1
    for offset in range(nights):
        day = START + timedelta(days=offset)
        _garmin(
            session,
            paths,
            wake=day,
            attributed=True,
            seconds=28830.5 if case == "fractional" else 0 if case == "zero" else 28800,
        )
        _google(
            session,
            paths,
            wake=day,
            main="true",
            nap="false",
            minutes="410.5" if case == "fractional" else "410",
        )
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


@pytest.mark.parametrize("case", ["full", "sparse", "missing", "ambiguous", "fractional", "zero"])
@pytest.mark.parametrize("days", [7, 30])
def test_route_matches_accepted_packet(statistics_ui, monkeypatch, case, days):
    session, paths, client = statistics_ui
    seed(session, paths, case)
    packet = PeriodSummaryService(session).build(end_date=END, days=days)
    original_build = PeriodSummaryService.build
    rendered_packets = []

    def capture_packet(service, **kwargs):
        result = original_build(service, **kwargs)
        rendered_packets.append((result, deepcopy(result)))
        return result

    monkeypatch.setattr(PeriodSummaryService, "build", capture_packet)
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
    parser = MetricParser(response.text)
    cells = parser.cells
    assert len(rendered_packets) == 1
    actual, before_render = rendered_packets[0]
    assert actual == before_render
    assert {k: v for k, v in actual.items() if k != "evaluated_at"} == {
        k: v for k, v in packet.items() if k != "evaluated_at"
    }
    assert len(cells) == 12
    for side in packet["sides"]:
        for code, cell in side["metrics"].items():
            text = cells[code, side["position"]]
            value = cell["aggregation"]["value"]
            headline = parser.values[code, side["position"]].strip()
            details = parser.details[code, side["position"]]
            if value is None:
                assert headline == "Недоступно"
            elif isinstance(value, dict):
                for kind, count in value.items():
                    assert f"{kind}: {int(count)} сессий" in headline
            else:
                assert headline == format_statistics_value(code, value)
            assert f"{value if value is not None else 'Недоступно'} / " in details
            numerator = cell["aggregation"]["numerator"]
            assert f"/ {numerator if numerator is not None else 'Недоступно'}" in details
            if cell["state"] in {"source_missing", "selection_required", "not_collected"}:
                assert "Наблюдения и знаменатель не оценены" in text
                assert "Допустимо: 0" not in text
                assert "без наблюдений" not in text
            else:
                assert f"Допустимо: {cell['aggregation']['eligible_count']}" in text
                assert f"без наблюдений {cell['missing_day_count']} дней" in text
                assert cell["coverage"]["state"] in text
            assert f"{cell['source_unit']} → {cell['unit']}" in details
            assert cell["conversion"] in details
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
        # Navigation must retain identities from the SAME persisted database.
        # Each pytest parameter has a fresh DB; export both windows together.
        for window in (7, 30):
            rendered = client.get("/statistics", params={"days": window, "end_date": str(END)})
            assert rendered.status_code == 200
            (directory / f"{case}-{window}.html").write_text(rendered.text, encoding="utf-8")
            if case == "ambiguous":
                garmin = session.scalar(
                    select(GarminSource).where(GarminSource.device_attributed.is_(True))
                )
                google = session.scalar(
                    select(GoogleSource).where(
                        GoogleSource.source_instance_id != "synthetic-other-source"
                    )
                )
                selected = client.get(
                    "/statistics",
                    params=dict(
                        days=window,
                        end_date=str(END),
                        garmin_source_id=garmin.id,
                        google_source_id=google.id,
                    ),
                )
                assert selected.status_code == 200
                (directory / f"ambiguous-selected-{window}.html").write_text(
                    selected.text, encoding="utf-8"
                )


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
    assert "8 ч 0 мин" in cells[SLEEP_CODE, "left"]
    for days in (7, 30):
        assert client.get("/statistics", params={**params, "days": days}).status_code == 200


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
    assert "8 ч 0 мин" in cells[SLEEP_CODE, "left"]
    assert "Источник отсутствует" in cells[SLEEP_CODE, "right"]
    assert "Недоступно" in cells[SLEEP_CODE, "right"]
    assert "Не собирается" in cells["activity_session_count", "right"]


@pytest.mark.parametrize(
    "code,value,expected",
    [
        (SLEEP_CODE, None, "Недоступно"),
        (SLEEP_CODE, 0.0, "0 мин"),
        (SLEEP_CODE, 28800.0, "8 ч 0 мин"),
        (SLEEP_CODE, 24600.0, "6 ч 50 мин"),
        (SLEEP_CODE, 28830.5, "8 ч 0 мин 30,5 с"),
        (SLEEP_CODE, 0.001, "<0,01 с"),
        ("tennis_duration_seconds", None, "Недоступно"),
        ("tennis_duration_seconds", 0, "0 мин"),
        ("tennis_duration_seconds", 3600.0, "1 ч 0 мин"),
        ("tennis_duration_seconds", 3661.25, "1 ч 1 мин 1,25 с"),
        ("tennis_duration_seconds", 59.999, "1 мин"),
        ("cycling_distance_meters", None, "Недоступно"),
        ("cycling_distance_meters", 0.0, "0 км"),
        ("cycling_distance_meters", 21000, "21 км"),
        ("cycling_distance_meters", 12345.6, "12,35 км"),
        ("cycling_distance_meters", 999995, "1000 км"),
        ("cycling_distance_meters", 1, "<0,01 км"),
        ("activity_session_count", 2.0, "2 сессий"),
        ("activity_session_count", 0.0, "0 сессий"),
        ("tennis_session_count", 1.0, "1 сессий"),
        ("activity_type_counts", 2.0, "2 сессий"),
    ],
)
def test_headline_formatting(code, value, expected):
    assert format_statistics_value(code, value) == expected
