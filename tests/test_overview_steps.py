"""Overview source denominators and shared completed periods, with synthetic storage."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from healthcheck.config import Settings
from healthcheck.google.contracts import FAMILY_ALL_SOURCES
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.web import overview_body_battery, overview_completed, overview_steps, pages
from healthcheck.web.overview_view import overview_whole_number
from healthcheck.web.steps_presentation import steps_mean_display
from healthcheck.web.ui_app import create_ui_app
from test_garmin_completed_steps import acquire
from test_google_steps_countsum import civil, payload, persist
from test_overview_completed import NOW, seed_completed
from test_stress_baseline import database as database


def seed(database):
    paths, _, session, store = database
    source_id, settings = seed_completed(database)
    for day, value, status in [(1, 0, "succeeded"), (3, 10, "succeeded"),
                               (5, 999, "partial"), (8, 100000, "succeeded")]:
        acquire(session, store, value, day=date(2099, 1, day),
                at=NOW + timedelta(days=1) if day == 8 else NOW, status=status,
                account="synthetic-stress-account", receipt=status == "succeeded")
    google_db = (paths, session, ContentAddressedGooglePayloadStore(paths.root / "artifacts"))
    for day, value in [(2, "0"), (4, "20"), (6, "40"), (8, "200000")]:
        persist(google_db, payload(value, start=civil(day), end=civil(day + 1)))
    return source_id, settings


def read(database, source_id, *, start=date(2099, 1, 1), end=date(2099, 1, 8), preset=None):
    window = overview_completed.completed_overview_window(
        start=start, end=end, preset=preset, evaluated_at=NOW)
    return overview_steps.read_overview_steps(database[2], paths=database[0], window=window,
        source_id=source_id, evaluated_at=NOW)


def test_actual_readers_separate_denominators_missing_zero_partial_today_and_no_writes(database):
    source_id, _ = seed(database)
    statements = []

    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement.lstrip().split()[0].lower())

    event.listen(database[1], "before_cursor_execute", capture)
    try:
        result = read(database, source_id)
    finally:
        event.remove(database[1], "before_cursor_execute", capture)
    garmin, google = result["items"]
    assert [(row["mean_display"], row["count"], row["days"]) for row in result["items"]] == [
        ("5.0", 2, 7), ("20.0", 3, 7)]
    assert garmin["technical"].start_date == google["technical"]["start_date"] == date(2099, 1, 1)
    assert garmin["technical"].end_date == google["technical"]["end_date"] == date(2099, 1, 7)
    assert google["technical"]["coverage"] == google["technical"]["finality"] == "unknown"
    assert not {"insert", "update", "delete", "create", "alter"}.intersection(statements)


@pytest.mark.parametrize("preset", ["7", "30", "90"])
def test_rolling_dates_are_shared_and_google_never_substitutes_supported_window(database, preset):
    source_id, _ = seed(database)
    result = read(database, source_id, preset=preset)
    assert result["window"]["calendar_days"] == int(preset)
    assert result["window"]["end_date"] == "2099-01-07"
    assert result["items"][0]["technical"].start_date.isoformat() == result["window"]["start_date"]
    google = result["items"][1]
    if preset == "90":
        assert google["technical"] is None and google["mean_display"] is None
        assert google["reason"] == "unsupported_google_period"
    else:
        assert google["technical"]["start_date"].isoformat() == result["window"]["start_date"]


def test_custom_short_window_stays_exact_and_empty_today_has_no_reader_call(database, monkeypatch):
    source_id, _ = seed(database)
    result = read(database, source_id, start=date(2099, 1, 3), end=date(2099, 1, 3))
    assert result["items"][0]["mean_display"] == "10.0"
    assert result["items"][0]["days"] == 1
    assert result["items"][1]["reason"] == "unsupported_google_period"

    def forbidden(*_args, **_kwargs):
        pytest.fail("today-only period must not query or fall back")

    monkeypatch.setattr(overview_steps, "read_completed_steps_window", forbidden)
    monkeypatch.setattr(overview_steps, "read_saved_steps_window", forbidden)
    result = read(database, source_id, start=date(2099, 1, 8), end=date(2099, 1, 8))
    assert all(row["mean_display"] is None and row["reason"] == "no_completed_days"
               for row in result["items"])


def test_incomplete_reader_prefix_is_withheld_for_each_source(database, monkeypatch):
    source_id, _ = seed(database)
    original = overview_steps.read_completed_steps_window
    google_original = overview_steps.read_saved_steps_window
    monkeypatch.setattr(overview_steps, "read_completed_steps_window", lambda *a, **kw:
        replace(original(*a, **kw), search_complete=False, reason="candidate_cap"))
    monkeypatch.setattr(overview_steps, "read_saved_steps_window", lambda *a, **kw:
        dict(google_original(*a, **kw), search_complete=False, reason="record_cap"))
    assert all(row["mean_display"] is None and row["count"] is None
               for row in read(database, source_id)["items"])


def test_no_garmin_selection_never_autoselects_or_blends_other_account(database):
    source_id, _ = seed(database)
    acquire(database[2], database[3], 9000, account="other-account", receipt=True,
            day=date(2099, 1, 1), at=NOW)
    assert read(database, source_id)["items"][0]["mean_display"] == "5.0"
    assert read(database, None)["items"][0]["reason"] == "source_not_selected"


def test_zero_only_and_missing_period_are_distinct_and_google_families_never_pool(database):
    source_id, _ = seed(database)
    zero = read(database, source_id, start=date(2098, 12, 27), end=date(2099, 1, 2))
    assert all(row["mean_display"] == "0.0" and row["count"] == 1 for row in zero["items"])
    missing = read(database, source_id, start=date(2098, 12, 1), end=date(2098, 12, 7))
    assert all(row["mean_display"] is None and row["count"] == 0 for row in missing["items"])
    google_db = (database[0], database[2],
                 ContentAddressedGooglePayloadStore(database[0].root / "artifacts"))
    persist(google_db, payload("999999"), family=FAMILY_ALL_SOURCES)
    ambiguous = read(database, source_id)["items"][1]
    assert ambiguous["mean_display"] is None and ambiguous["reason"] == "source_selection_required"


def test_actual_route_shared_dates_and_four_columns_hrv_under_stress(database, monkeypatch):
    source_id, settings = seed(database)

    class FrozenDatetime(type(NOW)):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(pages, "datetime", FrozenDatetime)
    app, _ = create_ui_app(settings)
    app.state.engine = database[1]
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        response = client.get("/brief", params={"start_date": "2099-01-01",
            "end_date": "2099-01-08", "garmin_source_id": source_id})
    assert response.status_code == 200
    overview = response.context["overview"]
    assert overview["steps"]["window"] == overview["completed_window"]
    secondary = response.text.split('<section class="overview-secondary"', 1)[1].split(
        "</section>", 1)[0]
    columns = secondary.split("<article>")[1:]
    assert len(columns) == 4
    for column, marker in zip(columns, ["data-overview-rhr", "data-overview-steps",
                                       "data-overview-stress", "data-overview-body-battery"]):
        assert marker in column
    assert columns[2].index("data-overview-stress") < columns[2].index("data-overview-hrv")
    assert 'data-steps-provider="Garmin"' in columns[1]
    assert 'data-steps-provider="Google"' in columns[1]
    assert "последнее среднее за неделю" in columns[2]


@pytest.mark.parametrize("value,expected", [("0", "0"), ("10.49", "10"),
                                          ("10.5", "11"), ("60.51", "61")])
def test_mean_display_rounding_only(value, expected):
    precise = Decimal(value)
    assert overview_whole_number(precise) == expected
    assert precise == Decimal(value)


def test_tiny_positive_mean_is_not_rendered_as_observed_zero():
    assert steps_mean_display(1, 30) == "<0.1"
    assert steps_mean_display(0, 30) == "0.0"
    assert steps_mean_display(18446744073709551614, 3) == (
        "6\u202f148\u202f914\u202f691\u202f236\u202f517\u202f204.7")


def test_stress_and_battery_present_whole_means_without_changing_precision(database, monkeypatch):
    from healthcheck.web.garmin_query import GarminQueryService

    monkeypatch.setattr(GarminQueryService, "scalar_series", lambda *_a, **_kw: {"points": [
        {"analytic_date": "2099-01-01", "value": 10, "status": "usable"},
        {"analytic_date": "2099-01-02", "value": 11, "status": "usable"}]})
    monkeypatch.setattr(overview_body_battery, "read_body_battery_period", lambda *_a: {
        "mean_value": Decimal("60.5"), "mean_exact": {"numerator": 121, "denominator": 2},
        "search": {"complete": True}, "daily_maxima": []})
    result = overview_completed.read_completed_overview(
        database[2], Settings(data_dir=database[0].root),
        start=date(2099, 1, 1), end=date(2099, 1, 7), preset=None,
        source_id="synthetic", evaluated_at=NOW)
    assert result["period_stress"]["mean_value"] == Decimal("10.5")
    assert result["period_stress"]["mean_display"] == "11"
    assert [point["value"] for point in result["period_stress"]["figure"]["points"]] == [10, 11]
    assert result["body_battery"]["selected"]["mean_display"] == "61"
    assert result["body_battery"]["selected"]["mean_exact"] == {"numerator": 121, "denominator": 2}
