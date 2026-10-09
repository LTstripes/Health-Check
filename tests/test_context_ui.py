"""Synthetic Context dashboard acceptance and write-boundary regressions (#294)."""

from __future__ import annotations

import logging
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html.parser import HTMLParser
from uuid import uuid4

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import select

from healthcheck.config import Settings
from healthcheck.context import ContextService, ContextValidationError, parse_date_only
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import ContextEventRevision
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.runtime import prepare_runtime
from healthcheck.web.ui_app import create_ui_app

BASE = "http://127.0.0.1:8120"


class FormParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.values = {}
        self.in_form = False
        self.in_text = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.in_form = attrs.get("id") == "context-form"
        if self.in_form and tag == "input":
            self.values[attrs["name"]] = attrs.get("value", "")
        if self.in_form and tag == "textarea":
            self.in_text = True
            self.values["original_text"] = ""

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_form = False
        if tag == "textarea":
            self.in_text = False
            # HTML strips its first LF; the template supplies one to preserve the original.
            self.values["original_text"] = self.values["original_text"].removeprefix("\n")

    def handle_data(self, data):
        if self.in_text:
            self.values["original_text"] += data


@pytest.fixture
def ui(tmp_path, monkeypatch):
    original_connect = socket.socket.connect

    def local_only(sock, address):
        # Windows asyncio uses a loopback socketpair; remote/provider sockets remain blocked.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        raise AssertionError("Context must not call an external network/provider")

    def forbidden(*args, **kwargs):
        raise AssertionError("Context must not call a network/provider")

    monkeypatch.setattr(socket.socket, "connect", local_only)
    monkeypatch.setattr(requests.Session, "request", forbidden)
    settings = Settings(data_dir=tmp_path / "synthetic")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())
    engine = create_sqlite_engine(paths)
    with TestClient(app, base_url=BASE, headers={"Origin": BASE}) as client:
        yield client, engine, settings
    engine.dispose()
    if getattr(app.state, "engine", None):
        app.state.engine.dispose()


def payload(**changes):
    return {
        "event_date": "2099-01-02",
        "original_text": "Synthetic комментарий",
        "operation_id": str(uuid4()),
        **changes,
    }


def rows(engine):
    with session_scope(engine) as session:
        return tuple(
            session.scalars(
                select(ContextEventRevision).order_by(ContextEventRevision.revision_number)
            )
        )


def test_date_only_unicode_source_escaping_and_restart(ui):
    client, engine, settings = ui
    original = '  Текст ё 日本語\n<script>window.bad=1</script>& "  '
    response = client.post("/context", data=payload(original_text=original))
    assert response.status_code == 200
    assert "Сохранено" in response.text
    assert "&lt;script&gt;" in response.text
    assert "<script>window.bad" not in response.text
    assert response.headers["cache-control"] == "no-store"
    (row,) = rows(engine)
    assert row.original_text == original
    assert row.capture_source == "dashboard"
    assert row.start_precision == "date"
    assert row.start_at_utc is row.start_source_timestamp is row.start_timezone is None
    assert "Записано автоматически" in response.text
    assert FormParser(response.text).values["original_text"] == original
    app, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())
    with TestClient(app, base_url=BASE) as restarted:
        readback = restarted.get(f"/context/{row.event_id}")
        assert FormParser(readback.text).values["original_text"] == original
        assert f'data-revision="{row.id}"' in readback.text
    app.state.engine.dispose()


@pytest.mark.parametrize(
    "fields,kind,precision",
    [
        (
            {"event_time": "19:30", "offset": "+03:00", "timezone_name": "Europe/Moscow"},
            "instant",
            "minute",
        ),
        ({"event_time": "19:30:10.123456", "offset": "Z"}, "instant", "microsecond"),
        ({"end_date": "2099-01-05"}, "interval", "date"),
        (
            {
                "event_time": "19:30:00",
                "offset": "+03:00",
                "end_date": "2099-01-02",
                "end_time": "21:00:00",
                "end_offset": "+03:00",
                "timezone_name": "Europe/Moscow",
            },
            "interval",
            "second",
        ),
        (
            {
                "event_date": "2026-11-01",
                "event_time": "01:30",
                "offset": "-04:00",
                "timezone_name": "America/New_York",
            },
            "instant",
            "minute",
        ),
        (
            {
                "event_date": "2026-11-01",
                "event_time": "01:30",
                "offset": "-05:00",
                "timezone_name": "America/New_York",
            },
            "instant",
            "minute",
        ),
    ],
)
def test_explicit_time_ranges_precision_roundtrip(ui, fields, kind, precision):
    client, engine, _ = ui
    response = client.post("/context", data=payload(**fields))
    assert response.status_code == 200
    (row,) = rows(engine)
    assert (row.temporal_kind, row.start_precision) == (kind, precision)
    readback = FormParser(response.text).values
    for key, value in fields.items():
        assert readback[key] == value
    response = client.post(f"/context/{row.event_id}", data=readback)
    assert response.status_code == 200
    new = rows(engine)[-1]
    assert new.start_source_timestamp == row.start_source_timestamp
    assert new.end_source_timestamp == row.end_source_timestamp
    assert new.start_timezone == row.start_timezone


@pytest.mark.parametrize(
    "fields",
    [
        {"original_text": " \n "},
        {"original_text": "x\x00y"},
        {"original_text": "x" * 4001},
        {"event_date": "2099-02-30"},
        {"event_date": "today"},
        {"event_time": "19:30"},
        {"offset": "+03:00"},
        {"timezone_name": "Europe/Moscow"},
        {"event_time": "19:30", "offset": "-00:00"},
        {"event_time": "19:30", "offset": "+02:00", "timezone_name": "Europe/Moscow"},
        {"event_time": "19:30", "offset": "Z", "timezone_name": "Invalid/Zone"},
        {"end_time": "21:00"},
        {"end_date": "2099-01-01"},
        {"event_time": "19:30", "offset": "+03:00", "end_date": "2099-01-02"},
        {
            "event_time": "19:30",
            "offset": "+03:00",
            "end_date": "2099-01-02",
            "end_time": "18:30",
            "end_offset": "+03:00",
        },
        {
            "event_time": "19:30",
            "offset": "Z",
            "end_date": "2099-01-03",
            "end_time": "19:30:00",
            "end_offset": "Z",
        },
        {
            "event_date": "2026-03-08",
            "event_time": "02:30",
            "offset": "-05:00",
            "timezone_name": "America/New_York",
        },
        {"event_date": "2026-11-01", "event_time": "01:30", "timezone_name": "America/New_York"},
    ],
)
def test_invalid_bounds_time_dst_no_writes(ui, fields):
    client, engine, _ = ui
    response = client.post("/context", data=payload(**fields))
    assert response.status_code == 422
    assert "Проверь текст" in response.text
    assert rows(engine) == ()


def test_retries_conflict_revision_history_and_stale_draft(ui):
    client, engine, _ = ui
    add = payload()
    first = client.post("/context", data=add)
    retry = client.post("/context", data=add)
    assert first.url == retry.url
    (row,) = rows(engine)
    stale = FormParser(first.text).values
    revise = {**stale, "original_text": "Synthetic исправление"}
    revised = client.post(f"/context/{row.event_id}", data=revise)
    assert revised.status_code == 200
    assert client.post(f"/context/{row.event_id}", data=revise).url == revised.url
    conflict = client.post(
        f"/context/{row.event_id}",
        data={**stale, "original_text": "Synthetic stale draft", "operation_id": str(uuid4())},
    )
    assert conflict.status_code == 409
    assert FormParser(conflict.text).values["original_text"] == "Synthetic stale draft"
    assert len(rows(engine)) == 2
    conflict = client.post("/context", data={**add, "original_text": "different"})
    assert conflict.status_code == 409
    older_retry = client.post("/context", data=add)
    assert "более новая актуальная версия" in older_retry.text
    assert "История исправлений</h2>" not in revised.text
    history = client.get(f"/context/{row.event_id}?history=1")
    assert "История исправлений</h2>" in history.text
    assert "Предыдущая" in history.text
    assert row.original_text in history.text
    assert "Synthetic исправление" in history.text


def test_simultaneous_retry_and_stale_edits(ui):
    client, engine, _ = ui
    form = payload()
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = tuple(pool.map(lambda _: client.post("/context", data=form), range(2)))
    assert [reply.status_code for reply in replies] == [200, 200]
    assert len(rows(engine)) == 1
    edit = FormParser(replies[0].text).values
    event = rows(engine)[0].event_id
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = tuple(
            pool.map(
                lambda i: client.post(
                    f"/context/{event}",
                    data={
                        **edit,
                        "original_text": f"Synthetic editor {i}",
                        "operation_id": str(uuid4()),
                    },
                ),
                range(2),
            )
        )
    assert sorted(reply.status_code for reply in replies) == [200, 409]
    assert len(rows(engine)) == 2


def test_filtered_overlap_bounded_list_and_history(ui):
    client, engine, _ = ui
    with session_scope(engine) as session:
        service = ContextService(session)
        for i in range(51):
            service.add(text=f"Synthetic {i}", temporal=parse_date_only("2099-01-02"))
    response = client.get("/context?from_date=2099-01-01&to_date=2099-01-03")
    assert response.text.count('data-revision="') == 50
    assert "Есть ещё" in response.text
    assert "комментариев нет" in client.get("/context?from_date=2099-01-03&to_date=2099-01-04").text
    assert client.get("/context?from_date=2099-01-03&to_date=2099-01-01").status_code == 422
    assert client.get("/context?from_date=invalid").status_code == 422
    client.post("/context", data=payload(end_date="2099-01-05", original_text="overlap"))
    assert "overlap" in client.get("/context?from_date=2099-01-04&to_date=2099-01-04").text
    event = rows(engine)[0].event_id
    with session_scope(engine) as session:
        service = ContextService(session)
        for i in range(51):
            service.revise(event, text=f"Synthetic revision {i}")
    response = client.get(f"/context/{event}?history=1")
    assert response.text.count('data-revision="') == 51  # current + 50 history entries
    assert "Есть ещё" in response.text


def test_origin_host_encoding_duplicate_and_input_bounds(ui, caplog):
    client, engine, _ = ui
    marker = "synthetic-private-marker"
    form = payload(original_text=marker)
    with caplog.at_level(logging.DEBUG):
        assert (
            client.post("/context", data=form, headers={"Origin": "http://evil.test"}).status_code
            == 403
        )
        assert (
            client.post("/context", data=form, headers={"Host": "evil.test:8120"}).status_code
            == 403
        )
        with TestClient(client.app, base_url=BASE) as no_origin:
            assert no_origin.post("/context", data=form).status_code == 403
        assert client.post("/context", json=form).status_code == 422
        assert (
            client.post(
                "/context",
                content="event_date=2099-01-02&event_date=2099-01-03",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ).status_code
            == 422
        )
        assert client.post("/context", data={**form, "capture_source": "cli"}).status_code == 422
        assert (
            client.post(
                "/context",
                content="original_text=" + "x" * 65536,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ).status_code
            == 422
        )
    assert marker not in caplog.text
    assert rows(engine) == ()


def test_unavailable_storage_and_invalid_event_sanitized(ui, caplog):
    client, engine, _ = ui
    assert client.get(f"/context/{uuid4()}").status_code == 404
    assert client.get("/context/not-a-uuid").status_code == 422
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE context_event_heads")
    marker = "synthetic-private-unavailable-marker"
    assert client.get("/context").status_code == 503
    response = client.post("/context", data=payload(original_text=marker))
    assert response.status_code == 503
    assert marker not in caplog.text
    assert FormParser(response.text).values["original_text"] == marker


def test_dashboard_service_preserves_tags_and_reserved_source_stays_closed(ui):
    _, engine, _ = ui
    with session_scope(engine) as session:
        service = ContextService(session)
        view = service.add(
            text="Synthetic",
            temporal=parse_date_only("2099-01-02"),
            capture_source="dashboard",
            tags=["Теннис"],
        )
        assert view.tags[0].provenance_source == "dashboard"
        revised = service.revise(
            view.event_id, text="Synthetic correction", capture_source="dashboard"
        )
        assert revised.tags == view.tags
        with pytest.raises(ContextValidationError):
            service.add(
                text="Synthetic", temporal=parse_date_only("2099-01-02"), capture_source="telegram"
            )


def test_default_date_visible_secondary_navigation(ui):
    client, _, _ = ui
    response = client.get("/context")
    assert FormParser(response.text).values["event_date"] == date.today().isoformat()
    assert 'aria-label="Основные разделы"' in response.text
    assert response.text.count('href="/context"') >= 1
    assert "Текст сохраняется без перефразирования" in response.text
