"""Compact combined evidence: synthetic size, parity and fail-closed boundaries."""
from __future__ import annotations

import hashlib
import io
import json
import re
import socket
import sys
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from healthcheck import combined_evidence as evidence
from healthcheck import export_combined_evidence as cli
from healthcheck.analytics import period_summary_read as bounded
from healthcheck.analytics import sleep_source_view
from healthcheck.chat_evidence import MAX_OUTPUT_BYTES, EvidenceError, _json
from healthcheck.context import ContextService, parse_date_only
from healthcheck.db.engine import session_scope
from healthcheck.db.models import (
    GarminSource,
    GarminSourceRecord,
    GoogleRecordMetric,
    GoogleSleepRecord,
    GoogleSourceRecord,
)
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from test_combined_evidence import _acquire_stress, _seed_battery, cells, read, stdout_args
from test_combined_evidence import profile as profile
from test_combined_evidence import sleep_profile as sleep_profile
from test_period_summary import _activity, _coverage
from test_sleep_evidence import DAY
from test_sleep_metrics import (
    GARMIN_SLEEP_FIXTURE,
    _google_sleep_payload,
    _persist_garmin,
    _persist_google,
    _stage,
)


def compact(profile, **changes):
    return read(profile, replace(profile[2], projection="compact", **changes))


def assert_parity(detailed, projected):
    assert projected["version"] == (evidence.SELECTED_COMPACT_VERSION
                                    if detailed["version"] == evidence.SELECTED_VERSION
                                    else evidence.COMPACT_VERSION)
    for key in detailed.keys() - {"version", "generated_at_utc", "envelope_hash", "sections"}:
        assert projected[key] == detailed[key]
    assert projected["sections"]["activity"] == detailed["sections"]["activity"]
    assert projected["sections"].get("context") == detailed["sections"].get("context")
    for metric in ("stress", "body_battery"):
        assert projected["sections"].get(metric) == detailed["sections"].get(metric)
    for provider, old in detailed["sections"]["sleep"]["providers"].items():
        new = projected["sections"]["sleep"]["providers"][provider]
        assert {k: v for k, v in new.items() if k != "source_range"} == {
            k: v for k, v in old.items() if k != "source_range"}
        if old["source_range"] is None:
            assert new["source_range"] is None
            continue
        assert {k: v for k, v in old["source_range"].items() if k != "days"} == {
            k: v for k, v in new["source_range"].items() if k != "days"}
        assert len(old["source_range"]["days"]) == len(new["source_range"]["days"])
        for before, after in zip(old["source_range"]["days"], new["source_range"]["days"]):
            assert before.keys() == after.keys()
            assert {k: v for k, v in before.items() if k != "sources"} == {
                k: v for k, v in after.items() if k != "sources"}
            assert len(before["sources"]) == len(after["sources"])
            for source, target in zip(before["sources"], after["sources"]):
                assert target["source"] == source["source"]
                assert target["ambiguous"] == source["ambiguous"]
                assert target["summary_record_id"] == (
                    None if source["summary"] is None else source["summary"]["record_id"])
                assert len(source["sessions"]) == len(target["sessions"])
                for original, actual in zip(source["sessions"], target["sessions"]):
                    assert {k: v for k, v in original.items() if k != "metrics"} == {
                        k: v for k, v in actual.items()
                        if k not in {"metrics", "evidence_common", "field_path_sets",
                                     "session_interval_sets", "quality_input_sets"}}
                    assert original["metrics"].keys() == actual["metrics"].keys()
                    for code, metric in original["metrics"].items():
                        cell = actual["metrics"][code]
                        assert {k: v for k, v in metric.items() if k != "evidence"} == {
                            k: v for k, v in cell.items() if k != "evidence"}
                        restored = evidence._restore_compact_sleep_evidence(actual, cell)
                        restored["field_paths"] = actual["field_path_sets"][
                            restored.pop("field_paths_index")]
                        assert {k: v for k, v in metric["evidence"].items()
                                if k not in {"interval_snapshots", "interval_ids"}} == {
                            k: v for k, v in restored.items() if k != "interval_summary"}
                        summary = dict(restored["interval_summary"])
                        snapshots = metric["evidence"]["interval_snapshots"]
                        ids = metric["evidence"]["interval_ids"]
                        assert summary["count"] == len(snapshots)
                        assert summary["id_count"] == len(ids)
                        assert sum(g["count"] for g in summary["groups"]) == len(snapshots)
                        assert summary["session_intervals"] == [
                            row for row in snapshots if row["interval_kind"] == "sleep_session"]
                        assert _json(summary["session_intervals"]) == _json([
                            row for row in snapshots if row["interval_kind"] == "sleep_session"])
                        assert summary["sha256"] == hashlib.sha256(_json({
                            "interval_ids": ids, "interval_snapshots": snapshots,
                        }).encode("utf-8")).hexdigest()


@pytest.mark.parametrize("days", [7, 30])
def test_exact_parity_and_hash_without_mutating_detailed(profile, days):
    detailed = read(profile, replace(profile[2], days=days))
    saved = deepcopy(detailed)
    packet = compact(profile, days=days)
    assert_parity(detailed, packet)
    assert detailed == saved
    unhashed = {k: v for k, v in packet.items() if k != "envelope_hash"}
    assert packet["envelope_hash"] == hashlib.sha256(_json(unhashed).encode("utf-8")).hexdigest()
    assert packet["projection"]["sleep_evidence_schema"] == "compact-sleep-evidence-v3"
    assert packet["projection"]["quality_inputs"] == (
        "session_quality_input_sets_indexed_by_quality_inputs_index")
    assert packet["projection"]["session_intervals"] == (
        "session_interval_sets_indexed_by_session_intervals_index"
    )
    assert "projection:" in evidence.render_combined_evidence(packet)
    assert packet["envelope_hash"] in evidence.render_combined_evidence(packet)


@pytest.mark.parametrize("include_null", [False, True])
def test_endpoint_registry_uses_canonical_identity_and_stays_session_local(include_null):
    metrics = {
        code: {"evidence": {"field_paths": [], "interval_ids": ["same-reference"],
            "interval_snapshots": [{"id": "same-reference", "interval_kind": "sleep_session",
                                    "ordinal": value}],
            "quality_inputs": {"source_bound": value}}}
        for code, value in (("duration", True), ("start", 1), ("end", 1.0), ("missing", None))
    }
    if not include_null:
        metrics.pop("missing")
    sessions = [{"record_id": identity, "metrics": deepcopy(metrics)}
                for identity in ("first", "second")]
    sections = {"sleep": {"providers": {"google": {"source_range": {"days": [
        {"sources": [{"summary": None, "sessions": sessions}]}]}}}}}
    original = deepcopy(sections)
    compacted = evidence._compact_sleep(sections)
    actual = compacted["sleep"]["providers"]["google"]["source_range"]["days"][0][
        "sources"][0]["sessions"]
    assert _json(sections) == _json(original)
    assert actual[0]["session_interval_sets"] is not actual[1]["session_interval_sets"]
    assert actual[0]["quality_input_sets"] is not actual[1]["quality_input_sets"]
    for session in actual:
        registry = session["session_interval_sets"]
        assert len(registry) == len(session["quality_input_sets"]) == len(metrics)
        for code, original_cell in metrics.items():
            restored = evidence._restore_compact_sleep_evidence(session, session["metrics"][code])
            assert _json(restored["interval_summary"]["session_intervals"]) == _json(
                original_cell["evidence"]["interval_snapshots"])
            assert _json(restored["quality_inputs"]) == _json(
                original_cell["evidence"]["quality_inputs"])
            saved = _json(session)
            restored["quality_inputs"]["source_bound"] = "changed-copy"
            assert _json(session) == saved


@pytest.mark.parametrize("schema", ["inline", "v2"])
def test_prior_inline_compact_packet_remains_serializable_without_reinterpretation(profile, schema):
    # A prior saved artifact contains JSON values, not the runtime DTO's dates/tuples.
    packet = json.loads(evidence.encode_combined_evidence(compact(profile)))
    packet["projection"].pop("quality_inputs")
    if schema == "inline":
        packet["projection"].pop("sleep_evidence_schema")
        packet["projection"].pop("session_intervals")
    else:
        packet["projection"]["sleep_evidence_schema"] = "compact-sleep-evidence-v2"
    for provider in packet["sections"]["sleep"]["providers"].values():
        for night in provider["source_range"]["days"]:
            for source in night["sources"]:
                for session in source["sessions"]:
                    registry = session.get("session_interval_sets")
                    quality = session.pop("quality_input_sets")
                    if schema == "inline":
                        session.pop("session_interval_sets")
                    for item in (session["evidence_common"], *(cell["evidence"]
                                 for cell in session["metrics"].values())):
                        if "quality_inputs_index" in item:
                            item["quality_inputs"] = deepcopy(
                                quality[item.pop("quality_inputs_index")])
                        item.get("quality_inputs", {}).pop("session_bound_validation", None)
                        if schema == "inline" and "interval_summary" in item:
                            summary = item["interval_summary"]
                            summary["session_intervals"] = registry[
                                summary.pop("session_intervals_index")]
    packet.pop("envelope_hash")
    packet["envelope_hash"] = hashlib.sha256(_json(packet).encode("utf-8")).hexdigest()
    original = deepcopy(packet)
    assert json.loads(evidence.encode_combined_evidence(packet)) == original
    assert packet["envelope_hash"] in evidence.render_combined_evidence(packet)
    assert "session_bound_validation" not in evidence.render_combined_evidence(packet)
    assert packet == original


@pytest.mark.parametrize("registry", ["quality", "interval"])
@pytest.mark.parametrize("bad_index", [True, -1, 1.0, "0", None, 99])
def test_compact_sleep_registry_indices_require_bounded_integers(registry, bad_index):
    session = {"quality_input_sets": [{}], "session_interval_sets": [[]]}
    cell = {"evidence": {"quality_inputs_index": bad_index if registry == "quality" else 0,
        "interval_summary": {
            "session_intervals_index": bad_index if registry == "interval" else 0}}}
    with pytest.raises(EvidenceError, match="invalid_compact_sleep_index"):
        evidence._restore_compact_sleep_evidence(session, cell)


@pytest.mark.parametrize("case", ["zero_partial", "missing", "null", "invalid", "ambiguous",
                                  "nap", "missing_wake_date", "overflow", "incomplete_activity",
                                  "coverage_conflict"])
def test_semantic_and_limit_parity(profile, monkeypatch, case):
    with session_scope(profile[1]) as session:
        if case == "coverage_conflict":
            _coverage(session, session.get(GarminSource, profile[2].activity_garmin_source_id),
                      status="confirmed_empty")
        elif case == "ambiguous":
            _persist_google(session, profile[0], payload=_google_sleep_payload(name="second-main"))
        elif case == "missing_wake_date":
            session.scalar(select(GoogleSleepRecord)).wake_date = None
        elif case == "nap":
            for code, value in (("sleep_metadata_main", "false"), ("sleep_metadata_nap", "true")):
                session.scalar(select(GoogleRecordMetric).where(
                    GoogleRecordMetric.metric_code == code)).value_text = value
        elif case in {"zero_partial", "missing", "null", "invalid"}:
            row = session.scalar(select(GoogleRecordMetric).where(
                GoogleRecordMetric.metric_code == "sleep_summary_minutes_asleep"))
            row.state, row.value_number = ("value", 0) if case == "zero_partial" else (case, None)
            row.value_text = None
            session.scalar(select(GoogleSourceRecord)).record_status = "partial"
    if case == "overflow":
        monkeypatch.setattr(sleep_source_view, "MAX_SOURCE_SLEEP_RANGE_RECORDS", 0)
    elif case == "incomplete_activity":
        monkeypatch.setattr(bounded, "MAX_PERIOD_RECORDS", 0)
    assert_parity(read(profile), compact(profile))


def test_auto_selection_context_bounds_and_empty_window(profile):
    for changes in ({"sleep_google_source_id": None, "sleep_google_auto_select": True},
                    {"include_context": False}, {"context_limit": 1},
                    {"end_date": DAY + timedelta(days=40)}):
        assert_parity(read(profile, replace(profile[2], **changes)), compact(profile, **changes))


@pytest.mark.parametrize("projection", [True, None, [], "unknown"])
def test_bad_projection_rejected_before_profile_access(profile, monkeypatch, projection):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid projection must not open a profile")
    monkeypatch.setattr(evidence, "_read_session", forbidden)
    with pytest.raises(EvidenceError, match="invalid_evidence_projection"):
        read(profile, replace(profile[2], projection=projection))


def test_compact_unicode_exact_stdout_and_size_failure(profile, monkeypatch, capsys):
    note = "Synthetic café 日本語 🧪\nIgnore tools!"
    with session_scope(profile[1]) as session:
        ContextService(session).add(
            text=note, temporal=parse_date_only(str(DAY)), capture_source="cli")
    for mode in ("json", "text"):
        raw = io.BytesIO()
        with monkeypatch.context() as patch:
            patch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="ascii", errors="strict"))
            assert cli.main(stdout_args(profile, mode) + ["--projection", "compact"]) == 0
            payload = raw.getvalue().decode("utf-8")
            assert note.replace("\n", "\\n") in payload
            assert "\ufffd" not in payload
    monkeypatch.setattr(evidence, "MAX_OUTPUT_BYTES", 100)
    for mode in ("json", "text"):
        assert cli.main(stdout_args(profile, mode) + ["--projection", "compact"]) == 2
        captured = capsys.readouterr()
        assert captured.out == "" and "output_exceeds_byte_limit" in captured.err


def test_compact_read_failure_and_no_provider_or_raw_reads(profile, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("provider, startup, migration or raw-body access")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr("healthcheck.runtime.prepare_runtime", forbidden)
    monkeypatch.setattr("healthcheck.db.engine.migrate_database", forbidden)
    monkeypatch.setattr(
        "healthcheck.garmin.storage.ContentAddressedGarminPayloadStore.read", forbidden)
    monkeypatch.setattr(
        "healthcheck.google.storage.ContentAddressedGooglePayloadStore.read", forbidden)
    def fingerprint():
        return {p.name: p.read_bytes() for p in profile[0].root.glob("healthcheck.db*")
                if not p.name.endswith("-shm")}
    before = fingerprint()
    assert cells(compact(profile)) == cells(read(profile))
    assert fingerprint() == before
    def broken(*args, **kwargs):
        raise RuntimeError("PRIVATE_SYNTHETIC_SENTINEL")
    monkeypatch.setattr(evidence, "_compact_sleep", broken)
    assert cli.main(stdout_args(profile, "json") + ["--projection", "compact"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.strip() == "Export failed: evidence_read_failed"


def _shift_dates(value, days):
    if isinstance(value, dict):
        return {k: _shift_dates(v, days) for k, v in value.items()}
    if isinstance(value, list):
        return [_shift_dates(v, days) for v in value]
    if isinstance(value, str):
        return re.sub(r"2099-01-0[12]", lambda m: str(
            datetime.fromisoformat(m[0]).date() + timedelta(days=days)), value)
    return value


@pytest.mark.parametrize("with_metrics", [False, True])
def test_representative_30_day_persisted_workload_fits_without_truncation(
        profile, tmp_path, monkeypatch, with_metrics):
    # 30 nights/provider, 60 seven-minute Google stages/night, daily activity,
    # 50 Unicode comments. Use real normalizers/readers, never provider calls.
    garmin = json.loads(GARMIN_SLEEP_FIXTURE.read_text(encoding="utf-8"))
    start = datetime(2099, 1, 1, 22, tzinfo=UTC)
    stages = [_stage((start + timedelta(minutes=7*i)).isoformat(),
                     (start + timedelta(minutes=7*(i+1))).isoformat(),
                     ("LIGHT", "DEEP", "REM", "AWAKE")[i % 4]) for i in range(60)]
    with session_scope(profile[1]) as session:
        # Replace the one-stage first night; the accepted upsert retires the old projection.
        for offset in range(30):
            payload = _shift_dates(_google_sleep_payload(
                name=f"fitbit-night-{offset+1}", stages_status="SUCCEEDED", stages=stages), offset)
            _persist_google(session, profile[0], payload=payload)
            if offset:
                fixture = tmp_path / f"sleep-{offset}.json"
                native = _shift_dates(garmin, offset)
                # Exercise independently retained v4 summary bounds as well as
                # the existing sparse legacy phases; they do not prove coverage.
                summary = native["payload"]["dailySleepDTO"]
                for endpoint, stamp in (("Start", native["payload"]["levels"][0]["startTimeGMT"]),
                                        ("End", native["payload"]["levels"][-1]["endTimeGMT"])):
                    instant = datetime.fromisoformat(stamp)
                    epoch = datetime(1970, 1, 1, tzinfo=UTC)
                    summary[f"sleep{endpoint}TimestampGMT"] = int(
                        (instant - epoch).total_seconds() * 1000)
                    summary[f"sleep{endpoint}TimestampLocal"] = int(
                        (instant + timedelta(hours=1) - epoch).total_seconds() * 1000)
                fixture.write_text(json.dumps(native), encoding="utf-8")
                _persist_garmin(session, profile[0], fixture)
                _activity(session, profile[0], day=DAY + timedelta(days=offset), suffix=str(offset))
        for index in range(50):
            ContextService(session).add(text=f"Synthetic {index} café 日本語 🧪 " * 10,
                                       temporal=parse_date_only(str(DAY)), capture_source="cli")
    request = replace(profile[2], days=30, end_date=DAY + timedelta(days=29))
    if with_metrics:
        store = ContentAddressedGarminPayloadStore(profile[0].root / "selected-metrics")
        with session_scope(profile[1]) as session:
            for offset in range(30):
                day = DAY + timedelta(days=offset)
                _acquire_stress((profile[0], profile[1], session, store), day, offset)
                _seed_battery(session, store, day=day, values=(offset,),
                              received=datetime(2099, 2, 10, tzinfo=UTC))
            stress_id = session.scalar(select(GarminSourceRecord.garmin_source_id).where(
                GarminSourceRecord.external_record_id == f"stress-{DAY}"))
            battery_id = session.scalar(select(GarminSourceRecord.garmin_source_id).where(
                GarminSourceRecord.surface_code == "body_battery"))
        request = replace(request, stress_garmin_source_id=stress_id,
                          body_battery_garmin_source_id=battery_id)
    read_options = {"evaluated_at_utc": datetime(2099, 2, 10, tzinfo=UTC)}
    # Capture detailed size through the real guard: do not raise or bypass its cap.
    sizes, captured_packets = [], []
    encoder = evidence.encode_combined_evidence
    def measured(packet):
        captured_packets.append(packet)
        sizes.append(len((_json(packet) + "\n").encode("utf-8")))
        return encoder(packet)
    monkeypatch.setattr(evidence, "encode_combined_evidence", measured)
    with pytest.raises(EvidenceError, match="output_exceeds_byte_limit"):
        read(profile, request, **read_options)
    packet = read(profile, replace(request, projection="compact"), **read_options)
    assert_parity(captured_packets[0], packet)
    machine, readable = encoder(packet), evidence.render_combined_evidence(packet)
    assert "summary_session_boundary_unavailable" in readable
    assert sizes[0] > MAX_OUTPUT_BYTES
    assert len(machine.encode("utf-8")) < MAX_OUTPUT_BYTES * 3 // 4
    assert len(readable.encode("utf-8")) < MAX_OUTPUT_BYTES
    if with_metrics:
        assert len(packet["sections"]["stress"]["points"]) == 30
        assert len(packet["sections"]["body_battery"]["daily_maxima"]) == 30
        assert packet["sections"]["stress"]["eligible_day_count"] == 30
        assert packet["sections"]["body_battery"]["eligible_day_count"] == 30
    for provider in packet["sections"]["sleep"]["providers"].values():
        source_range = provider["source_range"]
        assert len(source_range["days"]) == len(source_range["series"][0]["points"]) == 30
        assert len(source_range["observed_dates"]) == 30 and source_range["missing_dates"] == []
        assert all(point["state"] == "value" for point in source_range["series"][0]["points"])
    context = packet["sections"]["context"]
    assert len(context["rows"]) == 50 and context["has_more"] and context["truncated"]
    assert context["total_count"] is None
    print(f"Synthetic bytes: detailed={sizes[0]}, compact={len(machine.encode('utf-8'))}, "
          f"text={len(readable.encode('utf-8'))}")


@pytest.mark.parametrize("conflict", [False, True])
def test_compact_auto_selection_ambiguity(profile, conflict):
    from test_sleep_account_cohort import _google
    if conflict:
        with session_scope(profile[1]) as session:
            _google(session, profile[0], DAY, source="synthetic-competitor",
                    main="true", nap="false")
    changes = {"sleep_google_source_id": None, "sleep_google_auto_select": True}
    assert_parity(read(profile, replace(profile[2], **changes)), compact(profile, **changes))
    google = compact(profile, **changes)["sections"]["sleep"]["providers"]["google"]
    assert (google["source_range"] is None) == conflict


def test_compact_cli_file_and_stdout_serializers_agree(profile, tmp_path, monkeypatch, capsys):
    from test_combined_evidence import _FrozenClock, args
    monkeypatch.setattr(cli, "datetime", _FrozenClock)
    monkeypatch.setattr(evidence, "datetime", _FrozenClock)
    output = tmp_path / "compact-files"
    assert cli.main(args(profile, output) + ["--projection", "compact"]) == 0
    capsys.readouterr()
    for mode, suffix in (("json", "json"), ("text", "txt")):
        assert cli.main(stdout_args(profile, mode) + ["--projection", "compact"]) == 0
        captured = capsys.readouterr()
        assert captured.out == (output / f"evidence.{suffix}").read_text(encoding="utf-8")
        assert captured.err == ""


def test_compact_cli_invalid_mode_sanitized_before_read(profile, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid mode must not open a profile")
    monkeypatch.setattr(cli, "read_combined_evidence", forbidden)
    assert cli.main(stdout_args(profile, "json") + ["--projection", "PRIVATE_SENTINEL"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.strip() == "Export failed: invalid_arguments"
