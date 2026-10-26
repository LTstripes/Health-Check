"""Lighter UI contracts over synthetic saved data and unchanged production readers."""

import json
import os
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from healthcheck.config import Settings
from healthcheck.db.models import GarminSourceRecord
from healthcheck.web import pages
from healthcheck.web.ui_app import create_ui_app
from overview_html import parse_overview
from test_overview_completed import NOW, seed_completed
from test_overview_completed import database as database
from test_sleep_evidence import CLOCK, DAY
from test_sleep_evidence import profile as _sleep_profile
from test_statistics_ui import projection_database as projection_database
from test_statistics_ui import statistics_ui as statistics_ui

sleep_profile = _sleep_profile


def capture(name, value):
    if directory := os.environ.get("HC492_CAPTURE_DIR"):
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(value, encoding="utf-8")


def assert_period_tooltip(html, *, empty=False):
    document = parse_overview(html)
    tooltip = document.one(id="overview-period-scope")
    assert tooltip.attrs.get("role") == "tooltip"
    trigger = document.one("p", classes={"brief-period"})
    assert trigger.attrs.get("tabindex") == "0"
    assert "overview-period-scope" in trigger.attrs.get("aria-describedby", "").split()
    assert trigger.one(id="overview-period-scope") is tooltip
    spans = [child for child in tooltip.children if getattr(child, "tag", None) == "span"]
    assert len(spans) == 2
    requested_start = "8" if empty else "1"
    assert spans[0].text.strip() == (
        f"Вес и активности: {requested_start} января 2099 — 8 января 2099.")
    completed = ("в выбранном периоде нет завершённых дней по МСК" if empty else
                 "1 января 2099 — 7 января 2099 · завершённые дни, МСК")
    assert spans[1].text.strip() == f"Сон, шаги, стресс и Body Battery: {completed}."


@pytest.mark.parametrize("mode", ["filled", "empty", "partial"])
def test_one_period_description_replaces_card_ranges_without_changing_windows(
    database, monkeypatch, mode,
):
    source_id = None
    settings = Settings(data_dir=database[0].root)
    if mode != "empty":
        source_id, settings = seed_completed(database)
    if mode == "partial":
        for record in database[2].scalars(select(GarminSourceRecord)):
            record.record_status = "partial"
        database[2].commit()

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(pages, "datetime", FrozenDatetime)
    with TestClient(create_ui_app(settings)[0], base_url="http://127.0.0.1:8120") as client:
        response = client.get("/brief", params={"start_date": "2099-01-01",
            "end_date": "2099-01-08", "garmin_source_id": source_id or ""})
        empty = client.get("/brief?start_date=2099-01-08&end_date=2099-01-08")
    assert response.status_code == empty.status_code == 200
    assert response.context["packet"]["period"]["end_date"] == "2099-01-08"
    assert response.context["overview"]["completed_window"]["end_date"] == "2099-01-07"
    assert response.context["overview"]["steps"]["window"] == response.context["overview"][
        "completed_window"]
    assert_period_tooltip(response.text)
    assert_period_tooltip(empty.text, empty=True)
    if mode == "filled":
        harmless = response.text.replace(
            'class="overview-period-tooltip" id="overview-period-scope" role="tooltip"',
            'role="tooltip" class="extra overview-period-tooltip" id="overview-period-scope"')
        harmless = harmless.replace(
            'class="brief-period" tabindex="0" aria-describedby="overview-period-scope"',
            'aria-describedby="overview-period-scope" tabindex="0" class="extra brief-period"')
        assert_period_tooltip(harmless)
        document = parse_overview(response.text)
        tooltip_text = document.one(id="overview-period-scope").text
        # Text moved outside the nested tooltip must never satisfy its contract.
        start = response.text.index('<span class="overview-period-tooltip"')
        end = response.text.index('</span></span>', start) + len('</span></span>')
        mutations = {
            "outside text": response.text[:start] +
                '<span id="overview-period-scope" role="tooltip"></span>' +
                tooltip_text + response.text[end:],
            "wrong date": response.text[:start] +
                response.text[start:end].replace('7 января 2099', '6 января 2099') +
                response.text[end:],
            "missing aria": response.text.replace(
                'aria-describedby="overview-period-scope"', ''),
            "wrong role": response.text.replace('role="tooltip"', 'role="note"'),
            "duplicate target": response.text +
                '<span id="overview-period-scope" role="tooltip"></span>',
        }
        for name, mutated in mutations.items():
            assert mutated != response.text, name
            with pytest.raises(AssertionError):
                assert_period_tooltip(mutated)
    assert 'data-period-coverage' not in response.text
    assert 'data-overview-chart="stress"' not in response.text
    for removed in ["data-weekly-preview", "overview-download", "overview-all-sources",
                    "brief-limitations", "brief-sleep", "brief-provenance"]:
        assert removed not in response.text
    assert '/static/overview.js' in response.text
    assert 'Наблюдения и подробности ·' not in response.text
    assert 'Покрытие дней не подтверждено полностью. Дни без записи — не ноль.' not in response.text
    assert '<a href="/weight">Последнее измерение веса</a></h3>' in response.text
    assert 'class="owner-details overview-chart-values"' not in response.text
    disclosure = parse_overview(response.text).one(
        "details", **{"data-stress-evidence": None})
    assert "overview-info" in disclosure.attrs.get("class", "").split()
    assert disclosure.one("summary").attrs.get("aria-label")
    capture(f"overview-{mode}.html", response.text)
    capture("overview-no-completed.html", empty.text)


def test_simplified_export_defaults_bind_existing_full_packet(sleep_profile, monkeypatch):
    from types import SimpleNamespace

    from healthcheck.web import analysis_export

    paths, _engine, garmin_id, google_id, _comment = sleep_profile
    monkeypatch.setattr(analysis_export, "datetime", SimpleNamespace(now=lambda _zone: CLOCK))
    app, _ = create_ui_app(Settings(data_dir=paths.root, ui_port=8120))
    with TestClient(app, base_url="http://127.0.0.1:8120",
                    headers={"Origin": "http://127.0.0.1:8120"}) as client:
        page = client.get(f"/imports?export_end_date={DAY}&export_days=7")
        inventory = client.get("/api/analysis-export/sources").json()
        body = {"days": 7, "end_date": str(DAY), "garmin_source_id": garmin_id,
                "google_hrv_source_id": google_id, "steps_view": "completed"}
        response = client.post("/api/analysis-export", json=body)
    assert response.status_code == 200
    packet = json.loads(response.json()["json"])
    assert packet["request"]["steps_view"] == "completed"
    assert set(packet["sections"]) == {
        "sleep", "activity", "context", "stress", "body_battery", "hrv", "rhr", "steps", "weight"}
    assert packet["sections"]["context"]["returned_count"] > 0
    assert set(packet["sections"]["hrv"]["providers"]) == {"garmin", "google"}
    assert [row["id"] for row in inventory["sources"]
            if row["provider"] == "garmin_connect"] == [garmin_id]
    assert [row["id"] for row in inventory["sources"]
            if row["provider"] == "google_health"] == [google_id]
    assert 'id="analysis-export-options" hidden' in page.text
    assert '<input type="hidden" name="steps_view" value="completed">' in page.text
    assert 'Сохранённые показатели и ваши комментарии' in page.text
    assert 'Скачайте и приложите' not in page.text and '2 MiB' not in page.text
    capture("export.html", page.text)
    capture("export-sources.json", json.dumps(inventory))
    capture("export-request.json", json.dumps(body))
    capture("export-response.json", json.dumps(response.json()))


@pytest.mark.parametrize("mode", ["filled", "empty", "partial", "zero", "large",
                                  "eight-digits", "nine-digits", "twelve-digits"])
def test_statistics_steps_keep_exact_values_and_explicit_day_choice(
    statistics_ui, monkeypatch, mode,
):
    from datetime import timedelta

    from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
    from test_garmin_completed_steps import BOUNDARY, DAY, NOW, acquire

    session, paths, client = statistics_ui
    monkeypatch.setattr("healthcheck.web.statistics.steps_evaluation_instant",
                        lambda: NOW + timedelta(days=7))
    values = {"filled": [12345, 17890, 0, 15000], "partial": [12345, None, True, 0],
              "zero": [0, 0, 0], "large": [9223372036854775807, 0], "empty": [],
              "eight-digits": [99999999, 0], "nine-digits": [999999999, 0],
              "twelve-digits": [999999999999, 0]}[mode]
    source = None
    store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    for index, value in enumerate(values):
        saved = acquire(session, store, value, day=DAY + timedelta(days=index),
                        at=BOUNDARY + timedelta(days=index))
        source = saved.source.id
    response = client.get("/statistics", params={"period": "7",
        "end_date": str(DAY + timedelta(days=6)), "garmin_source_id": source or ""})
    assert response.status_code == 200
    header = response.text.split('<header data-statistics-side="left">', 1)[1]
    header = header.split('<details', 1)[0]
    assert '<h2>Garmin</h2>' in header and 'source_instance_id' not in header
    assert 'statistics-denominator' not in response.text
    assert 'statistics-source-choice' not in response.text
    assert 'type="hidden" form="statistics-controls" name="garmin_source_id"' in response.text
    assert 'data-steps-info="garmin"' in response.text
    assert 'Дни и подробности Garmin' not in response.text
    assert 'Источник и границы чтения шагов</summary>' not in response.text
    if values:
        view = response.context["garmin_steps_view"]
        assert view["selected"] is None and view["selected_index"] is None
        assert 'data-steps-cursor hidden' in response.text
        assert '<option value="" selected disabled>Выберите день</option>' in response.text
        assert 'class="steps-tick"' in response.text
        assert all(row["value"] is None or isinstance(row["value"], str)
                   for row in view["rows"])
        if mode == "large":
            assert view["rows"][0]["value"] == "9223372036854775807"
            assert view["rows"][0]["display"] == (
                "9\u202f223\u202f372\u202f036\u202f854\u202f775\u202f807")
    capture(f"statistics-{mode}.html", response.text)
