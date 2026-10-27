"""Synthetic semantics and real read-only combined-export regressions."""

import hashlib
import json
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


@pytest.mark.parametrize("selected", [False, True])
def test_source_method_and_travel_partitions_never_select_a_later_night_for_same_event(selected):
    data = sections()
    night = item(data, 1)
    for endpoint in ("start", "end"):
        temporal = night["metrics"][f"sleep_{endpoint}_at"]["evidence"]["interval_snapshots"][0][
            f"{endpoint}_temporal"]
        temporal.update(source_timezone=None, source_utc_offset_minutes=60)
    data["context"]["rows"] = [event(item(data)["metrics"]["sleep_start_at"]["value"])]
    result = analyze(data, request(context_pairing_hours=48, context_event_revisions=(
        (("event-1", "revision-1"),) if selected else None)))
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


@pytest.mark.parametrize("selected", [False, True])
def test_zero_missing_and_incompatible_methods_have_explicit_counts(selected):
    data = sections()
    for i in range(3):
        data["context"]["rows"].append(event(item(data, i)["metrics"]["sleep_start_at"]["value"],
                                                number=i))
    item(data, 1)["metrics"]["sleep_duration_asleep_seconds"].update(
        eligible=False, state="missing", value=None)
    item(data, 2)["metrics"]["sleep_duration_asleep_seconds"]["comparison_basis"] = "other"
    req = request(context_event_revisions=(tuple(
        (f"event-{i}", f"revision-{i}") for i in range(3)) if selected else None))
    result = analyze(data, req)["context_recovery"]["comparisons"][0]["metrics"]
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



@pytest.mark.parametrize("endpoint", ["start", "end"])
@pytest.mark.parametrize("temporal", [None, "omitted"])
def test_missing_endpoint_temporal_object_is_an_exclusion(endpoint, temporal):
    data = sections(count=1)
    snapshot = item(data)["metrics"][f"sleep_{endpoint}_at"]["evidence"]["interval_snapshots"][0]
    if temporal == "omitted":
        del snapshot[f"{endpoint}_temporal"]
    else:
        snapshot[f"{endpoint}_temporal"] = temporal
    result = analyze(data)["sleep_analysis_inputs"]
    assert result["nights"] == []
    assert result["night_exclusions"][0]["reason"] == f"{endpoint}_temporal_unavailable"


def test_persisted_missing_temporal_json_does_not_abort_export(profile):
    from sqlalchemy import select

    from healthcheck.db.models import GoogleSleepInterval
    with session_scope(profile[1]) as session:
        row = session.scalar(select(GoogleSleepInterval).where(
            GoogleSleepInterval.interval_kind == "sleep_session"))
        row.end_temporal_json = "null"
    packet = read(profile, replace(profile[2], include_sleep_regularity=True,
                                   include_context_recovery=True))
    exclusions = packet["sections"]["sleep_analysis_inputs"]["night_exclusions"]
    assert any(n["provider"] == "google" and n["reason"] == "end_temporal_unavailable"
               for n in exclusions)
    google = packet["sections"]["sleep"]["providers"]["google"]["source_range"]["days"][-1]
    assert google["sources"][0]["sessions"][0]["metrics"]["sleep_end_at"]["eligible"] is True


@pytest.mark.parametrize("selection,error", [
    ((), "invalid_context_event_selection"),
    ([], "invalid_context_event_selection"),
    ((("event",),), "invalid_context_event_selection"),
    ((["event", "revision"],), "invalid_context_event_selection"),
    ((("", "revision"),), "invalid_context_event_selection"),
    ((("event", " "),), "invalid_context_event_selection"),
    ((("event", True),), "invalid_context_event_selection"),
    ((("e" * 37, "revision"),), "invalid_context_event_selection"),
    ((("event", "r" * 37),), "invalid_context_event_selection"),
    (tuple((f"e{i}", f"r{i}") for i in range(101)), "invalid_context_event_selection"),
    ((("event", "r1"), ("event", "r1")), "duplicate_context_event_selection"),
    ((("event", "r1"), ("event", "r2")), "duplicate_context_event_selection"),
])
def test_selected_context_invalid_request_never_opens_profile(tmp_path, monkeypatch, selection,
                                                             error):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid selection opened a profile")
    monkeypatch.setattr(combined, "_read_session", forbidden)
    with pytest.raises(EvidenceError, match=f"^{error}$"):
        combined.read_combined_evidence(
            profile=tmp_path, profile_kind="synthetic",
            request=request(context_event_revisions=selection), evaluated_at_utc=datetime.now(UTC),
            evaluation_local_date=date(2026, 10, 10))


def test_selected_context_requires_opt_in_and_allows_the_existing_100_event_cap():
    selected = tuple((f"e{i}", f"r{i}") for i in range(100))
    request(context_event_revisions=selected).validate()
    with pytest.raises(EvidenceError, match="^selection_requires_context_recovery$"):
        replace(request(context_event_revisions=selected),
                include_context_recovery=False).validate()
    with pytest.raises(EvidenceError, match="^context_analysis_requires_context$"):
        replace(request(context_event_revisions=selected), include_context=False).validate()


def test_selected_nights_are_not_pooled_and_other_observed_context_is_disclosed():
    data = sections()
    selected = []
    for i in range(3):
        anchor = item(data, i)["metrics"]["sleep_start_at"]["value"]
        for number in (i, i + 10):
            row = event(anchor, number=number)
            row["tags"] = ["synthetic-same-tag"]
            data["context"]["rows"].append(row)
            selected.append((row["event_id"], row["revision_id"]))
    for number, night in ((20, 0), (21, 3)):
        row = event(item(data, night)["metrics"]["sleep_start_at"]["value"], number=number)
        row["tags"] = ["synthetic-same-tag"]
        data["context"]["rows"].append(row)
    data["context"]["rows"].append(event(None, number=22, precision="date"))
    pooled = analyze(deepcopy(data))["context_recovery"]
    output = analyze(data, request(context_event_revisions=tuple(selected)))
    result = output["context_recovery"]
    assert pooled["version"] == "saved-context-next-sleep-v1"
    assert pooled["comparisons"][0]["paired_unique_nights"] == 4
    assert "event_selection" not in pooled and "observed_context_by_night" not in pooled
    assert result["version"] == "saved-context-next-sleep-v2"
    assert len(result["pairs"]) == 6
    comparison = result["comparisons"][0]
    assert comparison["paired_unique_nights"] == 3 and comparison["reference_nights"] == 4
    metric = comparison["metrics"][0]
    assert (metric["paired_mean"], metric["reference_mean"], metric["mean_difference"]) == (
        60, 270, -210)
    assert metric["paired_n"] == 3 and metric["reference_n"] == 4
    assert result["event_exclusions"] == []
    assert [e["event_id"] for e in result["other_event_exclusions"]] == ["event-22"]
    observations = {n["record_id"]: n for n in result["observed_context_by_night"]}
    assert len(observations["night-0"]["selected_events"]) == 2
    assert observations["night-0"]["other_observed_events"][0]["event_id"] == "event-20"
    assert observations["night-3"]["selected_events"] == []
    assert observations["night-3"]["other_observed_events"][0]["event_id"] == "event-21"
    assert observations["night-6"]["other_observed_events"] == []
    assert "unknown" in result["accompanying_context"]["completeness"]
    assert "not_proof" in result["accompanying_context"]["empty_list"]
    assert "exposure_unknown" in result["reference"]
    assert output["sleep_regularity"] == analyze(deepcopy(data))["sleep_regularity"]


@pytest.mark.parametrize("hours", [1, 24, 48])
@pytest.mark.parametrize("kind", ["instant", "interval"])
def test_selected_event_pairing_keeps_exact_inclusive_window(hours, kind):
    data = sections(count=1)
    start = analysis._instant(item(data)["metrics"]["sleep_start_at"]["value"])
    anchor = start - timedelta(hours=hours)
    data["context"]["rows"] = [
        event(anchor.isoformat(), number=1, kind=kind, precision="microsecond"),
        event((anchor - timedelta(microseconds=1)).isoformat(), number=2, kind=kind,
              precision="microsecond"),
        event((start + timedelta(microseconds=1)).isoformat(), number=3, kind=kind,
              precision="microsecond"),
    ]
    selected = tuple((row["event_id"], row["revision_id"]) for row in data["context"]["rows"])
    result = analyze(data, request(context_pairing_hours=hours,
                                  context_event_revisions=selected))["context_recovery"]
    assert [(p["event_id"], p["lag_to_sleep_start_hours"]) for p in result["pairs"]] == [
        ("event-1", hours)]
    assert {p["event_id"] for p in result["event_exclusions"]} == {"event-2", "event-3"}


def test_selected_date_only_remains_excluded_even_with_other_usable_events():
    data = sections()
    data["context"]["rows"] = [event(None, number=1, precision="date"),
        event(item(data)["metrics"]["sleep_start_at"]["value"], number=2)]
    result = analyze(data, request(context_event_revisions=(("event-1", "revision-1"),)))[
        "context_recovery"]
    assert result["pairs"] == []
    assert result["event_exclusions"][0]["reason"] == "event_anchor_not_an_explicit_instant"
    assert result["comparisons"][0]["paired_unique_nights"] == 0
    assert result["comparisons"][0]["reference_nights"] == 7
    assert all(m["state"] == "insufficient" and m["mean_difference"] is None
               for m in result["comparisons"][0]["metrics"])


def test_selected_context_production_versions_hash_compact_text_and_caps(profile, monkeypatch):
    from test_weekly_digest import seed_google

    current = profile[-1]
    req = replace(profile[2], include_context_recovery=True, include_sleep_regularity=True,
                  context_event_revisions=((current.event_id, current.revision_id),))
    original = read(profile)
    google_steps = seed_google(profile)
    for steps in (None, google_steps):
        detailed = read(profile, replace(req, steps_google_source_id=steps))
        compact = read(profile, replace(req, projection="compact", steps_google_source_id=steps))
        assert detailed["version"] == "health-chat-combined-evidence-v8"
        assert compact["version"] == "health-chat-combined-compact-evidence-v8"
        assert compact["projection"]["detailed_version"] == detailed["version"]
        for key in ("sleep_analysis_inputs", "context_recovery", "sleep_regularity"):
            assert detailed["sections"][key] == compact["sections"][key]
        assert detailed["sections"]["context"] == original["sections"]["context"]
        for packet in (detailed, compact):
            selection = packet["request"]["analyses"]["context_event_revisions"]
            assert selection == [{"event_id": current.event_id, "revision_id": current.revision_id}]
            assert selection == packet["sections"]["context_recovery"]["event_selection"]["events"]
            bound = {k: v for k, v in packet.items() if k != "envelope_hash"}
            assert hashlib.sha256(analysis._json(bound).encode()).hexdigest() == (
                packet["envelope_hash"])
            changed = deepcopy(bound)
            changed["request"]["analyses"]["context_event_revisions"][0]["revision_id"] = "changed"
            assert hashlib.sha256(analysis._json(changed).encode()).hexdigest() != (
                packet["envelope_hash"])
            decoded = json.loads(combined.encode_combined_evidence(packet))
            assert decoded["envelope_hash"] == packet["envelope_hash"]
            assert decoded["sections"]["context_recovery"]["event_selection"]["events"] == selection
            text = combined.render_combined_evidence(packet)
            assert current.revision_id in text and "observed_context_by_night" in text
            assert "exposure_unknown" in text
        legacy = read(profile, replace(req, context_event_revisions=None,
                                       steps_google_source_id=steps))
        assert legacy["version"] == f"health-chat-combined-evidence-v{7 if steps else 6}"
        assert "context_event_revisions" not in legacy["request"]["analyses"]
        assert legacy["sections"]["context_recovery"]["version"] == "saved-context-next-sleep-v1"
    monkeypatch.setattr(combined, "MAX_OUTPUT_BYTES", 1)
    with pytest.raises(EvidenceError, match="^output_exceeds_byte_limit$"):
        read(profile, req)


def test_selected_unavailable_stale_and_capped_context_fail_closed(profile):
    from sqlalchemy import select

    from healthcheck.db.models import ContextEventRevision

    current = profile[-1]
    req = replace(profile[2], include_context_recovery=True)
    with session_scope(profile[1]) as session:
        outside = session.scalar(select(ContextEventRevision).where(
            ContextEventRevision.original_text == "OUTSIDE"))
        outside_selection = ((outside.event_id, outside.id),)
    for selection in ((("absent", "absent"),), outside_selection):
        with pytest.raises(EvidenceError, match="^selected_context_event_unavailable_in_snapshot$"):
            read(profile, replace(req, context_event_revisions=selection))
    with pytest.raises(EvidenceError, match="^stale_context_event_revision$"):
        read(profile, replace(req, context_event_revisions=((current.event_id, "old"),)))
    full = read(profile, req)["sections"]["context"]["rows"]
    capped = read(profile, replace(req, context_limit=1))["sections"]["context"]
    missing = next(row for row in full if row["event_id"] != capped["rows"][0]["event_id"])
    with pytest.raises(EvidenceError, match="^selected_context_event_unavailable_in_snapshot$"):
        read(profile, replace(req, context_limit=1, context_event_revisions=(
            (missing["event_id"], missing["revision_id"]),)))
    kept = capped["rows"][0]
    accepted = read(profile, replace(req, context_limit=1, context_event_revisions=(
        (kept["event_id"], kept["revision_id"]),)))
    assert accepted["sections"]["context_recovery"]["context_coverage"]["truncated"] is True


def test_selected_duplicate_snapshot_rows_are_not_resolved_arbitrarily():
    data = sections(count=1)
    row = event(item(data)["metrics"]["sleep_start_at"]["value"])
    data["context"]["rows"] = [row, deepcopy(row)]
    with pytest.raises(EvidenceError, match="^selected_context_event_ambiguous_in_snapshot$"):
        analyze(data, request(context_event_revisions=(("event-1", "revision-1"),)))


def test_selected_revision_checked_in_original_snapshot_during_concurrent_correction(profile,
                                                                                    monkeypatch):
    from healthcheck import sleep_evidence

    current = profile[-1]
    req = replace(profile[2], include_context_recovery=True,
                  context_event_revisions=((current.event_id, current.revision_id),))
    original, original_list = sleep_evidence._assemble, ContextService.list
    changed = False
    reads = []
    def tracked(self, **kwargs):
        reads.append(self.session)
        return original_list(self, **kwargs)
    def concurrent(*args, **kwargs):
        nonlocal changed
        result = original(*args, **kwargs)
        if not changed:
            changed = True
            with session_scope(profile[1]) as writer:
                ContextService(writer).revise(event_id=current.event_id,
                    text="Synthetic concurrent correction", capture_source="cli")
        return result
    monkeypatch.setattr(ContextService, "list", tracked)
    monkeypatch.setattr(sleep_evidence, "_assemble", concurrent)
    packet = read(profile, req)
    assert len(reads) == 1
    assert packet["sections"]["context_recovery"]["event_exclusions"][0]["revision_id"] == (
        current.revision_id)
    with pytest.raises(EvidenceError, match="^stale_context_event_revision$"):
        read(profile, req)


def test_selected_context_cli_success_and_failure_emit_no_partial_payload(profile, capsys):
    from healthcheck.export_combined_evidence import main

    current = profile[-1]
    selected = f"{current.event_id}={current.revision_id}"
    args = [*stdout_args(profile, "json"), "--include-context-recovery",
            "--context-event", selected]
    assert main(args) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    packet = json.loads(captured.out)
    assert packet["version"] == "health-chat-combined-evidence-v8"
    assert packet["request"]["analyses"]["context_event_revisions"] == [
        {"event_id": current.event_id, "revision_id": current.revision_id}]
    for options in (["--context-event", selected],
                    ["--context-event", "absent=private-value"],
                    ["--context-event", f"{current.event_id}=old"],
                    ["--context-event", "malformed"]):
        assert main([*args, *options]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.startswith("Export failed: ")
        assert "private-value" not in captured.err and current.event_id not in captured.err
