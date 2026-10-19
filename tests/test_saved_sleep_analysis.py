"""Synthetic semantics and real read-only combined-export regressions."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from healthcheck import combined_evidence as combined
from healthcheck import saved_sleep_analysis as analysis
from healthcheck.chat_evidence import EvidenceError
from healthcheck.combined_evidence import CombinedEvidenceRequest
from healthcheck.context import ContextService, parse_interval, parse_timestamp
from healthcheck.db.engine import session_scope
from test_combined_evidence import profile as profile
from test_combined_evidence import read, stdout_args
from test_combined_evidence import sleep_profile as sleep_profile
from test_sleep_evidence import DAY
from test_sleep_metrics import _google_sleep_payload, _persist_google


def request(**kwargs):
    return CombinedEvidenceRequest(date(2026, 10, 10), 30, "activity", "garmin",
                                   include_context_recovery=True, include_sleep_regularity=True,
                                   **kwargs)


def sections(count=7, provider="google", zone="UTC", offset=0):
    days = []
    for i in range(count):
        end = datetime(2026, 10, i + 2, 7, tzinfo=UTC)
        start = end - timedelta(hours=8)
        temporal = {"precision": "instant", "source_timezone": zone,
                    "source_utc_offset_minutes": offset}
        metrics = {}
        for endpoint, instant in (("start", start), ("end", end)):
            row = {"interval_kind": "sleep_session" if provider == "google" else "sleep_stage",
                   f"{endpoint}_at_utc": instant.isoformat(), f"{endpoint}_temporal": temporal}
            metrics[f"sleep_{endpoint}_at"] = {
                "state": "value", "value": instant.isoformat(), "unit": "UTC instant",
                "eligible": True, "reason": None, "field_path": endpoint,
                "comparison_basis": "explicit_session_boundary" if provider == "google" else
                "explicit_record_boundary" if endpoint == "start" else "complete_stage_boundary",
                "evidence": {"interval_snapshots": [row],
                             "normalization_provenance": {"normalization_contract_version": "v1"}}}
        metrics["sleep_duration_asleep_seconds"] = {
            "state": "value", "value": i * 60, "eligible": True, "is_zero": i == 0,
            "reason": None, "unit": "seconds", "comparison_basis": "persisted_metric"}
        item = {"record_id": f"night-{i}", "wake_date": end.date().isoformat(),
                "record_status": "ok", "reason": None, "variant": None,
                "role": None if provider == "garmin" else {"selection": "explicit_main"},
                "metrics": metrics, "temporal_evidence": temporal}
        days.append({"wake_date": end.date().isoformat(), "state": "records", "sources": [
            {"source": {"source_id": "sleep"}, "ambiguous": False, "sessions": [item]}]})
    return {"sleep": {"providers": {provider: {"selected_source_id": "sleep",
            "acquisition_coverage": {"state": "unknown"}, "source_range": {
                "state": "records", "days": days, "series": [], "missing_dates": [],
                "wake_date_missing_count": 0}}}},
            "context": {"rows": [], "truncated": False, "has_more": False, "limit": 50}}


def item(data, i=0, provider="google"):
    return data["sleep"]["providers"][provider]["source_range"]["days"][i]["sources"][0][
        "sessions"][0]


def event(anchor, *, number=1, kind="instant", precision="second"):
    return {"event_id": f"event-{number}", "revision_id": f"revision-{number}",
            "revision_number": 2, "capture_source": "manual", "tags": [],
            "created_at": "2020-01-01T00:00:00Z",
            "temporal": {"kind": kind, "start_precision": precision,
                         "start_at_utc": anchor if kind != "interval" else "2026-09-01T00:00Z",
                         "end_precision": precision, "end_at_utc": anchor}}


def analyze(data, req=None):
    before = deepcopy(data)
    analysis.analyze_saved_sleep(data, req or request())
    assert data["sleep"] == before["sleep"] and data["context"] == before["context"]
    return data


def test_midnight_circular_math_sparse_undefined_and_zero():
    result = analysis.circular_local_clock([1410, 0, 30])
    assert min(result["mean_clock_minutes"], 1440 - result["mean_clock_minutes"]) < 1e-10
    assert result["circular_sd_minutes"] == pytest.approx(24.512413, abs=1e-5)
    assert analysis.circular_local_clock([0, 0, 0])["circular_sd_minutes"] == 0
    assert analysis.circular_local_clock([0, 30])["circular_sd_minutes"] is None
    assert analysis.circular_local_clock([0, 480, 960])["state"] == "undefined_direction"
    # Independent formula for two equal angles and one shifted angle.
    assert analysis.circular_local_clock([0, 0, 720])["resultant_length"] == pytest.approx(1 / 3)


def test_multiple_corrected_events_interval_end_date_only_and_deduplicated_comparison():
    data = sections()
    for i in range(3):
        anchor = item(data, i)["metrics"]["sleep_start_at"]["value"]
        data["context"]["rows"].extend([event(anchor, number=i), event(anchor, number=i + 10,
                                                                           kind="interval")])
    data["context"]["rows"].append(event(None, number=99, precision="date"))
    result = analyze(data)["context_recovery"]
    assert len(result["pairs"]) == 6
    assert all(p["revision_number"] == 2 for p in result["pairs"])
    assert {p["anchor"] for p in result["pairs"]} == {"start", "end"}
    comparison = result["comparisons"][0]
    assert comparison["paired_unique_nights"] == 3 and comparison["reference_nights"] == 4
    metric = comparison["metrics"][0]
    assert metric["paired_mean"] == 60 and metric["reference_mean"] == 270
    assert metric["mean_difference"] == -210
    assert "exposure_unknown" in result["reference"]
    assert result["event_exclusions"][0]["reason"] == "event_anchor_not_an_explicit_instant"


def test_explicit_window_and_first_eligible_night_no_created_at_fallback():
    data = sections()
    start = analysis._instant(item(data)["metrics"]["sleep_start_at"]["value"])
    data["context"]["rows"] = [event((start - timedelta(hours=24)).isoformat()),
                                   event((start - timedelta(hours=24, seconds=1)).isoformat(),
                                         number=2)]
    pairs = analyze(data)["context_recovery"]["pairs"]
    assert len(pairs) == 1 and pairs[0]["record_id"] == "night-0"
    assert pairs[0]["lag_to_sleep_start_hours"] == 24


@pytest.mark.parametrize("problem,reason", [
    ("role", "google_main_sleep_unconfirmed"), ("nap", "google_nap_only"),
    ("ambiguous", "ambiguous_google_main"), ("endpoint", "end_instant_unavailable"),
    ("timezone", "start_local_timezone_unavailable"),
    ("travel", "within_night_timezone_change"), ("wake_date", "local_wake_date_conflict")])
def test_exclusions(problem, reason):
    data = sections(count=1)
    night = item(data)
    if problem == "role":
        night["role"]["selection"] = "uncertain_session"
    elif problem == "nap":
        night["reason"] = "google_nap_only"
    elif problem == "ambiguous":
        duplicate = deepcopy(night)
        duplicate["record_id"] = "other"
        data["sleep"]["providers"]["google"]["source_range"]["days"][0]["sources"][0][
            "sessions"].append(duplicate)
    elif problem == "endpoint":
        night["metrics"]["sleep_end_at"]["value"] = None
    elif problem == "timezone":
        temporal = night["metrics"]["sleep_start_at"]["evidence"]["interval_snapshots"][0][
            "start_temporal"]
        temporal.update(source_timezone=None, source_utc_offset_minutes=None)
    elif problem == "travel":
        night["metrics"]["sleep_end_at"]["evidence"]["interval_snapshots"][0]["end_temporal"] = {
            "precision": "instant", "source_timezone": "Europe/Paris",
            "source_utc_offset_minutes": 120}
    else:
        data["sleep"]["providers"]["google"]["source_range"]["days"][0]["wake_date"] = "2026-10-03"
    result = analyze(data)["sleep_analysis_inputs"]
    assert result["nights"] == []
    assert result["night_exclusions"][0]["reason"] == reason


def test_garmin_null_role_and_endpoint_method_respected():
    data = analyze(sections(provider="garmin"))
    nights = data["sleep_analysis_inputs"]["nights"]
    assert len(nights) == 7 and nights[0]["role"] is None
    assert nights[0]["end"]["method"] == "complete_stage_boundary"


def test_dst_midpoint_uses_elapsed_utc_and_travel_partitions():
    data = sections(count=1)
    for i in range(1):
        night = item(data, i)
        night["wake_date"] = "2026-11-01"
        data["sleep"]["providers"]["google"]["source_range"]["days"][i][
            "wake_date"] = "2026-11-01"
        for endpoint, stamp, offset in (("start", "2026-11-01T04:00:00Z", -240),
                                        ("end", "2026-11-01T09:00:00Z", -300)):
            cell = night["metrics"][f"sleep_{endpoint}_at"]
            cell["value"] = stamp
            cell["evidence"]["interval_snapshots"] = [{"interval_kind": "sleep_session",
                f"{endpoint}_at_utc": stamp, f"{endpoint}_temporal": {
                    "precision": "instant", "source_timezone": "America/New_York",
                    "source_utc_offset_minutes": offset}}]
    result = analyze(data)
    midpoint = result["sleep_analysis_inputs"]["nights"][0]["midpoint"]
    assert midpoint["clock_minutes"] == 90 and midpoint["fold"] == 1
    # Distinct dates remain required even when a malformed input repeats a night.


def test_explicit_nonstandard_work_free_unknown_and_missing_classification():
    data = sections()
    result = analyze(data)["sleep_regularity"]["groups"][0]
    assert result["clocks"]["start"]["state"] == "sufficient"
    assert result["social_jetlag"]["state"] == "insufficient"
    assert result["social_jetlag"]["unknown_nights"] == 7
    data = sections()
    labels = tuple((f"2026-10-{i + 2:02}", "work" if i < 3 else "free") for i in range(6))
    result = analyze(data, request(sleep_day_types=labels))["sleep_regularity"]["groups"][0]
    assert result["social_jetlag"]["signed_minutes"] == pytest.approx(0)
    assert result["social_jetlag"]["groups"]["free"]["n"] == 3
    assert result["social_jetlag"]["unknown_nights"] == 1


@pytest.mark.parametrize("changes", [
    {"include_sleep_regularity": 1}, {"context_pairing_hours": 0},
    {"context_pairing_hours": True}, {"context_pairing_hours": 49},
    {"sleep_day_types": (("2026-10-02", "weekend"),)},
    {"sleep_day_types": (("2026-10-02", "work"), ("2026-10-02", "free"))},
    {"sleep_day_types": (("2026-11-01", "free"),)},
    {"include_context": False, "include_context_recovery": True}])
def test_options_fail_before_profile_access(tmp_path, monkeypatch, changes):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid options opened profile")
    monkeypatch.setattr(combined, "_read_session", forbidden)
    with pytest.raises(EvidenceError):
        combined.read_combined_evidence(profile=tmp_path, profile_kind="synthetic",
            request=replace(request(), **changes), evaluated_at_utc=datetime.now(UTC),
            evaluation_local_date=date(2026, 10, 10))


def test_production_snapshot_revision_compact_text_caps_and_default_compatibility(profile):
    baseline = read(profile)
    req = replace(profile[2], include_sleep_regularity=True, include_context_recovery=True)
    detailed, compact = read(profile, req), read(profile, replace(req, projection="compact"))
    assert detailed["version"] == "health-chat-combined-evidence-v6"
    assert baseline["version"] == "health-chat-combined-evidence-v1"
    for key in ("sleep_regularity", "context_recovery", "sleep_analysis_inputs"):
        assert detailed["sections"][key] == compact["sections"][key]
        assert key not in baseline["sections"]
        assert f"{key}: " in combined.render_combined_evidence(detailed)
    assert detailed["sections"]["sleep"] == baseline["sections"]["sleep"]
    assert detailed["snapshot"] == "one_sqlite_read_transaction"
    assert len(detailed["sections"]["sleep_analysis_inputs"]["nights"]) == 1
    corrected = detailed["sections"]["context_recovery"]["event_exclusions"]
    assert any(r["revision_id"] == profile[-1].revision_id for r in corrected)
    limited = read(profile, replace(req, context_limit=1))
    assert limited["sections"]["context_recovery"]["context_coverage"]["truncated"] is True


def test_production_multiple_nights_cli_and_interval_end(profile, capsys):
    from healthcheck.export_combined_evidence import main
    with session_scope(profile[1]) as session:
        for i in range(1, 7):
            wake = DAY - timedelta(days=i)
            payload = _google_sleep_payload(name=f"extra-{i}")
            component = payload["dataPoints"][0]["sleep"]
            component["interval"]["startTime"] = f"{wake - timedelta(days=1)}T22:00:00Z"
            component["interval"]["endTime"] = f"{wake}T05:00:00Z"
            component["interval"]["civilStartTime"]["date"] = str(wake)
            component["interval"]["civilEndTime"]["date"] = str(wake)
            _persist_google(session, profile[0], payload=payload)
            if i <= 3:
                ContextService(session).add(text="Synthetic interval", capture_source="cli",
                    temporal=parse_interval(f"{wake - timedelta(days=1)}T18:00+03:00",
                                            f"{wake - timedelta(days=1)}T20:00+03:00"))
        ContextService(session).add(text="Synthetic instant", capture_source="cli",
                                   temporal=parse_timestamp("2099-01-01T20:00+03:00"))
    assert main([*stdout_args(profile, "json"), "--include-context-recovery",
                 "--include-sleep-regularity", "--projection", "compact",
                 "--sleep-day-type", f"{DAY}=unknown"]) == 0
    import json
    packet = json.loads(capsys.readouterr().out)
    assert len(packet["sections"]["sleep_analysis_inputs"]["nights"]) == 7
    comparison = packet["sections"]["context_recovery"]["comparisons"][0]
    assert comparison["paired_unique_nights"] == 4
    assert comparison["reference_nights"] == 3
    assert any(m["state"] == "sufficient" for m in comparison["metrics"])


def test_source_method_and_travel_partitions_never_select_a_later_night_for_same_event():
    data = sections()
    night = item(data, 1)
    for endpoint in ("start", "end"):
        temporal = night["metrics"][f"sleep_{endpoint}_at"]["evidence"]["interval_snapshots"][0][
            f"{endpoint}_temporal"]
        temporal.update(source_timezone=None, source_utc_offset_minutes=60)
    data["context"]["rows"] = [event(item(data)["metrics"]["sleep_start_at"]["value"])]
    result = analyze(data, request(context_pairing_hours=48))
    assert len(result["sleep_regularity"]["groups"]) == 2
    assert [p["record_id"] for p in result["context_recovery"]["pairs"]] == ["night-0"]


def test_duplicate_source_nights_do_not_inflate_counts():
    data = sections(count=1)
    days = data["sleep"]["providers"]["google"]["source_range"]["days"]
    duplicate = deepcopy(days[0])
    duplicate["sources"][0]["sessions"][0]["record_id"] = "duplicate"
    days.append(duplicate)
    result = analyze(data)["sleep_analysis_inputs"]
    assert len(result["nights"]) == 1
    assert result["night_exclusions"][0]["reason"] == "duplicate_source_wake_date"


def test_zero_missing_and_incompatible_methods_have_explicit_counts():
    data = sections()
    for i in range(3):
        data["context"]["rows"].append(event(item(data, i)["metrics"]["sleep_start_at"]["value"],
                                                number=i))
    item(data, 1)["metrics"]["sleep_duration_asleep_seconds"].update(
        eligible=False, state="missing", value=None)
    item(data, 2)["metrics"]["sleep_duration_asleep_seconds"]["comparison_basis"] = "other"
    result = analyze(data)["context_recovery"]["comparisons"][0]["metrics"]
    original = next(m for m in result if m["method"]["comparison_basis"] == "persisted_metric")
    assert original["paired_n"] == 1  # explicit zero counts
    assert original["paired_missing_or_incompatible"] == 2
    assert original["mean_difference"] is None and original["state"] == "insufficient"


def test_spring_dst_midpoint_and_zone_offset_conflict():
    data = sections(count=1)
    night = item(data)
    day = data["sleep"]["providers"]["google"]["source_range"]["days"][0]
    day["wake_date"] = "2026-03-08"
    for endpoint, stamp, offset in (("start", "2026-03-08T05:00:00Z", -300),
                                    ("end", "2026-03-08T09:00:00Z", -240)):
        cell = night["metrics"][f"sleep_{endpoint}_at"]
        cell["value"] = stamp
        cell["evidence"]["interval_snapshots"] = [{"interval_kind": "sleep_session",
            f"{endpoint}_at_utc": stamp, f"{endpoint}_temporal": {
                "precision": "instant", "source_timezone": "America/New_York",
                "source_utc_offset_minutes": offset}}]
    assert analyze(data)["sleep_analysis_inputs"]["nights"][0]["midpoint"]["clock_minutes"] == 180
    night["metrics"]["sleep_end_at"]["evidence"]["interval_snapshots"][0]["end_temporal"][
        "source_utc_offset_minutes"] = -300
    assert analyze(data)["sleep_analysis_inputs"]["night_exclusions"][0]["reason"] == (
        "end_zone_offset_conflict")


def test_read_limit_and_output_limit_still_fail_closed(profile, monkeypatch):
    from healthcheck.analytics import sleep_source_view
    req = replace(profile[2], include_sleep_regularity=True, include_context_recovery=True)
    monkeypatch.setattr(sleep_source_view, "MAX_SOURCE_SLEEP_RANGE_RECORDS", 0)
    packet = read(profile, req)
    assert packet["sections"]["sleep_analysis_inputs"]["nights"] == []
    assert all(c["range"]["state"] == "read_limit_exceeded"
               for c in packet["sections"]["sleep_analysis_inputs"]["coverage"].values())
    monkeypatch.setattr(combined, "MAX_OUTPUT_BYTES", 1)
    with pytest.raises(EvidenceError, match="output_exceeds_byte_limit"):
        read(profile, req)


def test_optional_analyses_use_same_snapshot_and_single_context_read(profile, monkeypatch):
    from contextlib import contextmanager
    calls = []
    original_read, original_list = combined._read_session, ContextService.list
    @contextmanager
    def tracked(root):
        with original_read(root) as session:
            calls.append(("snapshot", session))
            yield session
    def current(self, **kwargs):
        calls.append(("context", self.session))
        return original_list(self, **kwargs)
    monkeypatch.setattr(combined, "_read_session", tracked)
    monkeypatch.setattr(ContextService, "list", current)
    read(profile, replace(profile[2], include_context_recovery=True, include_sleep_regularity=True))
    assert [name for name, _ in calls] == ["snapshot", "context"]
    assert calls[0][1] is calls[1][1]

