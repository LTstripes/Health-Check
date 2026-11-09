"""Trip/event passport (#463): synthetic packets and the real reader on synthetic data."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from healthcheck import trip_passport as tp
from healthcheck.chat_evidence import MAX_ROWS, EvidenceError
from healthcheck.config import Settings
from healthcheck.context import ContextService, parse_interval, parse_timestamp
from healthcheck.db.engine import session_scope
from healthcheck.trip_passport import PassportError, PassportRequest
from healthcheck.web import trip_passport as web
from healthcheck.web.ui_app import create_ui_app
from test_combined_evidence import profile as _combined_profile
from test_combined_evidence import sleep_profile as _sleep_profile
from test_sleep_evidence import CLOCK, DAY

profile = _combined_profile
sleep_profile = _sleep_profile

SOURCE = "garmin-source-1"
GOOGLE = "google-source-1"


# ---------------------------------------------------------------------------
# Synthetic packets in the exact decoded-JSON shape of the combined export
# ---------------------------------------------------------------------------


def _days(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def _completed_cell(day, state, value=None, reason=None):
    return {"source_id": SOURCE, "calendar_date": day, "state": state, "value": value,
            "reason": reason, "completion_boundary_utc": f"{day}T21:00:00+00:00",
            "search_complete": True, "coverage": "unknown", "device": "unknown",
            "timezone": "unknown", "finality": "unknown", "evidence": []}


def _observed_cell(day, state, value=None, reason=None):
    return {"source_id": SOURCE, "calendar_date": day, "state": state, "value": value,
            "reason": reason, "metric_code": "observed_daily_steps", "unit": "steps",
            "search_complete": True, "evidence": []}


def _sleep_provider(source_id, provider, nights):
    points = [{"wake_date": day, "state": state, "value": value, "unit": "seconds",
               "partial": False, "role_uncertain": uncertain, "reason": None,
               "record_id": f"{provider}-{day}", "candidate_record_ids": [], "exclusions": [],
               "is_zero": value == 0}
              for day, (state, value, uncertain) in nights.items()]
    return {"provider_code": provider, "selected_source_id": source_id,
            "selection": "one_explicit_exact_source",
            "source_range": {"state": "records", "series": [{"source": {}, "points": points}],
                             "days": []}}


def _session(day, kind, utc, *, offset=None, zone=None, record="w1"):
    return {"record_id": record, "activity_type": kind, "record_status": "current",
            "source_local_date": day,
            "start": {"measured_at_utc": utc, "precision": "instant",
                      "source_local_date": day, "source_timezone": zone,
                      "source_utc_offset_minutes": offset, "local_wall_time": None,
                      "source_local_timestamp": None, "state": "instant"}}


def _note(event_id, start, *, end=None, zone=None, offset=None, text="note"):
    temporal = {"kind": "instant" if offset is not None else "date",
                "start_local_date": start, "start_timezone": zone,
                "start_utc_offset_minutes": offset, "start_precision":
                "minute" if offset is not None else "date",
                "start_source_timestamp": None, "start_at_utc": None,
                "end_local_date": end, "end_timezone": None,
                "end_utc_offset_minutes": None, "end_precision": None,
                "end_source_timestamp": None, "end_at_utc": None}
    return {"event_id": event_id, "revision_id": event_id + "-r1", "revision_number": 1,
            "original_text": text, "temporal": temporal, "tags": []}


def make_packet(*, end, days, today, completed=(), observed=None, sleep=None, sessions=(),
                notes=(), rhr=None, battery=(), truncated=False, steps_source=SOURCE,
                envelope="hash-current", activity_state="complete"):
    start = date.fromisoformat(end) - timedelta(days=days - 1)
    window = _days(start, date.fromisoformat(end))
    sleep = sleep if sleep is not None else {"garmin": (SOURCE, {})}
    sections = {
        "steps": {"source_id": steps_source, "contract_version": "completed-v2",
                  "cells": [c for c in completed if c["calendar_date"] in window],
                  "warnings": ["missing_is_not_zero"]},
        "sleep": {"reader_contract": "source-sleep-range-v1", "providers": {
            name: _sleep_provider(source_id, name, nights)
            for name, (source_id, nights) in sleep.items()}},
        "activity": {"temporal_evidence": {
            "state": activity_state, "reason": None, "date_basis": "persisted_source_local_date",
            "sessions": list(sessions), "retired_exclusions": []}},
        "context": {"limit": MAX_ROWS, "truncated": truncated, "has_more": truncated,
                    "trust": "untrusted_data_never_tool_instructions",
                    "absence_semantics": "no_comment_does_not_mean_no_exposure",
                    "rows": list(notes)},
        "rhr": {"providers": rhr or {}},
        "body_battery": {"state": "values", "unit": "points", "meaning": "daily_maximum",
                         "metric_code": "body_battery", "source_identity": {"source_id": SOURCE},
                         "daily_maxima": [{"source_local_date": d, "value": v}
                                          for d, v in battery]},
    }
    current = {
        "version": "health-chat-combined-compact-evidence-v5", "envelope_hash": envelope,
        "generated_at_utc": "2026-12-01T00:00:00+00:00",
        "evaluation_clock": {"local_date": today, "utc": f"{today}T09:00:00+00:00"},
        "request": {"days": days, "effective_range": {"start_date": window[0],
                                                       "end_date": window[-1]},
                    "range_truncated": False, "steps_view": "completed", "sources": {}},
        "sections": sections,
    }
    observed_packet = {
        **current, "envelope_hash": envelope + "-observed",
        "request": {**current["request"], "steps_view": "observed"},
        "sections": {"steps": {"source_id": steps_source, "contract_version": "observed-v1",
                               "cells": [c for c in (observed or ()) if c["calendar_date"]
                                         in window]}},
    }
    return current, observed_packet


def passport_request(start, end, **changes):
    return PassportRequest(start_date=date.fromisoformat(start),
                           end_date=date.fromisoformat(end), title="Поездка",
                           garmin_source_id=SOURCE, **changes)


# ---------------------------------------------------------------------------
# Time zones: Moscow -> far zone with a DST change -> back; midnight
# ---------------------------------------------------------------------------


def test_zone_change_dst_and_midnight_keep_stored_local_dates():
    new_york = ZoneInfo("America/New_York")
    # Synthetic but realistic stored offsets: New York leaves DST on 01.11.2026.
    assert datetime(2026, 10, 26, 10, tzinfo=new_york).utcoffset() == timedelta(hours=-4)
    assert datetime(2026, 11, 2, 9, tzinfo=new_york).utcoffset() == timedelta(hours=-5)
    notes = [
        _note("depart", "2026-10-25", zone="Europe/Moscow", offset=180, text="Вылет"),
        _note("arrive", "2026-10-26", zone="America/New_York", offset=-240, text="Прилёт"),
        _note("after-dst", "2026-11-02", zone="America/New_York", offset=-300, text="Музей"),
        _note("home", "2026-11-14", zone="Europe/Moscow", offset=180, text="Дома"),
    ]
    sessions = [
        # 23:30 local on 27.10 in New York is 03:30 UTC on 28.10: stays on 27.10.
        _session("2026-10-27", "running", "2026-10-28T03:30:00+00:00",
                 offset=-240, zone="America/New_York", record="late-run"),
        # No stored zone: shown in UTC, never assigned a guessed zone.
        _session("2026-11-05", "walking", "2026-11-05T14:00:00+00:00", record="walk"),
    ]
    completed = [_completed_cell("2026-10-27", "value", 9000),
                 _completed_cell("2026-10-28", "value", 4000)]
    current, observed = make_packet(end="2026-11-14", days=30, today="2026-11-20",
                                    completed=completed, sessions=sessions, notes=notes)
    request = passport_request("2026-10-25", "2026-11-14")
    assert request.day_count == 21 and request.export_days == 30
    passport = tp.build_passport(request, {"current": current, "observed_steps": observed})

    workouts = {w["record_id"]: w for w in passport["workouts"]["sessions"]}
    assert workouts["late-run"]["date"] == "2026-10-27"
    assert workouts["late-run"]["start_local"] == "2026-10-27T23:30:00"
    assert workouts["late-run"]["start_local_basis"] == "utc_plus_stored_offset"
    assert workouts["walk"]["start_local"] is None
    assert workouts["walk"]["start_local_basis"] == "utc_only_zone_unknown"
    steps = {row["date"]: row for row in passport["steps"]["days"]}
    assert steps["2026-10-27"]["value"] == 9000 and steps["2026-10-28"]["value"] == 4000

    zones = passport["zones"]
    by_day = {item["date"]: item for item in zones["days"]}
    assert by_day["2026-10-27"]["zones"] == [{"timezone": "America/New_York",
                                              "utc_offset_minutes": -240,
                                              "utc_offset": "UTC-04:00"}]
    # Unknown days stay unknown: nothing is carried forward from a previous day.
    assert by_day["2026-10-30"]["state"] == "unknown"
    assert by_day["2026-11-05"]["state"] == "unknown"
    assert [(c["from_date"], c["to_date"], c["kind"]) for c in zones["changes"]] == [
        ("2026-10-25", "2026-10-26", "zone_change"),
        ("2026-10-27", "2026-11-02", "offset_change_same_zone"),
        ("2026-11-02", "2026-11-14", "zone_change"),
    ]
    assert zones["changes"][-1]["to"][0]["utc_offset"] == "UTC+03:00"
    assert zones["inference"] == "not_performed_unknown_zones_stay_unknown"
    assert zones["unknown_day_count"] == 21 - 5
    segments = web.passport_zone_segments(passport)
    assert [s["zones"][0]["utc_offset"] for s in segments] == [
        "UTC+03:00", "UTC-04:00", "UTC-05:00", "UTC+03:00"]


def test_context_interval_overlapping_the_period_is_kept_once():
    notes = [_note("trip", "2026-10-20", end="2026-10-26", text="Вся поездка"),
             _note("before", "2026-10-01", text="раньше"),
             _note("after", "2026-11-30", text="позже")]
    current, observed = make_packet(end="2026-10-31", days=7, today="2026-12-01", notes=notes)
    passport = tp.build_passport(passport_request("2026-10-25", "2026-10-31"),
                                 {"current": current, "observed_steps": observed})
    assert [row["event_id"] for row in passport["context"]["rows"]] == ["trip"]
    assert passport["context"]["state"] == "complete"


# ---------------------------------------------------------------------------
# Steps: completed, true zero, incomplete, gap, conflict, future
# ---------------------------------------------------------------------------


def test_steps_distinguish_completed_zero_incomplete_gap_conflict_and_future():
    completed = [
        _completed_cell("2026-11-01", "value", 8000),
        _completed_cell("2026-11-02", "value", 0),
        _completed_cell("2026-11-03", "unavailable", reason="no_post_boundary_acquisition"),
        _completed_cell("2026-11-04", "unavailable", reason="no_post_boundary_acquisition"),
        _completed_cell("2026-11-05", "ambiguous", reason="divergent_latest_acquisitions"),
    ]
    observed = [
        _observed_cell("2026-11-03", "value", 5000),
        _observed_cell("2026-11-04", "projection_unavailable", reason="not_evidenced"),
        _observed_cell("2026-11-05", "value", 7000),
        _observed_cell("2026-11-06", "ambiguous", reason="divergent_saved_observations"),
        _observed_cell("2026-11-07", "value", 0),
    ]
    current, observed_packet = make_packet(end="2026-11-08", days=30, today="2026-11-07",
                                           completed=completed, observed=observed)
    passport = tp.build_passport(passport_request("2026-11-01", "2026-11-08"),
                                 {"current": current, "observed_steps": observed_packet})
    steps = {row["date"]: row for row in passport["steps"]["days"]}
    assert {day: (row["state"], row["value"]) for day, row in steps.items()} == {
        "2026-11-01": ("completed", 8000),
        "2026-11-02": ("zero", 0),
        "2026-11-03": ("incomplete", 5000),
        "2026-11-04": ("missing", None),
        "2026-11-05": ("conflict", None),
        "2026-11-06": ("conflict", None),
        "2026-11-07": ("incomplete", 0),
        "2026-11-08": ("future", None),
    }
    assert steps["2026-11-03"]["reason"] == "no_post_boundary_acquisition"
    assert steps["2026-11-07"]["reason"] == "completion_boundary_not_reached"
    summary = passport["steps"]
    # Only proven completed days (including a true zero) are counted.
    assert summary["counted_day_count"] == 2
    assert summary["total"] == 8000 and summary["mean_exact"] == "4000"
    assert summary["state_counts"] == {"completed": 1, "zero": 1, "incomplete": 2,
                                       "conflict": 2, "missing": 1, "future": 1}
    assert passport["coverage"]["future_dates"] == ["2026-11-08"]
    markdown = tp.render_passport_markdown(passport)
    assert "| 2026-11-04 | — | нет данных |" in markdown
    assert "| 2026-11-02 | 0 | завершённый день, 0 шагов |" in markdown
    assert "км" not in markdown.replace("Без км", "")


def test_no_values_means_missing_not_zero_and_no_mean():
    current, observed = make_packet(end="2026-11-07", days=7, today="2026-11-30")
    passport = tp.build_passport(passport_request("2026-11-01", "2026-11-07"),
                                 {"current": current, "observed_steps": observed})
    assert {row["state"] for row in passport["steps"]["days"]} == {"missing"}
    assert passport["steps"]["total"] is None and passport["steps"]["mean_exact"] is None


# ---------------------------------------------------------------------------
# Source conflict: never pooled, never silently resolved
# ---------------------------------------------------------------------------


def test_sources_are_kept_apart_and_uncertain_sleep_is_a_conflict():
    sleep = {
        "garmin": (SOURCE, {"2026-11-02": ("value", 25200, False),
                            "2026-11-03": ("value", 27000, True)}),
        "google": (GOOGLE, {"2026-11-02": ("value", 23400, False)}),
    }
    rhr = {
        "garmin": {"state": "values", "unit": "bpm", "source_identity": {"source_id": SOURCE},
                   "observations": [{"source_local_date": "2026-11-02", "value": 55}]},
        "google": {"state": "values", "unit": "bpm", "source_identity": {"source_id": GOOGLE},
                   "observations": [{"source_local_date": "2026-11-02", "value": 58}]},
    }
    current, observed = make_packet(end="2026-11-07", days=7, today="2026-11-30",
                                    sleep=sleep, rhr=rhr, battery=[("2026-11-02", 80)])
    passport = tp.build_passport(passport_request("2026-11-01", "2026-11-07"),
                                 {"current": current, "observed_steps": observed})
    providers = passport["sleep"]["providers"]
    assert providers["garmin"]["nights"][0]["value"] == 25200
    assert providers["google"]["nights"][0]["value"] == 23400
    assert providers["garmin"]["nights"][1] | {"record_id": None} == {
        **providers["garmin"]["nights"][1], "state": "conflict", "value": None,
        "reason": "role_uncertain", "record_id": None}
    assert passport["sleep"]["source_pooling"] == "not_performed"
    values = {name: item["values"] for name, item in passport["recovery"]["rhr"].items()}
    assert values["garmin"][0]["value"] == 55 and values["google"][0]["value"] == 58
    row = web.passport_rows(passport)[1]
    assert [item["value"] for item in row["recovery"]] == [55, 58, 80]
    assert row["sleep"]["garmin"]["value"] == 25200 and row["sleep"]["google"]["value"] == 23400


def test_comparison_only_when_compatible():
    previous_completed = [_completed_cell("2026-10-28", "value", 6000)]
    current_completed = [_completed_cell("2026-11-02", "value", 9000)]
    current, observed = make_packet(end="2026-11-07", days=7, today="2026-11-30",
                                    completed=current_completed)
    previous, _ = make_packet(end="2026-10-31", days=7, today="2026-11-30",
                              completed=previous_completed, envelope="hash-previous")
    request = passport_request("2026-11-01", "2026-11-07", compare_previous=True)
    assert (request.previous_start, request.previous_end) == (date(2026, 10, 25),
                                                              date(2026, 10, 31))
    packets = {"current": current, "observed_steps": observed, "previous": previous}
    comparison = tp.build_passport(request, packets)["comparison"]
    assert comparison["steps"]["state"] == "compared"
    assert comparison["steps"]["current"]["mean_exact"] == "9000"
    assert comparison["steps"]["previous"]["mean_exact"] == "6000"
    other, _ = make_packet(end="2026-10-31", days=7, today="2026-11-30",
                           completed=previous_completed, steps_source="other-source")
    packets["previous"] = other
    assert tp.build_passport(request, packets)["comparison"]["steps"] == {
        "state": "incompatible", "reason": "different_steps_source"}
    assert tp.build_passport(passport_request("2026-11-01", "2026-11-07"), packets)[
        "comparison"] == {"state": "not_requested"}


# ---------------------------------------------------------------------------
# Sampling limits: no stitching, no partial passport
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("days", "window"), [(1, 7), (7, 7), (8, 30), (21, 30), (30, 30)])
def test_export_window_is_an_existing_cap(days, window):
    end = date(2026, 12, 7)
    request = passport_request((end - timedelta(days=days - 1)).isoformat(), end.isoformat(),
                               compare_previous=True)
    exports = tp.export_requests(request)
    assert set(exports) == {"current", "observed_steps", "previous"}
    for role, export in exports.items():
        assert export.days == window
        export.validate()
    assert exports["current"].end_date == end
    assert exports["previous"].end_date == request.start_date - timedelta(days=1)
    assert exports["current"].context_limit == MAX_ROWS
    assert exports["current"].steps_view == "completed"
    assert exports["observed_steps"].steps_view == "observed"
    assert not exports["observed_steps"].include_context


@pytest.mark.parametrize(("start", "end", "code"), [
    ("2026-11-01", "2026-12-01", "period_exceeds_export_cap"),
    ("2026-11-02", "2026-11-01", "start_after_end"),
])
def test_requests_over_the_cap_are_refused(start, end, code):
    with pytest.raises(PassportError) as caught:
        passport_request(start, end).validate()
    assert caught.value.code == code


def test_reader_refusal_is_not_hidden_and_context_cap_is_visible(monkeypatch, tmp_path):
    def refuse(**_kwargs):
        raise EvidenceError("steps_search_incomplete")

    with pytest.raises(EvidenceError, match="steps_search_incomplete"):
        tp.read_passport_exports(
            profile=tmp_path, profile_kind="synthetic",
            request=passport_request("2026-11-01", "2026-11-07"),
            evaluated_at_utc=datetime(2026, 11, 8, tzinfo=UTC),
            evaluation_local_date=date(2026, 11, 8), reader=refuse)
    current, observed = make_packet(end="2026-11-07", days=7, today="2026-11-30",
                                    notes=[_note("a", "2026-11-02")], truncated=True)
    passport = tp.build_passport(passport_request("2026-11-01", "2026-11-07"),
                                 {"current": current, "observed_steps": observed})
    assert passport["context"]["state"] == "truncated"
    assert "Показаны не все комментарии" in tp.render_passport_markdown(passport)
    monkeypatch.setattr(tp, "MAX_BUNDLE_BYTES", 100)
    with pytest.raises(EvidenceError, match="output_exceeds_byte_limit"):
        tp.encode_passport_bundle(passport, {"current": current, "observed_steps": observed})
    assert "#380" in web._message("period_exceeds_export_cap")
    assert "предела выборки" in web._message("hrv_selected_points_exceed_max")


def test_build_is_deterministic_and_facts_match_packets():
    completed = [_completed_cell("2026-11-02", "value", 1234)]
    sleep = {"garmin": (SOURCE, {"2026-11-02": ("value", 25200, False)})}
    current, observed = make_packet(end="2026-11-07", days=7, today="2026-11-30",
                                    completed=completed, sleep=sleep,
                                    notes=[_note("n", "2026-11-03")],
                                    sessions=[_session("2026-11-04", "cycling",
                                                       "2026-11-04T07:00:00+00:00")])
    packets = {"current": current, "observed_steps": observed}
    request = passport_request("2026-11-01", "2026-11-07")
    first, second = tp.build_passport(request, packets), tp.build_passport(request, packets)
    assert first == second
    assert first["source_exports"]["current"]["envelope_hash"] == "hash-current"
    assert first["source_exports"]["observed_steps"]["steps_view"] == "observed"
    bundle = json.loads(tp.encode_passport_bundle(first, packets))
    assert bundle["passport"] == first
    assert tp.build_passport(request, bundle["source_exports"]) == first


# ---------------------------------------------------------------------------
# Real reader, synthetic database, web adapter
# ---------------------------------------------------------------------------


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return CLOCK if tz is None else CLOCK.astimezone(tz)


@pytest.fixture
def client(profile, monkeypatch):
    monkeypatch.setattr(web, "datetime", FrozenDatetime)
    app, _ = create_ui_app(Settings(data_dir=profile[0].root, ui_port=8120))
    with TestClient(app, base_url="http://127.0.0.1:8120",
                    headers={"Origin": "http://127.0.0.1:8120"}) as result:
        yield result


def _query(profile, **changes):
    start = DAY - timedelta(days=3)
    return {"start_date": start.isoformat(), "end_date": DAY.isoformat(),
            "title": "Синтетическая поездка", "place": "Тест",
            "garmin_source_id": profile[2].activity_garmin_source_id, **changes}


def test_page_and_downloads_carry_the_same_facts_as_the_source_exports(client, profile):
    page = client.get("/passport", params=_query(profile, compare="1"))
    assert page.status_code == 200, page.text
    assert page.headers["cache-control"] == "no-store"
    assert "Синтетическая поездка" in page.text and "По дням" in page.text
    assert "Технические детали" in page.text
    frozen = _page_downloads(page.text)
    shown = json.loads(frozen["json"])
    assert shown["passport"]["passport_hash"] in page.text
    assert shown["passport"]["comparison"]["state"] == "compared"
    assert tp.render_passport_markdown(shown["passport"]) == frozen["md"]
    assert "/passport/export.json?" not in page.text  # page links never re-read storage

    response = client.get("/passport/export.json", params=_query(profile, compare="1"))
    assert response.status_code == 200, response.text
    assert "attachment" in response.headers["content-disposition"]
    bundle = json.loads(response.text)
    passport, packets = bundle["passport"], bundle["source_exports"]
    assert set(packets) == {"current", "observed_steps", "previous"}
    for role, packet in packets.items():
        assert passport["source_exports"][role]["envelope_hash"] == packet["envelope_hash"]
        assert packet["request"]["days"] == 7
    request = PassportRequest(
        start_date=DAY - timedelta(days=3), end_date=DAY, title="Синтетическая поездка",
        place="Тест", garmin_source_id=profile[2].activity_garmin_source_id,
        compare_previous=True)
    # Reproducible: the passport is exactly what the builder makes of the exports.
    assert tp.build_passport(request, packets) == passport
    current = packets["current"]
    cells = {cell["calendar_date"]: cell for cell in current["sections"]["steps"]["cells"]}
    for row in passport["steps"]["days"]:
        if row["state"] in {"completed", "zero"}:
            assert cells[row["date"]]["value"] == row["value"]
    session_ids = {s["record_id"] for s in
                   current["sections"]["activity"]["temporal_evidence"]["sessions"]}
    assert {w["record_id"] for w in passport["workouts"]["sessions"]} <= session_ids
    context_ids = {row["revision_id"] for row in current["sections"]["context"]["rows"]}
    assert {row["revision_id"] for row in passport["context"]["rows"]} <= context_ids
    assert passport["context"]["rows"], "the fixture Context note lies in the period"

    markdown = client.get("/passport/export.md", params=_query(profile))
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert "# Синтетическая поездка" in markdown.text


def test_context_event_sets_the_period_and_default_title(client, profile):
    with session_scope(profile[1]) as session:
        start, end = DAY - timedelta(days=2), DAY
        view = ContextService(session).add(
            text="Командировка в Новосибирск\nподробности", capture_source="cli",
            temporal=parse_interval(start.isoformat(), end.isoformat()))
    response = client.get("/passport", params={
        "event_id": view.event_id,
        "garmin_source_id": profile[2].activity_garmin_source_id})
    assert response.status_code == 200, response.text
    assert "Командировка в Новосибирск" in response.text
    assert f'value="{start.isoformat()}"' in response.text
    missing = client.get("/passport", params={"event_id": "0" * 36})
    assert missing.status_code == 422
    assert "Комментарий не найден" in missing.text


def test_over_cap_period_is_refused_clearly_without_reading(client, profile, monkeypatch):
    def forbidden(**_kwargs):
        raise AssertionError("no export read for a refused period")

    monkeypatch.setattr(tp, "read_combined_evidence", forbidden)
    params = _query(profile, start_date=(DAY - timedelta(days=30)).isoformat())
    page = client.get("/passport", params=params)
    assert page.status_code == 422
    assert "не больше 30" in page.text and "#380" in page.text
    download = client.get("/passport/export.json", params=params)
    assert download.status_code == 422
    assert download.json()["code"] == "period_exceeds_export_cap"


def _page_downloads(html):
    class Payload(HTMLParser):
        active = False
        value = ""

        def handle_starttag(self, tag, attrs):
            self.active = tag == "script" and dict(attrs).get("id") == "passport-downloads"

        def handle_endtag(self, tag):
            if tag == "script":
                self.active = False

        def handle_data(self, data):
            if self.active:
                self.value += data

    parser = Payload()
    parser.feed(html)
    return json.loads(parser.value)


def test_activity_cap_is_unknown_count_not_zero_and_preserves_reader_reason(client, monkeypatch):
    current, observed = make_packet(end="2026-11-07", days=7, today="2026-11-30")
    current["sections"]["activity"]["temporal_evidence"].update(
        state="incomplete", reason="projected_current_sessions_limit_exceeded",
        sessions=None, retired_exclusions=None)
    packets = {"current": current, "observed_steps": observed}
    request = passport_request("2026-11-01", "2026-11-07")
    passport = tp.build_passport(request, packets)
    assert passport["workouts"]["session_count"] is None
    assert passport["workouts"]["sessions"] == []
    markdown = tp.render_passport_markdown(passport)
    assert "Список неполон" in markdown
    assert "Сохранённых тренировок в периоде нет" not in markdown
    monkeypatch.setattr(web, "_read", lambda *_: (packets, passport))
    page = client.get("/passport", params={
        "start_date": "2026-11-01", "end_date": "2026-11-07", "title": "Cap"})
    assert page.status_code == 200
    assert "projected_current_sessions_limit_exceeded" in page.text
    assert 'passport-figure">—</p>' in page.text


def test_unknown_zone_days_break_segments():
    current, observed = make_packet(
        end="2026-11-07", days=7, today="2026-11-30", notes=[
            _note("one", "2026-11-01", zone="Europe/Moscow", offset=180),
            _note("two", "2026-11-03", zone="Europe/Moscow", offset=180)])
    passport = tp.build_passport(passport_request("2026-11-01", "2026-11-07"),
                                 {"current": current, "observed_steps": observed})
    assert [(s["first"], s["last"]) for s in web.passport_zone_segments(passport)] == [
        ("2026-11-01", "2026-11-01"), ("2026-11-03", "2026-11-03")]


def test_comparison_rejects_changed_steps_policy_and_excludes_partial_sleep():
    current, observed = make_packet(
        end="2026-11-07", days=7, today="2026-11-30",
        completed=[_completed_cell("2026-11-01", "value", 1000)],
        sleep={"garmin": (SOURCE, {"2026-11-01": ("value", 25200, False)})})
    previous, _ = make_packet(
        end="2026-10-31", days=7, today="2026-11-30",
        completed=[_completed_cell("2026-10-31", "value", 2000)],
        sleep={"garmin": (SOURCE, {"2026-10-31": ("value", 100, False)})})
    previous["sections"]["steps"]["display_zone"] = "Pacific/Honolulu"
    previous["sections"]["sleep"]["providers"]["garmin"]["source_range"]["series"][0][
        "points"][0]["partial"] = True
    passport = tp.build_passport(
        passport_request("2026-11-01", "2026-11-07", compare_previous=True),
        {"current": current, "observed_steps": observed, "previous": previous})
    assert passport["comparison"]["steps"] == {
        "state": "incompatible", "reason": "different_steps_contract"}
    assert passport["comparison"]["sleep"]["garmin"]["state"] == "incompatible"


def test_frozen_download_is_literal_and_survives_later_context_edit(client, profile):
    malicious = '</script><script>alert(1)</script> ![image](https://invalid.test/image)'
    with session_scope(profile[1]) as session:
        view = ContextService(session).add(
            text=malicious, capture_source="cli",
            temporal=parse_interval((DAY - timedelta(days=1)).isoformat(), DAY.isoformat()))
    page = client.get("/passport", params=_query(profile))
    assert page.status_code == 200
    assert malicious not in page.text
    frozen = _page_downloads(page.text)
    bundle = json.loads(frozen["json"])
    assert any(row["original_text"] == malicious for row in bundle["passport"]["context"]["rows"])
    assert "![image](" not in frozen["md"]
    with session_scope(profile[1]) as session:
        ContextService(session).revise(view.event_id, text="changed after page render")
    later = client.get("/passport/export.json", params=_query(profile)).json()
    assert later["passport"]["passport_hash"] != bundle["passport"]["passport_hash"]
    assert json.loads(frozen["json"]) == bundle


def test_both_serializers_must_pass_before_page_or_download(client, profile, monkeypatch):
    monkeypatch.setattr(tp, "MAX_BUNDLE_BYTES", 100)
    page = client.get("/passport", params=_query(profile))
    assert page.status_code == 422
    assert 'id="passport-downloads"' not in page.text
    assert client.get("/passport/export.md", params=_query(profile)).status_code == 422


@pytest.mark.parametrize("item", [
    {"start_local": "2026-11-01T01:30:12.123400", "start_precision": "local"},
    {"start_utc": "2026-11-01T05:30:12.123400+00:00", "start_precision": "instant"},
])
def test_workout_display_retains_saved_seconds_and_fraction(item):
    assert "01:30:12.123400" in web.passport_workout_time(item) or (
        "05:30:12.123400" in web.passport_workout_time(item))


def test_real_sleep_values_and_wake_dates_match_export(profile):
    request = PassportRequest(
        DAY - timedelta(days=3), DAY, "Sleep", profile[2].sleep_garmin_source_id)
    packets = tp.read_passport_exports(
        profile=profile[0].root, profile_kind="synthetic", request=request,
        evaluated_at_utc=CLOCK, evaluation_local_date=CLOCK.date())
    passport = tp.build_passport(request, packets)
    for name, provider in passport["sleep"]["providers"].items():
        points = [point for series in packets["current"]["sections"]["sleep"]["providers"][
            name]["source_range"]["series"] for point in series["points"]]
        assert any(point["state"] == "value" for point in points)
        for night in provider["nights"]:
            point = next(p for p in points if p["wake_date"] == night["wake_date"])
            assert night["unit"] == point["unit"]
            if night["state"] == "value":
                assert night["value"] == point["value"]


def test_real_context_travel_dst_fold_midnight_and_return(profile):
    # Three weeks, Moscow -> New York -> Moscow. Both 01:30 occurrences on
    # the DST fold keep their original offsets/precision, not the host timezone.
    timestamps = [
        ("2026-10-25T23:59:30.1200+03:00", "Europe/Moscow"),
        ("2026-11-01T01:30:15-04:00", "America/New_York"),
        ("2026-11-01T01:30:15-05:00", "America/New_York"),
        ("2026-11-14T00:01+03:00", "Europe/Moscow"),
    ]
    with session_scope(profile[1]) as session:
        for timestamp, zone in timestamps:
            ContextService(session).add(text="synthetic travel", capture_source="cli",
                                       temporal=parse_timestamp(timestamp, timezone_name=zone))
    request = PassportRequest(date(2026, 10, 25), date(2026, 11, 14), "Travel",
                              profile[2].activity_garmin_source_id)
    packets = tp.read_passport_exports(
        profile=profile[0].root, profile_kind="synthetic", request=request,
        evaluated_at_utc=datetime(2026, 11, 20, tzinfo=UTC),
        evaluation_local_date=date(2026, 11, 20))
    passport = tp.build_passport(request, packets)
    rows = passport["context"]["rows"]
    assert {r["temporal"]["start_source_timestamp"] for r in rows} == {
        timestamp for timestamp, _ in timestamps}
    assert {r["temporal"]["start_precision"] for r in rows} >= {"second", "microsecond"}
    zone_days = {d["date"]: d for d in passport["zones"]["days"]}
    assert {z["utc_offset_minutes"] for z in zone_days["2026-11-01"]["zones"]} == {-240, -300}
    assert zone_days["2026-11-14"]["zones"][0]["timezone"] == "Europe/Moscow"
    assert zone_days["2026-11-02"]["state"] == "unknown"
    assert len(passport["steps"]["days"]) == 21
    assert passport["steps"]["total"] is None  # no invented activity on this trip


@pytest.mark.parametrize("revision", ["n-r1", "stale-revision", None])
def test_selected_context_revision_must_exist_in_the_export(revision):
    current, observed = make_packet(end="2026-11-07", days=7, today="2026-11-30",
                                    notes=[_note("n", "2026-11-02")])
    request = passport_request("2026-11-01", "2026-11-07", context_event_id="n",
                               context_revision_id=revision)
    packets = {"current": current, "observed_steps": observed}
    if revision == "n-r1":
        assert tp.build_passport(request, packets)["selection"]["context_revision_id"] == revision
    else:
        with pytest.raises(PassportError, match="selected_context_revision_unavailable"):
            tp.build_passport(request, packets)
    current["sections"]["context"].update(rows=[], truncated=True)
    with pytest.raises(PassportError, match="selected_context_revision_unavailable"):
        tp.build_passport(request, packets)


@pytest.mark.parametrize(("seconds", "label"), [(0, "0 мин"), (1, "<1 мин"),
                                             (59, "<1 мин"), (60, "1 мин")])
def test_markdown_duration_matches_page_precision(seconds, label):
    assert tp._md_duration(seconds) == label == web.owner_duration(seconds)
