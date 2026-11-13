"""Synthetic #464 UI arithmetic, classification, exclusions and persisted forms."""

import json
import re
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pytest

from healthcheck.saved_sleep_analysis import _nights, circular_local_clock
from healthcheck.sleep_schedule_settings import (
    SleepScheduleSettings,
    read_sleep_schedule_settings,
    update_sleep_schedule_settings,
)
from healthcheck.web.sleep_social_jetlag import build_social_jetlag
from healthcheck.web.sleep_timeline import build_sleep_timeline, sleep_timeline_client
from test_garmin_query_dashboard import _ui
from test_saved_sleep_analysis import item, sections
from test_sleep_owner_ui import client_for
from test_sleep_schedule_ui import END, _render, _timeline
from test_sleep_timeline_ui import _regularity_packet


def _inputs(data):
    nights, (exclusions, _) = _nights(data["sleep"])
    return {"nights": nights, "night_exclusions": exclusions}


def _bounds(night, start, end, zone="UTC"):
    for endpoint, instant in (("start", start), ("end", end)):
        temporal = {"precision": "instant", "source_timezone": zone,
                    "source_utc_offset_minutes": instant.astimezone(
                        ZoneInfo(zone)).utcoffset().total_seconds() / 60}
        stamp = instant.astimezone(UTC).isoformat()
        cell = night["metrics"][f"sleep_{endpoint}_at"]
        cell["value"] = stamp
        row = cell["evidence"]["interval_snapshots"][0]
        row[f"{endpoint}_at_utc"] = stamp
        row[f"{endpoint}_temporal"] = temporal


def test_two_night_midnight_mean_keeps_legacy_minimum():
    value = circular_local_clock([1410, 30], min_nights=2)
    assert min(value["mean_clock_minutes"], 1440 - value["mean_clock_minutes"]) < 1e-9
    assert circular_local_clock([1410, 30])["state"] == "insufficient"


@pytest.mark.parametrize("direction", [1, -1])
def test_signed_midpoint_difference_across_midnight_and_wake_date(direction):
    data = sections()
    settings = SleepScheduleSettings()
    for i in range(7):
        night = item(data, i)
        free = settings.day_type(night["wake_date"]) == "free"
        midpoint = 30 if free == (direction == 1) else 1410
        wake = datetime.fromisoformat(night["wake_date"]).replace(tzinfo=UTC)
        center = wake + timedelta(minutes=midpoint) - (
            timedelta(days=1) if midpoint > 720 else timedelta())
        _bounds(night, center - timedelta(hours=4), center + timedelta(hours=4))
    result = build_social_jetlag(_inputs(data), settings)
    group, = result["groups"]
    assert group["groups"]["work"]["n"] == 5
    assert group["groups"]["free"]["n"] == 2
    assert group["signed_minutes"] == pytest.approx(direction * 60)
    assert f"сдвиг {direction * 60:+d} мин" in group["text"]
    assert "23:30" in group["text"] and "00:30" in group["text"]


def test_default_weekdays_override_unknown_sparse_and_undefined():
    data = _inputs(sections(count=4))
    default = build_social_jetlag(data, SleepScheduleSettings())
    assert default["groups"][0]["state"] == "sufficient"  # Fri/Mon, Sat/Sun.
    override = build_social_jetlag(data, SleepScheduleSettings(overrides={"2026-10-03": "work"}))
    group = override["groups"][0]
    assert group["signed_minutes"] is None and "рабочих 3, свободных 1" in group["text"]
    unknown = build_social_jetlag(data, SleepScheduleSettings(state="unavailable"))
    assert unknown["unknown_nights"] == 4
    assert unknown["groups"][0]["signed_minutes"] is None
    unknown_day = build_social_jetlag(data, SleepScheduleSettings(
        overrides={"2026-10-03": "unknown"}))
    assert unknown_day["unknown_nights"] == 1
    assert unknown_day["groups"][0]["groups"]["free"]["n"] == 1
    undefined = deepcopy(data)
    undefined["nights"][0]["midpoint"]["clock_minutes"] = 0
    undefined["nights"][3]["midpoint"]["clock_minutes"] = 720
    group = build_social_jetlag(undefined, SleepScheduleSettings())["groups"][0]
    assert group["signed_minutes"] is None and "Нет устойчивой" in group["text"]


def test_dst_uses_elapsed_midpoint_and_does_not_mark_travel():
    data = sections(count=4)
    dates = ["2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02"]
    for i, day in enumerate(dates):
        night = item(data, i)
        night["wake_date"] = day
        data["sleep"]["providers"]["google"]["source_range"]["days"][i]["wake_date"] = day
        end = datetime.fromisoformat(day + "T04:00:00").replace(tzinfo=ZoneInfo("America/New_York"))
        start = (end.astimezone(UTC) - timedelta(hours=5)).astimezone(end.tzinfo)
        _bounds(night, start, end, "America/New_York")
    inputs = _inputs(data)
    # Fall-back night: 00:00 EDT -> 04:00 EST, midpoint 01:30 EST, fold 1.
    dst = inputs["nights"][2]["midpoint"]
    assert dst["local"] == "2026-11-01T01:30:00-05:00" and dst["fold"] == 1
    result = build_social_jetlag(inputs, SleepScheduleSettings())
    assert result["travel_nights"] == 0
    assert result["groups"][0]["state"] == "sufficient"


def test_zone_change_and_following_night_excluded_across_partitions():
    data = sections()
    for i in range(2, 7):
        night = item(data, i)
        end = datetime.fromisoformat(night["wake_date"] + "T07:00:00+00:00")
        _bounds(night, end - timedelta(hours=8), end, "Europe/Moscow")
    result = build_social_jetlag(_inputs(data), SleepScheduleSettings())
    assert result["travel_nights"] == 2
    assert {e["reason"]: e["count"] for e in result["exclusions"]} == {
        "timezone_change": 1, "night_after_timezone_change": 1}
    assert sum(g["groups"][k]["n"] for g in result["groups"] for k in ("work", "free")) == 5
    assert result["night_types"]["2026-10-04"] == {
        "day_type": "unknown", "reason": "timezone_change"}


@pytest.mark.parametrize("prior_zones,excluded", [
    (("Europe/Moscow", "UTC"), 1), (("Europe/Moscow", "Europe/Moscow"), 2)])
def test_period_boundary_travel_context_never_enters_denominators(prior_zones, excluded):
    raw = _regularity_packet()
    history = _regularity_packet(count=0, days=30, end=date(2026, 10, 1))
    source = deepcopy(raw["days"][0]["sources"][0])
    for index, (day, zone) in enumerate(zip(history["days"][-2:], prior_zones, strict=True)):
        prior_source = deepcopy(source)
        night = prior_source["sessions"][0]
        night["record_id"] = f"prior-{index}"
        end = datetime.fromisoformat(day["wake_date"] + "T07:00:00+00:00")
        _bounds(night, end - timedelta(hours=8), end, zone)
        day["sources"] = [prior_source]
    timeline = build_sleep_timeline({"google": raw}, days=7, end_date=END,
                                    travel_ranges={"google": history})
    row, = timeline["regularity"]["sources"]
    assert row["eligible_nights"] == 7
    result = row["jetlag"]
    assert result["travel_history"] == "bounded_30_days"
    assert result["travel_nights"] == excluded
    assert sum(g["groups"][k]["n"] for g in result["groups"] for k in ("work", "free")) == (
        7 - excluded)
    assert all(day >= "2026-10-02" for day in result["night_types"])


def test_within_night_zone_change_also_excludes_following():
    data = sections(count=4)
    night = item(data, 1)
    cell = night["metrics"]["sleep_end_at"]
    cell["evidence"]["interval_snapshots"][0]["end_temporal"] = {
        "precision": "instant", "source_timezone": "Europe/Moscow",
        "source_utc_offset_minutes": 180}
    result = build_social_jetlag(_inputs(data), SleepScheduleSettings())
    assert result["travel_nights"] == 2
    assert any(e["reason"] == "night_after_timezone_change" for e in result["exclusions"])


@pytest.mark.parametrize("problem", ["nap", "ambiguous", "missing_time"])
def test_naps_ambiguous_missing_times_are_excluded_and_counted(problem):
    data = sections(count=4)
    night = item(data)
    if problem == "nap":
        night["reason"] = "google_nap_only"
    elif problem == "ambiguous":
        source = data["sleep"]["providers"]["google"]["source_range"]["days"][0]["sources"][0]
        source["sessions"].append({**deepcopy(night), "record_id": "competitor"})
    else:
        night["metrics"]["sleep_start_at"]["eligible"] = False
    inputs = _inputs(data)
    result = build_social_jetlag(inputs, SleepScheduleSettings())
    assert result["other_excluded_nights"] == len(inputs["night_exclusions"]) > 0
    assert result["groups"][0]["signed_minutes"] is None


def test_sources_remain_separate_toggle_and_free_day_ticks(tmp_path):
    ranges = {p: _regularity_packet(p) for p in ("garmin", "google")}
    for day in ranges["google"]["days"]:
        if SleepScheduleSettings().day_type(day["wake_date"]) == "free":
            night = day["sources"][0]["sessions"][0]
            start, end = [datetime.fromisoformat(night["metrics"][f"sleep_{key}_at"]["value"])
                          + timedelta(hours=2) for key in ("start", "end")]
            _bounds(night, start, end)
    data = sleep_timeline_client(build_sleep_timeline(ranges, days=7, end_date=END))
    assert [row["jetlag"]["groups"][0]["signed_minutes"] for row in
            data["regularity"]["sources"]] == pytest.approx([0, 120])
    full, google, garmin = _render(tmp_path, {"data": data},
        {"data": data, "hidden": {"garmin:sleep": True}},
        {"data": data, "hidden": {"google:sleep": True}})
    assert full["html"].count('data-sleep-jetlag=') == 2
    assert 'data-sleep-jetlag="garmin:sleep"' not in google["html"]
    assert 'data-sleep-jetlag="google:sleep"' not in garmin["html"]
    assert full["html"].count('class="sleep-schedule-free"') == 2
    for result in (google, garmin):
        assert result["html"].count('data-sleep-jetlag=') == 1
        assert "(5 и 2 ночи)" in result["html"]
        assert "не диагноз и не объяснение самочувствия" in result["html"]
        assert "Минимум 2" in result["html"]
        assert "1440/(2π)" in result["html"]  # Circular mean is expressed in minutes.
        assert 'sleep-jetlag-method" open' not in result["html"]
    assert "03:00 → 03:00 · сдвиг 0 мин" in garmin["html"]
    assert "03:00 → 05:00 · сдвиг +120 мин" in google["html"]
    for source in data["regularity"]["sources"]:
        for day in ("2026-10-03", "2026-10-04"):
            source["jetlag"]["night_types"][day] = {
                "day_type": "unknown", "reason": "timezone_change"}
    travel, = _render(tmp_path, {"data": data})
    assert 'class="sleep-schedule-free"' not in travel["html"]


def test_empty_http_page_has_insufficient_text_and_no_zero_result(tmp_path):
    app, _, _ = _ui(tmp_path)
    with client_for(app) as client:
        response = client.get("/sleep?days=7&wake_date=2026-10-08")
    schedule = response.text.split('id="sleep-schedule">', 1)[1].split(
        '<details class="owner-details sleep-day-settings">', 1)[0]
    assert "Недостаточно ночей для сравнения" in schedule
    assert "0 мин" not in schedule


@pytest.mark.parametrize("count", [0, 1, 2])
def test_insufficient_html_has_no_numeric_jetlag(tmp_path, count):
    data = sleep_timeline_client(_timeline(count=count))
    rendered, = _render(tmp_path, {"data": data})
    assert "Недостаточно ночей для сравнения" in rendered["html"]
    summaries = re.findall(r'<td[^>]*data-sleep-jetlag="[^"]*"[^>]*>(.*?)</td>',
                           rendered["html"])
    assert len(summaries) == len(data["regularity"]["sources"]) > 0
    assert all("сдвиг " not in text and "0 мин" not in text for text in summaries)
    for source in data["regularity"]["sources"]:
        assert all(g["signed_minutes"] is None for g in source["jetlag"]["groups"])


def test_same_provider_incompatible_methods_not_combined():
    raw = _regularity_packet()
    for day in raw["days"][-3:]:
        day["sources"][0]["sessions"][0]["metrics"]["sleep_end_at"][
            "comparison_basis"] = "different_method"
    timeline = build_sleep_timeline({"google": raw}, days=7, end_date=END)
    row, = timeline["regularity"]["sources"]
    assert len(row["jetlag"]["groups"]) == 2
    assert sum(g["groups"]["work"]["n"] for g in row["jetlag"]["groups"]) == 5


def test_config_roundtrip_preserves_other_settings_and_restart(tmp_path):
    _, settings, paths = _ui(tmp_path)
    paths.config.write_text('title = "Тест"\n[unrelated]\nnumber = 42\n', encoding="utf-8")
    current = read_sleep_schedule_settings(settings)
    assert current.day_type("2026-10-03") == "free"
    update_sleep_schedule_settings(settings, revision=current.revision,
                                   work_weekdays=[1, 2, 3, 4, 5])
    current = read_sleep_schedule_settings(settings)
    assert current.day_type("2026-10-03") == "work"
    assert current.day_type("2026-10-05") == "free"
    update_sleep_schedule_settings(settings, revision=current.revision,
                                   override_date="2026-10-03", day_type="free")
    current = read_sleep_schedule_settings(settings)
    assert current.day_type("2026-10-03") == "free"
    assert '[unrelated]\nnumber = 42' in paths.config.read_text(encoding="utf-8")
    update_sleep_schedule_settings(settings, revision=current.revision,
                                   override_date="2026-10-03", day_type="default")
    assert read_sleep_schedule_settings(settings).day_type("2026-10-03") == "work"
    with pytest.raises(ValueError, match="reload"):
        update_sleep_schedule_settings(settings, revision=current.revision, work_weekdays=[])


@pytest.mark.parametrize("text", ['[sleep_schedule]\nwork_weekdays = [true]',
    '[sleep_schedule]\nwork_weekdays = [7]', '[sleep_schedule]\nwork_weekdays = [1,1]',
    '[sleep_schedule]\noverrides = {"bad" = "free"}',
    '[sleep_schedule]\noverrides = {"2026-10-03" = "unknown"}', 'bad toml'])
def test_invalid_settings_unknown_and_not_silently_overwritten(tmp_path, text):
    _, settings, paths = _ui(tmp_path)
    paths.config.write_text(text, encoding="utf-8")
    value = read_sleep_schedule_settings(settings)
    assert value.state == "unavailable" and value.day_type("2026-10-03") == "unknown"
    with pytest.raises(ValueError):
        update_sleep_schedule_settings(settings, revision="", work_weekdays=[0])
    assert paths.config.read_text(encoding="utf-8") == text


def test_http_forms_persist_readback_and_reject_stale_or_cross_origin(tmp_path):
    app, settings, paths = _ui(tmp_path)
    headers = {"Origin": "http://127.0.0.1:8120"}
    target = "/sleep?days=7&wake_date=2026-10-08&google_sleep_source_id=sleep"
    with client_for(app) as client:
        page = client.get(target)
        assert "Рабочие дни недели" in page.text
        current = read_sleep_schedule_settings(settings)
        form = {"operation": "override", "date": "2026-10-03", "day_type": "work",
                "revision": current.revision, "return_to": target}
        response = client.post("/sleep/settings", data=form, headers=headers,
                               follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == target
        assert client.post("/sleep/settings", data=form, headers=headers).status_code == 422
        form["revision"] = read_sleep_schedule_settings(settings).revision
        assert client.post("/sleep/settings", data=form,
                           headers={"Origin": "http://foreign.test"}).status_code == 403
        form["operation"] = "weekdays"
        form.pop("date")
        form.pop("day_type")
        response = client.post("/sleep/settings", data=form, headers=headers)
        assert response.status_code == 200
        packet = json.loads(re.search(
            r'<script id="sleep-timeline-data" type="application/json">(.*?)</script>',
            response.text, re.S).group(1))
        assert packet["day_types"]["2026-10-03"] == "work"  # Override wins.
        assert packet["day_types"]["2026-10-05"] == "free"  # Empty workweek.
        assert read_sleep_schedule_settings(settings).work_weekdays == ()
        before = paths.config.read_bytes()
        body = urlencode({**form, "revision": read_sleep_schedule_settings(settings).revision})
        for bad in (body + "&operation=override", body + "&weekday=7",
                    body.replace("%2Fsleep", "https%3A%2F%2Fforeign.test%2Fsleep"),
                    body + "&unused=x", "x=" + "x" * 8192):
            response = client.post("/sleep/settings", content=bad, headers={
                **headers, "Content-Type": "application/x-www-form-urlencoded"})
            assert response.status_code == 422
        assert paths.config.read_bytes() == before
