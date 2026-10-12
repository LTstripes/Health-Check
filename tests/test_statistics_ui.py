"""Synthetic route/packet equivalence, desktop fixture exports and read-failure parity for #347."""

from __future__ import annotations

import os
import socket
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.analytics import activity_period_sessions as reader
from healthcheck.analytics.period_summary import SLEEP_CODE, PeriodSummaryService
from healthcheck.config import Settings
from healthcheck.db.engine import migrate_database
from healthcheck.db.models import GarminRecordMetric, GarminSource, GarminSourceRecord, GoogleSource
from healthcheck.google.contracts import FAMILY_ALL_SOURCES, FAMILY_GOOGLE_WEARABLES
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.runtime import prepare_runtime
from healthcheck.web.statistics import format_statistics_value, statistics_source_labels
from healthcheck.web.ui_app import create_ui_app
from test_period_summary import END, START, _activity, _coverage
from test_sleep_account_cohort import _garmin, _google
from test_sleep_metrics import projection_database as projection_database


@pytest.mark.parametrize("days", [7, 30])
@pytest.mark.parametrize("case", [
    "sole", "explicit_missing", "eligible", "conflict", "empty", "other_family", "outside", "zero",
])
def test_google_sleep_default_is_exact_and_window_bound(statistics_ui, case, days):
    session, paths, client = statistics_ui
    _garmin(session, paths, wake=START, seconds=28800, attributed=True)
    _google(session, paths, wake=START, minutes="0" if case == "zero" else "410",
            family=FAMILY_ALL_SOURCES if case == "other_family" else FAMILY_GOOGLE_WEARABLES)
    family = session.scalar(select(GoogleSource))
    _google(session, paths, wake=END, source="synthetic-alternative", nap="true")
    alternative = session.scalar(select(GoogleSource).where(GoogleSource.id != family.id))
    if case in {"eligible", "conflict"}:
        _google(session, paths, wake=START, source="synthetic-alternative", name="other-main",
                main="true", nap="false")
    if case == "conflict":
        _google(session, paths, wake=START, source="synthetic-alternative", name="other-conflict",
                main="true", nap="false")
    if case == "empty":
        from healthcheck.db.models import GoogleRecordMetric
        for metric in session.scalars(select(GoogleRecordMetric).where(
            GoogleRecordMetric.metric_code == "sleep_summary_minutes_asleep",
        )):
            metric.state, metric.value_text, metric.value_number = "null", None, None
    session.commit()
    params = {"days": days, "end_date": str(END)}
    if case == "explicit_missing":
        params["google_source_id"] = alternative.id
    if case == "outside":
        params["end_date"] = str(END + timedelta(days=40))
    response = client.get("/statistics", params=params)
    assert response.status_code == 200
    parser = MetricParser(response.text)
    text = parser.cells[SLEEP_CODE, "right"]
    if case in {"sole", "zero", "explicit_missing"}:
        chosen = alternative if case == "explicit_missing" else family
        expected = PeriodSummaryService(session).build(
            end_date=END, days=days, google_source_id=chosen.id,
        )["sides"][1]["metrics"][SLEEP_CODE]
        assert parser.values[SLEEP_CODE, "right"].strip() == format_statistics_value(
            SLEEP_CODE, expected["aggregation"]["value"],
        )
        assert chosen.id in parser.details[SLEEP_CODE, "right"]
        assert f"Допустимо: {expected['aggregation']['eligible_count']}" in text
        assert expected["aggregation"]["denominator"] in parser.details[SLEEP_CODE, "right"]
    else:
        assert parser.values[SLEEP_CODE, "right"].strip() == "Недоступно"
        assert "Выбери источник" in text
    assert "Не собирается" in parser.cells["activity_session_count", "right"]
    export = os.environ.get("HEALTHCHECK_STATISTICS_FIXTURES_DIR")
    if export:
        Path(export).mkdir(parents=True, exist_ok=True)
        (Path(export) / f"source-{case}-{days}.html").write_text(response.text, encoding="utf-8")


def test_readable_labels_disambiguate_same_model_exact_sources():
    sources = [{"source_id": f"uuid-{index}", "device_model": "Same Watch"} for index in (1, 2)]
    labels = statistics_source_labels({
        "sides": [{"position": "left", "available_sources": sources}],
    })
    assert labels == {"uuid-1": "Garmin · Same Watch · источник 1",
                      "uuid-2": "Garmin · Same Watch · источник 2"}


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
    assert "Шаги за завершённые дни" in response.text
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


def _export_failure_html(name, text):
    export = os.environ.get("HEALTHCHECK_STATISTICS_FIXTURES_DIR")
    if not export:
        return
    directory = Path(export)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(text, encoding="utf-8")


def test_uninitialized_store_uses_accepted_russian_error_document(tmp_path):
    """Uninitialized storage keeps the accepted 503 document, never raw JSON (#347 parity)."""
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        assert client.get("/statistics").status_code == 200
    app.state.engine.dispose()
    paths.database.unlink()
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        response = client.get("/statistics")
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("text/html")
    primary, technical = response.text.split('<details class="card owner-details', 1)
    assert 'role="alert"' in primary
    assert 'data-owner-state="error"' in primary
    assert "Локальное хранилище данных не готово." in primary
    assert "<h1>Статистика</h1>" in response.text
    assert 'href="/statistics" class="active" aria-current="page"' in response.text
    assert "database_unavailable" in technical
    assert "no such table" not in response.text.lower()
    assert "OperationalError" not in response.text
    details_open_tag = response.text.split("<details", 1)[1].split(">", 1)[0]
    assert "open" not in details_open_tag
    _export_failure_html("unavailable-503.html", response.text)


def test_read_failure_is_russian_alert_without_raw_internals(statistics_ui, monkeypatch):
    """Read failures keep the shared Russian alert document, never raw JSON (#347 parity)."""
    _, _, client = statistics_ui

    def failing_build(*args, **kwargs):
        raise SQLAlchemyError("synthetic Stage-7 read failure")

    monkeypatch.setattr(PeriodSummaryService, "build", failing_build)
    response = client.get("/statistics")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("text/html")
    primary, technical = response.text.split('<details class="card owner-details', 1)
    assert 'role="alert"' in primary
    assert "Не удалось показать страницу" in primary
    assert "Не удалось выполнить запрос. Попробуй повторить его." in primary
    assert "synthetic Stage-7" not in response.text
    assert "<h1>Статистика</h1>" in response.text
    assert 'href="/statistics" class="active" aria-current="page"' in response.text
    assert "persistence_error" in technical
    details_open_tag = response.text.split("<details", 1)[1].split(">", 1)[0]
    assert "open" not in details_open_tag
    _export_failure_html("read-error-500.html", response.text)


def read(session, source, **kwargs):
    return reader.read_activity_period_sessions(
        session,
        source_id=source.id,
        start_date=START,
        end_date=END,
        metric_code=kwargs.pop("metric_code", "tennis_session_count"),
        sport=kwargs.pop("sport", "tennis"),
        **kwargs,
    )


def records(session):
    return list(
        session.scalars(
            select(GarminSourceRecord)
            .where(
                GarminSourceRecord.stream_code == "activity",
            )
            .order_by(GarminSourceRecord.id)
        )
    )


@pytest.mark.parametrize("count", [0, 1, 2, 51])
def test_saved_window_empty_singleton_same_day_beyond_journal_limit(projection_database, count):
    session, paths = projection_database
    _activity(session, paths, kind="tennis", count=max(count, 1))
    source = session.scalar(select(GarminSource))
    if not count:
        rows = records(session)
        rows[0].source_local_date = START - timedelta(days=1)
    session.flush()
    packet = read(session, source)
    assert packet["complete"] and packet["reason"] is None
    assert len(packet["sessions"]) == count
    assert all(item["source_local_date"] == str(START) for item in packet["sessions"])


def test_boundaries_sports_source_local_not_utc_and_source_separation(projection_database):
    session, paths = projection_database
    for offset in [-1, 0, 6, 7]:
        _activity(
            session, paths, kind="tennis_v2", day=START + timedelta(days=offset), suffix=str(offset)
        )
    _activity(session, paths, kind="cycling", suffix="other-sport")
    _activity(session, paths, kind="tennis", suffix="other-source", attributed=False)
    source = session.scalar(select(GarminSource).where(GarminSource.device_attributed.is_(True)))
    for row in records(session):
        row.source_timestamp_utc = datetime(2080, 1, 1, tzinfo=UTC)
    session.flush()
    packet = read(session, source)
    assert {i["source_local_date"] for i in packet["sessions"]} == {str(START), str(END)}
    assert len(packet["sessions"]) == 2
    assert (
        len(read(session, source, metric_code="activity_session_count", sport="all")["sessions"])
        == 3
    )
    assert (
        len(
            read(session, source, metric_code="cycling_distance_meters", sport="cycling")[
                "sessions"
            ]
        )
        == 1
    )


@pytest.mark.parametrize("case", ["missing", "null", "invalid", "unit", "negative", "zero"])
def test_originating_metric_eligibility_matches_statistics(projection_database, case):
    session, paths = projection_database
    _activity(session, paths, kind="tennis_v2")
    source = session.scalar(select(GarminSource))
    metric = session.scalar(
        select(GarminRecordMetric).where(
            GarminRecordMetric.metric_code == "duration_seconds",
        )
    )
    if case in {"missing", "null", "invalid"}:
        metric.state, metric.value_number, metric.value_text = case, None, None
    elif case == "unit":
        metric.unit = "minutes"
    else:
        metric.value_number = -1 if case == "negative" else 0
    session.flush()
    summary = PeriodSummaryService(session).build(days=7, end_date=END)["sides"][0]["metrics"]
    for code in ["tennis_session_count", "tennis_duration_seconds"]:
        packet = read(session, source, metric_code=code)
        assert len(packet["sessions"]) == summary[code]["aggregation"]["eligible_count"]
        assert len(packet["sessions"]) == (1 if code.endswith("count") or case == "zero" else 0)
    count_row = read(session, source)["sessions"][0]
    assert count_row["metrics"]["duration_seconds"]["state"] == metric.state
    assert count_row["metrics"]["duration_seconds"]["value"] == metric.value_number
    assert count_row["metrics"]["duration_seconds"]["unit"] == metric.unit


def test_invalid_retired_duplicate_current_identity_across_sport(projection_database):
    session, paths = projection_database
    _activity(session, paths, kind="tennis", count=5)
    rows = records(session)
    rows[0].record_status = "invalid"
    rows[1].projection_status = "retired"
    rows[1].retired_at = datetime.now(UTC)
    rows[1].retire_reason = "synthetic-test"
    rows[2].external_record_id = rows[3].external_record_id
    rows[3].activity_type = "cycling"
    session.flush()
    source = session.scalar(select(GarminSource))
    assert [i["record_id"] for i in read(session, source)["sessions"]] == [rows[4].id]


@pytest.mark.parametrize("count", [2, 3, 4])
@pytest.mark.parametrize("cap_type", ["candidate", "display"])
def test_explicit_caps_and_extra_record(projection_database, monkeypatch, count, cap_type):
    session, paths = projection_database
    _activity(session, paths, kind="tennis", count=count)
    source = session.scalar(select(GarminSource))
    monkeypatch.setattr(
        reader, "MAX_CANDIDATE_RECORDS" if cap_type == "candidate" else "MAX_DISPLAY_SESSIONS", 3
    )
    packet = read(session, source)
    assert packet["complete"] == (count <= 3)
    if count > 3:
        assert packet["reason"] == (
            "candidate_record_limit_exceeded"
            if cap_type == "candidate"
            else "display_session_limit_exceeded"
        )
        assert len(packet["sessions"]) == (0 if cap_type == "candidate" else 3)
    else:
        assert len(packet["sessions"]) == count


def test_budget_incomplete_never_empty(projection_database, monkeypatch):
    session, paths = projection_database
    _activity(session, paths, kind="tennis")
    source = session.scalar(select(GarminSource))

    def exhausted(*args, **kwargs):
        raise reader.IncompletePeriodRead("time_budget_exceeded")

    monkeypatch.setattr(reader.PeriodReadBudget, "check", exhausted)
    packet = read(session, source)
    assert not packet["complete"] and packet["reason"] == "time_budget_exceeded"
    assert not packet["sessions"]


class Links(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs))


@pytest.mark.parametrize("period", ["7", "30", "calendar_year", "year_to_date", "trailing365"])
def test_statistics_resolved_source_window_handoff_and_return(statistics_ui, period):
    session, paths, client = statistics_ui
    _activity(session, paths, kind="tennis_v2", count=2)
    source = session.scalar(select(GarminSource))
    ids = {r.id for r in records(session)}
    session.commit()
    statements = []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(session.bind, "before_cursor_execute", capture)
    try:
        # No explicit source: the link must carry the source resolved by Statistics.
        response = client.get(
            "/statistics",
            params={"period": period, "end_date": str(END), "calendar_year": END.year},
        )
        link = next(
            a["href"]
            for a in Links(response.text).links
            if a.get("data-session-drilldown") == "tennis_session_count"
        )
        params = parse_qs(urlsplit(link).query)
        assert params["garmin_source_id"] == [source.id]
        drilldown = client.get(link)
        assert drilldown.status_code == 200
        assert drilldown.headers["cache-control"] == "no-store"
        details = [
            a["href"]
            for a in Links(drilldown.text).links
            if a["href"].startswith("/garmin/session?")
        ]
        assert len(details) == 2
        assert {parse_qs(urlsplit(href).query)["record_id"][0] for href in details} == ids
        for href in details:
            query = parse_qs(urlsplit(href).query)
            assert query["garmin_source_id"] == params["garmin_source_id"]
            assert query["start_date"] == params["start_date"]
            assert query["end_date"] == params["end_date"]
            assert query["origin_metric_code"] == params["metric_code"]
            assert "metric_code" not in query
            detail = client.get(href)
            assert detail.status_code == 200
            assert query["record_id"][0] in detail.text
        back = next(a["href"] for a in Links(drilldown.text).links if "data-statistics-return" in a)
        back_query = parse_qs(urlsplit(back).query)
        assert back_query["period"] == [period]
        assert back_query["garmin_source_id"] == [source.id]
        assert back_query["end_date"] == [str(END)]
        assert client.get(back).status_code == 200
    finally:
        event.remove(session.bind, "before_cursor_execute", capture)
    assert statements and set(statements) <= {"SELECT", "BEGIN", "PRAGMA"}


@pytest.mark.parametrize(
    "override",
    [
        {"garmin_source_id": "unknown"},
        {"metric_code": "sleep_duration_asleep_seconds"},
        {"metric_code": "made-up"},
        {"sport": "cycling"},
        {"start_date": str(END + timedelta(days=1))},
        {"start_date": str(END - timedelta(days=366))},
        {"origin_period": "made-up"},
    ],
)
def test_route_rejects_invalid_context(statistics_ui, override):
    session, paths, client = statistics_ui
    _activity(session, paths, kind="tennis")
    source = session.scalar(select(GarminSource))
    session.commit()
    response = client.get(
        "/statistics/sessions",
        params={
            "garmin_source_id": source.id,
            "metric_code": "tennis_session_count",
            "sport": "tennis",
            "start_date": str(START),
            "end_date": str(END),
            **override,
        },
    )
    assert response.status_code == 400


def test_route_read_failure_and_incomplete_copy(statistics_ui, monkeypatch):
    session, paths, client = statistics_ui
    _activity(session, paths, kind="tennis", count=2)
    source = session.scalar(select(GarminSource))
    session.commit()
    params = {
        "garmin_source_id": source.id,
        "metric_code": "tennis_session_count",
        "sport": "tennis",
        "start_date": str(START),
        "end_date": str(END),
    }
    monkeypatch.setattr(reader, "MAX_CANDIDATE_RECORDS", 1)
    response = client.get("/statistics/sessions", params=params)
    assert "Список неполный" in response.text and "нет допустимых сессий" not in response.text

    def failed(*args, **kwargs):
        raise SQLAlchemyError("synthetic failure")

    monkeypatch.setattr("healthcheck.web.activity_period.read_activity_period_sessions", failed)
    assert client.get("/statistics/sessions", params=params).status_code == 500
