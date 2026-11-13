"""Synthetic #462 event markers, exact-source pairs and per-night medians."""

import json
import os
import subprocess
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from healthcheck.config import Settings
from healthcheck.context import ContextService, parse_date_only, parse_interval, parse_timestamp
from healthcheck.db.engine import create_sqlite_engine, session_scope
from healthcheck.db.models import Base
from healthcheck.saved_sleep_analysis import _nights, compare_context_night, pair_context_nights
from healthcheck.web.pages import templates
from healthcheck.web.sleep_context import read_sleep_context
from healthcheck.web.sleep_timeline import build_sleep_timeline, sleep_timeline_client
from healthcheck.web.ui_app import create_ui_app
from test_garmin_query_dashboard import _ui
from test_saved_sleep_analysis import sections
from test_sleep_owner_ui import client_for
from test_sleep_schedule_ui import _render
from test_sleep_timeline_ui import _regularity_packet, _seed_regularity_nights, _timeline_json

END = date(2026, 10, 31)
ROOT = Path(__file__).resolve().parents[1]


def _event(value="2026-10-30T21:00:00Z", *, number=1, end=None, text="Synthetic context"):
    temporal = (parse_interval(value, end) if end else parse_timestamp(value) if "T" in value
                else parse_date_only(value))
    return jsonable_encoder({"event_id": f"event-{number}", "revision_id": f"revision-{number}",
        "revision_number": 2, "capture_source": "manual", "temporal": asdict(temporal),
        "tags": [], "original_text": text})


def _ranges(days=7):
    ranges, history = {}, {}
    for provider in ("garmin", "google"):
        for target, length, end in ((ranges, days, END), (history, 30, date(2026, 10, 31-days))):
            raw = _regularity_packet(provider, count=30, days=length, end=end)
            by_date = {d["wake_date"]: d["sources"][0]["sessions"][0]
                       for d in raw["days"] if d["sources"]}
            for point in raw["series"][0]["points"]:
                night = by_date[point["wake_date"]]
                point["record_id"] = night["record_id"]
                night["metrics"]["sleep_duration_asleep_seconds"]["value"] = 8 * 3600
            target[provider] = raw
    return ranges, history


def _timeline(*events, days=7, has_more=False, ranges=None, history=None):
    if ranges is None:
        ranges, history = _ranges(days)
    return build_sleep_timeline(ranges, days=days, end_date=END, travel_ranges=history,
        context={"rows": list(events), "has_more": has_more})


def test_instant_interval_end_date_only_midnight_and_multiple_events():
    instant = _event()
    interval = _event("2026-10-29T23:40:00Z", end="2026-10-30T22:00:00Z", number=2)
    date_only = _event("2026-10-29", number=3)
    timeline = _timeline(instant, interval, date_only)
    result = timeline["context_events"]
    assert len(result["rows"]) == 3
    for series in ("garmin:sleep", "google:sleep"):
        [marker] = result["markers"][series]
        assert marker["wake_date"] == "2026-10-31"
        assert "2 события" in marker["text"]
        assert "первая ночь после окончания события" in marker["text"]
    for row in result["rows"][:2]:
        assert all(c["night"] == "2026-10-31" for c in row["sources"])
    assert all(c["night"] is None and c["reason"] == "нет времени"
               for c in result["rows"][2]["sources"])
    assert result["rows"][2]["time_missing"] is True


def test_prior_window_median_excludes_all_event_nights_and_sources():
    ranges, history = _ranges()
    # An earlier event lies outside the visible seven days but must exclude
    # its paired reference night. Two events on it still exclude just one night.
    events = [_event(), _event("2026-10-04T22:00:00Z", number=2),
              _event("2026-10-04T22:30:00Z", number=3)]
    for raw in (ranges["google"], history["google"]):
        for day in raw["days"]:
            for source in day["sources"]:
                for night in source["sessions"]:
                    night["metrics"]["sleep_duration_asleep_seconds"]["value"] = 7 * 3600
    target = ranges["google"]["days"][-1]["sources"][0]["sessions"][0]
    target["metrics"]["sleep_duration_asleep_seconds"]["value"] = 7 * 3600 + 35 * 60
    for endpoint, shift in (("start", 40), ("end", 15)):
        cell = target["metrics"][f"sleep_{endpoint}_at"]
        stamp = (datetime.fromisoformat(cell["value"]) + timedelta(minutes=shift)).isoformat()
        cell["value"] = stamp
        cell["evidence"]["interval_snapshots"][0][f"{endpoint}_at_utc"] = stamp
    result = _timeline(*events, ranges=ranges, history=history)["context_events"]
    assert len(result["rows"]) == 1  # historical events are exclusion context only
    google = next(c for c in result["rows"][0]["sources"] if c["label"] == "Google")
    garmin = next(c for c in result["rows"][0]["sources"] if c["label"] == "Garmin")
    assert "+35 мин" in google["comparison"] and "+0 мин" in garmin["comparison"]
    assert "засыпание на 40 мин позже" in google["comparison"]
    comparisons = [t for t in result["technical"] if "comparison" in t]
    assert all(t["comparison"]["reference_n"] == 27 for t in comparisons)
    assert all("night-3" not in t["comparison"]["reference_record_ids"] for t in comparisons)


@pytest.mark.parametrize("problem", ["sparse", "missing", "method", "overflow", "history"])
def test_missing_incompatible_capped_and_sparse_never_become_zero(problem):
    ranges, history = _ranges()
    if problem == "sparse":
        for packet in list(ranges.values()) + list(history.values()):
            for day in packet["days"]:
                if day["wake_date"] < "2026-10-27":
                    day["sources"] = []
    elif problem in {"missing", "method"}:
        for packet in ranges.values():
            cell = packet["days"][-1]["sources"][0]["sessions"][0]["metrics"][
                "sleep_duration_asleep_seconds"]
            cell["value"] = None if problem == "missing" else 8 * 3600
            if problem == "method":
                cell["comparison_basis"] = "other_method"
    elif problem == "history":
        history = None
    result = _timeline(_event(), ranges=ranges, history=history,
                       has_more=problem == "overflow")["context_events"]
    for cell in result["rows"][0]["sources"]:
        assert "+0 мин" not in cell["comparison"] or problem in {"missing", "method"}
        assert ("мало ночей" in cell["comparison"] or "недоступн" in cell["comparison"])
        if problem == "missing":
            assert cell["duration"] == "Недоступно"


def test_accepted_pairing_window_boundaries_and_clock_median_wrap():
    nights, _ = _nights(sections(count=10)["sleep"])
    target = nights[-1]
    previous = nights[:-1]
    for i, night in enumerate(previous):
        night["start"]["clock_minutes"] = 1430 if i % 2 else 10
    target["start"]["clock_minutes"] = 30
    value = compare_context_night(target, nights, [])
    assert value["reference_n"] == 9
    assert value["start_delta_minutes"] == 20
    first = _event("2026-10-01T23:00:00Z")
    pairs, _ = pair_context_nights(nights, {"rows": [first]})
    assert pairs[0]["record_id"] == "night-0"
    # The production helper is exactly the legacy export's inclusive 24h rule.
    edge = _event("2026-09-30T23:00:00Z")
    assert pair_context_nights(nights, {"rows": [edge]})[0][0]["record_id"] == "night-0"
    outside = _event("2026-09-30T22:59:59Z")
    assert pair_context_nights(nights, {"rows": [outside]})[0] == []


@pytest.mark.parametrize("problem", ["travel", "within_night", "nap", "ambiguous"])
def test_travel_naps_and_ambiguity_have_reasons_and_no_marker(problem):
    ranges, history = _ranges()
    for packet in ranges.values():
        night = packet["days"][-1]["sources"][0]["sessions"][0]
        if problem in {"travel", "within_night"}:
            for endpoint in (["start", "end"] if problem == "travel" else ["end"]):
                temporal = night["metrics"][f"sleep_{endpoint}_at"]["evidence"][
                    "interval_snapshots"][0][f"{endpoint}_temporal"]
                temporal.update(source_timezone=None, source_utc_offset_minutes=60)
        elif problem == "nap":
            night["reason"] = "google_nap_only"
        else:
            other = deepcopy(night)
            other["record_id"] = "second-night"
            packet["days"][-1]["sources"][0]["sessions"].append(other)
    result = _timeline(_event(), ranges=ranges, history=history)["context_events"]
    assert all(not markers for markers in result["markers"].values())
    for cell in result["rows"][0]["sources"]:
        assert cell["night"] is None
        assert ("смена" in cell["reason"] if "night" in problem or problem == "travel" else
                "неоднознач" in cell["reason"])


def test_unpaired_no_data_outside_window_and_unavailable_source():
    for event, expected in ((_event("2026-10-31T22:00:00Z"), "нет данных"),):
        result = _timeline(event)["context_events"]
        assert all(expected in c["reason"] for c in result["rows"][0]["sources"])
    ranges, history = _ranges()
    for packet in ranges.values():
        packet["state"] = "read_limit_exceeded"
    result = _timeline(_event(), ranges=ranges, history=history)["context_events"]
    assert result["markers"] == {}
    ranges, history = _ranges()
    for packet in ranges.values():
        for day in packet["days"]:
            if day["wake_date"] in {"2026-10-26", "2026-10-27"}:
                day["sources"] = []
    result = _timeline(_event("2026-10-25T21:00:00Z"), ranges=ranges,
                       history=history)["context_events"]
    assert all(c["reason"] == "вне окна 24 часов" for c in result["rows"][0]["sources"])


def test_explicit_google_identity_selects_its_own_pairs_and_medians():
    ranges, history = _ranges()
    for packet in (ranges["google"], history["google"]):
        alternate = deepcopy(packet["series"][0])
        alternate["source"]["source_id"] = "alternate"
        for point in alternate["points"]:
            point["record_id"] += "-alternate"
        packet["series"].append(alternate)
        for day in packet["days"]:
            for source in list(day["sources"]):
                other = deepcopy(source)
                other["source"]["source_id"] = "alternate"
                for night in other["sessions"]:
                    night["record_id"] += "-alternate"
                    night["metrics"]["sleep_duration_asleep_seconds"]["value"] = 6 * 3600
                day["sources"].append(other)
    context = {"rows": [_event()], "has_more": False}
    unresolved = build_sleep_timeline(ranges, days=7, end_date=END,
                                     travel_ranges=history, context=context)
    assert set(unresolved["context_events"]["markers"]) == {"garmin:sleep"}
    selected = build_sleep_timeline(ranges, days=7, end_date=END, travel_ranges=history,
                                   context=context, google_source_id="alternate")
    result = selected["context_events"]
    assert set(result["markers"]) == {"garmin:sleep", "google:alternate"}
    assert result["markers"]["google:alternate"][0]["record_id"].endswith("-alternate")
    assert result["rows"][0]["sources"][1]["duration"] == "6 ч 00 мин"
    comparisons = [t["comparison"] for t in result["technical"] if "comparison" in t]
    assert all(c["duration_delta_minutes"] == 0 for c in comparisons)


def test_night_after_zone_change_also_excluded():
    ranges, history = _ranges()
    for packet in ranges.values():
        for day in packet["days"]:
            if day["wake_date"] < "2026-10-28":
                continue
            night = day["sources"][0]["sessions"][0]
            for endpoint in ("start", "end"):
                night["metrics"][f"sleep_{endpoint}_at"]["evidence"]["interval_snapshots"][0][
                    f"{endpoint}_temporal"].update(
                        source_timezone=None, source_utc_offset_minutes=60)
    result = _timeline(_event("2026-10-28T21:00:00Z"), ranges=ranges,
                       history=history)["context_events"]
    assert all(not markers for markers in result["markers"].values())
    assert all("смена" in c["reason"] for c in result["rows"][0]["sources"])


def test_html_escaping_short_text_disclosure_and_compact_client():
    text = '<img src=x onerror="alert(1)">' + "я" * 70
    timeline = _timeline(_event(text=text))
    context = timeline["context_events"]
    assert len(context["rows"][0]["text"]) == 60
    assert context["rows"][0]["text"].endswith("…")
    html = templates.env.get_template("sleep_context.html").render(timeline=timeline)
    assert "&lt;img" in html and "<img" not in html
    assert "описание, не причина и не диагноз" in html
    assert "Отсутствие заметки не означает отсутствие события" in html
    assert '<details class="owner-details"><summary>Как считается</summary>' in html
    packet = sleep_timeline_client(timeline)
    assert set(packet["context_events"]) == {"markers", "state"}
    assert "original_text" not in json.dumps(packet)
    assert "event-1" not in html and "revision-1" not in html


def test_schedule_markers_hover_text_escaping_and_source_toggles(tmp_path):
    timeline = _timeline(_event(text='<script>"untrusted"</script>'))
    packet = sleep_timeline_client(timeline)
    full, google, hidden = _render(tmp_path, {"data": packet},
        {"data": packet, "hidden": {"garmin:sleep": True}},
        {"data": packet, "hidden": {"garmin:sleep": True, "google:sleep": True}})
    assert full["html"].count('sleep-context-marker sleep-schedule-event') == 2
    assert google["html"].count('sleep-context-marker sleep-schedule-event') == 1
    assert 'sleep-context-marker sleep-schedule-event' not in hidden["html"]
    assert '&lt;script&gt;&quot;untrusted&quot;&lt;/script&gt;' in full["html"]
    assert '<script>"untrusted"</script>' not in full["html"]
    assert 'aria-label="1 событие' in full["html"]
    assert 'первая ночь после окончания события' in full["html"]
    assert '>⚑</span>' in full["html"]
    assert '⚑ событие перед сном' in full["html"]
    assert 'tabindex="0" role="img"' in full["html"]
    from overview_html import parse_overview

    schedule = parse_overview(full["html"])
    for marker in schedule.find("span", classes=("sleep-schedule-event",)):
        source = marker.attrs["data-schedule-bar"]
        # The flag belongs at the start of its exact source's saved interval.
        bar = next(bar for bar in schedule.find("span", classes=("sleep-schedule-bar",))
                   if bar.attrs["data-schedule-bar"] == source)
        marker_left = marker.attrs["style"].split("left:")[1].split(";")[0]
        bar_left = bar.attrs["style"].split("left:")[1].split(";")[0]
        assert marker_left == bar_left


def test_event_columns_keep_whole_comparison_and_one_date_only_state():
    from overview_html import parse_overview

    timeline = _timeline(_event(), _event("2026-10-30", number=2))
    html = templates.env.get_template("sleep_context.html").render(timeline=timeline)
    table = parse_overview(html).one("table")
    assert [cell.text for cell in table.one("thead").find("th")] == [
        "Событие", "Следующая ночь", "Длительность", "Начало сна", "К обычному",
    ]
    for row in timeline["context_events"]["rows"][:1]:
        for cell in row["sources"]:
            assert cell["comparison"].replace("-", "−") in html
            assert cell["duration"] in html
    assert html.count("только дата, с ночью не связывается") == 1
    assert "нет времени" not in table.text
    assert "<style>" not in html


def test_timeline_markers_focus_and_hover_use_production_renderer(tmp_path):
    path = tmp_path / "context-timeline.json"
    path.write_text(json.dumps(sleep_timeline_client(_timeline(_event(text='<b>"note"</b>')))),
                    encoding="utf-8")
    result = subprocess.run(["node", str(ROOT / "scripts/render_sleep_context.cjs"), str(path)],
                            check=True, capture_output=True, text=True, encoding="utf-8")
    data = json.loads(result.stdout)
    assert data["dots"] == 2
    assert all("1 событие" in text and '<b>"note"</b>' in text for text in data["labels"])
    assert '&lt;b&gt;&quot;note&quot;&lt;/b&gt;' in data["focus_html"]
    assert '&lt;b&gt;&quot;note&quot;&lt;/b&gt;' in data["hover_html"]
    assert "<b>" not in data["focus_html"]
    assert data["hidden_cells"] == [True, False]


def test_production_current_revision_snapshot_and_period(tmp_path):
    app, _, paths = _ui(tmp_path)
    _seed_regularity_nights(paths)
    engine = create_sqlite_engine(paths)
    with session_scope(engine) as session:
        service = ContextService(session)
        original = service.add(text="Synthetic old note", capture_source="manual",
            temporal=parse_timestamp("2099-01-04T21:00:00Z"), operation_id="context-old")
        corrected = service.revise(original.event_id, text='Corrected <script>"event"</script>',
            capture_source="manual", temporal=parse_timestamp("2099-01-05T21:00:00Z"),
            operation_id="context-corrected")
        service.add(text="Synthetic date only", capture_source="manual",
                    temporal=parse_date_only("2099-01-06"), operation_id="context-date")
    with session_scope(engine) as session:
        current = read_sleep_context(session, start=date(2099, 1, 1), end=date(2099, 1, 7))
        assert len(current["rows"]) == 2
        row = next(r for r in current["rows"] if r["event_id"] == original.event_id)
        assert row["revision_id"] == corrected.revision_id
    engine.dispose()
    with client_for(app) as client:
        response = client.get("/sleep?wake_date=2099-01-07&days=7")
    assert response.status_code == 200
    html = response.text
    assert "Synthetic old note" not in html
    assert "Corrected &lt;script&gt;&#34;event&#34;&lt;/script&gt;" in html
    assert html.index('id="sleep-schedule-title"') < html.index('id="sleep-context-title"')
    assert html.count("только дата, с ночью не связывается") == 1
    packet = _timeline_json(html)
    assert packet["context_events"]["state"] == "available"
    assert corrected.revision_id in html  # technical disclosure only


def test_current_context_reader_order_corrections_overlap_and_overflow_in_memory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with session_scope(engine) as session:
            service = ContextService(session)
            original = service.add(text="Old synthetic revision", capture_source="manual",
                temporal=parse_timestamp("2026-10-30T20:00:00Z"), operation_id="old")
            corrected = service.revise(original.event_id, text="Corrected synthetic revision",
                capture_source="manual", temporal=parse_timestamp("2026-10-28T20:00:00Z"),
                operation_id="corrected")
            service.add(text="Date only", capture_source="manual",
                        temporal=parse_date_only("2026-10-31"), operation_id="date")
            service.add(text="Overlapping interval", capture_source="manual",
                temporal=parse_interval("2026-10-20T18:00:00Z", "2026-10-26T20:00:00Z"),
                operation_id="interval")
            read = read_sleep_context(session, start=date(2026, 10, 25), end=END)
            assert [r["original_text"] for r in read["rows"]] == [
                "Date only", "Corrected synthetic revision", "Overlapping interval"]
            assert read["rows"][1]["revision_id"] == corrected.revision_id
            assert read["has_more"] is False
            timeline = _timeline(*read["rows"])
            assert len(timeline["context_events"]["rows"]) == 3
            assert "2026-10-20" in timeline["context_events"]["rows"][-1]["time"]
            for i in range(200):
                service.add(text=f"Synthetic capped note {i}", capture_source="manual",
                    temporal=parse_timestamp("2026-10-30T22:00:00Z"), operation_id=f"cap-{i}")
            capped = read_sleep_context(session, start=date(2026, 10, 25), end=END)
            assert capped["has_more"] is True and len(capped["rows"]) == 199
            result = _timeline(*capped["rows"], has_more=True)["context_events"]
            assert all("недоступно" in cell["comparison"] for row in result["rows"]
                       for cell in row["sources"] if cell["night"])
    finally:
        engine.dispose()


def test_http_context_projection_with_injected_memory_snapshot(monkeypatch):
    """Exercise the actual route/templates with in-memory DB and typed range packets.

    The separate persisted-profile HTTP test remains necessary for reader wiring.
    This case deliberately never starts a filesystem runtime/lifespan.
    """
    from healthcheck.web import pages

    ranges, history = _ranges()
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        service = ContextService(session)
        original = service.add(text="Old synthetic text", capture_source="manual",
            temporal=parse_timestamp("2026-10-29T22:00:00Z"), operation_id="http-old")
        corrected = service.revise(original.event_id, text='<script>"current"</script>',
            capture_source="manual", temporal=parse_timestamp("2026-10-30T22:00:00Z"),
            operation_id="http-current")
    settings = Settings(data_dir=Path(os.environ["HEALTHCHECK_DATA_DIR"]))
    app, _ = create_ui_app(settings)
    app.state.engine = engine
    monkeypatch.setattr(pages, "read_source_sleep_range", lambda _session, **kw:
                        deepcopy((ranges if kw["wake_date"] == END else history)[kw["provider"]]))
    try:
        client = client_for(app)
        page = client.get(f"/sleep?wake_date={END}&days=7")
        assert page.status_code == 200
        assert "Old synthetic text" not in page.text
        assert "&lt;script&gt;&#34;current&#34;&lt;/script&gt;" in page.text
        assert "<script>\"current\"</script>" not in page.text
        packet = _timeline_json(page.text)
        assert all(len(markers) == 1 for markers in packet["context_events"]["markers"].values())
        assert corrected.revision_id in page.text  # JSON-serializable technical disclosure
        assert 'id="sleep-context-title"' in page.text
    finally:
        engine.dispose()
