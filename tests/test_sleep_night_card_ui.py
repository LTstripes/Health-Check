"""Selected-night card on /sleep: production JS helpers rendered on synthetic sessions."""

from __future__ import annotations

import json
import re
import subprocess
from html import unescape
from pathlib import Path

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
    # Everything before the first disclosure is the always-visible part of the card.
    return html.split("<details", 1)[0]


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
