"""Synthetic Context dashboard acceptance and write-boundary regressions (#294)."""

from __future__ import annotations

import logging
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from uuid import uuid4

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import select

from healthcheck.config import Settings
from healthcheck.context import (
    ContextService,
    ContextValidationError,
    parse_date_only,
    parse_interval,
    parse_timestamp,
)
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import ContextEvent, ContextEventHead, ContextEventRevision
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
        self.select = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.in_form = attrs.get("id") == "context-form"
        if self.in_form and tag == "input":
            self.values[attrs["name"]] = attrs.get("value", "")
        if self.in_form and tag == "select" and "disabled" not in attrs:
            self.select = attrs["name"]
            self.values[self.select] = ""
        if self.select and tag == "option" and "selected" in attrs:
            self.values[self.select] = attrs.get("value", "")
        if self.in_form and tag == "textarea":
            self.in_text = True
            self.values["original_text"] = ""

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_form = False
        if tag == "select":
            self.select = None
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
            {"event_time": "19:30", "timezone_name": "Europe/Moscow"},
            "instant",
            "minute",
        ),
        ({"event_time": "19:30:10.123456", "timezone_name": "UTC"}, "instant", "microsecond"),
        ({"end_date": "2099-01-05"}, "interval", "date"),
        (
            {
                "event_time": "19:30:00",
                "end_date": "2099-01-02",
                "end_time": "21:00:00",
                "timezone_name": "Europe/Moscow",
            },
            "interval",
            "second",
        ),
        (
            {
                "event_date": "2026-11-01",
                "event_time": "01:30",
                "occurrence": "first",
                "timezone_name": "America/New_York",
            },
            "instant",
            "minute",
        ),
        (
            {
                "event_date": "2026-11-01",
                "event_time": "01:30",
                "occurrence": "second",
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
        {"offset": "+03:00"},  # Obsolete/foreign adapter field, never an offset override.
        {"timezone_name": "Europe/Moscow"},
        {"event_time": "19:30", "timezone_name": "Invalid/Zone"},
        {"end_time": "21:00"},
        {"end_date": "2099-01-01"},
        {"event_time": "19:30", "timezone_name": "Europe/Moscow", "end_date": "2099-01-02"},
        {
            "event_time": "19:30",
            "timezone_name": "Europe/Moscow",
            "end_date": "2099-01-02",
            "end_time": "18:30",
        },
        {
            "event_time": "19:30",
            "timezone_name": "UTC",
            "end_date": "2099-01-03",
            "end_time": "19:30:00",
        },
        {"event_date": "2026-03-08", "event_time": "02:30", "timezone_name": "America/New_York"},
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


def test_default_date_visible_primary_navigation(ui):
    client, _, _ = ui
    response = client.get("/context")
    assert FormParser(response.text).values["event_date"] == date.today().isoformat()
    assert 'aria-label="Основные разделы"' in response.text
    assert response.text.count('href="/context"') == 1
    assert 'href="/context" class="active" aria-current="page">Комментарии</a>' in response.text
    assert "Текст сохраняется без перефразирования" in response.text


@pytest.mark.parametrize(
    "zone,day,clock,offset,utc",
    [
        ("Asia/Kathmandu", "2026-01-02", "00:15", "+05:45", "2026-01-01T18:30:00+00:00"),
        (
            "Australia/Adelaide",
            "2026-07-02",
            "12:00:10.123400",
            "+09:30",
            "2026-07-02T02:30:10.123400+00:00",
        ),
        ("America/St_Johns", "2026-01-02", "00:15", "-03:30", "2026-01-02T03:45:00+00:00"),
        ("Pacific/Kiritimati", "2026-01-02", "00:15", "+14:00", "2026-01-01T10:15:00+00:00"),
        ("Pacific/Pago_Pago", "2026-01-02", "23:15", "-11:00", "2026-01-03T10:15:00+00:00"),
    ],
)
def test_city_zone_exact_numeric_offsets(ui, zone, day, clock, offset, utc):
    client, engine, _ = ui
    response = client.post(
        "/context",
        data=payload(
            event_date=day,
            event_time=clock,
            timezone_name=zone,
        ),
    )
    assert response.status_code == 200
    row = rows(engine)[0]
    assert row.start_source_timestamp == f"{day}T{clock}{offset}"
    assert row.start_at_utc.replace(tzinfo=UTC) == datetime.fromisoformat(utc)
    assert row.start_timezone == zone
    assert 'name="offset"' not in response.text
    assert 'name="end_offset"' not in response.text


def test_fold_requires_each_endpoint_and_retry_keeps_occurrences(ui):
    client, engine, _ = ui
    form = payload(
        event_date="2026-11-01",
        event_time="01:15",
        end_date="2026-11-01",
        end_time="01:45",
        timezone_name="America/New_York",
        original_text="  Synthetic fold 日本語\n<script>bad</script>  ",
    )
    response = client.post("/context", data=form)
    assert response.status_code == 422
    assert 'name="occurrence"' in response.text and 'name="end_occurrence"' in response.text
    assert FormParser(response.text).values["original_text"] == form["original_text"]
    assert FormParser(response.text).values["operation_id"] == form["operation_id"]
    assert rows(engine) == ()
    assert client.post("/context", data={**form, "occurrence": "first"}).status_code == 422
    form.update(occurrence="first", end_occurrence="second")
    response = client.post("/context", data=form)
    assert response.status_code == 200
    row = rows(engine)[0]
    assert row.start_source_timestamp == "2026-11-01T01:15-04:00"
    assert row.end_source_timestamp == "2026-11-01T01:45-05:00"
    assert (row.end_at_utc - row.start_at_utc).total_seconds() == 5400
    assert client.post("/context", data=form).url == response.url
    edit = FormParser(response.text).values
    edit["original_text"] = "Synthetic revised fold"
    revised = client.post(f"/context/{row.event_id}", data=edit)
    assert revised.status_code == 200
    assert client.post(f"/context/{row.event_id}", data=edit).url == revised.url
    latest = rows(engine)[-1]
    assert latest.start_source_timestamp == row.start_source_timestamp
    assert latest.end_source_timestamp == row.end_source_timestamp
    assert len(rows(engine)) == 2
    # The original edit retry stays identical after a later head advance.
    fresh = FormParser(revised.text).values
    client.post(f"/context/{row.event_id}", data={**fresh, "original_text": "Synthetic third"})
    assert client.post(f"/context/{row.event_id}", data=edit).status_code == 200
    assert len(rows(engine)) == 3


@pytest.mark.parametrize(
    "fields",
    [
        {"event_date": "2026-03-08", "event_time": "02:30", "timezone_name": "America/New_York"},
        {
            "event_date": "2026-03-08",
            "event_time": "01:30",
            "end_date": "2026-03-08",
            "end_time": "02:30",
            "timezone_name": "America/New_York",
        },
        {"event_date": "2011-12-30", "event_time": "12:00", "timezone_name": "Pacific/Apia"},
        {"event_date": "1900-01-02", "event_time": "12:00", "timezone_name": "Europe/Paris"},
        {
            "event_date": "2026-01-02",
            "event_time": "12:00",
            "timezone_name": "UTC",
            "occurrence": "first",
        },
        {"event_date": "9999-12-31", "event_time": "23:59", "timezone_name": "America/New_York"},
        {"event_time": "12:00:00.1234567", "timezone_name": "UTC"},
        {
            "event_date": "2026-11-01",
            "event_time": "01:30",
            "timezone_name": "America/New_York",
            "occurrence": "second",
            "end_date": "2026-11-01",
            "end_time": "01:45",
            "end_occurrence": "first",
        },
    ],
)
def test_city_invalid_time_preserves_draft_without_write(ui, fields):
    client, engine, _ = ui
    form = payload(**fields)
    response = client.post("/context", data=form)
    assert response.status_code == 422
    read = FormParser(response.text).values
    assert read["original_text"] == form["original_text"]
    assert read["operation_id"] == form["operation_id"]
    assert rows(engine) == ()


def test_dst_interval_derives_independent_offsets(ui):
    client, engine, _ = ui
    response = client.post(
        "/context",
        data=payload(
            event_date="2026-03-08",
            event_time="01:30",
            end_date="2026-03-08",
            end_time="03:30",
            timezone_name="America/New_York",
        ),
    )
    assert response.status_code == 200
    row = rows(engine)[0]
    assert row.start_source_timestamp.endswith("-05:00")
    assert row.end_source_timestamp.endswith("-04:00")
    assert (row.end_at_utc - row.start_at_utc).total_seconds() == 3600


@pytest.mark.parametrize(
    "zone,day,clock,first,second,delta",
    [
        ("Australia/Lord_Howe", "2026-04-05", "01:45", "+11:00", "+10:30", 1800),
        ("Europe/Dublin", "2026-10-25", "01:30", "+01:00", "+00:00", 3600),
    ],
)
def test_fold_orders_actual_instants_including_half_hour_and_negative_dst(
    ui,
    zone,
    day,
    clock,
    first,
    second,
    delta,
):
    client, engine, _ = ui
    instants = []
    for occurrence, offset in [("first", first), ("second", second)]:
        response = client.post(
            "/context",
            data=payload(
                event_date=day, event_time=clock, timezone_name=zone, occurrence=occurrence
            ),
        )
        assert response.status_code == 200
        with session_scope(engine) as session:
            view = ContextService(session).list()[0]
        assert view.temporal.start_source_timestamp == f"{day}T{clock}{offset}"
        instants.append(view.temporal.start_at_utc)
    assert (instants[1] - instants[0]).total_seconds() == delta


def test_only_ambiguous_end_requires_choice(ui):
    client, engine, _ = ui
    form = payload(
        event_date="2026-11-01",
        event_time="00:30",
        end_date="2026-11-01",
        end_time="01:30",
        timezone_name="America/New_York",
    )
    response = client.post("/context", data=form)
    assert response.status_code == 422
    assert 'name="occurrence"' not in response.text
    assert 'name="end_occurrence"' in response.text
    assert rows(engine) == ()
    assert client.post("/context", data={**form, "end_occurrence": "second"}).status_code == 200


@pytest.mark.parametrize(
    "temporal",
    [
        parse_timestamp("2026-01-02T19:30Z"),
        parse_timestamp("2026-01-02T19:30:10.123400+00:00"),
        parse_timestamp("2026-01-02T19:30:00-03:30"),
        parse_timestamp("2026-01-02T19:30:00.000000+03:00", timezone_name="Europe/Moscow"),
        parse_timestamp("2026-10-25T01:30Z", timezone_name="Europe/Dublin"),
        parse_interval("2026-03-08T01:30-05:00", "2026-03-08T03:30-04:00"),
    ],
)
def test_text_only_edit_preserves_original_temporal_representation(ui, temporal):
    client, engine, _ = ui
    with session_scope(engine) as session:
        original = ContextService(session).add(
            text="Synthetic legacy", temporal=temporal, tags=["Tennis"]
        )
    read = client.get(f"/context/{original.event_id}")
    edit = FormParser(read.text).values
    if temporal.start_timezone == "Europe/Dublin":
        assert edit["occurrence"] == "second"  # Native required select must allow text-only submit.
    edit["original_text"] = "Synthetic text-only correction"
    response = client.post(f"/context/{original.event_id}", data=edit)
    assert response.status_code == 200
    with session_scope(engine) as session:
        current = ContextService(session).list()[0]
        assert current.temporal == original.temporal
        assert current.tags == original.tags
    assert client.post(f"/context/{original.event_id}", data=edit).url == response.url
    assert len(rows(engine)) == 2
    if not temporal.start_timezone:
        changed = {**FormParser(response.text).values, "event_time": "20:30"}
        assert client.post(f"/context/{original.event_id}", data=changed).status_code == 422


@pytest.mark.parametrize("zone", [None, "Legacy/Removed"])
def test_historical_second_offset_record_text_edit_does_not_reparse_or_round(ui, zone):
    client, engine, _ = ui
    event_id = str(uuid4())
    revision_id = str(uuid4())
    with session_scope(engine) as session:
        session.add(ContextEvent(id=event_id))
        session.flush()
        # Direct INSERT models historical input without weakening append-only guards.
        session.add(
            ContextEventRevision(
                id=revision_id,
                event_id=event_id,
                revision_number=1,
                operation_id=str(uuid4()),
                operation_kind="add",
                request_fingerprint="0" * 64,
                original_text="Synthetic historical",
                capture_source="manual",
                temporal_kind="instant",
                start_precision="microsecond",
                start_local_date=date(1900, 1, 2),
                start_utc_offset_minutes=9,
                start_timezone=zone,
                start_source_timestamp="1900-01-02T12:00:10.123400+00:09:21",
                start_at_utc=datetime(1900, 1, 2, 11, 50, 49, 123400, tzinfo=UTC),
            )
        )
        session.flush()
        session.add(ContextEventHead(event_id=event_id, revision_id=revision_id))
    with session_scope(engine) as session:
        before = ContextService(session).list()[0]
    edit = FormParser(client.get(f"/context/{event_id}").text).values
    assert edit["event_time"] == "12:00:10.123400"
    assert edit["timezone_name"] == (zone or "")
    response = client.post(
        f"/context/{event_id}",
        data={**edit, "original_text": "Synthetic corrected historical"},
    )
    assert response.status_code == 200
    with session_scope(engine) as session:
        after = ContextService(session).list()[0]
        assert after.temporal == before.temporal
    assert rows(engine)[0].original_text == "Synthetic historical"
