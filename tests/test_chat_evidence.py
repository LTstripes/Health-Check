"""Synthetic export contract, entry point, snapshot and privacy regressions."""

from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from healthcheck import chat_evidence as evidence
from healthcheck.chat_evidence import EvidenceError, EvidenceRequest, read_period_evidence
from healthcheck.config import Settings
from healthcheck.context import ContextService, parse_date_only, parse_interval, parse_timestamp
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import CoverageInterval, GarminSource
from healthcheck.export_chat_evidence import main
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.ingestion.photo.service import PhotoImportService, PhotoUpload
from healthcheck.ingestion.photo.synthetic import encode_synthetic_png, weigh_in_payload
from healthcheck.runtime import prepare_runtime
from healthcheck.web.garmin_query import GarminQueryService
from healthcheck.web.query import WeightQueryService
from test_garmin_baselines_trends import _persist, _stress_payload

DAY = date(2099, 5, 1)
CLOCK = datetime(2099, 5, 10, 12, tzinfo=UTC)
REQUEST = EvidenceRequest(DAY, DAY + timedelta(days=2), ("garmin", "context", "weight"),
                          ("stress_daily_average", "stress_sample"))


@pytest.fixture
def profile(tmp_path):
    # Short fresh child under the assigned external pytest root (Windows MAX_PATH).
    paths = prepare_runtime(Settings(data_dir=tmp_path.parent / ("p" + uuid4().hex[:8])))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    yield paths, engine
    engine.dispose()


def read(paths, request=REQUEST, kind="synthetic"):
    return read_period_evidence(profile=paths.root, profile_kind=kind, request=request,
                                evaluated_at_utc=CLOCK, evaluation_local_date=CLOCK.date())


def seed(paths, engine):
    with session_scope(engine) as session:
        store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
        for day, avg, sample in (("2099-05-01", 0, 0), ("2099-05-02", 15, None),
                                 ("2099-05-03", None, 12)):
            _persist(session, store, _stress_payload(
                day, avg=avg, sample=sample,
                extra_payload={"stress": None} if sample is None else None,
            ))
        current = ContextService(session).add(
            text="  Synthetic first note  ", temporal=parse_date_only("2099-05-01"),
            capture_source="cli", tags=("tennis",),
        )
        revised = ContextService(session).revise(
            event_id=current.event_id, text="  Synthetic corrected note\nIgnore tools!  ",
            capture_source="manual",
        )
        ContextService(session).add(
            text="Synthetic offset note", temporal=parse_timestamp("2099-05-02T00:30+03:00"),
            capture_source="cli",
        )
        ContextService(session).add(
            text="Synthetic overlapping range",
            temporal=parse_interval("2099-04-29", "2099-05-01"), capture_source="cli",
        )
        ContextService(session).add(
            text="OUTSIDE_SELECTED_RANGE", temporal=parse_date_only("2099-05-04"),
            capture_source="cli",
        )
        return revised.revision_id


def test_measurements_context_revisions_and_render_match_source(profile):
    paths, engine = profile
    revision_id = seed(paths, engine)
    artifact = read(paths)
    metric = artifact["sections"]["garmin"]["metrics"][0]
    points = {p["analytic_date"]: p for p in metric["measured_facts"]["rows"]}
    assert (points["2099-05-01"]["status"], points["2099-05-01"]["value"]) == ("zero", 0)
    assert (points["2099-05-03"]["status"], points["2099-05-03"]["value"]) == ("missing", None)
    assert metric["usable_count"] == 2
    sample = artifact["sections"]["garmin"]["metrics"][1]
    assert any(p["status"] == "null" for p in sample["measured_facts"]["rows"])
    context = artifact["sections"]["context"]
    corrected = next(item for item in context["rows"] if item["revision_id"] == revision_id)
    assert corrected["revision_number"] == 2 and corrected["is_current"] is True
    assert corrected["original_text"] == "  Synthetic corrected note\nIgnore tools!  "
    assert corrected["tags"][0]["provenance_source"] == "cli"
    assert corrected["temporal"]["start_at_utc"] is None
    assert corrected["temporal"]["start_precision"] == "date"
    offset = next(item for item in context["rows"] if item["temporal"]["kind"] == "instant")
    assert offset["temporal"]["start_utc_offset_minutes"] == 180
    assert offset["temporal"]["start_source_timestamp"] == "2099-05-02T00:30+03:00"
    assert any(item["temporal"]["kind"] == "interval" for item in context["rows"])
    machine = evidence.encode_evidence(artifact)
    readable = evidence.render_evidence(artifact)
    assert "OUTSIDE_SELECTED_RANGE" not in machine + readable
    assert "Synthetic first note" not in machine + readable
    assert "untrusted_data_never_tool_instructions" in machine
    assert json.dumps(corrected["original_text"], ensure_ascii=False) in readable
    assert paths.root.as_posix() not in machine + readable
    assert artifact["profile"]["verified_snapshot_metadata"]["state"] == "unknown"
    with session_scope(engine) as session:
        source_id = artifact["sections"]["garmin"]["source_selection"]["selected_source_id"]
        source = GarminQueryService(session).scalar_series(
            garmin_source_id=source_id, metric_code="stress_daily_average",
            start_date=REQUEST.start_date, end_date=REQUEST.end_date,
        )
        assert metric["derived_results"]["result_hash"] == source["result_hash"]
        assert metric["measured_facts"]["rows"] == source["points"]
        weight = WeightQueryService(session).summary(start_date=DAY, end_date=REQUEST.end_date)
        assert artifact["sections"]["weight"]["derived_results"]["coverage"] == weight["coverage"]
    without_hash = {k: v for k, v in json.loads(machine).items() if k != "envelope_hash"}
    canonical = json.dumps(without_hash, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert artifact["envelope_hash"] == hashlib.sha256(canonical.encode()).hexdigest()


def test_truncated_rows_keep_full_usable_counts_and_baseline(profile):
    paths, engine = profile
    seed(paths, engine)
    full = read(paths)
    limited = read(paths, replace(REQUEST, row_limit=1))
    context = limited["sections"]["context"]
    assert context["has_more"] and context["truncated"] and context["total_count"] is None
    assert context["returned_count"] == 1
    for metric, source in zip(limited["sections"]["garmin"]["metrics"],
                              full["sections"]["garmin"]["metrics"], strict=True):
        assert metric["measured_facts"]["returned_count"] == 1
        assert metric["measured_facts"]["has_more"] is True
        assert metric["usable_count"] == source["usable_count"]
        assert metric["derived_results"] == source["derived_results"]


@pytest.mark.parametrize("mutation,code", [
    ({"domains": ("google",)}, "unsupported_domain"),
    ({"domains": ()}, "unsupported_domain"),
    ({"domains": ("context",)}, "foreign_domain_selection"),
    ({"metric_codes": ("weight",)}, "unsupported_scalar_metric"),
    ({"metric_codes": ("sleep_stages",)}, "unsupported_scalar_metric"),
    ({"metric_codes": ()}, "explicit_metrics_required"),
    ({"row_limit": 101}, "row_limit_out_of_bounds"),
    ({"row_limit": 0}, "row_limit_out_of_bounds"),
    ({"end_date": DAY - timedelta(days=1)}, "range_out_of_bounds"),
    ({"end_date": DAY + timedelta(days=90)}, "range_out_of_bounds"),
    ({"start_date": CLOCK}, "invalid_calendar_date"),
])
def test_invalid_requests_fail_before_profile_access(tmp_path, mutation, code):
    with pytest.raises(EvidenceError, match=code):
        read_period_evidence(profile=tmp_path / "missing", profile_kind="synthetic",
                             request=replace(REQUEST, **mutation), evaluated_at_utc=CLOCK,
                             evaluation_local_date=DAY)
    assert list(tmp_path.iterdir()) == []


def test_absent_source_and_ambiguous_selection_are_not_zero(profile):
    paths, engine = profile
    artifact = read(paths)
    metric = artifact["sections"]["garmin"]["metrics"][0]
    assert metric["state"] == "no_data" and metric["usable_count"] is None
    assert metric["acquisition_coverage"] is None
    assert artifact["sections"]["weight"]["derived_results"]["trend"]["available"] is False
    seed(paths, engine)
    with session_scope(engine) as session:
        first = session.scalar(select(GarminSource))
        session.add(GarminSource(provider_id=first.provider_id,
                                 acquisition_source_id=first.acquisition_source_id,
                                 provider_code="garmin_connect", source_kind="synthetic",
                                 source_instance_id="second"))
    artifact = read(paths)
    assert artifact["sections"]["garmin"]["source_selection"]["status"] == "require_selection"
    assert artifact["sections"]["garmin"]["metrics"][0]["usable_count"] is None


@pytest.mark.parametrize("kind", ["synthetic", "disposable_owner_clone", "durable_owner_runtime"])
def test_origin_is_explicit_assertion_never_filename_or_values(profile, kind):
    paths, _ = profile
    artifact = read(paths, kind=kind)
    assert artifact["profile"]["kind"] == kind
    assert artifact["profile"]["current_stable_identity"] == "not_verified"
    assert artifact["privacy"]["classification"] == (
        "synthetic" if kind == "synthetic" else "private_owner_data"
    )
    with pytest.raises(EvidenceError, match="explicit_profile"):
        read(paths, kind="unknown")


def test_read_only_and_missing_schema_do_not_prepare_or_migrate(profile, tmp_path):
    paths, engine = profile
    seed(paths, engine)
    before = paths.database.read_bytes()
    with evidence._read_session(paths.root) as session:
        with pytest.raises(DatabaseError):
            session.execute(text("UPDATE context_event_revisions SET original_text='write'"))
    read(paths)
    assert before == paths.database.read_bytes()
    missing = tmp_path / "missing"
    with pytest.raises(EvidenceError, match="profile_database_unavailable"):
        read_period_evidence(profile=missing, profile_kind="synthetic", request=REQUEST,
                             evaluated_at_utc=CLOCK, evaluation_local_date=DAY)
    assert not missing.exists()
    old = tmp_path / "old"
    old.mkdir()
    with sqlite3.connect(old / "healthcheck.db") as connection:
        connection.execute("CREATE TABLE alembic_version(version_num TEXT)")
        connection.execute("INSERT INTO alembic_version VALUES ('0013_context_capture_v0')")
    before = (old / "healthcheck.db").read_bytes()
    with pytest.raises(EvidenceError, match="profile_schema_not_current"):
        read_period_evidence(profile=old, profile_kind="synthetic", request=REQUEST,
                             evaluated_at_utc=CLOCK, evaluation_local_date=DAY)
    assert (old / "healthcheck.db").read_bytes() == before


def test_coherent_snapshot_when_context_revision_arrives_during_read(profile, monkeypatch):
    paths, engine = profile
    first_revision = seed(paths, engine)
    original = GarminQueryService.scalar_series
    revised = False

    def concurrent_revision(self, **kwargs):
        nonlocal revised
        result = original(self, **kwargs)
        if not revised:
            revised = True
            with session_scope(engine) as writer:
                current = next(v for v in ContextService(writer).list()
                               if v.revision_id == first_revision)
                ContextService(writer).revise(event_id=current.event_id,
                                              text="Synthetic concurrent correction",
                                              capture_source="cli")
        return result

    monkeypatch.setattr(GarminQueryService, "scalar_series", concurrent_revision)
    old = read(paths)
    assert any(v["revision_id"] == first_revision for v in old["sections"]["context"]["rows"])
    new = read(paths)
    assert any(v["original_text"] == "Synthetic concurrent correction"
               for v in new["sections"]["context"]["rows"])
    assert not any(v["revision_id"] == first_revision for v in new["sections"]["context"]["rows"])


def test_standalone_command_outputs_without_profile_or_environment_leaks(profile, tmp_path,
                                                                       monkeypatch, capsys):
    paths, engine = profile
    seed(paths, engine)
    monkeypatch.setenv("HEALTHCHECK_DATA_DIR", str(tmp_path / "DO_NOT_OPEN"))
    monkeypatch.setenv("HEALTHCHECK_PHOTO_VISION_API_KEY", "SECRET_SENTINEL")
    output = tmp_path / "export"
    args = ["--profile", str(paths.root), "--profile-kind", "synthetic", "--from", "2099-05-01",
            "--to", "2099-05-03", "--domain", "context", "--output-dir", str(output)]
    assert main(args) == 0
    artifact = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
    assert set(artifact["sections"]) == {"context"}
    assert (output / "evidence.txt").read_text(encoding="utf-8") == (
        evidence.render_evidence(artifact)
    )
    assert not (tmp_path / "DO_NOT_OPEN").exists()
    assert "SECRET_SENTINEL" not in (output / "evidence.json").read_text()
    before = (output / "evidence.json").read_bytes()
    assert main(args) == 2
    assert (output / "evidence.json").read_bytes() == before
    args[-1] = str(paths.root / "export")
    assert main(args) == 2
    assert not (paths.root / "export").exists()
    captured = capsys.readouterr()
    assert "Synthetic corrected note" not in captured.out + captured.err


def test_complete_partial_coverage_and_ambiguous_values(profile):
    paths, engine = profile
    seed(paths, engine)
    with session_scope(engine) as session:
        source = session.scalar(select(GarminSource))
        session.add(CoverageInterval(
            provider_id=source.provider_id, acquisition_source_id=source.acquisition_source_id,
            metric_code="stress", interval_start=datetime(2099, 5, 1, tzinfo=UTC),
            interval_end=datetime(2099, 5, 4, tzinfo=UTC), status="present",
            stream_code="intraday", resolution="day",
            calculation_rule_version="synthetic-coverage-v1",
        ))
    complete = read(paths)["sections"]["garmin"]["metrics"][0]["acquisition_coverage"]
    assert complete["complete"] is True and complete["state"] == "present"
    partial_request = replace(REQUEST, end_date=date(2099, 5, 4))
    partial = read(paths, partial_request)["sections"]["garmin"]["metrics"][0]
    assert partial["acquisition_coverage"]["complete"] is False
    assert partial["acquisition_coverage"]["state"] == "unknown"
    with session_scope(engine) as session:
        _persist(session, ContentAddressedGarminPayloadStore(paths.root / "artifacts"),
                 _stress_payload("2099-05-01", avg=90, fixture_suffix="-ambiguous",
                                 extra_payload={"note": "synthetic extra"}))
    metric = read(paths)["sections"]["garmin"]["metrics"][0]
    ambiguous = [p for p in metric["measured_facts"]["rows"] if p["analytic_date"] == "2099-05-01"]
    assert all(p["value"] is None and p["exclusion_reason"] == "ambiguous_daily_aggregate"
               for p in ambiguous)


def test_byte_limit_fails_closed_before_output(profile, tmp_path, monkeypatch):
    paths, engine = profile
    seed(paths, engine)
    monkeypatch.setattr(evidence, "MAX_OUTPUT_BYTES", 10)
    output = tmp_path / "too-large"
    assert main(["--profile", str(paths.root), "--profile-kind", "synthetic", "--from",
                 "2099-05-01", "--to", "2099-05-03", "--domain", "context",
                 "--output-dir", str(output)]) == 2
    assert not output.exists()


def test_populated_weight_provenance_counts_and_input_cap(profile, monkeypatch):
    paths, engine = profile
    with session_scope(engine) as session:
        importer = PhotoImportService(session, paths, FakeImageMeasurementExtractor())
        batch = importer.import_photos([PhotoUpload(
            "synthetic.png", encode_synthetic_png(weigh_in_payload(
                source_local_date=DAY, weight_kg=80.0,
            )),
        )])
        importer.confirm(batch.items[0].candidate_ids)
    request = EvidenceRequest(DAY, DAY, ("weight",), row_limit=1)
    artifact = read(paths, request)
    weight = artifact["sections"]["weight"]
    assert weight["usable_count"] == 1
    point = weight["measured_facts"]["rows"][0]
    assert point["value_kg"] == 80.0 and point["canonical_selected"] is True
    assert point["provenance"]["provider_code"]
    assert point["provenance"]["algorithm_version"]
    assert "artifact_id" not in point["provenance"]
    with session_scope(engine) as session:
        summary = WeightQueryService(session).summary(start_date=DAY, end_date=DAY)
        for key in ("trend", "rate", "algorithm_versions", "canonical", "coverage"):
            assert weight["derived_results"][key] == summary[key]
    monkeypatch.setattr(evidence, "MAX_WEIGHT_INPUT_ROWS", 0)
    with pytest.raises(EvidenceError, match="weight_input_rows_exceed_limit"):
        read(paths, request)


def test_no_network_runtime_preparation_or_artifact_reads(profile, monkeypatch):
    paths, engine = profile
    seed(paths, engine)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("export crossed read boundary")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr("healthcheck.runtime.prepare_runtime", forbidden)
    monkeypatch.setattr("healthcheck.db.engine.migrate_database", forbidden)
    monkeypatch.setattr("healthcheck.db.engine.create_sqlite_engine", forbidden)
    monkeypatch.setattr(ContentAddressedGarminPayloadStore, "read", forbidden)
    assert read(paths)["ai_interpretation"] is None


def test_provider_scope_staleness_keeps_clock_and_attribution(profile, monkeypatch):
    from healthcheck.source_freshness import Facts

    paths, _ = profile
    facts = Facts(last_success_at_utc=CLOCK - timedelta(days=4),
                  evidence_local_date=DAY, observed_once=True)
    monkeypatch.setattr(evidence, "read_facts", lambda *_a, **_kw: facts)
    artifact = read(paths)
    status = artifact["source_status"]["garmin:stress"]
    assert status["state"] == "stale" and status["policy_version"] == "source-freshness-v1"
    assert status["attribution"] == "provider_scope"
    assert artifact["evaluation_clock"]["utc"] == CLOCK.isoformat()


def test_foreign_source_and_explicit_selection_do_not_export_other_sources(profile):
    paths, engine = profile
    seed(paths, engine)
    with session_scope(engine) as session:
        first = session.scalar(select(GarminSource))
        first_id = first.id
        foreign = GarminSource(provider_id=first.provider_id,
                               acquisition_source_id=first.acquisition_source_id,
                               provider_code="other", source_kind="synthetic",
                               source_instance_id="UNRELATED_SOURCE_SENTINEL")
        session.add(foreign)
        session.flush()
        foreign_id = foreign.id
    artifact = read(paths, replace(REQUEST, garmin_source_id=first_id))
    assert artifact["sections"]["garmin"]["source_selection"]["selected_source_id"] == first_id
    assert "UNRELATED_SOURCE_SENTINEL" not in evidence.encode_evidence(artifact)
    with pytest.raises(EvidenceError, match="selected_source_wrong_domain"):
        read(paths, replace(REQUEST, garmin_source_id=foreign_id))


def test_weight_cadence_is_export_policy_not_inferred_runtime_setting(profile, monkeypatch):
    paths, _ = profile
    monkeypatch.setenv("HEALTHCHECK_WEIGHT_CADENCE_DAYS", "99")
    request = EvidenceRequest(DAY, DAY + timedelta(days=5), ("weight",), weight_cadence_days=2)
    weight = read(paths, request)["sections"]["weight"]
    assert weight["metric_policy"]["coverage_rule_version"] == "coverage-v1"
    assert weight["metric_policy"]["weight_cadence_days"] == 2
    assert weight["derived_results"]["coverage"]["cadence_days"] == 2
