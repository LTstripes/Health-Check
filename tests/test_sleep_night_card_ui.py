"""Selected-night card on /sleep: production JS helpers rendered on synthetic sessions."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import date
from html import unescape
from pathlib import Path

import pytest

from test_sleep_metrics import projection_database as projection_database

REPO = Path(__file__).resolve().parents[1]
GARMIN = {"provider": "garmin", "label": "Garmin", "series_id": "garmin:s1",
          "source": {"source_id": "s1"}}
GOOGLE = {"provider": "google", "label": "Google Health", "series_id": "google:s2",
          "source": {"source_id": "s2"}}
POINT = {"wake_date": "2026-10-26", "state": "value", "value_seconds": 30900,
         "record_id": "r1"}


def _cell(value, *, eligible=True, state="value", evidence=None):
    return {"value": value, "eligible": eligible, "state": state,
            "reason": None if eligible else "synthetic_reason", "evidence": evidence or {}}


def _instant(utc, offset=180):
    return {"precision": "instant", "measured_at_utc": utc, "source_utc_offset_minutes": offset}


def _session(**metrics):
    base = {
        "sleep_duration_asleep_seconds": _cell(30900),
        "sleep_start_at": _cell("2026-10-25T19:42:00Z"),
        "sleep_end_at": _cell("2026-10-26T04:19:00Z", evidence={
            "quality_inputs": {"summary_boundary": {"end": _instant("2026-10-26T04:19:00Z")}}}),
        "sleep_time_in_bed_seconds": _cell(31020),
        "sleep_stage_light_seconds": _cell(19320),
        "sleep_stage_deep_seconds": _cell(4740),
        "sleep_stage_rem_seconds": _cell(6840),
        "sleep_awake_waso_seconds": _cell(120),
        "sleep_score": _cell(88),
    }
    base.update(metrics)
    return {
        "record_id": "r1", "record_status": "current", "role": "main",
        "temporal_evidence": {"precision": "instant",
                              "source_timestamp_utc": "2026-10-25T19:42:00Z",
                              "source_utc_offset_minutes": 180},
        "metrics": {code: cell for code, cell in base.items() if cell is not None},
    }


def _render(tmp_path, cases):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    result = subprocess.run(
        ["node", str(REPO / "scripts/render_sleep_night_card.cjs"), str(path)],
        cwd=REPO, check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(result.stdout)


def _main_view(html):
    # Interval and technical disclosures are both collapsed in the main card.
    return re.sub(r"<details\b.*?</details>", "", html, flags=re.S)


def _text(html):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def test_complete_garmin_night_is_compact_and_keeps_detail_collapsed(tmp_path):
    [card] = _render(tmp_path, [{"series": GARMIN, "point": POINT, "session": _session()}])
    head = card["head"]
    assert "Ночь на 26 октября 2026 г." in head
    assert 'class="swatch sleep-series-garmin"' in head and ">Garmin</p>" in head
    assert 'aria-label="8 ч 35 мин"' in head
    assert '<span class="night-card-num">8</span>' in head
    assert '<span class="night-card-num">35</span>' in head
    main = _main_view(card["session"])
    # Short source-local clock; the zone and full dates live in the disclosure only.
    assert '<time class="night-card-clock">22:42</time>' in main
    assert '<time class="night-card-clock">07:19</time>' in main
    assert "UTC" not in main and "октября" not in main and "r1" not in main
    # One stacked bar for a complete stage record, with minutes and shares in the legend.
    assert main.count('class="night-stage night-stage-') == 4
    assert 'data-night-stages="complete"' in main and "неполные" not in main
    legend = _text(main)
    assert "Лёгкий 5 ч 22 мин 62 %" in legend
    assert "Глубокий 1 ч 19 мин 15 %" in legend
    assert "Быстрый (REM) 1 ч 54 мин 22 %" in legend
    assert "Бодрствование 2 мин <1 %" in legend
    assert "Время в постели 8 ч 37 мин" in legend
    assert "Оценка сна Garmin 88 из 100" in legend
    details = card["session"].split("<details", 1)[1]
    assert '<details class="owner-details night-card-tech"><summary>ⓘ Данные сессии</summary>' in (
        "<details" + details)
    assert " open" not in details.split(">", 1)[0]
    assert "25 октября 2026 г., 22:42 UTC+0300" in details
    assert "26 октября 2026 г., 07:19 UTC+0300" in details
    assert "<dt>Запись</dt><dd>r1</dd>" in details


def test_partial_stages_are_labelled_without_bar_shares_or_zero(tmp_path):
    session = _session(
        sleep_stage_deep_seconds=_cell(None, eligible=False, state="missing"),
        sleep_stage_rem_seconds=_cell(6840, eligible=False),
    )
    [card] = _render(tmp_path, [{"series": GARMIN, "point": POINT, "session": session}])
    main = _main_view(card["session"])
    assert "night-stage-bar" not in main and "%" not in main
    assert 'data-night-stages="partial"' in main
    assert '<span class="night-card-flag">неполные</span>' in main
    text = _text(main)
    assert "Глубокий нет данных" in text
    assert "Быстрый (REM) не подтверждено" in text
    assert "Лёгкий 5 ч 22 мин" in text
    assert "0 мин" not in text


def test_sparse_session_says_no_data_instead_of_zero(tmp_path):
    missing = _cell(None, eligible=False, state="missing")
    session = _session(
        sleep_start_at=missing, sleep_end_at=missing, sleep_time_in_bed_seconds=missing,
        sleep_stage_light_seconds=missing, sleep_stage_deep_seconds=missing,
        sleep_stage_rem_seconds=missing, sleep_awake_waso_seconds=missing,
        sleep_score=None,
    )
    [card] = _render(tmp_path, [{"series": GARMIN, "point": POINT, "session": session}])
    text = _text(_main_view(card["session"]))
    assert "Начало и окончание сна нет данных" in text
    assert "Стадии сна нет данных" in text
    assert "Время в постели нет данных" in text
    assert "Оценка сна Garmin нет данных" in text
    assert re.search(r"\b0\b", text) is None


def test_explicit_zero_stage_is_a_value_and_google_has_no_score_tile(tmp_path):
    session = _session(
        sleep_awake_waso_seconds=_cell(0),
        sleep_start_at=_cell("2026-10-09T22:00:00Z"),
        sleep_end_at=_cell("2026-10-10T06:00:00Z"),
    )
    session["temporal_evidence"] = {}
    [card] = _render(tmp_path, [{"series": GOOGLE, "point": POINT, "session": session}])
    main = _main_view(card["session"])
    assert main.count('class="night-stage night-stage-') == 3
    assert "Бодрствование 0 мин 0 %" in _text(main)
    # Without a paired source offset the short clock stays explicitly UTC.
    assert '<time class="night-card-clock">22:00 UTC</time>' in main
    assert "Оценка сна" not in main and "sleep_score" not in main


def test_non_value_points_have_header_without_duration_figure(tmp_path):
    point = {"wake_date": "2026-10-27", "state": "ambiguous", "note": "Несколько записей."}
    [card] = _render(tmp_path, [{"series": GARMIN, "point": point, "session": None}])
    assert "Ночь на 27 октября 2026 г." in card["head"]
    assert "night-card-figure" not in card["head"]


def test_timeline_script_keeps_session_states_and_loads_card_helpers():
    static = REPO / "src/healthcheck/web/static"
    timeline = (static / "sleep_timeline.js").read_text(encoding="utf-8")
    for state in ("loading", "error", "limited", "missing"):
        assert f'data-sleep-session-state="{state}"' in timeline
    assert "ⓘ Основание точки" in timeline
    assert 'aria-controls", "sleep-timeline-detail"' in timeline
    template = (REPO / "src/healthcheck/web/templates/sleep.html").read_text(encoding="utf-8")
    card_script = template.index("/static/sleep_night_card.js")
    assert card_script < template.index("/static/sleep_timeline.js")


def test_withheld_source_values_read_unconfirmed_not_missing(tmp_path):
    withheld = _cell(None, eligible=False)
    session = _session(sleep_start_at=withheld, sleep_end_at=withheld,
                       sleep_time_in_bed_seconds=withheld, sleep_stage_light_seconds=withheld,
                       sleep_stage_deep_seconds=withheld, sleep_stage_rem_seconds=withheld,
                       sleep_awake_waso_seconds=withheld)
    [card] = _render(tmp_path, [{"series": GARMIN, "point": POINT, "session": session}])
    text = _text(_main_view(card["session"]))
    assert "Начало и окончание сна не подтверждены" in text
    assert "Стадии сна не подтверждены" in text
    assert "Время в постели не подтверждено" in text
    assert "Оценка сна Garmin 88 из 100" in text
    assert "нет данных" not in text


def _interval(start, end, stage, *, offset=180, end_offset=None, ordinal=0):
    return {
        "id": f"stage-{ordinal}", "ordinal": ordinal, "interval_kind": "sleep_stage",
        "interval_state": "value", "start_state": "value", "end_state": "value",
        "start_precision": "instant", "end_precision": "instant",
        "start_at_utc": start, "end_at_utc": end, "stage_type": stage,
        "start_temporal": _instant(start, offset),
        "end_temporal": _instant(end, offset if end_offset is None else end_offset),
    }


def _interval_session(rows, start="2026-10-25T20:00:00Z", end="2026-10-26T00:00:00Z"):
    session = _session(
        sleep_start_at=_cell(start), sleep_end_at=_cell(end),
        sleep_stage_light_seconds=_cell(None, eligible=False, evidence={
            "interval_snapshots": rows}),
    )
    session["temporal_evidence"] = {}
    return session


def _graph(html):
    return html.split('<svg class="night-hypno-plot"', 1)[1].split("</figure>", 1)[0]


def _interval_table(html):
    return html.split('<tbody>', 1)[1].split('</tbody>', 1)[0]


def test_hypnogram_positions_steps_durations_and_accessible_rows(tmp_path):
    rows = [
        _interval("2026-10-25T20:00:00Z", "2026-10-25T21:00:00Z", "AWAKE"),
        _interval("2026-10-25T21:00:00Z", "2026-10-25T22:00:00Z", "LIGHT", ordinal=1),
        _interval("2026-10-25T22:00:00Z", "2026-10-25T23:00:00Z", "DEEP", ordinal=2),
        _interval("2026-10-25T23:00:00Z", "2026-10-26T00:00:00Z", "REM", ordinal=3),
    ]
    session = _interval_session(rows)
    # Real packets repeat these snapshots on multiple metric cells: no doubled rows.
    session["metrics"]["sleep_stage_deep_seconds"]["evidence"] = {"interval_snapshots": rows}
    [card] = _render(tmp_path, [{"series": GARMIN, "point": POINT, "session": session}])
    html = card["session"]
    graph = _graph(html)
    for x1, x2, y in [(0, 25, 10), (25, 50, 50), (50, 75, 70), (75, 100, 30)]:
        assert (f'class="night-hypno-line" x1="{x1}%" x2="{x2}%" '
                f'y1="{y}" y2="{y}"') in graph
    assert graph.count('class="night-hypno-step"') == 3
    assert graph.count('tabindex="0" role="img"') == 4
    assert 'aria-label="REM · 02:00–03:00 · 60 мин"' in graph
    assert 'text-anchor="start">23:00</text>' in graph
    assert 'text-anchor="end">03:00</text>' in graph
    assert "night-hypno-gap" not in graph
    assert '<summary>Интервалы стадий</summary>' in html
    assert '<details class="owner-details night-hypno-intervals">' in html
    table = _interval_table(html)
    assert table.count('<tr>') == 4
    assert ('<td>2026-10-26 02:00 UTC+03:00</td><td>2026-10-26 03:00 UTC+03:00</td>'
            '<td>REM</td><td>60</td>') in table
    assert "0 мин" not in _text(table)


def test_hypnogram_totals_only_never_invents_an_order(tmp_path):
    [card] = _render(tmp_path, [{"series": GOOGLE, "point": POINT, "session": _session()}])
    html = card["session"]
    assert 'data-hypnogram="totals-only"' in html
    assert "Последовательность стадий не сохранена — показаны только итоги" in html
    assert 'night-hypno-plot' not in html and 'Интервалы стадий' not in html


def test_hypnogram_missing_and_unknown_intervals_leave_unconnected_hatched_gaps(tmp_path):
    rows = [
        _interval("2026-10-25T20:30:00Z", "2026-10-25T21:00:00Z", "LIGHT"),
        _interval("2026-10-25T21:30:00Z", "2026-10-25T22:00:00Z", "UNMAPPED", ordinal=1),
        _interval("2026-10-25T22:00:00Z", "2026-10-25T23:30:00Z", "REM", ordinal=2),
    ]
    [card] = _render(tmp_path, [{"series": GOOGLE, "point": POINT,
                               "session": _interval_session(rows)}])
    graph = _graph(card["session"])
    assert graph.count('class="night-hypno-gap"') == 3
    assert 'x="0%" y="80" width="12.5%"' in graph
    assert 'x="25%" y="80" width="25%"' in graph
    assert 'x="87.5%" y="80" width="12.5%"' in graph
    assert graph.count('class="night-hypno-line"') == 2
    assert 'night-hypno-step' not in graph
    assert 'night-hypno-awake' not in graph
    table = _interval_table(card["session"])
    assert table.count('<tr>') == 3
    assert 'Неизвестная стадия (не показан на графике)' in table
    assert re.search(r'>0(?:[ <])', table) is None


@pytest.mark.parametrize("problem", ["overlap", "invalid", "local-only", "outside", "zero"])
def test_hypnogram_unconfirmed_intervals_do_not_become_stages(tmp_path, problem):
    rows = [_interval("2026-10-25T20:00:00Z", "2026-10-25T22:00:00Z", "LIGHT")]
    if problem == "overlap":
        rows.append(_interval("2026-10-25T21:00:00Z", "2026-10-25T23:00:00Z", "DEEP"))
    elif problem == "invalid":
        rows[0]["interval_state"] = "invalid"
    elif problem == "local-only":
        rows[0]["start_precision"] = "local_datetime"
        rows[0]["start_at_utc"] = None
    elif problem == "outside":
        rows[0]["start_at_utc"] = "2026-10-25T19:00:00Z"
    else:
        rows[0]["end_at_utc"] = rows[0]["start_at_utc"]
    [card] = _render(tmp_path, [{"series": GARMIN, "point": POINT,
                               "session": _interval_session(rows)}])
    graph = _graph(card["session"])
    assert 'night-hypno-line' not in graph
    assert 'width="100%" height="8"' in graph
    assert '(не показан на графике)' in _interval_table(card["session"])


def test_hypnogram_dst_keeps_elapsed_durations_and_does_not_guess_transition(tmp_path):
    rows = [
        _interval("2026-10-25T00:00:00Z", "2026-10-25T01:00:00Z", "LIGHT",
                  offset=120, end_offset=60),
        _interval("2026-10-25T02:00:00Z", "2026-10-25T04:00:00Z", "REM",
                  offset=None, ordinal=1),
    ]
    session = _interval_session(rows, start="2026-10-25T00:00:00Z", end="2026-10-25T04:00:00Z")
    [card] = _render(tmp_path, [{"series": GOOGLE, "point": POINT, "session": session}])
    graph = _graph(card["session"])
    assert 'LIGHT' not in graph
    assert 'Лёгкий · 02:00 UTC+02:00–02:00 UTC+01:00 · 60 мин' in graph
    assert 'REM · 02:00 UTC–04:00 UTC · 120 мин' in graph
    assert 'x1="50%" x2="100%"' in graph
    assert 'где смещение неизвестно, показано UTC' in card["session"]


@pytest.mark.parametrize("provider", ["garmin", "google"])
def test_hypnogram_renders_actual_saved_source_packet(projection_database, tmp_path, provider):
    from healthcheck.analytics.sleep_source_view import read_source_sleep_night
    from healthcheck.garmin.persistence import GarminPersistenceRepository
    from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
    from test_sleep_metrics import _google_sleep_payload, _persist_google, _stage
    from test_sleep_production_shape import normalized, production_sleep

    session, paths = projection_database
    if provider == "garmin":
        payload = production_sleep()
        # A saved internal gap withholds totals/end metric, but summary bounds survive.
        payload["sleepLevels"].pop(1)
        GarminPersistenceRepository(session, payload_store=ContentAddressedGarminPayloadStore(
            paths.root / "garmin-artifacts")).persist_result(normalized(payload), payload=payload)
    else:
        _persist_google(session, paths, payload=_google_sleep_payload(stages_status="SUCCEEDED",
            stages=[_stage("2099-01-01T22:00:00Z", "2099-01-01T23:00:00Z", "LIGHT"),
                    _stage("2099-01-02T00:00:00Z", "2099-01-02T05:00:00Z", "REM")]))
    session.commit()
    packet = read_source_sleep_night(session, provider=provider, wake_date=date(2099, 1, 2))
    selected = packet["sources"][0]["sessions"][0]
    snapshots = selected["metrics"]["sleep_stage_light_seconds"]["evidence"]["interval_snapshots"]
    stage_rows = [row for row in snapshots if row["interval_kind"] == "sleep_stage"]
    assert len(stage_rows) == (3 if provider == "garmin" else 2)
    assert stage_rows[0]["start_precision"] == "instant"
    assert stage_rows[0]["start_temporal"]["source_utc_offset_minutes"] == (
        60 if provider == "garmin" else 180)
    series = GARMIN if provider == "garmin" else GOOGLE
    [card] = _render(tmp_path, [{"series": series, "point": POINT, "session": selected}])
    graph = _graph(card["session"])
    assert graph.count('class="night-hypno-gap"') == 1
    assert graph.count('class="night-hypno-line"') == len(stage_rows)
    assert _interval_table(card["session"]).count('<tr>') == len(stage_rows)
    assert ('text-anchor="start">23:00</text>' if provider == "garmin" else
            'text-anchor="start">01:00</text>') in graph


def test_hypnogram_missing_bounds_never_invents_a_window(tmp_path):
    session = _interval_session([
        _interval("2026-10-25T20:00:00Z", "2026-10-25T21:00:00Z", "REM")])
    session["metrics"]["sleep_end_at"] = _cell(None, eligible=False, state="missing")
    [card] = _render(tmp_path, [{"series": GARMIN, "point": POINT, "session": session}])
    assert 'data-hypnogram="unavailable"' in card["session"]
    assert 'night-hypno-plot' not in card["session"]
    assert '<td>REM (не показан на графике)</td><td>60</td>' in _interval_table(card["session"])
