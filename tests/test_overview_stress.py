"""#357 Overview slice through the real stress reader and route, synthetic only."""

from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from healthcheck.analytics import stress_baseline as adapter
from healthcheck.config import Settings
from healthcheck.web import pages, period_brief_query
from healthcheck.web.garmin_query import GarminQueryService
from healthcheck.web.overview_stress import read_overview_stress
from healthcheck.web.overview_view import read_overview_values
from healthcheck.web.ui_app import create_ui_app
from test_stress_baseline import ABSENT, NOW, D, acquire, metric
from test_stress_baseline import database as database


@pytest.fixture
def evaluation_clock(monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2099, 2, 1, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(pages, "datetime", FrozenDatetime)
    monkeypatch.setattr(period_brief_query, "datetime", FrozenDatetime)


def seed_days(database, *, n=21, current=2, values=None, early_day=None, **kwargs):
    values = [0] * (n - 1) + [n] if values is None else values
    history = [
        acquire(
            database,
            day,
            value,
            zone=None,
            at=datetime.combine(day, datetime.min.time(), UTC) if day == early_day else None,
            **kwargs,
        )
        for i, value in enumerate(values)
        for day in [D - timedelta(days=28 - i)]
    ]
    saved = (
        acquire(
            database,
            D,
            current,
            zone=None,
            at=datetime.combine(D, datetime.min.time(), UTC) if D == early_day else None,
            **kwargs,
        )
        if current is not ABSENT
        else None
    )
    return saved or history[0], history


def view(database, source_id, *, day=D, now=NOW):
    paths, _engine, session, _store = database
    return read_overview_stress(
        session,
        Settings(data_dir=paths.root),
        selected_date=day,
        garmin_source_id=source_id,
        evaluated_at_utc=now,
    )


def page(database, source_id, *, start=None, end=D):
    paths = database[0]
    app, _ = create_ui_app(Settings(data_dir=paths.root))
    params = {"start_date": (start or end).isoformat(), "end_date": end.isoformat()}
    if source_id is not None:
        params["garmin_source_id"] = source_id
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        response = client.get("/brief", params=params)
    assert response.status_code == 200
    return response


def card(response):
    class Bounds(HTMLParser):
        def __init__(self):
            super().__init__()
            self.depth = 0
            self.start = self.end = None

        def handle_starttag(self, tag, attrs):
            if tag != "div":
                return
            if "data-overview-stress" in dict(attrs):
                assert self.start is None, "Duplicate Stress card"
                self.start = self.getpos()
                self.depth = 1
            elif self.depth:
                self.depth += 1

        def handle_endtag(self, tag):
            if tag == "div" and self.depth:
                self.depth -= 1
                if not self.depth:
                    self.end = self.getpos()

    parser = Bounds()
    parser.feed(response.text)
    parser.close()
    assert parser.start is not None and parser.end is not None and parser.depth == 0
    lines = response.text.splitlines(keepends=True)

    def offset(position):
        line, column = position
        return sum(map(len, lines[:line - 1])) + column

    return response.text[offset(parser.start):offset(parser.end) + len("</div>")]


@pytest.mark.parametrize(
    "current,expected",
    [
        (2, "На 1 балл. выше среднего"),
        (1, "Совпадает со средним"),
        (0, "На 1 балл. ниже среднего"),
    ],
)
def test_real_reader_uses_daily_mean_not_median_and_keeps_result_identity(
    database,
    current,
    expected,
):
    saved, _history = seed_days(database, current=current)
    result = view(database, saved.source.id)
    assert result["current"]["value"] == current
    assert result["mean_display"] == "1"  # median of these days is zero
    assert result["delta_text"] == expected
    assert result["observed_days"] == 21
    original = GarminQueryService(database[2], Settings(data_dir=database[0].root)).stress_baseline(
        garmin_source_id=saved.source.id,
        selected_date=D,
        evaluated_at=NOW,
        analysis_day_policy=adapter.MOSCOW_ANALYSIS_DAY_POLICY,
        comparison_method=adapter.ARITHMETIC_MEAN_COMPARISON,
    )
    assert result["result_hash"] == original["result_hash"]
    assert original["comparison"]["mean"] == 1 and original["comparison"]["median"] == 0


@pytest.mark.parametrize("n", [20, 21, 28])
def test_real_reader_keeps_21_of_28_gate_and_zero_distinct(database, n):
    saved, _history = seed_days(database, n=n, current=0, values=[0] * n)
    result = view(database, saved.source.id)
    assert result["current"]["value"] == 0
    assert result["observed_days"] == n
    assert result["mean_display"] == ("0" if n >= 21 else None)
    assert result["delta_text"] == ("Совпадает со средним" if n >= 21 else None)
    if n < 21:
        assert result["reason"] == "Нужно не менее 21 пригодного дня истории из 28."


def test_fractional_difference_does_not_look_equal_after_display_rounding(database):
    saved, _history = seed_days(database, current=0, values=[0] * 20 + [0.021])
    result = view(database, saved.source.id)
    assert result["mean_display"] == "0"
    assert result["delta_text"] == "Менее чем на 0,01 балла ниже среднего"


@pytest.mark.parametrize("bad", [ABSENT, None, True, "2"])
def test_no_older_day_fallback_for_missing_null_invalid_current(database, bad):
    saved, _history = seed_days(database, current=ABSENT)
    if bad is not ABSENT:
        acquire(database, D, bad, zone=None)
    result = view(database, saved.source.id)
    assert result["current"]["value"] is None
    assert result["current"]["date"] == D.isoformat()
    assert result["mean_display"] is result["delta_text"] is None
    assert result["reason"] == "За выбранную дату нет однозначного пригодного значения."


@pytest.mark.parametrize("scope", ["current", "history"])
@pytest.mark.parametrize("failure", ["early_receipt", "unit", "method", "original", "clock"])
def test_real_proof_failure_blocks_whole_comparison_without_subset(
    database,
    scope,
    failure,
):
    early_day = (
        (D if scope == "current" else D - timedelta(days=28))
        if failure == "early_receipt"
        else None
    )
    saved, history = seed_days(database, n=22, early_day=early_day)
    target = saved if scope == "current" else history[0]
    day = target.records[0].source_local_date
    if failure == "early_receipt":
        # Seed the selected acquisition early initially; a later valid version must not exist.
        pass
    elif failure == "clock":
        acquire(database, day, 3, zone=None, extra={"utcOffset": "+04:00"})
    elif failure == "original":
        acquire(
            database,
            day,
            3,
            zone=None,
            original={"calendarDate": day.isoformat(), "avgStressLevel": 99},
        )
    else:
        if failure == "unit":
            metric(database[2], target).unit = "percent"
        else:
            target.records[0].normalization_contract_version = "unknown-stress-version"
        database[2].commit()
    result = view(database, saved.source.id)
    assert result["mean_display"] is result["delta_text"] is None
    assert result["reason"]
    assert result["comparison_state"] != "available"
    if scope == "history":
        assert result["current"]["value"] == 2


def test_real_caps_are_short_user_reasons_not_partial_statistics(database, monkeypatch):
    saved, _history = seed_days(database)
    monkeypatch.setattr(adapter, "MAX_ARTIFACT_BYTES", 10)
    result = view(database, saved.source.id)
    assert result["current"]["value"] == 2
    assert result["mean_display"] is result["delta_text"] is None
    assert result["reason"] == "Достигнут лимит размера исходных данных."


def test_moscow_policy_rejects_other_confirmed_zone_and_does_not_pool_sources(database):
    saved, _history = seed_days(database)
    other = acquire(database, D, 99, zone="Asia/Tokyo", account="other-synthetic-account")
    assert view(database, saved.source.id)["mean_display"] == "1"
    foreign = view(database, other.source.id)
    assert foreign["current"]["value"] == 99
    assert foreign["mean_display"] is None
    assert "даты и время" in foreign["reason"]
    assert "Выберите источник Garmin" in view(database, None)["reason"]


def test_late_evaluation_never_upgrades_early_acquisition(database):
    saved, _history = seed_days(database, current=ABSENT)
    acquire(database, D, 2, zone=None, at=datetime.combine(D, datetime.min.time(), UTC))
    for instant in (NOW, NOW + timedelta(days=90)):
        result = view(database, saved.source.id, now=instant)
        assert result["current"]["value"] == 2
        assert result["mean_display"] is None
        assert result["reason"] == "Данные одного из дней получены до окончания суток."


def test_route_mean_uses_selected_period_without_28_day_baseline(
    database,
    evaluation_clock,
    monkeypatch,
):
    saved, _history = seed_days(database)
    calls = []
    real = GarminQueryService.scalar_series

    def capture(self, **kwargs):
        if kwargs["metric_code"] == "stress_daily_average":
            calls.append((kwargs["start_date"], kwargs["end_date"],
                self.session.connection().connection.driver_connection.in_transaction))
        return real(self, **kwargs)

    monkeypatch.setattr(GarminQueryService, "scalar_series", capture)
    results = []
    for start in (D, D - timedelta(days=6), D - timedelta(days=29)):
        response = page(database, saved.source.id, start=start)
        results.append(response.context["overview"]["period_stress"])
        text = card(response)
        assert "Среднее за период" in text and "data-stress-mean" in text
        assert "data-stress-delta" not in text and "Выбранная дата" not in text
        assert "data-stress-evidence" in text
    assert [item["mean_display"] for item in results] == ["2", "2", "1"]
    assert results[-1]["mean_value"] > 1  # Display rounding does not change the mean.
    assert [item["eligible_days"] for item in results] == [1, 1, 22]
    assert [item["days"] for item in results] == [1, 7, 30]
    assert calls == [(start, D, True) for start in (D, D - timedelta(days=6),
                                                  D - timedelta(days=29))]


def test_route_missing_end_day_keeps_period_mean_and_separate_saved_snapshot(
    database,
    evaluation_clock,
):
    saved, _history = seed_days(database, current=ABSENT)
    response = page(database, saved.source.id, start=D - timedelta(days=28))
    text = card(response)
    result = response.context["overview"]["period_stress"]
    assert result["mean_display"] == "1" and result["eligible_days"] == 21
    assert result["days"] == 29 and "21/29 дней" not in text
    assert "data-stress-mean" in text and "Выбранная дата" not in text
    assert response.context["overview"]["garmin"]["stress_daily_average"]["value"] == 21


def test_route_keeps_existing_technical_data_without_dumping_comparison_evidence(
    database,
    evaluation_clock,
):
    saved, _history = seed_days(database)
    response = page(database, saved.source.id)
    before = read_overview_values(database[2], start=D, end=D, selected_id=saved.source.id)
    assert response.context["overview"]["technical"] == before["technical"]
    assert "arithmetic-mean-v1" not in response.text
    # The same scalar hash may already exist in the unchanged packet disclosure;
    # the compact card itself must not dump that technical result.
    assert response.context["overview"]["period_stress"]["technical"]["result_hash"] not in (
        card(response))
    assert "Технические детали" not in card(response)


def test_route_requires_choice_with_multiple_garmin_sources(database, evaluation_clock):
    seed_days(database)
    acquire(database, D, 99, account="another-synthetic-account")
    response = page(database, None)
    assert response.context["source_selection"]["status"] == "require_selection"
    assert "Выберите источник Garmin" in card(response)
    assert response.context["overview"]["period_stress"]["mean_value"] is None


def test_history_unrepresentable_date_stays_card_reason_not_an_invented_window(database):
    result = view(database, None, day=date.min)
    assert result["mean_display"] is None and result["history_start"] is None
    assert "нельзя построить" in result["reason"]
