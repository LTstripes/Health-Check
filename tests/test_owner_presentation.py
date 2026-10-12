"""Presentation boundaries over synthetic values and actual route renderers."""

import re
from datetime import UTC, date, datetime

import pytest

from healthcheck.context import ContextService, parse_date_only, parse_interval, parse_timestamp
from healthcheck.db.engine import session_scope
from healthcheck.web.owner_presentation import owner_date, owner_distance, owner_duration
from test_context_ui import ui as ui
from test_statistics_ui import projection_database as projection_database
from test_statistics_ui import statistics_ui as statistics_ui


@pytest.mark.parametrize("value,precision,expected", [
    (date(2024, 2, 29), "date", "29 февраля 2024"),
    ("2026-01-02", "date", "2 января 2026"),
    ("2026-01-02T00:15+14:00", "minute", "2 января 2026, 00:15 UTC+1400"),
    ("2026-01-02T23:15-11:00", "minute", "2 января 2026, 23:15 UTC-1100"),
    ("2026-01-02T00:15:00+05:45", "second", "2 января 2026, 00:15:00 UTC+0545"),
    ("2026-01-02T19:30:10.123400Z", "microsecond", "2 января 2026, 19:30:10.123400 UTC"),
    ("2026-01-02T19:30:00.000000+03:00", "microsecond", "2 января 2026, 19:30:00.000000 UTC+0300"),
    (
        "1900-01-02T12:00:10.123400+00:09:21", "microsecond",
        "2 января 1900, 12:00:10.123400 UTC+000921",
    ),
    (datetime(2026, 1, 2, 0, 15, tzinfo=UTC), "microsecond", "2 января 2026, 00:15:00.000000 UTC"),
    ("2026-01-02T19:30:10.120Z", "source", "2 января 2026, 19:30:10.120 UTC"),
    ("2026-01-02T19:30", "source", "2 января 2026, 19:30"),
    ("2026-02-30", "date", "Дата не указана"),
    (None, "date", "Дата не указана"),
])
def test_date_precision_and_source_local_day(value, precision, expected):
    assert owner_date(value, precision) == expected


@pytest.mark.parametrize("value,duration,distance", [
    (None, "Недоступно", "Недоступно"),
    (False, "Недоступно", "Недоступно"),
    ("60", "Недоступно", "Недоступно"),
    (-1, "Недоступно", "Недоступно"),
    (float("nan"), "Недоступно", "Недоступно"),
    (float("inf"), "Недоступно", "Недоступно"),
    (0, "0 мин", "0 км"),
    (0.001, "<0,01 с", "<0,01 км"),
    (0.005, "0,01 с", "<0,01 км"),
    (1, "1 с", "<0,01 км"),
    (59.999, "1 мин", "0,06 км"),
    (60, "1 мин", "0,06 км"),
    (3599.999, "1 ч 0 мин", "3,6 км"),
    (3600, "1 ч 0 мин", "3,6 км"),
    (3901.5, "1 ч 5 мин 1,5 с", "3,9 км"),
    (360000, "100 ч 0 мин", "360 км"),
])
def test_native_units_display_only(value, duration, distance):
    assert owner_duration(value) == duration
    assert owner_distance(value) == distance


@pytest.mark.parametrize("temporal", [
    parse_date_only("2024-02-29"),
    parse_timestamp("2026-01-02T00:15+14:00", timezone_name="Pacific/Kiritimati"),
    parse_timestamp("2026-01-02T19:30:00.000000+03:00", timezone_name="Europe/Moscow"),
    parse_timestamp("2026-01-02T19:30:10.123400Z"),
    parse_interval("2026-03-08T01:30-05:00", "2026-03-08T03:30-04:00"),
    parse_interval("2026-01-02", "2026-01-04"),
])
def test_comments_list_detail_history_render_without_changing_evidence(ui, temporal):
    client, engine, _ = ui
    with session_scope(engine) as session:
        first = ContextService(session).add(text="Synthetic original", temporal=temporal)
        current = ContextService(session).revise(first.event_id, text="Synthetic correction")
    for path in [
        "/context?from_date=2024-01-01&to_date=2026-12-31",
        f"/context/{first.event_id}",
        f"/context/{first.event_id}?history=1",
    ]:
        response = client.get(path)
        assert response.status_code == 200
        headings = re.findall(r"<h3>Событие: (.*?)</h3>", response.text)
        assert headings
        assert all("T19:" not in h and "2026-01-02" not in h for h in headings)
        expected = owner_date(temporal.start_source_timestamp or temporal.start_local_date,
                              temporal.start_precision)
        assert all(expected in h for h in headings)
        if temporal.end_local_date:
            assert all(owner_date(temporal.end_source_timestamp or temporal.end_local_date,
                                  temporal.end_precision) in h for h in headings)
        assert str(temporal.start_source_timestamp or temporal.start_local_date) in response.text
        assert "Записано автоматически (не время события)" in response.text
        assert "UTC" in response.text
        if temporal.start_timezone:
            assert temporal.start_timezone in response.text
        if temporal.start_precision == "date":
            assert all(", 00:00" not in h and "UTC" not in h for h in headings)
    with session_scope(engine) as session:
        assert ContextService(session).list()[0].temporal == temporal
        history = ContextService(session).list(history=True)
        assert len(history) == 2 and history[0].revision_id == current.revision_id


def test_statistics_primary_window_has_human_dates_and_native_controls(statistics_ui):
    _, _, client = statistics_ui
    response = client.get("/statistics", params={"end_date": "2024-02-29", "period": "7"})
    assert response.status_code == 200
    window = response.text.split('class="statistics-window">', 1)[1].split("</p>", 1)[0]
    assert "23 февраля 2024" in window and "29 февраля 2024" in window
    assert "2024-02-29" not in window
    assert 'name="end_date" value="2024-02-29"' in response.text


@pytest.mark.parametrize("duration,distance,expected_duration,expected_distance", [
    (0, 0, "0 мин", "0 км"),
    (0.001, 0.001, "&lt;0,01 с", "&lt;0,01 км"),
    (3901.5, 12345.6, "1 ч 5 мин 1,5 с", "12,35 км"),
    (None, None, "Источник передал null", "Источник передал null"),
])
def test_saved_session_list_detail_exact_native_values(
    statistics_ui, duration, distance, expected_duration, expected_distance,
):
    from sqlalchemy import select

    from healthcheck.db.models import GarminSourceRecord
    from test_period_summary import END, START, _activity

    session, paths, client = statistics_ui
    outcome = _activity(session, paths, duration=duration, distance=distance)
    record = session.scalar(select(GarminSourceRecord).where(
        GarminSourceRecord.garmin_source_id == outcome.source.id,
        GarminSourceRecord.stream_code == "activity",
    ))
    session.commit()
    response = client.get("/statistics/sessions", params={
        "garmin_source_id": outcome.source.id, "start_date": str(START),
        "end_date": str(END), "metric_code": "activity_session_count", "sport": "all",
    })
    assert response.status_code == 200
    for code, expected in [("duration_seconds", expected_duration),
                           ("distance_meters", expected_distance)]:
        cell = re.search(rf'data-session-metric="{code}"[^>]*>(.*?)</td>', response.text)
        assert cell and expected in cell[1]
    assert "Точные значения сессий" in response.text
    assert "seconds" in response.text and "meters" in response.text
    detail = client.get("/garmin/session", params={
        "garmin_source_id": outcome.source.id, "record_id": record.id,
    })
    assert detail.status_code == 200
    if duration is not None:
        assert expected_duration in detail.text and expected_distance in detail.text
        assert str(duration) in detail.text and str(distance) in detail.text
    else:
        assert "Не предоставлено" in detail.text


@pytest.mark.parametrize("case", ["missing", "invalid", "unit"])
def test_session_formatter_does_not_promote_ineligible_values(statistics_ui, case):
    from sqlalchemy import select

    from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord
    from test_period_summary import END, START, _activity

    session, paths, client = statistics_ui
    outcome = _activity(session, paths, duration=120)
    record = session.scalar(select(GarminSourceRecord).where(
        GarminSourceRecord.garmin_source_id == outcome.source.id,
        GarminSourceRecord.stream_code == "activity",
    ))
    metric = session.scalar(select(GarminRecordMetric).where(
        GarminRecordMetric.record_id == record.id,
        GarminRecordMetric.metric_code == "duration_seconds",
    ))
    if case == "missing":
        session.delete(metric)
    elif case == "invalid":
        metric.state = "invalid"
        metric.value_number = metric.value_text = None
    else:
        metric.unit = "minutes"
    session.commit()
    response = client.get("/statistics/sessions", params={
        "garmin_source_id": outcome.source.id, "start_date": str(START),
        "end_date": str(END), "metric_code": "activity_session_count", "sport": "all",
    })
    assert response.status_code == 200
    cell = re.search(r'data-session-metric="duration_seconds"[^>]*>(.*?)</td>', response.text)
    assert cell and "2 мин" not in cell[1] and "0 мин" not in cell[1]
    expected = {"missing": "Поле отсутствует", "invalid": "Некорректное значение",
                "unit": "Единица недоступна"}[case]
    assert expected in cell[1]


def test_overview_gap_titles_reuse_human_dates(ui):
    from scripts.serve_owner_formatting_fixture import seed_format_weight

    client, _, _ = ui
    seed_format_weight(client)
    response = client.get("/brief")
    assert response.status_code == 200
    titles = re.findall(r"<title[^>]*>(.*?)</title>", response.text)
    assert any(title.startswith("Нет наблюдений:") for title in titles)
    assert all(not re.search(r"\d{4}-\d{2}-\d{2}", title) for title in titles)


def test_javascript_civil_validation_and_python_parity():
    import json
    import subprocess
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", str(repo / "scripts/check_owner_dates.cjs")], cwd=repo,
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    packet = json.loads(result.stdout)
    assert packet["dateConversion"] is False
    assert packet["extraInvalidInputs"] == 2
    for case in packet["cases"]:
        if not case["pythonParity"]:
            continue
        expected = owner_date(case["value"], "source" if case["sourcePrecision"] else None)
        if expected == "Дата не указана" and case["value"] is not None and case["value"] != "":
            expected = "Некорректная дата/время"
        actual = re.sub(r" UTC([+-]\d{2}):(\d{2})$", r" UTC\1\2", case["actual"])
        # Existing JS labels retain four-digit years; Python labels use numeric years.
        actual = re.sub(r" (\d{4})(?=,|$)", lambda m: " " + str(int(m[1])), actual)
        assert actual == expected, case["value"]


@pytest.mark.parametrize("value,duration,distance", [
    (1e26, "≈2,78 × 10^22 ч", "≈1 × 10^23 км"),
    (1e30, "≈2,78 × 10^26 ч", "≈1 × 10^27 км"),
    (float.fromhex("0x1.fffffffffffffp+1023"),
     "≈4,99 × 10^304 ч", "≈1,8 × 10^305 км"),
    (float.fromhex("0x0.0000000000001p-1022"), "<0,01 с", "<0,01 км"),
    pytest.param(10**5000, "≈2,78 × 10^4996 ч", "≈1 × 10^4997 км", id="huge-native-int"),
])
def test_duration_distance_are_total_for_finite_extremes(value, duration, distance):
    from decimal import getcontext, localcontext

    before = getcontext().copy()
    assert owner_duration(value) == duration
    assert owner_distance(value) == distance
    assert getcontext().prec == before.prec
    with localcontext() as caller:
        caller.prec = 3
        caller.Emax = 5
        assert owner_duration(value) == duration
        assert owner_distance(value) == distance
        assert caller.prec == 3 and caller.Emax == 5
    assert len(duration) < 32 and len(distance) < 32


@pytest.mark.parametrize("duration,distance", [
    (1e26, 1e30),
    (float.fromhex("0x1.fffffffffffffp+1023"),
     float.fromhex("0x1.fffffffffffffp+1023")),
    (float.fromhex("0x0.0000000000001p-1022"),
     float.fromhex("0x0.0000000000001p-1022")),
])
def test_extreme_saved_values_render_list_detail_without_mutation(
    statistics_ui, duration, distance,
):
    import json
    from html import unescape

    from sqlalchemy import select

    from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord
    from test_period_summary import END, START, _activity

    session, paths, client = statistics_ui
    outcome = _activity(session, paths, duration=duration, distance=distance)
    record = session.scalar(select(GarminSourceRecord).where(
        GarminSourceRecord.garmin_source_id == outcome.source.id,
        GarminSourceRecord.stream_code == "activity",
    ))
    session.commit()
    params = {"garmin_source_id": outcome.source.id, "start_date": str(START),
              "end_date": str(END), "metric_code": "activity_session_count", "sport": "all"}
    response = client.get("/statistics/sessions", params=params)
    assert response.status_code == 200
    for code, expected in [("duration_seconds", owner_duration(duration)),
                           ("distance_meters", owner_distance(distance))]:
        cell = re.search(rf'data-session-metric="{code}"[^>]*>(.*?)</td>', response.text)
        assert cell and unescape(cell[1]) == expected
    detail = client.get("/garmin/session", params={
        "garmin_source_id": outcome.source.id, "record_id": record.id,
    })
    assert detail.status_code == 200
    assert owner_duration(duration) in unescape(detail.text)
    assert owner_distance(distance) in unescape(detail.text)
    raw = json.loads(re.search(
        r'<pre id="activity-session-evidence">(.*?)</pre>', detail.text, re.S,
    )[1])
    coverage = {item["metric_code"]: item for item in raw["metric_coverage"]}
    assert coverage["duration_seconds"]["value"] == duration
    assert coverage["distance_meters"]["value"] == distance
    assert coverage["duration_seconds"]["unit"] == "seconds"
    assert coverage["distance_meters"]["unit"] == "meters"
    for code, expected in [("duration_seconds", duration), ("distance_meters", distance)]:
        metric = session.scalar(select(GarminRecordMetric).where(
            GarminRecordMetric.record_id == record.id, GarminRecordMetric.metric_code == code,
        ))
        assert metric.value_number == expected and metric.state == "value"
