"""#515 compact presentation: whole-number Steps, coverage qualifiers, quiet scope notes."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from healthcheck.web import pages
from healthcheck.web.statistics import format_steps_value
from healthcheck.web.steps_presentation import (
    _chart,
    steps_mean_display,
    steps_whole_display,
)
from healthcheck.web.ui_app import create_ui_app
from overview_html import parse_overview
from test_garmin_completed_steps import BOUNDARY, DAY, NOW, acquire
from test_overview_completed import NOW as OVERVIEW_NOW
from test_overview_completed import seed_completed, seed_detail_navigation
from test_statistics_steps_ui import StepsParser, steps_html
from test_statistics_ui import projection_database as projection_database
from test_statistics_ui import statistics_ui as statistics_ui
from test_stress_baseline import database as database

NNBSP = " "


@pytest.mark.parametrize("value,expected", [
    (None, None),
    (0, "0"),
    (7, "7"),
    (999, "999"),
    (1000, f"1{NNBSP}000"),
    (12345, f"12{NNBSP}345"),
    # Exact large counts stay exact: no float round trip.
    (9_007_199_254_740_993, f"9{NNBSP}007{NNBSP}199{NNBSP}254{NNBSP}740{NNBSP}993"),
    # Defensive: a non-integer count is rounded half up only for display.
    (Decimal("2.5"), "3"),
    (Decimal("2.4999"), "2"),
    (Decimal("12344.5"), f"12{NNBSP}345"),
    (1234.4, f"1{NNBSP}234"),
])
def test_steps_whole_display_rounds_only_at_presentation(value, expected):
    assert steps_whole_display(value) == expected


def test_steps_whole_display_is_never_zero_for_missing_or_bool():
    assert steps_whole_display(None) is None
    assert steps_whole_display(True) is None


@pytest.mark.parametrize("total,count,expected", [
    (20, 3, "7"),  # 6.67
    (5, 2, "3"),  # exact .5 rounds up
    (7, 2, "4"),
    (1, 3, "0"),  # a real zero-ish mean stays a number, not "нет данных"
    (0, 4, "0"),  # genuine zeros keep a 0 mean
    (10**18 + 1, 2, f"500{NNBSP}000{NNBSP}000{NNBSP}000{NNBSP}000{NNBSP}001"),
])
def test_steps_mean_boundaries_are_whole_numbers(total, count, expected):
    shown = steps_mean_display(total, count)
    assert shown == expected
    assert "." not in shown and "," not in shown


def test_chart_labels_and_selected_day_values_are_whole_grouped_counts():
    chart = _chart([
        {"date": date(2099, 1, 1), "state": "value", "value": 12345},
        {"date": date(2099, 1, 2), "state": "missing", "value": None},
        {"date": date(2099, 1, 3), "state": "value", "value": 0},
    ])
    rows = chart["rows"]
    assert [row["display"] for row in rows] == [f"12{NNBSP}345", None, "0"]
    # The exact stored count stays available unchanged for the browser data.
    assert [row["value"] for row in rows] == ["12345", None, "0"]
    assert all("." not in tick["label"] for tick in chart["ticks"])
    assert format_steps_value(12345) == f"12{NNBSP}345"


def test_statistics_daily_table_shows_grouped_whole_counts_and_keeps_missing(
    statistics_ui, monkeypatch,
):
    session, paths, client = statistics_ui
    from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore

    store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    for index, count in enumerate([12345, 0, None, 1001]):
        saved = acquire(session, store, count, day=DAY + timedelta(days=index),
                        at=BOUNDARY + timedelta(days=index))
    session.commit()
    monkeypatch.setattr(
        "healthcheck.web.statistics.steps_evaluation_instant", lambda: NOW + timedelta(days=7))
    response = client.get("/statistics", params={
        "period": "7", "end_date": str(DAY + timedelta(days=6)),
        "garmin_source_id": saved.source.id,
    })
    assert response.status_code == 200
    html = steps_html(response)
    values = {day: text.strip() for day, text in StepsParser(html).values.items()}
    assert values[DAY.isoformat()] == f"12{NNBSP}345"
    assert values[(DAY + timedelta(days=1)).isoformat()] == "0"
    assert values[(DAY + timedelta(days=2)).isoformat()] == "Недоступно"
    assert values[(DAY + timedelta(days=3)).isoformat()] == f"1{NNBSP}001"
    # Mean over eligible days only: (12345 + 0 + 1001) / 3 = 4448.67 → 4 449.
    assert f"data-steps-mean>4{NNBSP}449</dd>" in html
    assert "Точное среднее: 13346 / 3" in html


def _frozen(monkeypatch, instant):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)

    monkeypatch.setattr(pages, "datetime", FrozenDatetime)


def test_overview_cards_show_short_coverage_qualifier_only_when_incomplete(
    database, monkeypatch,
):
    source_id, settings = seed_completed(database)
    _frozen(monkeypatch, OVERVIEW_NOW)
    with TestClient(create_ui_app(settings)[0], base_url="http://127.0.0.1:8120") as client:
        page = client.get("/brief", params={"start_date": "2099-01-01",
                                            "end_date": "2099-01-08",
                                            "garmin_source_id": source_id})
    assert page.status_code == 200
    dom = parse_overview(page.text)
    sleep = dom.one("div", **{"data-overview-period-sleep": None})
    stress = dom.one("div", **{"data-overview-stress": None})
    battery = dom.one("div", **{"data-overview-body-battery": None})
    for card, noun in ((sleep, "ночей"), (stress, "дней"),
                       (battery, "дней")):
        qualifier = card.one("span", classes=("overview-coverage",))
        assert qualifier.attrs["data-coverage-qualifier"] == "2/7"
        assert qualifier.text.strip() == f"2 из 7 {noun}"
        for detail in card.find("details"):
            if "open" not in detail.attrs:
                assert qualifier not in detail.find("span", classes=("overview-coverage",))
    # Means themselves are unchanged; missing days stay gaps, not zeros.
    assert "6 ч 00 мин" in sleep.text


@pytest.mark.parametrize("count,days,expected", [
    (3, 7, "3 из 7 дней"),
    (21, 31, "21 из 31 дня"),
    (10, 11, "10 из 11 дней"),
    (7, 7, ""),  # complete coverage: nothing extra to show
    (0, 7, ""),  # no value: the card already says «нет данных»
    (None, 7, ""),
])
def test_coverage_qualifier_wording(count, days, expected):
    template = pages.templates.env.from_string(
        "{% from 'overview_coverage.html' import coverage_qualifier %}"
        "{{ coverage_qualifier(count, days) }}")
    rendered = template.render(count=count, days=days)
    assert (expected in rendered) if expected else "overview-coverage" not in rendered


def test_sessions_and_detail_keep_return_links_visible_and_scope_notes_folded(
    database, monkeypatch,
):
    source, settings = seed_detail_navigation(database)
    instant = OVERVIEW_NOW + timedelta(hours=15)
    _frozen(monkeypatch, instant)
    with TestClient(create_ui_app(settings)[0], base_url="http://127.0.0.1:8120") as client:
        overview = client.get("/brief", params={"preset": "7", "period_at": instant.isoformat(),
                                                "garmin_source_id": source})
        frozen = overview.context["overview_href"]
        activity_link = overview.context["overview_detail_links"]["activity"]
        assert parse_qs(urlsplit(activity_link).query)["return_to"] == [frozen]
        sessions = client.get(activity_link)
        assert sessions.status_code == 200
        primary = sessions.text.split('<details class="statistics-details">', 1)[0]
        # Return target and short source/date caption stay in the main view.
        assert f'href="{frozen.replace("&", "&amp;")}" data-statistics-return' in primary
        assert "Вернуться к выбранному обзору" in primary
        assert 'class="muted sessions-caption">Garmin ·' in primary
        # Scope and limit explanations are kept, but folded.
        assert "Лимит списка" not in primary and "Лимит списка" in sessions.text
        assert "Исходный показатель" not in primary and "Исходный показатель" in sessions.text
        detail_href = sessions.context["packet"]["sessions"][0]["detail_href"]
        detail = client.get(detail_href)
        assert detail.status_code == 200
        back = parse_overview(detail.text).one(
            "p", classes=("activity-session-back",)).one("a")
        assert back.text.strip() == "К сессиям за период"
        assert client.get(back.attrs["href"]).context["back_href"] == frozen
        card = detail.text.split('<section class="card activity-session-detail"', 1)[1]
        card = card.split("</section>", 1)[0]
        folded = card.split('<details class="owner-info">', 1)[1].split("</details>", 1)[0]
        assert "остаётся отсутствующим, а не нулевым" in folded
        assert card.count("остаётся отсутствующим") == 1


def test_compact_styles_are_page_scoped_and_keep_touch_targets():
    from pathlib import Path

    static = Path(pages.__file__).parent / "static"
    css = (static / "owner_compact.css").read_text(encoding="utf-8")
    # Summaries keep the 44px project minimum: no override shrinks them.
    assert "min-height: 3" not in css and "min-height: 2" not in css
    for template in ("statistics.html", "garmin.html", "activity_period.html",
                     "activity_detail.html"):
        text = (static.parent / "templates" / template).read_text(encoding="utf-8")
        assert "/static/owner_compact.css" in text
    base = (static.parent / "templates" / "base.html").read_text(encoding="utf-8")
    assert "owner_compact.css" not in base


def test_activity_comparison_keeps_sign_convention_in_reading_guide(statistics_ui):
    _session, _paths, client = statistics_ui
    page = client.get("/garmin")
    assert page.status_code == 200
    comparison = page.text.split('id="activity-comparison"', 1)[1].split("</section>", 1)[0]
    guide = comparison.split("<summary>Как читать сравнение</summary>", 1)[1]
    assert "B минус A" in guide and "а не лучше или хуже" in guide


def test_google_exercise_keeps_short_unknown_completeness_visible(statistics_ui):
    _session, _paths, client = statistics_ui
    page = client.get("/garmin")
    card = page.text.split('id="google-exercise"', 1)[1].split("</section>", 1)[0]
    visible = card.split("<details", 1)[0]
    assert "Полнота истории неизвестна." in visible
    assert "Health Connect" not in visible and "Health Connect" in card


def test_value_meta_and_low_coverage_boundary():
    from healthcheck.web.owner_presentation import owner_low_coverage

    macro = pages.templates.env.get_template("owner_ui.html").module.value_meta
    partial = str(macro("Google", count=1, days=3))
    assert 'owner-meta-dot--google' in partial
    assert 'data-coverage-qualifier="1/3"' in partial
    assert "1 \u0438\u0437 3 \u0434\u043d\u0435\u0439" in partial
    assert 'data-coverage-qualifier' not in str(macro("Garmin", count=3, days=3))
    assert 'data-coverage-qualifier' not in str(macro("Garmin", count=0, days=3))
    assert owner_low_coverage(1, 3)
    assert not owner_low_coverage(2, 3)
    assert not owner_low_coverage(None, 3)
