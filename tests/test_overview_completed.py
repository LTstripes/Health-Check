"""Completed Moscow Overview windows and real synthetic saved measurements."""

import os
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from healthcheck.config import Settings
from healthcheck.db.models import GarminSourceRecord
from healthcheck.db.repositories import repositories_for
from healthcheck.garmin.normalization import GarminSourceIdentity, normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.web import overview_completed as module
from healthcheck.web import pages
from healthcheck.web.garmin_query import GarminQueryError, GarminQueryService
from healthcheck.web.owner_presentation import owner_date
from healthcheck.web.ui_app import create_ui_app
from test_body_battery_read import seed_battery
from test_stress_baseline import acquire
from test_stress_baseline import database as database

NOW = datetime(2099, 1, 7, 21, tzinfo=UTC)  # Jan 8 at 00:00 Moscow, still Jan 7 UTC.
IDENTITY = GarminSourceIdentity(source_kind="provider", provider_code="garmin_connect",
                               device_attributed=False,
                               source_instance_id="synthetic-stress-account")


@pytest.mark.parametrize("preset", ["7", "30", "90"])
@pytest.mark.parametrize("offset", [-10, 0, 14])
def test_rolling_windows_are_exact_completed_moscow_days_not_host_days(preset, offset):
    result = module.completed_overview_window(
        start=date(2020, 1, 1), end=date(2020, 1, 2), preset=preset,
        evaluated_at=NOW.astimezone(timezone(timedelta(hours=offset))),
    )
    assert result["end_date"] == "2099-01-07"
    assert result["calendar_days"] == int(preset)
    assert date.fromisoformat(result["start_date"]) == date(2099, 1, 8) - timedelta(
        days=int(preset))


@pytest.mark.parametrize("instant,expected", [
    (datetime(2099, 1, 7, 20, 59, 59, tzinfo=UTC), "2099-01-06"),
    (NOW, "2099-01-07"),
    (datetime(2100, 1, 1, 0, tzinfo=UTC), "2099-12-31"),
])
def test_moscow_midnight_and_year_boundary(instant, expected):
    window = module.completed_overview_window(start=date(2098, 1, 1), end=date(2100, 1, 1),
                                              preset="7", evaluated_at=instant)
    assert window["end_date"] == expected and window["calendar_days"] == 7


@pytest.mark.parametrize("start,end,lower,upper,count", [
    ("2099-01-01", "2099-01-03", "2099-01-01", "2099-01-03", 3),
    ("2099-01-01", "2099-01-08", "2099-01-01", "2099-01-07", 7),
    ("2099-01-07", "2099-01-20", "2099-01-07", "2099-01-07", 1),
    ("2099-01-08", "2099-01-20", None, None, 0),
])
def test_custom_intersection_never_moves_start_or_invents_a_previous_day(
    start, end, lower, upper, count,
):
    result = module.completed_overview_window(start=date.fromisoformat(start),
        end=date.fromisoformat(end), preset=None, evaluated_at=NOW)
    assert (result["requested_start"], result["requested_end"]) == (start, end)
    assert (result["start_date"], result["end_date"], result["calendar_days"]) == (
        lower, upper, count)


def seed_completed(database):
    paths, _engine, session, store = database
    for day, value in [(1, 0), (3, 20), (8, 99)]:
        saved = acquire(database, date(2099, 1, day), value)
    repository = GarminPersistenceRepository(session, payload_store=store)
    for day, seconds in [(1, 4 * 3600), (3, 8 * 3600), (8, 20 * 3600)]:
        payload = {"dailySleepDTO": {"calendarDate": f"2099-01-{day:02d}",
                                    "sleepTimeSeconds": seconds}}
        repository.persist_result(normalize_garmin_payload(payload, stream="sleep",
            source_identity=IDENTITY), payload=payload, received_at=NOW + timedelta(days=2))
    for day, values in [(1, (80, 10, 20)), (3, (40,)), (8, (100,))]:
        stamp = datetime(2099, 1, day, tzinfo=UTC)
        repos = repositories_for(session)
        run = repos.sync.create_run(provider_id=saved.source.provider_id,
                                    stream_code="garmin_incremental")
        run.started_at = stamp + timedelta(days=1)
        seed_battery(session, store, day=stamp.date(), values=values, identity=IDENTITY,
                     received=stamp + timedelta(days=1),
                     source_filename="body_battery.json", sync_run_id=run.id)
        repos.sync.finish_run(run.id, status="succeeded")
    session.commit()
    return saved.source.id, Settings(data_dir=paths.root)


def read(database, source_id, settings, *, start=date(2099, 1, 1), end=date(2099, 1, 8),
         preset=None):
    return module.read_completed_overview(database[2], settings, start=start, end=end,
        preset=preset, source_id=source_id, evaluated_at=NOW)


def test_real_readers_average_days_and_nights_not_samples_with_no_writes(database):
    source_id, settings = seed_completed(database)
    statements = []

    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement.lstrip().split()[0].lower())

    event.listen(database[1], "before_cursor_execute", capture)
    try:
        result = read(database, source_id, settings)
    finally:
        event.remove(database[1], "before_cursor_execute", capture)
    assert not {"insert", "update", "delete", "create", "alter"}.intersection(statements)
    sleep, stress, battery = (result[key] for key in (
        "period_sleep", "period_stress", "body_battery"))
    assert sleep["duration_display"] == "6 ч 0 мин" and sleep["mean_value"] == 21600
    assert stress["mean_display"] == "10"
    assert sleep["eligible_days"] == stress["eligible_days"] == 2
    assert sleep["days"] == stress["days"] == 7
    assert battery["selected"]["mean_display"] == "60"  # NOT (80+10+20+40)/4.
    assert [point["value"] for point in battery["figure"]["points"]] == [80, 40]
    assert battery["figure"]["low"] == 0
    assert all(point["date"] < "2099-01-08" for point in sleep["figure"]["points"])
    assert result["completed_window"]["requested_end"] == "2099-01-08"


@pytest.mark.parametrize("values", [(-10, -5), (-5, 10), (0,), (101,)])
def test_battery_bars_keep_signed_finite_values_and_true_zero_axis(values):
    figure = module.dated_chart([
        {"date": f"2099-01-{index + 1:02d}", "value": value, "state": "present"}
        for index, value in enumerate(values)
    ], start=date(2099, 1, 1), end=date(2099, 1, 7), include_zero=True)
    assert figure["low"] <= 0 <= figure["high"]
    assert 24 <= figure["zero_y"] <= 104
    assert [point["value"] for point in figure["points"]] == list(values)
    assert all(24 <= point["y"] <= 104 for point in figure["points"])


def test_today_only_window_has_no_fallback_or_reader_call(database, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("empty completed window must not query a previous day")

    monkeypatch.setattr(GarminQueryService, "scalar_series", forbidden)
    monkeypatch.setattr(module, "read_overview_body_battery", forbidden)
    result = read(database, None, Settings(data_dir=database[0].root),
                  start=date(2099, 1, 8), end=date(2099, 1, 8))
    assert result["completed_window"]["empty"]
    assert result["period_sleep"]["mean_value"] is None
    assert result["period_stress"]["mean_display"] is None
    assert result["body_battery"]["selected"] is None


def test_record_status_does_not_reinterpret_accepted_scalar_eligibility(database):
    source_id, settings = seed_completed(database)
    records = database[2].scalars(select(GarminSourceRecord).where(
        GarminSourceRecord.stream_code == "sleep",
        GarminSourceRecord.source_local_date == date(2099, 1, 3))).all()
    assert records
    for record in records:
        record.record_status = "partial"
    database[2].commit()
    sleep = read(database, source_id, settings)["period_sleep"]
    # Record-level status does not replace the scalar reader's metric-level state.
    assert sleep["partial_days"] == 0 and sleep["eligible_days"] == 2
    assert sleep["mean_value"] == 21600


def test_daily_guard_keeps_zero_partial_missing_and_collisions_distinct(database, monkeypatch):
    source_id, settings = seed_completed(database)
    points = [
        {"analytic_date": "2099-01-01", "value": 0, "status": "zero"},
        {"analytic_date": "2099-01-02", "value": 20, "status": "partial"},
        {"analytic_date": "2099-01-03", "value": None, "status": "null"},
        {"analytic_date": "2099-01-04", "value": 50, "status": "usable"},
        {"analytic_date": "2099-01-04", "value": 70, "status": "usable"},
    ]
    monkeypatch.setattr(GarminQueryService, "scalar_series", lambda *_args, **_kw: {
        "points": points})
    result = read(database, source_id, settings)
    for key in ("period_sleep", "period_stress"):
        assert result[key]["mean_value"] == Decimal(10)
        assert result[key]["eligible_days"] == 2 and result[key]["partial_days"] == 1
        collision = result[key]["figure"]["points"][-1]
        assert collision["value"] is None and collision["ambiguous"]


def test_caps_and_read_errors_never_expose_partial_prefix_mean(database, monkeypatch):
    source_id, settings = seed_completed(database)

    def capped(*_args, **_kwargs):
        raise GarminQueryError("selected_points_exceed_max", "bounded synthetic failure")

    monkeypatch.setattr(GarminQueryService, "scalar_series", capped)
    for args in ({}, {"start": date(2097, 1, 1)}):
        result = read(database, source_id, settings, **args)
        for key in ("period_sleep", "period_stress"):
            assert result[key]["mean_value"] is None and result[key]["figure"] is None
            assert result[key]["reason"] in {"read_unavailable", "range_exceeds_max"}
        # BB keeps its independent record-bound, without a new 400-day cap.
        assert result["body_battery"]["selected"]["mean_display"] == "60"


def test_route_preserves_requested_packet_and_form_but_shows_completed_card_ranges(
    database, monkeypatch,
):
    source_id, settings = seed_completed(database)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(pages, "datetime", FrozenDatetime)
    app, _ = create_ui_app(settings)
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        response = client.get("/brief", params={"start_date": "2099-01-01",
            "end_date": "2099-01-08", "garmin_source_id": source_id})
        assert response.status_code == 200
        assert response.context["packet"]["period"]["end_date"] == "2099-01-08"
        assert 'name="end_date" value="2099-01-08"' in response.text
        assert response.context["overview"]["completed_window"]["end_date"] == "2099-01-07"
        assert "6 ч 0 мин" in response.text
        assert 'data-overview-chart="body-battery"' in response.text
        assert "Максимум за сохранённый день" not in response.text
        assert "Дата окончания выбранного периода" not in response.text
        assert response.context["overview"]["rhr"]  # Existing independent RHR path retained.
        today = client.get("/brief?start_date=2099-01-08&end_date=2099-01-08")
        assert today.status_code == 200
        assert today.text.count("В выбранном периоде нет завершённых дней") == 3


@pytest.mark.parametrize("mode", ["empty", "zero", "partial", "invalid", "withheld"])
def test_battery_empty_plot_and_withheld_error_stay_distinct(database, monkeypatch, mode):
    source_id, settings = seed_completed(database)
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(pages, "datetime", FrozenDatetime)
    original = pages.read_completed_overview

    def presented(*args, **kwargs):
        result = original(*args, **kwargs)
        battery = result["body_battery"]
        dto = battery["selected"]
        if mode == "withheld":
            dto.update(reason="period_record_cap", state="search_incomplete",
                       mean_display=None, mean_exact=None, daily_maxima=[],
                       eligible_day_count=None)
            dto["search"]["complete"] = False
            battery["figure"] = None
        else:
            point = dict(dto["daily_maxima"][0], source_local_date="2099-01-03",
                         value=0, is_zero=True)
            available = mode in {"zero", "partial"}
            dto.update(mean_display="0" if available else None,
                       mean_exact={"numerator": 0, "denominator": 1} if available else None,
                       state="observed" if available else "no_eligible_in_period",
                       eligible_day_count=1 if available else 0,
                       daily_maxima=[point] if available else [])
            rows = [] if mode == "empty" else [{
                "date": "2099-01-03", "value": None if mode == "invalid" else 0,
                "state": "partial" if mode == "partial" else "present"}]
            battery["figure"] = module.dated_chart(rows, start=date(2099, 1, 1),
                end=date(2099, 1, 7), include_zero=True)
        return result

    monkeypatch.setattr(pages, "read_completed_overview", presented)
    with TestClient(create_ui_app(settings)[0], base_url="http://127.0.0.1:8120") as client:
        page = client.get("/brief", params={"start_date": "2099-01-01",
            "end_date": "2099-01-07", "garmin_source_id": source_id})
    assert page.status_code == 200
    assert ('data-overview-chart="body-battery"' in page.text) == (mode in {"zero", "partial"})
    assert ('data-overview-empty="body-battery"' in page.text) == (mode in {"empty", "invalid"})
    if mode == "withheld":
        assert "Достигнут лимит записей периода; среднее недоступно." in page.text
        assert "Поиск не завершён" in page.text
    assert f"{owner_date(date(2099, 1, 1))} — {owner_date(date(2099, 1, 7))}" in page.text
    if target := os.environ.get("HEALTHCHECK_WEEKLY_PREVIEW_DIR"):
        Path(target).mkdir(parents=True, exist_ok=True)
        Path(target, f"battery-{mode}.html").write_text(page.text, encoding="utf-8")


@pytest.mark.parametrize("value,trend,plot", [(None, None, False), (None, 70, False),
                                          (0, None, True), (70, None, True), (70, 71, True)])
def test_weight_observed_gate_and_actual_ewma_legend(database, monkeypatch, value, trend, plot):
    source_id, settings = seed_completed(database)
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(pages, "datetime", FrozenDatetime)
    original = pages.read_overview_charts

    def charts(*args, **kwargs):
        result = original(*args, **kwargs)
        result["weight_current"] = {"value_kg": value,
                                    "observed_date": "2099-01-03"} if value is not None else None
        result["weight_trend"]["available"] = trend is not None
        result["weight"] = module.dated_chart([
            {"date": "2099-01-03", "value": value, "trend": trend, "state": "present"}],
            start=date(2099, 1, 1), end=date(2099, 1, 7), weight_layout=True)
        return result

    monkeypatch.setattr(pages, "read_overview_charts", charts)
    with TestClient(create_ui_app(settings)[0], base_url="http://127.0.0.1:8120") as client:
        page = client.get("/brief", params={"start_date": "2099-01-01",
            "end_date": "2099-01-07", "garmin_source_id": source_id})
    assert page.status_code == 200
    assert ('data-overview-chart="weight"' in page.text) == plot
    if plot:
        figure = page.text.split('data-overview-chart="weight"', 1)[1].split('</figure>', 1)[0]
        assert ('overview-weight-diamond' in figure) == (trend is not None)
        assert 'overview-observed' in figure
    else:
        assert 'data-overview-empty="weight"' in page.text
    if target := os.environ.get("HEALTHCHECK_WEEKLY_PREVIEW_DIR"):
        Path(target).mkdir(parents=True, exist_ok=True)
        Path(target, f"weight-{value}-{trend}.html").write_text(page.text, encoding="utf-8")
