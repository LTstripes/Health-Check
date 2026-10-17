"""Synthetic production-entry regressions for one Sleep + Activity + Context snapshot."""

from __future__ import annotations

import hashlib
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

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
from healthcheck.context import ContextService, parse_date_only
from healthcheck.db.engine import session_scope
from healthcheck.db.models import GarminRecordMetric, GarminSource, GarminSourceRecord
from healthcheck.garmin.normalization import normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from test_period_summary import ACTIVITY as _ACTIVITY_FIXTURE
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


def _common_args(profile):
    request = profile[2]
    return ["--profile", str(profile[0].root), "--profile-kind", "synthetic",
            "--end-date", str(DAY), "--days", "7",
            "--activity-garmin-source-id", request.activity_garmin_source_id,
            "--sleep-garmin-source-id", request.sleep_garmin_source_id,
            "--sleep-google-source-id", request.sleep_google_source_id,
            "--evaluation-local-date", str(CLOCK.date())]


def args(profile, output):
    return [*_common_args(profile), "--output-dir", str(output)]


def stdout_args(profile, output_format):
    return [*_common_args(profile), "--stdout", output_format]


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


@pytest.mark.parametrize("conflict", [False, True])
def test_combined_google_auto_is_same_sleep_packet_and_renders(profile, conflict):
    if conflict:
        from test_sleep_account_cohort import _google
        with session_scope(profile[1]) as session:
            _google(session, profile[0], DAY, source="synthetic-competitor",
                    main="true", nap="false")
    request = replace(profile[2], sleep_google_source_id=None, sleep_google_auto_select=True)
    packet = read(profile, request)
    standalone = sleep_evidence.read_sleep_evidence(
        profile=profile[0].root, profile_kind="synthetic", request=request.domain_requests()[0],
        evaluated_at_utc=CLOCK, evaluation_local_date=CLOCK.date())
    assert packet["sections"]["sleep"]["providers"]["google"] == standalone["sections"]["google"]
    assert packet["sections"]["activity"] == read(profile)["sections"]["activity"]
    readable = evidence.render_combined_evidence(packet)
    assert ("selection_required" if conflict else "unique_eligible_source") in readable


def test_combined_cli_google_provider_selection_without_technical_id(profile, tmp_path):
    output = tmp_path.parent / "auto-combined-output"
    argv = args(profile, output)
    index = argv.index("--sleep-google-source-id")
    del argv[index:index + 2]
    argv.append("--sleep-google-auto-select")
    assert cli.main(argv) == 0
    packet = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
    assert packet["sections"]["sleep"]["providers"]["google"]["selected_source_id"] == (
        profile[2].sleep_google_source_id)


class _FrozenClock(datetime):
    """Aware clock frozen for one CLI invocation, as a real datetime subclass."""

    @classmethod
    def now(cls, tz=None):
        return cls(2099, 1, 10, 12, tzinfo=UTC)


def _add_context(profile, text):
    with session_scope(profile[1]) as session:
        ContextService(session).add(
            text=text, temporal=parse_date_only(DAY.isoformat()), capture_source="cli")


def test_cli_stdout_json_and_text_match_file_mode_with_frozen_clock(
        profile, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "datetime", _FrozenClock)
    monkeypatch.setattr(evidence, "datetime", _FrozenClock)
    output = tmp_path / "frozen-files"
    assert cli.main(args(profile, output)) == 0
    capsys.readouterr()
    machine = (output / "evidence.json").read_text(encoding="utf-8")
    readable = (output / "evidence.txt").read_text(encoding="utf-8")

    assert cli.main(stdout_args(profile, "json")) == 0
    captured = capsys.readouterr()
    assert captured.out == machine and captured.err == ""
    packet = json.loads(captured.out)
    assert packet["envelope_hash"] in readable

    assert cli.main(stdout_args(profile, "text")) == 0
    captured = capsys.readouterr()
    assert captured.out == readable and captured.err == ""

    unhashed = {key: value for key, value in packet.items() if key != "envelope_hash"}
    assert packet["envelope_hash"] == hashlib.sha256(
        chat_evidence._json(unhashed).encode("utf-8")).hexdigest()


def test_cli_stdout_creates_no_files_or_directories(profile, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("stdout mode must not create directories or write export files")
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    before = sorted(entry.name for entry in tmp_path.iterdir())
    for output_format in ("json", "text"):
        assert cli.main(stdout_args(profile, output_format)) == 0
    assert sorted(entry.name for entry in tmp_path.iterdir()) == before


@pytest.mark.parametrize("state", [
    "missing_profile", "profile_is_file", "missing_db", "old_schema", "unmigrated"])
def test_cli_stdout_missing_or_unmigrated_database_emits_no_payload(
        profile, tmp_path, capsys, state):
    root = tmp_path / "target"
    if state == "profile_is_file":
        root.write_text("not a directory", encoding="utf-8")
    elif state != "missing_profile":
        root.mkdir()
    if state in {"old_schema", "unmigrated"}:
        with sqlite3.connect(root / "healthcheck.db") as connection:
            if state == "old_schema":
                connection.execute("CREATE TABLE alembic_version(version_num TEXT)")
                connection.execute("INSERT INTO alembic_version VALUES ('old_synthetic_schema')")
    argv = stdout_args(profile, "json")
    argv[1] = str(root)
    assert cli.main(argv) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert str(root) not in captured.err


def test_cli_stdout_oversize_serializers_emit_no_payload(profile, monkeypatch, capsys):
    packet = read(profile)
    readable = evidence.render_combined_evidence(packet)
    monkeypatch.setattr(cli, "read_combined_evidence", lambda **kwargs: packet)
    monkeypatch.setattr(evidence, "MAX_OUTPUT_BYTES", 100)
    assert cli.main(stdout_args(profile, "json")) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "Export failed: output_exceeds_byte_limit"
    monkeypatch.setattr(evidence, "MAX_OUTPUT_BYTES", len(readable.encode("utf-8")) - 1)
    assert cli.main(stdout_args(profile, "text")) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "Export failed: output_exceeds_byte_limit"


def test_cli_stdout_unexpected_reader_and_serializer_errors_emit_no_payload(
        profile, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise RuntimeError("synthetic-private-payload")
    reader = cli.read_combined_evidence
    monkeypatch.setattr(cli, "read_combined_evidence", boom)
    assert cli.main(stdout_args(profile, "json")) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "Export failed: output_or_profile_unavailable"
    assert "synthetic-private-payload" not in captured.err
    monkeypatch.setattr(cli, "read_combined_evidence", reader)
    monkeypatch.setattr(cli, "render_combined_evidence", boom)
    assert cli.main(stdout_args(profile, "text")) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "Export failed: output_or_profile_unavailable"
    assert "synthetic-private-payload" not in captured.err


def test_cli_destination_required_keeps_file_mode_argparse_exit(profile, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("destination validation must precede the reader")
    monkeypatch.setattr(cli, "read_combined_evidence", forbidden)
    with pytest.raises(SystemExit) as excinfo:
        cli.main(_common_args(profile))
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""


@pytest.mark.parametrize("order", ["output_first", "stdout_first"])
def test_cli_stdout_conflicting_destinations_sanitized_before_read(
        profile, monkeypatch, capsys, order):
    def forbidden(*args, **kwargs):
        pytest.fail("destination validation must precede the reader")
    monkeypatch.setattr(cli, "read_combined_evidence", forbidden)
    destination = ["--output-dir", "unused", "--stdout", "json"]
    if order == "stdout_first":
        destination = ["--stdout", "json", "--output-dir", "unused"]
    assert cli.main([*_common_args(profile), *destination]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "Export failed: invalid_arguments"


_SENTINEL = "SYNTHETIC_PRIVATE_SENTINEL"


def _without(argv, flag):
    argv = list(argv)
    index = argv.index(flag)
    del argv[index:index + 2]
    return argv


def _with_value(argv, flag, value):
    argv = list(argv)
    argv[argv.index(flag) + 1] = value
    return argv


def _abbreviated_stdout(argv, abbreviation):
    argv = list(argv)
    argv[argv.index("--stdout")] = abbreviation
    return argv


def _equals_stdout(argv, abbreviation, value=None):
    argv = list(argv)
    index = argv.index("--stdout")
    argv[index:index + 2] = [f"{abbreviation}={argv[index + 1] if value is None else value}"]
    return argv


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda base: _without(base, "--profile"), id="missing_profile"),
    pytest.param(lambda base: _without(base, "--profile-kind"), id="missing_profile_kind"),
    pytest.param(lambda base: _with_value(base, "--profile-kind", _SENTINEL),
                 id="invalid_profile_kind"),
    pytest.param(lambda base: _with_value(base, "--end-date", _SENTINEL), id="malformed_end_date"),
    pytest.param(lambda base: _with_value(base, "--evaluation-local-date", _SENTINEL),
                 id="malformed_evaluation_local_date"),
    pytest.param(lambda base: _with_value(base, "--days", _SENTINEL), id="malformed_days"),
    pytest.param(lambda base: [*base, "--context-limit", _SENTINEL],
                 id="malformed_context_limit"),
    pytest.param(lambda base: [*base, "--stdout"], id="stdout_missing_value"),
    pytest.param(lambda base: [*base, "--stdout=" + _SENTINEL], id="stdout_invalid_choice"),
    pytest.param(lambda base: _with_value(_abbreviated_stdout(base, "--st"),
                                          "--profile-kind", _SENTINEL),
                 id="stdout_shortest_abbreviation_invalid_profile_kind"),
    pytest.param(lambda base: _with_value(_abbreviated_stdout(base, "--std"),
                                          "--profile-kind", _SENTINEL),
                 id="stdout_abbreviation_invalid_profile_kind"),
    pytest.param(lambda base: _with_value(_abbreviated_stdout(base, "--stdou"),
                                          "--profile-kind", _SENTINEL),
                 id="stdout_longer_abbreviation_invalid_profile_kind"),
    pytest.param(lambda base: _with_value(_equals_stdout(base, "--st"),
                                          "--profile-kind", _SENTINEL),
                 id="stdout_abbreviation_equals_invalid_profile_kind"),
    pytest.param(lambda base: _equals_stdout(base, "--stdo", _SENTINEL),
                 id="stdout_abbreviation_equals_invalid_choice"),
])
def test_cli_stdout_malformed_arguments_sanitized_before_read(
        profile, monkeypatch, capsys, mutate):
    def forbidden(*args, **kwargs):
        pytest.fail("argument parsing must precede the reader")
    monkeypatch.setattr(cli, "read_combined_evidence", forbidden)
    assert cli.main(mutate(stdout_args(profile, "json"))) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "Export failed: invalid_arguments"
    assert _SENTINEL not in captured.err


@pytest.mark.parametrize("destination", [
    ["--st", "json"], ["--std", "json"], ["--stdo", "json"], ["--stdou", "json"],
    ["--stdout", "json"], ["--st=json"], ["--stdou=json"],
])
def test_cli_stdout_abbreviations_reach_valid_stdout_path(
        profile, monkeypatch, capsys, destination):
    packet = read(profile)
    calls = []
    def reader(**kwargs):
        calls.append(kwargs)
        return packet
    monkeypatch.setattr(cli, "read_combined_evidence", reader)
    assert cli.main([*_common_args(profile), *destination]) == 0
    captured = capsys.readouterr()
    assert captured.out == evidence.encode_combined_evidence(packet)
    assert captured.err == ""
    assert len(calls) == 1


def test_cli_help_still_prints_usage_to_stdout(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("usage:")
    assert captured.err == ""


def test_module_cli_stdout_subprocess_preserves_non_ascii_context(profile):
    note = "synthetic caf\u00e9 \u2603 \u65e5\u672c\u8a9e \U0001F600\U0001F9EA"
    _add_context(profile, note)
    result = subprocess.run(
        [sys.executable, "-m", "healthcheck.export_combined_evidence",
         *stdout_args(profile, "json")],
        capture_output=True, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False, timeout=30)
    assert result.returncode == 0, result.stderr
    decoded = result.stdout.decode("utf-8")
    assert "\ufffd" not in decoded
    rows = json.loads(decoded)["sections"]["context"]["rows"]
    assert any(row["original_text"] == note for row in rows)


@pytest.mark.parametrize("output_format", ["json", "text"])
def test_cli_stdout_limited_console_keeps_exact_utf8(profile, monkeypatch, output_format):
    note = "synthetic caf\u00e9 \u2603 \U0001F600"
    _add_context(profile, note)
    raw = io.BytesIO()
    limited = io.TextIOWrapper(raw, encoding="ascii", errors="strict", newline="")
    monkeypatch.setattr(sys, "stdout", limited)
    assert cli.main(stdout_args(profile, output_format)) == 0
    payload = raw.getvalue().decode("utf-8")
    assert note in payload
    assert "\ufffd" not in payload
    if output_format == "json":
        rows = json.loads(payload)["sections"]["context"]["rows"]
        assert any(row["original_text"] == note for row in rows)


def temporal(packet):
    return packet["sections"]["activity"]["temporal_evidence"]


def session_for(packet, activity_type=None, external_record_id=None):
    for item in temporal(packet)["sessions"]:
        if activity_type is not None and item["activity_type"] == activity_type:
            return item
        if external_record_id is not None and item["external_record_id"] == external_record_id:
            return item
    raise AssertionError("projected session not found")


_TEMPORAL_KEYS = ("startTimeGMT", "startTimeLocal", "startTimeUTC", "startTime", "timestamp",
                  "time", "timeZoneId", "sourceUtcOffsetMinutes", "calendarDate", "date")


def _persist_temporal_activity(session, paths, *, activity_id, fields, kind="cycling", drop=()):
    """Persist one activity through the real normalizer with chosen temporal fields."""
    fixture = json.loads(_ACTIVITY_FIXTURE.read_text(encoding="utf-8"))
    template = fixture["payload"]["activities"][0]
    activity = dict(template, activityId=activity_id, activityType={"typeKey": kind})
    for key in (*_TEMPORAL_KEYS, *drop):
        activity.pop(key, None)
    activity.update(fields)
    fixture["payload"]["activities"] = [activity]
    return GarminPersistenceRepository(
        session, payload_store=ContentAddressedGarminPayloadStore(paths.root / "garmin-artifacts")
    ).persist_result(normalize_garmin_payload(fixture), payload=json.dumps(fixture).encode())


def test_activity_temporal_presence_and_standalone_reader_unchanged(profile):
    packet = read(profile)
    section = temporal(packet)
    assert section["contract_version"] == "health-chat-activity-temporal-evidence-v1"
    assert section["state"] == "complete" and section["reason"] is None
    assert section["date_basis"] == "persisted_source_local_date"
    assert section["window"] == {
        "start_date": str(DAY - timedelta(days=6)), "end_date": str(DAY),
        "precision": "inclusive_local_date"}
    assert section["source"]["source_id"] == profile[2].activity_garmin_source_id
    assert section["limits"] == {"candidate_records_per_source_surface": 4096,
                                 "projected_sessions": 200}
    assert section["candidate_count"] == 2 and section["current_session_count"] == 2
    assert all(item["end"] == {
        "state": "not_persisted_in_activity_contract",
        "reason": "no_typed_activity_end_in_this_slice", "eligible": False,
        "timing": None} for item in section["sessions"])
    standalone = activity_evidence.read_activity_evidence(
        profile=profile[0].root, profile_kind="synthetic",
        request=profile[2].domain_requests()[1],
        evaluated_at_utc=CLOCK, evaluation_local_date=CLOCK.date())
    assert "temporal_evidence" not in standalone["sections"]
    assert standalone["sections"] == packet["sections"]["activity"]["providers"]
    assert "activity temporal evidence: " in evidence.render_combined_evidence(packet)


def test_activity_temporal_instant_utc_offsets_and_boundaries(profile):
    with session_scope(profile[1]) as session:
        _persist_temporal_activity(
            session, profile[0], activity_id="synthetic-positive",
            fields={"startTimeLocal": "2099-01-02T00:30:00+03:00"})
        _persist_temporal_activity(
            session, profile[0], activity_id="synthetic-negative",
            fields={"startTimeLocal": "2099-01-01T23:30:00-05:00"})
    packet = read(profile)
    cycling = session_for(packet, external_record_id="synthetic-cycling--0")
    start = cycling["start"]
    assert start["state"] == "instant" and start["eligible"] is True
    assert start["measured_at_utc"] == "2099-01-02T08:00:00+00:00"
    assert start["source_local_date"] == "2099-01-02"
    assert start["source_utc_offset_minutes"] is None and start["source_timezone"] is None
    positive = session_for(packet, external_record_id="synthetic-positive")["start"]
    assert positive["measured_at_utc"] == "2099-01-01T21:30:00+00:00"
    assert positive["source_local_date"] == "2099-01-02"
    assert positive["source_utc_offset_minutes"] == 180
    negative = session_for(packet, external_record_id="synthetic-negative")["start"]
    assert negative["measured_at_utc"] == "2099-01-02T04:30:00+00:00"
    assert negative["source_local_date"] == "2099-01-01"
    assert negative["source_utc_offset_minutes"] == -300
    assert negative["source_timezone"] is None


def test_activity_temporal_date_only_local_zone_absent_and_absent_states(profile):
    with session_scope(profile[1]) as session:
        _persist_temporal_activity(
            session, profile[0], activity_id="synthetic-date-only",
            fields={"startTimeGMT": "2099-01-02"})
        _persist_temporal_activity(
            session, profile[0], activity_id="synthetic-local",
            fields={"startTimeLocal": "2099-01-02T08:00:00"})
        _persist_temporal_activity(
            session, profile[0], activity_id="synthetic-zoned-local",
            fields={"startTimeLocal": "2099-01-02T08:00:00",
                    "timeZoneId": "Europe/Moscow"})
    date_only_session = session_for(read(profile), external_record_id="synthetic-date-only")
    date_only = date_only_session["start"]
    assert date_only["state"] == "date_only" and date_only["eligible"] is False
    assert date_only["source_local_date"] == "2099-01-02"
    assert date_only_session["source_local_date"] == "2099-01-02"
    assert date_only["measured_at_utc"] is None and date_only["zone_policy"] == "local_date_only"
    local = session_for(read(profile), external_record_id="synthetic-local")["start"]
    assert local["state"] == "local" and local["eligible"] is True
    assert local["local_wall_time"] == "2099-01-02T08:00:00"
    assert local["measured_at_utc"] is None
    assert local["source_utc_offset_minutes"] is None and local["source_timezone"] is None
    zoned = session_for(read(profile), external_record_id="synthetic-zoned-local")["start"]
    assert zoned["source_timezone"] == "Europe/Moscow"
    assert zoned["source_utc_offset_minutes"] is None
    # A missing clock is absent, never a zero or host/Moscow zone.
    with session_scope(profile[1]) as session:
        row = session.scalar(select(GarminSourceRecord).where(
            GarminSourceRecord.external_record_id == "synthetic-local"))
        row.temporal_precision = "unknown"
    absent_session = session_for(read(profile), external_record_id="synthetic-local")
    absent = absent_session["start"]
    assert absent["state"] == "absent" and absent["eligible"] is False
    assert absent["reason"] == "no_usable_source_time"
    assert absent["measured_at_utc"] is None and absent["source_timezone"] is None
    assert absent["source_utc_offset_minutes"] is None
    # The persisted local date stays visible when the start clock is absent.
    assert absent["source_local_date"] == "2099-01-02"
    assert absent_session["source_local_date"] == "2099-01-02"


def test_activity_temporal_generic_clocks_are_ambiguous(profile):
    with session_scope(profile[1]) as session:
        _persist_temporal_activity(
            session, profile[0], activity_id="synthetic-timestamp",
            fields={"timestamp": "2099-01-02T08:00:00Z"})
        _persist_temporal_activity(
            session, profile[0], activity_id="synthetic-time",
            fields={"time": "2099-01-02T08:00:00"})
    for identity in ("synthetic-timestamp", "synthetic-time"):
        start = session_for(read(profile), external_record_id=identity)["start"]
        assert start["state"] == "ambiguous" and start["eligible"] is False
        assert start["reason"] == "source_start_field_not_proven"
        assert start["measured_at_utc"] is None and start["local_wall_time"] is None


def test_activity_temporal_invalid_conflicting_duplicate_and_retired(profile):
    with session_scope(profile[1]) as session:
        _persist_temporal_activity(
            session, profile[0], activity_id="synthetic-conflict",
            fields={"startTimeLocal": "2099-01-02T10:00:00+03:00",
                    "startTimeGMT": "2099-01-02T08:00:00Z"})
    # The real normalizer already persists the paired mismatch as partial with a
    # typed temporal diagnostic; no scalar field pairing is assumed.
    with session_scope(profile[1]) as session:
        record = session.scalar(select(GarminSourceRecord).where(
            GarminSourceRecord.external_record_id == "synthetic-conflict"))
        assert record.record_status == "partial"
        assert "paired_time_mismatch" in (record.diagnostics_json or "")
    conflict_session = session_for(read(profile), external_record_id="synthetic-conflict")
    conflict_start = conflict_session["start"]
    assert conflict_start["state"] == "ambiguous" and conflict_start["eligible"] is False
    assert conflict_start["reason"] == "conflicting_source_start_fields"
    assert conflict_start["measured_at_utc"] is None
    # The persisted local date stays visible for an ambiguous start.
    assert conflict_start["source_local_date"] == "2099-01-02"
    assert conflict_session["source_local_date"] == "2099-01-02"
    # Explicit persisted invalidity masks any otherwise-proven timing.
    with session_scope(profile[1]) as session:
        session.scalar(select(GarminSourceRecord).where(
            GarminSourceRecord.external_record_id == "synthetic-conflict"
        )).record_status = "invalid"
    invalid_start = session_for(read(profile), external_record_id="synthetic-conflict")["start"]
    assert invalid_start["state"] == "ambiguous" and invalid_start["eligible"] is False
    assert invalid_start["reason"] == "record_invalid"
    with session_scope(profile[1]) as session:
        session.scalar(select(GarminSourceRecord).where(
            GarminSourceRecord.external_record_id == "synthetic-conflict"
        )).record_status = "partial"
    # Duplicate current identities never get a winning timestamp.
    with session_scope(profile[1]) as session:
        for row in session.scalars(select(GarminSourceRecord).where(
                GarminSourceRecord.stream_code == "activity")):
            row.external_record_id = "same-synthetic-activity"
    packet = read(profile)
    assert all(item["start"]["state"] == "ambiguous"
               and item["start"]["reason"] == "duplicate_current_identity"
               and item["start"]["eligible"] is False
               for item in temporal(packet)["sessions"])
    assert all(item["source_local_date"] is not None for item in temporal(packet)["sessions"])
    # Retired records supply no current timing and are excluded with reasons.
    with session_scope(profile[1]) as session:
        rows = list(session.scalars(select(GarminSourceRecord).where(
            GarminSourceRecord.stream_code == "activity").order_by(GarminSourceRecord.id)))
        rows[0].projection_status = "retired"
        rows[0].retired_at = CLOCK
        rows[0].retire_reason = "authoritative_collection_replacement"
        retired_id = rows[0].id
    section = temporal(read(profile))
    assert section["retired_exclusions"] == [
        {"reason_code": "authoritative_collection_replacement", "count": 1}]
    assert section["current_session_count"] == 2
    assert all(item["record_id"] != retired_id for item in section["sessions"])


def test_activity_temporal_partial_unrelated_metrics_keep_proven_start(profile):
    with session_scope(profile[1]) as session:
        # Aware generic ``startTime`` populates both paired columns with the same
        # path; a missing unrelated metric marks the record partial.
        _persist_temporal_activity(
            session, profile[0], activity_id="synthetic-aware-partial",
            fields={"startTime": "2099-01-02T08:00:00+03:00"}, drop=("duration",))
        # A reconcilable paired Local/GMT start stays usable even when the record
        # is partial for an unrelated missing metric.
        _persist_temporal_activity(
            session, profile[0], activity_id="synthetic-paired-partial",
            fields={"startTimeLocal": "2099-01-02T11:00:00+03:00",
                    "startTimeGMT": "2099-01-02T08:00:00Z"}, drop=("duration",))
    with session_scope(profile[1]) as session:
        rows = {row.external_record_id: row for row in session.scalars(
            select(GarminSourceRecord).where(GarminSourceRecord.stream_code == "activity"))}
    for identity in ("synthetic-aware-partial", "synthetic-paired-partial"):
        assert rows[identity].record_status == "partial"
        assert "paired_time_mismatch" not in (rows[identity].diagnostics_json or "")
    aware_session = session_for(read(profile), external_record_id="synthetic-aware-partial")
    aware_start = aware_session["start"]
    assert aware_session["record_status"] == "partial"
    assert aware_start["state"] == "instant" and aware_start["eligible"] is True
    assert aware_start["source_field"] == aware_start["source_local_field"]
    assert aware_start["source_field"] == aware_start["source_utc_field"]
    assert aware_start["measured_at_utc"] == "2099-01-02T05:00:00+00:00"
    assert aware_start["source_local_date"] == "2099-01-02"
    paired = session_for(read(profile), external_record_id="synthetic-paired-partial")
    paired_start = paired["start"]
    assert paired_start["state"] == "instant" and paired_start["eligible"] is True
    assert paired_start["measured_at_utc"] == "2099-01-02T08:00:00+00:00"
    assert paired_start["source_local_field"] != paired_start["source_utc_field"]


def test_activity_temporal_unreadable_diagnostics_fail_closed(profile):
    with session_scope(profile[1]) as session:
        _persist_temporal_activity(
            session, profile[0], activity_id="synthetic-broken-diag",
            fields={"startTime": "2099-01-02T08:00:00+03:00"})
    with session_scope(profile[1]) as session:
        session.scalar(select(GarminSourceRecord).where(
            GarminSourceRecord.external_record_id == "synthetic-broken-diag"
        )).diagnostics_json = "not-a-diagnostic-list"
    start = session_for(read(profile), external_record_id="synthetic-broken-diag")["start"]
    assert start["state"] == "ambiguous" and start["eligible"] is False
    assert start["reason"] == "unreadable_temporal_diagnostics"
    assert start["measured_at_utc"] is None
    assert start["source_local_date"] == "2099-01-02"


def test_activity_temporal_time_budget_after_rows_keeps_metrics_and_incomplete(
        profile, monkeypatch):
    before = cells(read(profile))
    real_rows = activity_evidence._SnapshotActivityBudget.rows
    real_temporal = activity_evidence._read_activity_temporal
    state = {"in_temporal": False, "rows_done": False}

    def rows_with_marker(self, query, cap, reason, *, scalar=True):
        result = real_rows(self, query, cap, reason, scalar=scalar)
        if state["in_temporal"]:
            state["rows_done"] = True
        return result

    def check(self):
        if state["in_temporal"] and state["rows_done"]:
            raise bounded.IncompletePeriodRead("time_budget_exceeded")
        bounded.PeriodReadBudget.check(self)

    def wrapped_temporal(session, request):
        state["in_temporal"] = True
        try:
            return real_temporal(session, request)
        finally:
            state["in_temporal"] = False

    monkeypatch.setattr(activity_evidence._SnapshotActivityBudget, "rows", rows_with_marker)
    monkeypatch.setattr(activity_evidence._SnapshotActivityBudget, "check", check)
    monkeypatch.setattr(activity_evidence, "_read_activity_temporal", wrapped_temporal)
    packet = read(profile)
    section = temporal(packet)
    # Only the timing section degrades; the five Activity cells stay unchanged.
    assert cells(packet) == before
    assert section["state"] == "incomplete"
    assert section["reason"] == "time_budget_exceeded"
    assert section["sessions"] is None
    assert section["candidate_count"] is None and section["current_session_count"] is None
    assert section["retired_exclusions"] is None


def test_activity_temporal_window_and_no_end_from_duration(profile):
    with session_scope(profile[1]) as session:
        _activity(session, profile[0], day=DAY - timedelta(days=6), suffix="start", duration=999)
        _activity(session, profile[0], day=DAY + timedelta(days=1), suffix="after", duration=999)
    section = temporal(read(profile))
    identities = {item["external_record_id"] for item in section["sessions"]}
    assert "synthetic-cycling-start-0" in identities
    assert "synthetic-cycling-after-0" not in identities
    assert section["candidate_count"] == 3
    # A persisted duration never becomes an activity end endpoint.
    duration_record = next(item for item in section["sessions"]
                           if item["external_record_id"] == "synthetic-cycling-start-0")
    assert duration_record["end"]["state"] == "not_persisted_in_activity_contract"
    assert duration_record["end"]["timing"] is None


def test_activity_temporal_cap_overflow_no_prefix_and_metrics_unaffected(profile, monkeypatch):
    before = cells(read(profile))
    monkeypatch.setattr(activity_evidence, "ACTIVITY_TEMPORAL_MAX_SESSIONS", 1)
    packet = read(profile)
    section = temporal(packet)
    assert section["state"] == "incomplete"
    assert section["reason"] == "projected_current_sessions_limit_exceeded"
    assert section["sessions"] is None and section["candidate_count"] is None
    assert section["retired_exclusions"] is None
    assert cells(packet) == before
    monkeypatch.undo()
    monkeypatch.setattr(bounded, "MAX_PERIOD_RECORDS", 0)
    section = temporal(read(profile))
    assert section["state"] == "incomplete"
    assert section["reason"] == "candidate_record_limit_exceeded"
    assert section["sessions"] is None


def test_activity_temporal_compact_detailed_parity(profile):
    detailed = read(profile)
    compact = read(profile, replace(profile[2], projection="compact"))
    assert temporal(compact) == temporal(detailed)
    assert compact["sections"]["activity"]["temporal_evidence"]["contract_version"] == (
        "health-chat-activity-temporal-evidence-v1")


def test_activity_temporal_no_raw_reads_writes_or_provider_access(profile, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("temporal reader touched runtime, provider or raw body")
    monkeypatch.setattr("healthcheck.runtime.prepare_runtime", forbidden)
    monkeypatch.setattr("healthcheck.db.engine.migrate_database", forbidden)
    monkeypatch.setattr(
        "healthcheck.garmin.storage.ContentAddressedGarminPayloadStore.read", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    before = {p.relative_to(profile[0].root): p.read_bytes()
              for p in profile[0].root.rglob("*")
              if p.is_file() and not p.name.endswith("-shm")}
    assert temporal(read(profile))["state"] == "complete"
    assert {p.relative_to(profile[0].root): p.read_bytes()
            for p in profile[0].root.rglob("*")
            if p.is_file() and not p.name.endswith("-shm")} == before
