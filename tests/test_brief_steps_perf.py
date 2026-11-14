"""#620 exact old/new Steps packets, SSR comparison rows and request isolation."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from scripts.steps_read_reference import (
    read_completed_steps_window_reference,
    read_saved_steps_window_reference,
)
from sqlalchemy import event

from healthcheck.config import Settings
from healthcheck.garmin import completed_steps_read
from healthcheck.garmin.completed_steps_read import completion_boundary
from healthcheck.google.contracts import FAMILY_ALL_SOURCES
from healthcheck.google.steps_read import read_saved_steps_windows
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.web import overview_steps, pages, period_brief_query
from healthcheck.web.overview_compare import previous_overview_window
from healthcheck.web.overview_completed import completed_overview_window
from healthcheck.web.ui_app import create_ui_app
from test_garmin_completed_steps import acquire
from test_google_steps_countsum import MISSING, payload, persist
from test_stress_baseline import database as database

NOW = datetime(2099, 3, 2, 12, tzinfo=UTC)
END = date(2099, 3, 1)


def civil(day, *, nanos=0):
    return {"date": {"year": day.year, "month": day.month, "day": day.day},
            "time": {"hours": 0, "minutes": 0, "seconds": 0, "nanos": nanos}}


def seed(database):
    paths, _, session, store = database
    points = []
    for offset in range(65):
        day = END - timedelta(days=offset)
        value = (0, None, 6000, 15000, 21)[offset % 5]
        if offset % 11 == 0:
            continue  # A genuinely missing date, separate from stored zero/null.
        saved = acquire(session, store, value, day=day,
                        at=completion_boundary(day) + timedelta(hours=1),
                        receipt=True, commit=False)
        points.extend(payload(MISSING if offset % 7 == 0 else
                              None if value is None else str(value),
                              start=civil(day), end=civil(day + timedelta(days=1)))
                      ["rollupDataPoints"])
    session.commit()
    google = (paths, session, ContentAddressedGooglePayloadStore(paths.root / "artifacts"))
    persist(google, {"rollupDataPoints": points})
    # Latest unproved acquisition must hide the older count, not reveal it.
    acquire(session, store, 777, day=END - timedelta(days=3), at=NOW,
            status="failed", receipt=False)
    acquire(session, store, 99999, day=END - timedelta(days=1), at=NOW,
            account="other-account", receipt=True)
    return saved.source.id, google


def reference_pair(session, *, paths, window, previous_window, source_id, evaluated_at):
    """Old independent current/prior reads and exact source propagation."""
    with patch.object(overview_steps, "read_completed_steps_window",
                      read_completed_steps_window_reference), patch.object(
                          overview_steps, "read_saved_steps_window",
                          read_saved_steps_window_reference):
        current = overview_steps.read_overview_steps(
            session, paths=paths, window=window, source_id=source_id, evaluated_at=evaluated_at)
        google_id = (current["items"][1]["technical"] or {}).get("source_id")
        previous = current if window["empty"] else overview_steps.read_overview_steps(
            session, paths=paths, window=previous_window, source_id=source_id,
            evaluated_at=evaluated_at, google_source_id=google_id)
    return current, previous


def bounds(days):
    return completed_overview_window(start=END - timedelta(days=days - 1), end=END,
                                     preset=None, evaluated_at=NOW)


def read_pair(database, source, window, reader=overview_steps.read_overview_steps_pair):
    return reader(database[2], paths=database[0], window=window,
                  previous_window=previous_overview_window(window), source_id=source,
                  evaluated_at=NOW)


@pytest.mark.parametrize("days", [1, 7, 30, 90, 367])
@pytest.mark.parametrize("selection", ["selected", "none", "google_ambiguous"])
def test_complete_steps_context_equals_frozen_old_evaluators(database, days, selection):
    source, google = seed(database)
    if selection == "none":
        source = None
    if selection == "google_ambiguous":
        persist(google, payload("99999"), family=FAMILY_ALL_SOURCES)
    window = bounds(days)
    expected = read_pair(database, source, window, reference_pair)
    assert read_pair(database, source, window) == expected


@pytest.mark.parametrize("days", [7, 30, 90])
def test_ssr_steps_and_comparison_and_html_equal_old_path(database, monkeypatch, days):
    source, _ = seed(database)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(pages, "datetime", Clock)
    monkeypatch.setattr(period_brief_query, "datetime", Clock)
    app, _ = create_ui_app(Settings(data_dir=database[0].root))
    app.state.engine = database[1]
    params = {"start_date": (END - timedelta(days=days - 1)).isoformat(),
              "end_date": END.isoformat(), "garmin_source_id": source}
    client = TestClient(app, base_url="http://127.0.0.1:8120")
    try:
        with patch.object(pages, "read_overview_steps_pair", reference_pair):
            before = client.get("/brief", params=params)
        after = client.get("/brief", params=params)
    finally:
        client.close()
    assert before.status_code == after.status_code == 200
    assert after.context["overview"]["steps"] == before.context["overview"]["steps"]
    for response in (before, after):
        assert response.context["overview"]["comparison"]["coverage_threshold"] == {
            "numerator": 2, "denominator": 3}
    assert after.context["overview"]["comparison"] == before.context["overview"]["comparison"]
    assert after.text == before.text  # Includes labels, dates, provenance and freshness.


def test_pair_reads_each_source_once_and_does_not_write(database):
    source, _ = seed(database)
    statements = []

    def capture(_connection, _cursor, sql, *_args):
        statements.append(sql)

    event.listen(database[1], "before_cursor_execute", capture)
    try:
        result = read_pair(database, source, bounds(30))
    finally:
        event.remove(database[1], "before_cursor_execute", capture)
    assert result == read_pair(database, source, bounds(30), reference_pair)
    assert sum("FROM garmin_payload_observations" in sql for sql in statements) == 1
    assert sum("FROM google_source_records" in sql and "JOIN" not in sql
               and "EXISTS" not in sql for sql in statements) == 1
    assert all(sql.lstrip().split()[0].upper() in {"SELECT", "BEGIN"} for sql in statements)


def test_new_request_sees_correction_and_empty_window_stays_empty(database):
    source, google = seed(database)
    window = bounds(7)
    before = read_pair(database, source, window)
    corrected = END - timedelta(days=2)
    persist(google, payload("0", start=civil(corrected),
                            end=civil(corrected + timedelta(days=1))), epoch=2000)
    acquire(database[2], database[3], 0, day=corrected, at=NOW, receipt=True)
    after = read_pair(database, source, window)
    assert after == read_pair(database, source, window, reference_pair)
    assert before != after
    assert after[0]["items"][0]["technical"].cells[-3].value == 0
    assert after[0]["items"][1]["technical"]["cells"][-3]["value"] == 0
    empty = completed_overview_window(start=NOW.date(), end=NOW.date(),
                                      preset=None, evaluated_at=NOW)
    assert read_pair(database, source, empty) == read_pair(database, source, empty, reference_pair)


def test_overflowing_union_preserves_narrow_window_and_original_counts(database, monkeypatch):
    import scripts.steps_read_reference as reference

    source = None
    for day in (date(2099, 1, 1), date(2099, 1, 2), END):
        saved = acquire(database[2], database[3], 17, day=day,
                        at=completion_boundary(day), receipt=True)
        source = saved.source.id
    monkeypatch.setattr(completed_steps_read, "MAX_PROVENANCE", 2)
    monkeypatch.setattr(reference, "MAX_PROVENANCE", 2)
    result = read_pair(database, source, bounds(30))
    assert result == read_pair(database, source, bounds(30), reference_pair)
    assert result[0]["items"][0]["technical"].search_complete
    assert not result[1]["items"][0]["technical"].search_complete


def test_unlocatable_google_interval_outside_union_still_withholds_both(database):
    from sqlalchemy import select

    from healthcheck.db.models import GoogleRecordInterval

    source, _ = seed(database)
    row = database[2].scalar(select(GoogleRecordInterval).order_by(
        GoogleRecordInterval.start_local_date))
    row.start_temporal_json = "{}"
    database[2].commit()
    result = read_pair(database, source, bounds(7))
    assert result == read_pair(database, source, bounds(7), reference_pair)
    assert all(item["items"][1]["technical"]["reason"] == "unlocatable_interval"
               for item in result)


def test_google_overlap_across_windows_matches_independent_reads(database):
    source, google = seed(database)
    boundary = END - timedelta(days=7)
    persist(google, payload("100", start=civil(boundary),
                           end=civil(boundary + timedelta(days=2))))
    persist(google, payload("100", start=civil(END - timedelta(days=1), nanos=1),
                           end=civil(END, nanos=1)))
    result = read_pair(database, source, bounds(7))
    assert result == read_pair(database, source, bounds(7), reference_pair)
    assert result[0]["items"][1]["technical"]["cells"][-2]["state"] == "ambiguous"
    # Nonadjacent supported windows never invent intermediate requested dates.
    windows = ((END - timedelta(days=6), END),
               (END - timedelta(days=36), END - timedelta(days=30)))
    actual = read_saved_steps_windows(database[2], windows=windows)
    assert actual == [read_saved_steps_window_reference(database[2], start_date=start,
                                                        end_date=end)
                      for start, end in windows]


def test_empty_profile_matches_original_without_inventing_zero(database):
    actual = read_pair(database, None, bounds(7))
    assert actual == read_pair(database, None, bounds(7), reference_pair)
    assert all(item["mean_value"] is None for packet in actual for item in packet["items"])


def test_far_apart_windows_do_not_expand_the_intervening_calendar(database):
    _, google = seed(database)
    persist(google, payload("999", start=civil(date(1, 1, 1)),
                           end=civil(date(9999, 12, 31))))
    windows = ((date(1, 1, 1), date(1, 1, 7)),
               (date(9999, 12, 24), date(9999, 12, 30)))
    actual = read_saved_steps_windows(database[2], windows=windows)
    assert actual == [read_saved_steps_window_reference(database[2], start_date=start,
                                                        end_date=end)
                      for start, end in windows]
    assert all(len(packet["cells"]) == 7 for packet in actual)
