"""Synthetic Overview B1/B2 contracts through real readers and the SSR route."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
from scripts.profile_brief import parse_timing
from sqlalchemy import event, select

from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, session_scope
from healthcheck.db.models import GarminSource, GoogleSource
from healthcheck.db.repositories import repositories_for
from healthcheck.garmin.daily_energy import read_daily_energy
from healthcheck.garmin.normalization import GarminSourceIdentity
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.web import overview_compare as module
from healthcheck.web import pages
from healthcheck.web.overview_completed import completed_overview_window, read_completed_overview
from healthcheck.web.overview_coverage import overview_low_coverage
from healthcheck.web.overview_rhr import read_overview_rhr
from healthcheck.web.overview_steps import read_overview_steps
from test_body_battery_read import seed_battery
from test_garmin_completed_steps import acquire as acquire_daily
from test_garmin_query_dashboard import _ui
from test_google_daily_vitals import RHR, _daily_record, _persist
from test_google_steps_countsum import civil, payload, persist
from test_sleep_account_cohort import _garmin, _google
from test_sleep_metrics import _google_sleep_payload, _persist_google
from test_sleep_metrics import projection_database as projection_database
from test_stress_baseline import acquire as acquire_stress
from test_stress_baseline import database as database

NOW = datetime(2099, 3, 2, 12, tzinfo=UTC)


@pytest.mark.parametrize("preset", ["7", "30", "90", None])
@pytest.mark.parametrize("end", [date(2024, 3, 1), date(2026, 1, 1)])
def test_previous_is_adjacent_equal_length_across_month_leap_year_and_custom(preset, end):
    current = completed_overview_window(start=end - timedelta(days=12), end=end,
        preset=preset, evaluated_at=datetime.combine(end + timedelta(days=1),
                                                   datetime.min.time(), UTC))
    previous = module.previous_overview_window(current)
    assert previous["calendar_days"] == current["calendar_days"]
    assert date.fromisoformat(previous["end_date"]) + timedelta(days=1) == date.fromisoformat(
        current["start_date"])
    assert (date.fromisoformat(previous["end_date"])
            - date.fromisoformat(previous["start_date"])).days + 1 == current["calendar_days"]


@pytest.mark.parametrize("current,previous,reason", [
    ((2, 3), (2, 3), None), ((1, 3), (2, 3), "low_coverage_current"),
    ((2, 3), (1, 3), "low_coverage_previous"),
    ((20, 30), (20, 30), None), ((19, 30), (30, 30), "low_coverage_current"),
])
def test_exact_threshold_shared_with_ui_and_signed_zero_difference(current, previous, reason):
    def value(number, coverage):
        count, days = coverage
        return module._value(number, count, {"calendar_days": days})

    result = module._comparison("steps", "garmin", "source", "steps", "mean",
                                value(0, current), value(10, previous))
    assert result["reason"] == reason
    assert result["difference"] == (Decimal(-10) if reason is None else None)
    assert result["current"]["low_coverage"] == overview_low_coverage(*current)
    assert result["previous"]["low_coverage"] == overview_low_coverage(*previous)


@pytest.mark.parametrize("current,previous", [(None, 0), (0, None), (None, None)])
def test_missing_never_becomes_zero_or_difference(current, previous):
    result = module._comparison("stress", "garmin", "source", "points", "mean",
        module._value(current, 0 if current is None else 3, {"calendar_days": 3}),
        module._value(previous, 0 if previous is None else 3, {"calendar_days": 3}))
    assert result["difference"] is None and result["reason"] == "missing"


@pytest.fixture
def comparison_page(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromisoformat(NOW.isoformat()).astimezone(tz)

    monkeypatch.setattr(pages, "datetime", Clock)
    app, settings, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    with session_scope(engine) as session:
        # Two of three days in both windows; distinct providers and a stored zero.
        for day, seconds, minutes in [(date(2099, 2, 24), 1200, "40"),
                                      (date(2099, 2, 25), 2400, "50"),
                                      (date(2099, 2, 27), 0, "60"),
                                      (date(2099, 2, 28), 1800, "80")]:
            _garmin(session, paths, day, seconds=seconds)
            _google(session, paths, day, minutes=minutes, main="true")
        session.commit()
        source = session.scalar(select(GarminSource.id))
    engine.dispose()
    return app, settings, paths, source


def test_real_route_separates_values_coverage_and_missing_without_writes(comparison_page):
    app, _, paths, source = comparison_page
    engine = create_sqlite_engine(paths)
    app.state.engine = engine
    statements = []

    def capture(_c, _u, sql, *_):
        statements.append(sql.lstrip().split()[0].lower())

    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        event.listen(engine, "before_cursor_execute", capture)
        try:
            response = client.get("/brief", params={"start_date": "2099-02-27",
                "end_date": "2099-03-01", "garmin_source_id": source})
        finally:
            event.remove(engine, "before_cursor_execute", capture)
            engine.dispose()
    assert response.status_code == 200
    packet = response.context["overview"]["comparison"]
    rows = {(item["metric"], item["provider"]): item for item in packet["items"]}
    garmin, google = (rows["sleep_duration", provider] for provider in ("garmin", "google"))
    assert garmin["current"]["value"] == 900
    assert garmin["previous"]["value"] == 1800
    assert garmin["difference"] == -900
    assert google["current"]["value"] == 4200
    assert google["previous"]["value"] == 2700
    assert google["difference"] == 1500
    assert garmin["source_id"] != google["source_id"]
    for row in (garmin, google):
        assert row["current"]["coverage"] == row["previous"]["coverage"] == {"count": 2, "days": 3}
    assert rows["daily_calories_garmin_estimate", "garmin"]["current"]["value"] is None
    assert rows["steps", "google"]["current"]["reason"] == "unsupported_google_period"
    assert packet["coverage_threshold"] == {"numerator": 2, "denominator": 3}
    assert response.context["overview_low_coverage"](2, 3) is False
    assert len(jsonable_encoder(packet)["items"]) == 10
    assert not {"insert", "update", "delete", "create", "alter"}.intersection(statements)
    assert [item["wake_date"] for item in packet["last_nights"]] == ["2099-02-28"] * 2


def test_latest_night_preserves_midnight_and_each_endpoint_zone_change(projection_database):
    session, paths = projection_database
    payload = _google_sleep_payload()
    payload["dataPoints"][0]["sleep"]["interval"] = {
        "startTime": "2026-10-24T20:00:00Z", "startUtcOffset": "7200s",
        "endTime": "2026-10-25T06:00:00Z", "endUtcOffset": "3600s",
        "civilStartTime": {"date": "2026-10-24", "time": {"hours": 22}},
        "civilEndTime": {"date": "2026-10-25", "time": {"hours": 7}},
    }
    _persist_google(session, paths, payload=payload)
    session.commit()
    source = session.scalar(select(GoogleSource.id))
    window = {"empty": False, "calendar_days": 1,
              "start_date": "2026-10-25", "end_date": "2026-10-25"}
    packet = module._sleep(session, provider="google", window=window, source_id=source)
    night = module._last_night(session, provider="google", packet=packet)
    assert night["reason"] is None
    assert night["start"]["local_datetime"] == "2026-10-24T22:00:00+02:00"
    assert night["end"]["local_datetime"] == "2026-10-25T07:00:00+01:00"
    assert night["start"]["utc_offset_minutes"] == 120
    assert night["end"]["utc_offset_minutes"] == 60
    assert night["duration_seconds"] == 24600  # source asleep duration, not elapsed bounds


def test_missing_bounds_keep_duration_and_reason_instead_of_inventing_end(comparison_page):
    app, _, _, source = comparison_page
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        page = client.get("/brief", params={"start_date": "2099-02-27",
            "end_date": "2099-03-01", "garmin_source_id": source})
    garmin = page.context["overview"]["comparison"]["last_nights"][0]
    assert garmin["duration_seconds"] == 1800
    assert garmin["reason"] == "bounds_unavailable"
    assert garmin["end"]["at_utc"] is None


def test_newer_nap_does_not_replace_last_eligible_main_night(comparison_page):
    app, _, paths, source = comparison_page
    engine = create_sqlite_engine(paths)
    with session_scope(engine) as session:
        _google(session, paths, date(2099, 3, 1), minutes="90", nap="true", main="false")
    engine.dispose()
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        page = client.get("/brief", params={"start_date": "2099-02-27",
            "end_date": "2099-03-01", "garmin_source_id": source})
    night = page.context["overview"]["comparison"]["last_nights"][1]
    assert night["wake_date"] == "2099-02-28" and night["duration_seconds"] == 4800


def test_sleep_previous_window_stays_on_current_source(projection_database):
    session, paths = projection_database
    from healthcheck.google.contracts import FAMILY_GOOGLE_SOURCES

    for day in (date(2099, 1, 1), date(2099, 1, 8)):
        _google(session, paths, day, minutes="60")
    _google(session, paths, date(2099, 1, 1), family=FAMILY_GOOGLE_SOURCES, minutes="90")
    session.commit()
    current = {"empty": False, "calendar_days": 7,
               "start_date": "2099-01-08", "end_date": "2099-01-14"}
    selected = module._sleep(session, provider="google", window=current)
    prior = module._sleep(session, provider="google",
        window=module.previous_overview_window(current),
        source_id=selected["source_identity"]["source_id"])
    assert selected["source_identity"]["source_id"] == prior["source_identity"]["source_id"]
    assert prior["aggregation"]["value"] == 3600
    assert len(prior["eligible_dates"]) == 1


def test_intensity_selected_span_excludes_expanded_monday_and_preserves_zero(monkeypatch):
    window = {"empty": False, "calendar_days": 3,
              "start_date": "2099-02-27", "end_date": "2099-03-01"}
    monkeypatch.setattr(module, "read_intensity_minutes", lambda *a, **k: {
        "reason": None, "rows": [
            {"date": date(2099, 2, 23), "total": Decimal(999)},
            {"date": date(2099, 2, 27), "total": Decimal(0)},
            {"date": date(2099, 2, 28), "total": Decimal(15)},
            {"date": date(2099, 3, 1), "total": None},
        ]})
    value = module._intensity(None, source_id="source", window=window)
    assert value["value"] == 15 and value["coverage"] == {"count": 2, "days": 3}
    assert not value["low_coverage"]


def test_real_metric_readers_preserve_aggregation_sources_and_stored_zero(database):
    paths, _, session, store = database
    google_db = paths, session, ContentAddressedGooglePayloadStore(paths.root / "artifacts")
    identity = GarminSourceIdentity(source_kind="provider", provider_code="garmin_connect",
        source_instance_id="synthetic-stress-account", device_attributed=False)
    for number in (1, 2, 3, 4, 5, 8, 9, 10, 11, 12):
        day = date(2099, 1, number)
        current = number >= 8
        saved = acquire_stress(database, day, 0 if current else 10)
        daily = acquire_daily(session, store, 0 if current else 100, day=day, at=NOW,
            receipt=True, account=identity.source_instance_id, extra={
                "restingHeartRate": 50 if current else 60,
                "totalKilocalories": 0 if current else 1000,
                "moderateIntensityMinutes": 0 if current else 10,
                "vigorousIntensityMinutes": 0 if current else 5,
            })
        repos = repositories_for(session)
        run = repos.sync.create_run(provider_id=saved.source.provider_id,
                                    stream_code="garmin_incremental")
        run.started_at = NOW - timedelta(minutes=1)
        seed_battery(session, store, day=day, values=(0, 0) if current else (40, 10),
            identity=identity, received=NOW, source_filename="body_battery.json",
            sync_run_id=run.id)
        repos.sync.finish_run(run.id, status="succeeded")
        _persist(session, google_db[2], _daily_record(metric_code=RHR, local_date=day,
            value=70 if current else 65, external_record_id=f"rhr-{day}"))
        session.commit()
        persist(google_db, payload("0" if current else "200", start=civil(number),
                                  end=civil(number + 1)))
    settings = Settings(data_dir=paths.root)
    start, end = date(2099, 1, 8), date(2099, 1, 14)
    source = daily.source.id
    overview = read_completed_overview(session, settings, start=start, end=end,
        preset=None, source_id=source, evaluated_at=NOW)
    overview["steps"] = read_overview_steps(session, paths=paths,
        window=overview["completed_window"], source_id=source, evaluated_at=NOW)
    overview["rhr"] = read_overview_rhr(session, start=start, end=end, explicit_period=True,
        evaluated_at_utc=NOW, evaluation_local_date=NOW.date(), garmin_source_id=source)
    overview["energy"] = read_daily_energy(session, source_id=source, start=start, end=end)
    result = module.read_overview_comparison(session, settings, paths=paths, overview=overview,
        start=start, end=end, source_id=source, evaluated_at=NOW)
    rows = {(row["metric"], row["provider"]): row for row in result["items"]}
    for metric, provider, current, prior, delta in (
        ("resting_heart_rate", "garmin", 50, 60, -10),
        ("resting_heart_rate", "google", 70, 65, 5),
        ("steps", "garmin", 0, 100, -100), ("steps", "google", 0, 200, -200),
        ("stress", "garmin", 0, 10, -10), ("body_battery", "garmin", 0, 40, -40),
        ("daily_calories_garmin_estimate", "garmin", 0, 1000, -1000),
        ("intensity_minutes", "garmin", 0, 100, -100),
    ):
        row = rows[metric, provider]
        assert (row["current"]["value"], row["previous"]["value"], row["difference"]) == (
            current, prior, delta), row
        assert row["current"]["coverage"] == row["previous"]["coverage"] == {"count": 5, "days": 7}
        assert row["reason"] is None


def test_30_day_query_budget_with_both_windows_populated(comparison_page):
    app, _, paths, source = comparison_page
    engine = create_sqlite_engine(paths)
    with session_scope(engine) as session:
        for offset in range(60):
            day = date(2098, 12, 1) + timedelta(days=offset)
            _garmin(session, paths, day, seconds=18000)
            _google(session, paths, day, minutes="300", main="true")
    engine.dispose()
    params = {"start_date": "2098-12-31", "end_date": "2099-01-29",
              "garmin_source_id": source}
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        with patch.object(pages, "read_overview_comparison", return_value={}):
            baseline = client.get("/brief", params=params)
        candidate = client.get("/brief", params=params)
    assert baseline.status_code == candidate.status_code == 200
    counts = [sum(value for key, value in parse_timing(page.headers["Server-Timing"]).items()
                  if key.endswith("_queries")) for page in (baseline, candidate)]
    print(f"30-day populated windows SQL before/after: {counts}")
    assert counts[0] < counts[1] <= 2 * counts[0], counts
    row = candidate.context["overview"]["comparison"]["items"][0]
    assert row["current"]["coverage"] == row["previous"]["coverage"] == {"count": 30, "days": 30}
    assert row["difference"] == 0
