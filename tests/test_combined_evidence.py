"""Synthetic production-entry regressions for one Sleep + Activity + Context snapshot."""

from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from healthcheck import activity_evidence, chat_evidence, sleep_evidence
from healthcheck import combined_evidence as evidence
from healthcheck import export_combined_evidence as cli
from healthcheck.analytics import period_summary_read as bounded
from healthcheck.analytics import sleep_source_view
from healthcheck.chat_evidence import EvidenceError
from healthcheck.combined_evidence import CombinedEvidenceRequest
from healthcheck.context import ContextService
from healthcheck.db.engine import session_scope
from healthcheck.db.models import GarminRecordMetric, GarminSource, GarminSourceRecord
from test_period_summary import _activity, _coverage
from test_sleep_evidence import CLOCK, DAY
from test_sleep_evidence import profile as _sleep_profile

sleep_profile = _sleep_profile


@pytest.fixture
def profile(sleep_profile):
    paths, engine, garmin_id, google_id, current = sleep_profile
    with session_scope(engine) as session:
        _activity(session, paths, day=DAY, distance=0)
        _activity(session, paths, day=DAY, kind="tennis", duration=25)
        activity_id = session.scalar(select(GarminSourceRecord.garmin_source_id).where(
            GarminSourceRecord.activity_type == "cycling"))
    request = CombinedEvidenceRequest(DAY, 7, activity_id, garmin_id, google_id)
    return paths, engine, request, current


def read(profile, request=None, **kwargs):
    return evidence.read_combined_evidence(
        profile=profile[0].root, profile_kind=kwargs.pop("profile_kind", "synthetic"),
        request=request or profile[2], evaluated_at_utc=kwargs.pop("evaluated_at_utc", CLOCK),
        evaluation_local_date=kwargs.pop("evaluation_local_date", CLOCK.date()), **kwargs)


def cells(packet):
    return packet["sections"]["activity"]["providers"]["garmin"]["metrics"]


def args(profile, output):
    request = profile[2]
    return ["--profile", str(profile[0].root), "--profile-kind", "synthetic",
            "--end-date", str(DAY), "--days", "7",
            "--activity-garmin-source-id", request.activity_garmin_source_id,
            "--sleep-garmin-source-id", request.sleep_garmin_source_id,
            "--sleep-google-source-id", request.sleep_google_source_id,
            "--evaluation-local-date", str(CLOCK.date()), "--output-dir", str(output)]


@pytest.mark.parametrize("days", [7, 30])
@pytest.mark.parametrize("selection", ["garmin", "google", "both"])
def test_existing_public_service_equivalence_and_exact_sources(profile, days, selection):
    request = replace(profile[2], days=days,
                      sleep_garmin_source_id=None if selection == "google" else
                      profile[2].sleep_garmin_source_id,
                      sleep_google_source_id=None if selection == "garmin" else
                      profile[2].sleep_google_source_id)
    packet = read(profile, request)
    sleep_request, activity_request = request.domain_requests()
    call = dict(profile=profile[0].root, profile_kind="synthetic",
                evaluated_at_utc=CLOCK, evaluation_local_date=CLOCK.date())
    sleep = sleep_evidence.read_sleep_evidence(**call, request=sleep_request)
    activity = activity_evidence.read_activity_evidence(**call, request=activity_request)
    context = sleep["sections"].pop("context")
    assert packet["sections"]["sleep"]["providers"] == sleep["sections"]
    assert packet["sections"]["activity"]["providers"] == activity["sections"]
    assert packet["sections"]["context"] == {
        **context, "relationship": "local_date_window_cooccurrence_only"}
    for key in ("reader_contract", "metric_contract", "metric_rule_version", "limits"):
        assert packet["sections"]["sleep"][key] == sleep[key]
    assert packet["sections"]["activity"]["limits"] == activity["limits"]
    assert packet["request"]["effective_range"] == packet["request"]["requested_range"]
    assert packet["request"]["sources"] == {
        "sleep": sleep["request"]["sources"], "activity": activity["request"]["sources"]}
    assert packet["request"]["days"] == days
    assert cells(packet)["cycling_distance_meters"]["aggregation"]["value"] == 0
    assert cells(packet)["cycling_distance_meters"]["availability_counts"]["zero"] == 1


def test_context_once_same_session_and_no_public_reader_snapshots(profile, monkeypatch):
    original = evidence._read_session
    sessions, context_calls = [], []
    @contextmanager
    def inspected(root):
        with original(root) as session:
            sessions.append(session)
            yield session
    monkeypatch.setattr(evidence, "_read_session", inspected)
    original_context = ContextService.list
    def context(self, **kwargs):
        context_calls.append(self.session)
        return original_context(self, **kwargs)
    monkeypatch.setattr(ContextService, "list", context)
    def forbidden(*args, **kwargs):
        pytest.fail("independent domain snapshot must not be opened")
    monkeypatch.setattr(sleep_evidence, "_read_session", forbidden)
    monkeypatch.setattr(activity_evidence, "_read_session", forbidden)
    packet = read(profile)
    assert len(sessions) == 1 and context_calls == sessions
    assert "context" not in packet["sections"]["sleep"]["providers"]
    assert "context" not in packet["sections"]["activity"]["providers"]


def test_context_revision_overlap_precision_truncation_and_opt_out(profile, monkeypatch):
    packet = read(profile)
    context = packet["sections"]["context"]
    current = next(r for r in context["rows"] if r["event_id"] == profile[-1].event_id)
    assert current["revision_id"] == profile[-1].revision_id
    assert current["revision_number"] == 2 and current["is_current"] is True
    assert current["temporal"]["start_precision"] == "date"
    assert current["temporal"]["start_at_utc"] is None
    assert any(r["original_text"] == "Overlap" for r in context["rows"])
    assert any(r["temporal"]["start_utc_offset_minutes"] == 180 for r in context["rows"])
    limited = read(profile, replace(profile[2], context_limit=1))
    assert limited["sections"]["context"]["total_count"] is None
    assert limited["sections"]["context"]["truncated"] is True
    assert cells(limited) == cells(packet)
    assert limited["sections"]["sleep"] == packet["sections"]["sleep"] | {
        "limits": limited["sections"]["sleep"]["limits"]}
    def forbidden(*args, **kwargs):
        pytest.fail("Context opt out must avoid read")
    monkeypatch.setattr(ContextService, "list", forbidden)
    assert "context" not in read(profile, replace(profile[2], include_context=False))["sections"]


def test_coherent_sleep_activity_context_during_concurrent_correction(profile, monkeypatch):
    original = sleep_evidence._assemble
    changed = False
    def concurrent(*args, **kwargs):
        nonlocal changed
        result = original(*args, **kwargs)
        if not changed:
            changed = True
            with session_scope(profile[1]) as writer:
                metric = writer.scalar(select(GarminRecordMetric).where(
                    GarminRecordMetric.metric_code == "distance_meters"))
                metric.value_number = 22
                ContextService(writer).revise(
                    event_id=profile[-1].event_id, text="Concurrent", capture_source="cli")
        return result
    monkeypatch.setattr(sleep_evidence, "_assemble", concurrent)
    before, after = read(profile), read(profile)
    assert cells(before)["cycling_distance_meters"]["aggregation"]["value"] == 0
    assert cells(after)["cycling_distance_meters"]["aggregation"]["value"] == 22
    assert any(r["revision_id"] == profile[-1].revision_id
               for r in before["sections"]["context"]["rows"])
    assert any(r["original_text"] == "Concurrent" for r in after["sections"]["context"]["rows"])


@pytest.mark.parametrize("field", [
    "activity_garmin_source_id", "sleep_garmin_source_id", "sleep_google_source_id"])
@pytest.mark.parametrize("problem", ["absent", "cross_provider", "wrong_provider"])
def test_all_selections_validated_before_either_reader(profile, monkeypatch, field, problem):
    if problem == "absent":
        identity = "nonexistent"
    elif problem == "cross_provider":
        identity = (profile[2].sleep_garmin_source_id if field == "sleep_google_source_id"
                    else profile[2].sleep_google_source_id)
    else:
        identity = getattr(profile[2], field)
        model = sleep_evidence.PROVIDERS["google" if field == "sleep_google_source_id"
                                        else "garmin"][0]
        with session_scope(profile[1]) as session:
            original = session.get(model, identity)
            fields = dict(provider_id=original.provider_id,
                          acquisition_source_id=original.acquisition_source_id,
                          source_kind=original.source_kind, provider_code="other_provider",
                          source_instance_id="synthetic-wrong-provider")
            if field == "sleep_google_source_id":
                fields["source_contract_version"] = original.source_contract_version
            wrong = model(**fields)
            session.add(wrong)
            session.flush()
            identity = wrong.id
    def forbidden(*args, **kwargs):
        pytest.fail("domain or Context reader ran before full source validation")
    monkeypatch.setattr(sleep_evidence, "_assemble", forbidden)
    monkeypatch.setattr(activity_evidence, "_assemble", forbidden)
    with pytest.raises(EvidenceError, match="selected_source_(unavailable|wrong_provider)"):
        read(profile, replace(profile[2], **{field: identity}))


@pytest.mark.parametrize("changes", [
    {"days": True}, {"days": 8}, {"end_date": date.min}, {"end_date": date.max},
    {"end_date": CLOCK}, {"include_context": 1}, {"context_limit": 0},
    {"context_limit": 101}, {"context_limit": True}, {"activity_garmin_source_id": ""},
    {"sleep_garmin_source_id": "x" * 37},
    {"sleep_garmin_source_id": None, "sleep_google_source_id": None},
])
def test_invalid_request_before_profile_access(tmp_path, monkeypatch, changes):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid request opened a profile")
    monkeypatch.setattr(evidence, "_read_session", forbidden)
    request = replace(CombinedEvidenceRequest(DAY, 7, "activity", "sleep"), **changes)
    with pytest.raises(EvidenceError):
        evidence.read_combined_evidence(
            profile=tmp_path / "absent", profile_kind="synthetic", request=request,
            evaluated_at_utc=CLOCK, evaluation_local_date=DAY)


@pytest.mark.parametrize("changes", [
    {"profile_kind": ["synthetic"]}, {"profile_kind": "unknown"},
    {"evaluated_at_utc": datetime(2099, 1, 1)}, {"evaluation_local_date": CLOCK},
])
def test_invalid_caller_before_profile_access(profile, monkeypatch, changes):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid caller opened a profile")
    monkeypatch.setattr(evidence, "_read_session", forbidden)
    with pytest.raises(EvidenceError):
        read(profile, **changes)


def test_coverage_conflict_and_independent_domain_limits(profile, monkeypatch):
    with session_scope(profile[1]) as session:
        source = session.get(GarminSource, profile[2].activity_garmin_source_id)
        _coverage(session, source, status="confirmed_empty")
    packet = read(profile)
    coverage = cells(packet)["activity_session_count"]["coverage"]
    assert coverage["state"] == "contradictory"
    assert str(DAY) in coverage["observed_on_confirmed_empty_dates"]
    monkeypatch.setattr(bounded, "MAX_PERIOD_RECORDS", 0)
    limited = read(profile)
    assert all(c["search"]["complete"] is False and c["aggregation"]["value"] is None
               for c in cells(limited).values())
    assert limited["sections"]["sleep"]["providers"] == packet["sections"]["sleep"]["providers"]
    assert limited["sections"]["context"] == packet["sections"]["context"]


def test_sleep_overflow_preserved_without_truncating_activity_or_context(profile, monkeypatch):
    before = read(profile)
    monkeypatch.setattr(sleep_source_view, "MAX_SOURCE_SLEEP_RANGE_RECORDS", 0)
    packet = read(profile)
    for source in packet["sections"]["sleep"]["providers"].values():
        result = source["source_range"]
        assert result["state"] == "read_limit_exceeded"
        assert result["days"] == result["series"] == []
        assert result["observed_dates"] is result["missing_dates"] is None
        assert source["acquisition_coverage"]["completeness"] is None
    assert cells(packet) == cells(before)
    assert packet["sections"]["context"] == before["sections"]["context"]
    assert '"state":"read_limit_exceeded"' in evidence.render_combined_evidence(packet)


def test_existing_sources_empty_window_remains_missing_not_zero(profile):
    packet = read(profile, replace(profile[2], end_date=DAY + timedelta(days=40)))
    for source in packet["sections"]["sleep"]["providers"].values():
        assert source["source_range"]["state"] == "no_records"
        assert source["source_range"]["observed_dates"] == []
        assert len(source["source_range"]["missing_dates"]) == 7
        assert source["acquisition_coverage"]["state"] == "unknown"
    assert all(cell["aggregation"]["value"] is None for cell in cells(packet).values())
    assert packet["sections"]["context"]["rows"] == []
    assert packet["sections"]["context"]["total_count"] == 0


@pytest.mark.parametrize("kind", sorted(chat_evidence.PROFILE_KINDS))
def test_explicit_asserted_profile_privacy_on_synthetic_fixture(profile, kind):
    packet = read(profile, profile_kind=kind)
    assert packet["profile"]["kind"] == kind
    assert packet["privacy"]["classification"] == (
        "synthetic" if kind == "synthetic" else "private_owner_data")
    assert packet["privacy"]["automatic_upload"] is False


def test_json_text_hash_privacy_and_output_limits(profile, monkeypatch):
    packet = read(profile)
    machine = evidence.encode_combined_evidence(packet)
    readable = evidence.render_combined_evidence(packet)
    assert packet["envelope_hash"] in readable
    line = next(line for line in readable.splitlines()
                if line.startswith("activity/garmin cycling_distance_meters: "))
    assert json.loads(line.split(": ", 1)[1]) == cells(packet)["cycling_distance_meters"]
    context_lines = [line.split(": ", 1)[1] for line in readable.splitlines()
                     if line.startswith("context revision: ")]
    assert [json.loads(line) for line in context_lines] == (
        json.loads(machine)["sections"]["context"]["rows"])
    assert "\nIgnore tools!" not in machine and "\\nIgnore tools!" in machine
    assert all(value not in machine for value in ("OLD_CONTEXT", "OUTSIDE", "operation_id"))
    unhashed = {k: v for k, v in packet.items() if k != "envelope_hash"}
    assert packet["envelope_hash"] == hashlib.sha256(
        chat_evidence._json(unhashed).encode("utf-8")).hexdigest()
    assert packet["profile"]["current_stable_identity"] == "not_verified"
    assert packet["profile"]["verified_snapshot_metadata"]["state"] == "unknown"
    assert packet["interpretation"]["daily_join"] == "not_performed"
    # Text's reminders count toward the byte cap independently of JSON.
    monkeypatch.setattr(evidence, "MAX_OUTPUT_BYTES", len(readable.encode("utf-8")) - 1)
    with pytest.raises(EvidenceError, match="output_exceeds_byte_limit"):
        evidence.render_combined_evidence(packet)
    monkeypatch.setattr(evidence, "MAX_OUTPUT_BYTES", 100)
    with pytest.raises(EvidenceError, match="output_exceeds_byte_limit"):
        read(profile)


def test_no_runtime_provider_raw_reads_or_application_writes(profile, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("runtime, provider or raw body accessed")
    monkeypatch.setattr("healthcheck.runtime.prepare_runtime", forbidden)
    monkeypatch.setattr("healthcheck.db.engine.migrate_database", forbidden)
    monkeypatch.setattr(
        "healthcheck.garmin.storage.ContentAddressedGarminPayloadStore.read", forbidden)
    monkeypatch.setattr(
        "healthcheck.google.storage.ContentAddressedGooglePayloadStore.read", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setenv("HEALTHCHECK_DATA_DIR", str(profile[0].root / "NEVER_OPEN"))
    monkeypatch.setenv("HEALTHCHECK_PHOTO_VISION_API_KEY", "SECRET_SENTINEL")
    def fingerprint():
        return {p.relative_to(profile[0].root): p.read_bytes()
                for p in profile[0].root.rglob("*") if p.is_file() and not p.name.endswith("-shm")}
    before = fingerprint()
    assert "SECRET_SENTINEL" not in evidence.encode_combined_evidence(read(profile))
    assert fingerprint() == before
    with evidence._read_session(profile[0].root) as session:
        for sql in ("UPDATE garmin_sources SET device_code='forbidden'",
                    "CREATE TABLE forbidden(id INTEGER)", "PRAGMA busy_timeout=1"):
            with pytest.raises(DatabaseError):
                session.execute(text(sql))


@pytest.mark.parametrize("guard,value", [("MAX_SQL_STEPS", 0), ("READ_TIMEOUT_SECONDS", -1)])
def test_outer_sql_guards_retained(profile, monkeypatch, guard, value):
    monkeypatch.setattr(chat_evidence, guard, value)
    def costly(*args, **kwargs):
        args[0].execute(text(
            "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<10000) "
            "SELECT sum(x) FROM n")).scalar_one()
    monkeypatch.setattr(activity_evidence, "_assemble", costly)
    with pytest.raises(EvidenceError, match="^(evidence_read_failed|profile_schema_unavailable)$"):
        read(profile)


def test_cli_success_frozen_files_no_overwrite_and_no_console_health(profile, tmp_path, capsys):
    output = tmp_path / "export"
    assert cli.main(args(profile, output)) == 0
    packet = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
    assert (output / "evidence.txt").read_text(encoding="utf-8") == (
        evidence.render_combined_evidence(packet))
    assert set(packet["sections"]) == {"sleep", "activity", "context"}
    original = (output / "evidence.json").read_bytes()
    assert cli.main(args(profile, output)) == 2
    assert (output / "evidence.json").read_bytes() == original
    captured = capsys.readouterr()
    assert "Corrected synthetic note" not in captured.out + captured.err


@pytest.mark.parametrize("location", ["git_dir", "git_file", "workspace", "profile"])
def test_cli_unsafe_output_rejected_before_read(profile, tmp_path, monkeypatch, location):
    root = tmp_path / "unsafe"
    root.mkdir()
    extra = []
    if location == "git_dir":
        (root / ".git").mkdir()
    elif location == "git_file":
        (root / ".git").write_text("gitdir: synthetic")
    elif location == "workspace":
        extra = ["--agent-workspace-root", str(root)]
    else:
        root = profile[0].root
    output = root / "export"
    def forbidden(*args, **kwargs):
        pytest.fail("unsafe output must fail before read")
    monkeypatch.setattr(cli, "read_combined_evidence", forbidden)
    assert cli.main(args(profile, output) + extra) == 2
    assert not output.exists()


@pytest.mark.parametrize("state", ["missing_profile", "missing_db", "old_schema", "unmigrated"])
def test_cli_missing_database_never_creates_repairs_or_exports(profile, tmp_path, state, capsys):
    root = tmp_path / "target"
    if state != "missing_profile":
        root.mkdir()
    if state in {"old_schema", "unmigrated"}:
        with sqlite3.connect(root / "healthcheck.db") as connection:
            if state == "old_schema":
                connection.execute("CREATE TABLE alembic_version(version_num TEXT)")
                connection.execute("INSERT INTO alembic_version VALUES ('old_synthetic_schema')")
    before = {p.name: p.read_bytes() for p in root.glob("*")} if root.exists() else {}
    output = tmp_path / "export"
    argv = args(profile, output)
    argv[1] = str(root)
    assert cli.main(argv) == 2
    assert not output.exists()
    assert {p.name: p.read_bytes() for p in root.glob("*")} == before
    assert root.exists() is (state != "missing_profile")
    captured = capsys.readouterr()
    assert str(root) not in captured.out + captured.err


def test_module_cli_actual_process(profile, tmp_path):
    output = tmp_path / "subprocess"
    result = subprocess.run([sys.executable, "-m", "healthcheck.export_combined_evidence",
                             *args(profile, output), "--no-include-context"],
                            capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr
    packet = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
    assert set(packet["sections"]) == {"sleep", "activity"}
    assert packet["request"]["include_context"] is False
