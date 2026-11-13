"""Synthetic #580 endpoint projection and production JS schedule rendering."""

from __future__ import annotations

import json
import re
import subprocess
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

from healthcheck.web.sleep_timeline import build_sleep_timeline, sleep_timeline_client
from test_garmin_query_dashboard import _ui
from test_sleep_owner_ui import client_for
from test_sleep_timeline_ui import END as PERSISTED_END
from test_sleep_timeline_ui import _regularity_packet, _seed_regularity_nights

REPO = Path(__file__).resolve().parents[1]
END = date(2026, 10, 8)


def _timeline(count=7, *, days=7):
    ranges = {p: _regularity_packet(p, count=count, days=days) for p in ("garmin", "google")}
    for packet in ranges.values():
        records = {day["wake_date"]: day["sources"][0]["sessions"][0]["record_id"]
                   for day in packet["days"] if day["sources"]}
        for point in packet["series"][0]["points"]:
            point["record_id"] = records[point["wake_date"]]
    return build_sleep_timeline(ranges, days=days, end_date=END)


def _render(tmp_path, *cases):
    path = tmp_path / "schedule-cases.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    result = subprocess.run(
        ["node", str(REPO / "scripts/render_sleep_schedule.cjs"), str(path)],
        cwd=REPO, check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(result.stdout)


def test_compact_bounds_reuse_existing_analysis_and_exact_record():
    timeline = _timeline()
    before = deepcopy(timeline)
    packet = sleep_timeline_client(timeline)
    assert timeline == before
    assert "nights" not in packet and "table_rows" not in packet
    assert "night_bounds" not in packet["regularity"]
    assert set(packet["schedule_bounds"]) == {"garmin:sleep", "google:sleep"}
    for bounds in packet["schedule_bounds"].values():
        assert len(bounds) == 7
        assert set(bounds[0]) == {"wake_date", "record_id", "start_local", "end_local", "zone"}
        assert bounds[0]["start_local"] == "2026-10-01T23:00:00+00:00"
        assert bounds[0]["end_local"] == "2026-10-02T07:00:00+00:00"
    assert "interval_snapshots" not in json.dumps(packet)


@pytest.mark.parametrize("problem", ["no_zone", "ineligible", "ambiguous", "role", "wrong_date"])
def test_ineligible_bounds_are_not_invented(problem):
    raw = _regularity_packet(count=1)
    day = next(d for d in raw["days"] if d["sources"])
    source = day["sources"][0]
    item = source["sessions"][0]
    if problem == "no_zone":
        for endpoint in ("start", "end"):
            item["metrics"][f"sleep_{endpoint}_at"]["evidence"]["interval_snapshots"][0][
                f"{endpoint}_temporal"] = {"precision": "instant"}
    elif problem == "ineligible":
        item["metrics"]["sleep_start_at"]["eligible"] = False
    elif problem == "ambiguous":
        duplicate = deepcopy(item)
        duplicate["record_id"] = "other-record"
        source["sessions"].append(duplicate)
    elif problem == "role":
        item["role"] = {"selection": "role_uncertain"}
    else:
        day["wake_date"] = "2026-10-03"
    packet = sleep_timeline_client(build_sleep_timeline({"google": raw}, days=7, end_date=END))
    assert not packet["schedule_bounds"].get("google:sleep")


def test_midnight_late_start_and_axis_extension(tmp_path):
    data = sleep_timeline_client(_timeline())
    [normal] = _render(tmp_path, {"data": data})
    assert normal["axis"]["min"] == 1260 and normal["axis"]["max"] == 2100
    cell = normal["rows"][0]["cells"][0]
    assert cell["start"] == 1380 and cell["end"] == 1860
    assert normal["axis"]["ticks"] == list(range(1260, 2101, 120))
    assert 'left:14.285714285714286%;width:57.142857142857146%' in normal["html"]
    for bounds in data["schedule_bounds"].values():
        bounds[-1]["start_local"] = "2026-10-08T03:10:00+00:00"
    [late] = _render(tmp_path, {"data": data})
    assert late["rows"][0]["cells"][0]["start"] == 1630
    for bounds in data["schedule_bounds"].values():
        bounds[-1].update(start_local="2026-10-07T16:00:00+00:00",
                          end_local="2026-10-08T16:00:00+00:00")
    [extended] = _render(tmp_path, {"data": data})
    assert extended["axis"]["min"] == 960 and extended["axis"]["max"] == 2400
    assert 'left:0%;width:100%' in extended["html"]
    assert extended["rows"][0]["cells"][0]["start"] == 960
    assert extended["rows"][0]["cells"][0]["end"] == 2400


def test_missing_duration_without_bounds_and_exact_identity(tmp_path):
    data = sleep_timeline_client(_timeline(count=1))
    # A duration in a different night never supplies a schedule interval.
    for source in data["display_series"]:
        source["points"][-1].update(state="value", value_seconds=27000)
    [result] = _render(tmp_path, {"data": data})
    html = result["html"]
    assert html.count('data-schedule-date=') == 7
    assert 'нет данных' in html and 'границы не сохранены' in html
    assert html.count('data-schedule-bar=') == 4
    assert html.count('sleep-schedule-unbounded owner-chart-hatch') == 2
    chart = html.split('<details', 1)[0]
    assert 'sleep-schedule-note' not in chart
    assert re.search(r'class="sleep-schedule-bar sleep-schedule-unbounded[^>]*></span>', chart)
    assert '7 ч 30 мин' in html
    for bounds in data["schedule_bounds"].values():
        bounds[0]["record_id"] = "wrong-record"
    [mismatch] = _render(tmp_path, {"data": data})
    assert mismatch["html"].count('sleep-schedule-unbounded owner-chart-hatch') == 4
    assert all(cell["bound"] is None for row in mismatch["rows"] for cell in row["cells"])


def test_separate_sources_toggle_table_summary_and_travel(tmp_path):
    data = sleep_timeline_client(_timeline())
    for source in data["display_series"]:
        bounds = data["schedule_bounds"][source["series_id"]]
        for i, bound in enumerate(bounds):
            bound["zone"] = {"kind": "iana_zone", "zone": "Asia/Bangkok" if i < 3 else
                             "Europe/Moscow"}
    full, google, hidden = _render(tmp_path, {"data": data},
        {"data": data, "hidden": {"garmin:sleep": True}},
        {"data": data, "hidden": {"garmin:sleep": True, "google:sleep": True}})
    html = full["html"]
    assert html.count('data-schedule-bar="garmin:sleep"') == 7
    assert html.count('data-schedule-bar="google:sleep"') == 7
    assert 'top:2px;' in html and 'top:11px;' in html
    assert 'var(--series-1)' in html and 'var(--series-4)' in html
    assert 'Часовой пояс: Europe/Moscow → Asia/Bangkok' in html
    assert '<td>± 0 мин</td><td>± 0 мин</td>' in html
    assert '7 из 7 ночей' in html
    assert '<details class="owner-details"><summary>Таблица</summary>' in html
    assert 'scope="col">Часовой пояс' in html
    assert 'aria-label="8 окт · Garmin · 23:00 → 07:00 · 8 ч 00 мин' in html
    assert html.index('data-schedule-date="2026-10-08"') < html.index(
        'data-schedule-date="2026-10-02"')
    chart, table = google["html"].split(
        '<details class="owner-details"><summary>Таблица</summary>', 1)
    assert 'data-schedule-bar="garmin:sleep"' not in chart
    assert chart.count('data-schedule-bar="google:sleep"') == 7
    assert 'Garmin' in table
    assert 'Источники скрыты' in hidden["html"]
    assert 'data-regularity-source=' not in hidden["html"]


@pytest.mark.parametrize("count", [0, 2])
def test_insufficient_regularity_remains_text_not_zero(tmp_path, count):
    [result] = _render(tmp_path, {"data": sleep_timeline_client(_timeline(count=count))})
    assert 'Недостаточно ночей' in result["html"]
    assert '<td>± 0 мин</td>' not in result["html"]


@pytest.mark.parametrize("days", [7, 30])
def test_production_http_packet_and_js_render(tmp_path, days):
    app, _, paths = _ui(tmp_path)
    _seed_regularity_nights(paths)
    with client_for(app) as client:
        response = client.get(f"/sleep?days={days}&wake_date={PERSISTED_END}")
    assert response.status_code == 200
    html = response.text
    assert html.count('{% include') == 0
    assert html.count('id="sleep-schedule"') == 1
    assert '/static/sleep_schedule.js' in html
    section = html.split('<section class="card sleep-schedule"', 1)[1].split('</section>', 1)[0]
    assert '<style>' not in section
    assert 'Загрузка расписания…' in section
    assert re.search(r'<noscript>.*?Для расписания нужен JavaScript', section, re.S)
    assert 'Рабочие дни: пн–пт · изменить' in section
    assert 'Разброс начала' in section and 'Разброс окончания' in section
    assert 'Середина: рабочие → свободные · сдвиг' in section
    assert f'из {days} ночей' in section
    packet = json.loads(re.search(
        r'<script id="sleep-timeline-data" type="application/json">(.*?)</script>',
        html, re.S,
    ).group(1))
    assert 'interval_snapshots' not in json.dumps(packet)
    [result] = _render(tmp_path, {"data": packet})
    assert result["html"].count('data-schedule-date=') == min(days, 14)
    assert 'data-schedule-bar=' in result["html"]
    assert len(response.content) < 1_000_000


def test_schedule_partial_coverage_uses_supplied_policy(tmp_path):
    data = sleep_timeline_client(_timeline(count=4))
    [result] = _render(tmp_path, {"data": data, "threshold": {"numerator": 2, "denominator": 3}})
    assert 'data-coverage-qualifier="4/7"' in result["html"]
    assert 'class="owner-value-low"' in result["html"]
    assert '4 из 7 ночей' in result["html"]


def test_thirty_nights_expand_without_changing_packet_or_axis(tmp_path):
    data = sleep_timeline_client(_timeline(count=30, days=30))
    before = deepcopy(data)
    compact, full = _render(tmp_path, {"data": data}, {"data": data, "expanded": True})
    assert compact["html"].count('data-schedule-date=') == 14
    assert full["html"].count('data-schedule-date=') == 30
    assert 'все 30' in compact["html"] and '14 последних' in full["html"]
    assert compact["axis"] == full["axis"]
    assert data == before
    assert compact["html"].index('data-schedule-date="2026-10-08"') < compact["html"].index(
        'data-schedule-date="2026-09-25"')
    assert 'data-schedule-date="2026-09-24"' not in compact["html"]


def test_incompatible_partitions_match_by_identity_not_order(tmp_path):
    data = sleep_timeline_client(_timeline())
    source = data["regularity"]["sources"][0]
    first = source["groups"][0]
    second = deepcopy(first)
    second["partition"]["end_method"] = 'different-method'
    second["start"]["text"] = '17 мин'
    source["groups"].append(second)
    jet = deepcopy(source["jetlag"]["groups"][0])
    jet["partition"] = second["partition"]
    jet.update(state='insufficient', text='Недостаточно свободных ночей (1)', signed_minutes=None)
    source["jetlag"]["groups"].insert(0, jet)
    [result] = _render(tmp_path, {"data": data})
    table = result["html"].split('</tbody>', 1)[0]
    assert re.search(r'группа 2.*?17 мин.*?Недостаточно свободных ночей \(1\)', table)
    assert table.count('data-regularity-source="garmin"') == 2


def test_schedule_dom_selection_expand_and_json_failure():
    result = subprocess.run(
        ["node", str(REPO / "scripts/check_sleep_schedule.cjs")], cwd=REPO,
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    assert 'PASS: schedule selection' in result.stdout
