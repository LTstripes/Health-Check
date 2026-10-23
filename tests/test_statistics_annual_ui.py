"""Annual UI consumes the bounded packet without reinterpreting its evidence."""

import json
import os
import re
from copy import deepcopy
from datetime import date
from html import unescape
from pathlib import Path

import pytest
from sqlalchemy import select

from healthcheck.analytics import period_summary_read as bounded
from healthcheck.analytics.period_summary import SLEEP_CODE, PeriodSummaryService
from healthcheck.db.models import GarminSource, GoogleSource
from healthcheck.web.owner_presentation import owner_activity_types, owner_date
from healthcheck.web.statistics import format_statistics_value
from test_sleep_account_cohort import _garmin, _google
from test_statistics_ui import (
    MetricParser,
    SourceFormParser,
    seed,
)
from test_statistics_ui import (
    projection_database as projection_database,
)
from test_statistics_ui import (
    statistics_ui as statistics_ui,
)

PERIODS = [
    ("7", "2096-02-23", "2096-02-29", 7),
    ("30", "2096-01-31", "2096-02-29", 30),
    ("trailing365", "2095-03-02", "2096-02-29", 365),
    ("calendar_year", "2096-01-01", "2096-12-31", 366),
    ("year_to_date", "2096-01-01", "2096-02-29", 60),
]


def export(response, name):
    root = os.environ.get("HEALTHCHECK_STATISTICS_FIXTURES_DIR")
    if root:
        directory = Path(root)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"annual-{name}.html").write_text(response.text, encoding="utf-8")


@pytest.mark.parametrize("period,start,end,count", PERIODS)
@pytest.mark.parametrize("case", ["sparse", "zero", "missing"])
def test_annual_route_preserves_packet(statistics_ui, monkeypatch, period, start, end, count, case):
    session, paths, client = statistics_ui
    if case != "missing":
        _garmin(session, paths, date(2096, 2, 29), seconds=0 if case == "zero" else 28800,
                attributed=True)
        _google(session, paths, date(2096, 2, 29), minutes="0" if case == "zero" else "410",
                main="true", nap="false")
        session.commit()
    kwargs = {"days": int(period), "end_date": date(2096, 2, 29)} if period in {"7", "30"} else (
        {"period_type": period, "calendar_year": 2096} if period == "calendar_year" else
        {"period_type": period, "end_date": date(2096, 2, 29)}
    )
    expected = PeriodSummaryService(session).build(**kwargs, sleep_source_selection=True)
    original = PeriodSummaryService.build
    captured = []

    def capture(service, **selection):
        assert selection == dict(
            kwargs, garmin_source_id=None, google_source_id=None,
            sleep_source_selection=True, garmin_sleep_source_id=None, google_sleep_source_id=None,
        )
        packet = original(service, **selection)
        captured.append((packet, deepcopy(packet)))
        return packet

    monkeypatch.setattr(PeriodSummaryService, "build", capture)
    response = client.get("/statistics", params={
        "period": period, "end_date": "2096-02-29", "calendar_year": 2096,
    })
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    packet, before = captured[0]
    assert packet == before
    assert {k: v for k, v in packet.items() if k != "evaluated_at"} == {
        k: v for k, v in expected.items() if k != "evaluated_at"
    }
    assert f'{owner_date(start)} — {owner_date(end)} · {count} дней' in response.text
    assert f'value="{period}" selected' in response.text
    assert 'value="2096-02-29"' in response.text
    parser = MetricParser(response.text)
    for side in expected["sides"]:
        for code, cell in side["metrics"].items():
            if code == "activity_type_counts":
                assert (code, side["position"]) not in parser.cells
                if side["position"] == "right" and cell["state"] == "not_collected":
                    continue
                evidence = re.search(
                    r'data-activity-type-evidence="' + side["position"] + r'">(.*?)</pre>',
                    response.text, re.S,
                )
                assert evidence is not None
                assert json.loads(unescape(evidence[1])) == cell
                assert 'id="metric-activity_type_counts"' in response.text
                continue
            if side["position"] == "right" and cell["state"] == "not_collected":
                assert (code, "right") not in parser.cells
                continue
            value = cell["aggregation"]["value"]
            headline = format_statistics_value(code, value)
            types = side["metrics"]["activity_type_counts"]["aggregation"]["value"]
            if code == "activity_session_count" and value is not None and isinstance(types, dict):
                headline += ": " + owner_activity_types(types)
            assert parser.values[code, side["position"]].strip() == headline
            if code == "cycling_distance_meters" and side["position"] == "left" and value is None:
                # Metadata alone no longer selects a cycling source. The shared
                # packet is unchanged; the UI requires usable period distance.
                assert "Наблюдения и знаменатель не оценены" in parser.cells[code, "left"]
                assert "eligible_saved_sessions: 0" not in parser.details[code, "left"]
            elif cell["state"] not in {"source_missing", "not_collected"}:
                assert cell["aggregation"]["denominator"] in parser.details[code, side["position"]]
    assert "Google − Garmin:" not in response.text
    if period not in {"7", "30"} and case != "missing":
        assert "это не подтверждает полноту сбора или покрытие устройства" in response.text
    if os.environ.get("HEALTHCHECK_STATISTICS_FIXTURES_DIR"):
        # Browser navigation must use the same persisted identities in every window.
        monkeypatch.setattr(PeriodSummaryService, "build", original)
        for choice, *_ in PERIODS:
            rendered = client.get("/statistics", params={
                "period": choice, "end_date": "2096-02-29", "calendar_year": 2096,
            })
            assert rendered.status_code == 200
            export(rendered, f"{case}-{choice}")


@pytest.mark.parametrize("cap", ["MAX_PERIOD_RECORDS", "MAX_PERIOD_SOURCES"])
def test_incomplete_rendering_preserves_unknown_and_independent_cells(
    statistics_ui, monkeypatch, cap,
):
    session, paths, client = statistics_ui
    seed(session, paths, "full")
    source_id = session.scalar(select(GarminSource.id))
    monkeypatch.setattr(bounded, cap, 0 if cap == "MAX_PERIOD_SOURCES" else 1)
    response = client.get("/statistics", params={
        "period": "calendar_year", "calendar_year": 2099, "garmin_source_id": source_id,
    })
    assert response.status_code == 200
    parser = MetricParser(response.text)
    code = "activity_session_count"
    text = parser.cells[code, "left"]
    assert parser.values[code, "left"].strip() == "Недоступно"
    assert "Официальный итог и знаменатель недоступны" in text
    assert "пропуски и полнота сбора неизвестны" in text
    assert "Допустимо:" not in text and "None" not in text
    assert "Источник отсутствует" not in text and "Подтверждённое отсутствие" not in text
    assert "Google − Garmin:" not in response.text
    if cap == "MAX_PERIOD_SOURCES":
        assert f'value="{source_id}" selected' in response.text
        assert "Выбранный источник: поиск не завершён" in response.text
    header = response.text.split('<header data-statistics-side="left">', 1)[1].split(
        "</header>", 1,
    )[0]
    assert 'data-source-attention' in header
    assert 'class="statistics-details statistics-source-choice" open' in header
    assert "Полнота и доступность неизвестны" in header
    if cap == "MAX_PERIOD_SOURCES":
        assert f'value="{source_id}" selected' in header
    else:
        # Activity has two rows; sleep has seven, so both exceed this cap.
        assert parser.values[SLEEP_CODE, "left"].strip() == "Недоступно"
    export(response, f"incomplete-{cap}")


def test_incomplete_activity_keeps_complete_sleep(statistics_ui, monkeypatch):
    session, paths, client = statistics_ui
    seed(session, paths, "sparse")
    monkeypatch.setattr(bounded, "MAX_PERIOD_RECORDS", 1)
    response = client.get("/statistics", params={"period": "calendar_year", "calendar_year": 2099})
    parser = MetricParser(response.text)
    assert parser.values["activity_session_count", "left"].strip() == "Недоступно"
    assert parser.values[SLEEP_CODE, "left"].strip() == "8 ч 0 мин"
    assert "eligible_saved_nights: 1" in parser.details[SLEEP_CODE, "left"]
    export(response, "independent")


def test_annual_selection_is_explicit_bounded_and_retained(statistics_ui, monkeypatch):
    session, paths, client = statistics_ui
    seed(session, paths, "ambiguous")
    # Annual page must never use legacy per-night/inventory pre-scans.
    def forbidden(*args, **kwargs):
        raise AssertionError("unbounded legacy source scan")

    monkeypatch.setattr("healthcheck.analytics.period_summary.read_source_sleep_night", forbidden)
    garmin = session.scalar(select(GarminSource).where(GarminSource.device_attributed.is_(True)))
    google = session.scalar(select(GoogleSource))
    for period in ("trailing365", "calendar_year", "year_to_date"):
        params = {"period": period, "calendar_year": 2099, "end_date": "2099-01-08"}
        response = client.get("/statistics", params=params)
        assert "8 ч 0 мин" in MetricParser(response.text).cells[SLEEP_CODE, "left"]
        export(response, f"ambiguous-{period}")
        params.update(garmin_source_id=garmin.id, google_source_id=google.id)
        response = client.get("/statistics", params=params)
        assert response.status_code == 200
        selected = SourceFormParser(response.text).selected
        assert selected["garmin_source_id"] == garmin.id
        assert selected["google_source_id"] == google.id
        window = {"period_type": period, "calendar_year": 2099} if period == "calendar_year" else {
            "period_type": period, "end_date": date(2099, 1, 8),
        }
        expected = PeriodSummaryService(session).build(
            **window, garmin_source_id=garmin.id, google_source_id=google.id,
        )
        parser = MetricParser(response.text)
        for side in expected["sides"]:
            cell = side["metrics"][SLEEP_CODE]
            assert parser.values[SLEEP_CODE, side["position"]].strip() == format_statistics_value(
                SLEEP_CODE, cell["aggregation"]["value"],
            )
            assert f"eligible_saved_nights: {cell['aggregation']['eligible_count']}" in (
                parser.details[SLEEP_CODE, side["position"]]
            )
        assert "Google − Garmin:" not in response.text
        export(response, f"selected-{period}")


@pytest.mark.parametrize("params,bounds", [
    ({"period": "calendar_year", "calendar_year": 2095, "end_date": "2096-02-29"},
     "1 января 2095 — 31 декабря 2095 · 365 дней"),
    ({"period": "year_to_date", "end_date": "2096-01-01", "calendar_year": 2095},
     "1 января 2096 — 1 января 2096 · 1 дней"),
])
def test_calendar_and_ytd_controls_use_only_applicable_bounds(statistics_ui, params, bounds):
    session, paths, client = statistics_ui
    _garmin(session, paths, date(2095, 6, 1), seconds=28800, attributed=True)
    session.commit()
    response = client.get("/statistics", params=params)
    assert response.status_code == 200
    assert bounds in response.text
    parser = MetricParser(response.text)
    assert "Источник отсутствует" in parser.cells[SLEEP_CODE, "right"]
    assert parser.values[SLEEP_CODE, "left"].strip() == (
        "8 ч 0 мин" if params["period"] == "calendar_year" else "Недоступно"
    )
    assert "Google − Garmin:" not in response.text


@pytest.mark.parametrize("params", [
    {"period": "all_history"}, {"period": "365"}, {"period": "calendar_year", "calendar_year": 0},
    {"period": "calendar_year", "calendar_year": 9999}, {"period": "7", "days": 30},
    {"period": "trailing365", "end_date": "0001-01-01"},
    {"period": "year_to_date", "end_date": "9999-12-31"},
    {"period": "trailing365", "google_source_id": "unknown"},
])
def test_annual_invalid_requests_fail_closed(statistics_ui, params):
    assert statistics_ui[2].get("/statistics", params=params).status_code in {400, 422}
