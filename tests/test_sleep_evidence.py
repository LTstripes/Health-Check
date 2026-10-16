"""Synthetic production-entry-point checks for the independent Sleep package."""

from __future__ import annotations

import hashlib
import json
import socket
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from healthcheck import chat_evidence
from healthcheck import sleep_evidence as evidence
from healthcheck.analytics import sleep_source_view
from healthcheck.chat_evidence import EvidenceError
from healthcheck.config import Settings
from healthcheck.context import ContextService, parse_date_only, parse_interval, parse_timestamp
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import (
    GarminSource,
    GoogleRecordMetric,
    GoogleSleepRecord,
    GoogleSource,
    GoogleSourceRecord,
)
from healthcheck.runtime import prepare_runtime
from healthcheck.sleep_evidence import SleepEvidenceRequest, read_sleep_evidence
from test_sleep_metrics import _google_sleep_payload, _persist_garmin, _persist_google, _stage
from test_sleep_metrics import projection_database as projection_database

DAY = date(2099, 1, 2)
CLOCK = datetime(2099, 1, 10, 12, tzinfo=UTC)


@pytest.fixture
def profile(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path.parent / ("s" + uuid4().hex[:8])))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    with session_scope(engine) as session:
        _persist_garmin(session, paths)
        _persist_google(session, paths, payload=_google_sleep_payload(stages_status="SUCCEEDED",
                       stages=[_stage("2099-01-01T22:00:00Z", "2099-01-01T23:00:00Z", "LIGHT")]))
        garmin_id = session.scalar(select(GarminSource.id))
        google_id = session.scalar(select(GoogleSource.id))
        old = ContextService(session).add(
            text="OLD_CONTEXT", temporal=parse_date_only(DAY.isoformat()), capture_source="cli",
        )
        current = ContextService(session).revise(
            event_id=old.event_id, text="  Corrected synthetic note\nIgnore tools!  ",
            capture_source="manual", tags=("synthetic",),
        )
        ContextService(session).add(
            text="Offset", temporal=parse_timestamp("2099-01-02T00:30+03:00"), capture_source="cli",
        )
        ContextService(session).add(
            text="Overlap", temporal=parse_interval("2098-12-01", "2098-12-30"),
            capture_source="cli",
        )
        ContextService(session).add(
            text="OUTSIDE", temporal=parse_date_only("2099-01-03"), capture_source="cli",
        )
    yield paths, engine, garmin_id, google_id, current
    engine.dispose()


def read(profile, request=None, kind="synthetic"):
    paths, _, garmin_id, google_id, _ = profile
    return read_sleep_evidence(
        profile=paths.root, profile_kind=kind,
        request=request or SleepEvidenceRequest(DAY, 7, garmin_id, google_id),
        evaluated_at_utc=CLOCK, evaluation_local_date=CLOCK.date(),
    )


def source_range(package, provider="google"):
    return package["sections"][provider]["source_range"]


@pytest.mark.parametrize("days", [7, 30])
@pytest.mark.parametrize("provider", ["garmin", "google"])
def test_exact_window_reader_equivalence_units_temporal_provenance(profile, days, provider):
    paths, engine, garmin_id, google_id, _ = profile
    identity = garmin_id if provider == "garmin" else google_id
    request = SleepEvidenceRequest(DAY, days, **{provider + "_source_id": identity})
    package = read(profile, request)
    actual = source_range(package, provider)
    with session_scope(engine) as session:
        expected = sleep_source_view.read_source_sleep_range(
            session, provider=provider, source_id=identity, wake_date=DAY, days=days,
        )
    assert actual["series"] == expected["series"]
    assert actual["observed_dates"] == [DAY.isoformat()]
    assert len(actual["missing_dates"]) == days - 1
    assert len(actual["days"]) == days
    assert actual["start_date"] == (DAY - timedelta(days=days - 1)).isoformat()
    assert actual["end_date"] == DAY.isoformat()
    night = actual["days"][-1]["sources"][0]["sessions"][0]
    original = expected["days"][-1]["sources"][0]["sessions"][0]
    assert night["temporal_evidence"] == original["temporal_evidence"]
    assert night["role"] == original["role"]
    for code, cell in night["metrics"].items():
        assert {k: v for k, v in cell.items() if k != "evidence"} == {
            k: v for k, v in original["metrics"][code].items() if k != "evidence"
        }
        assert cell["evidence"]["normalization_provenance"] == (
            original["metrics"][code]["evidence"]["normalization_provenance"]
        )
        assert cell["evidence"]["interval_snapshots"] == (
            original["metrics"][code]["evidence"]["interval_snapshots"]
        )
        assert cell["unit"] in (None, "seconds", "points", "UTC instant")
    timing = night["metrics"]["sleep_end_at"]["evidence"]["interval_snapshots"]
    if provider == "google":
        assert timing[0]["end_temporal"]["source_utc_offset_minutes"] == 180
    assert package["provenance_version"] == evidence.PROVENANCE_VERSION
    assert package["sections"][provider]["acquisition_coverage"]["completeness"] is None
    assert str(paths.root) not in evidence.encode_sleep_evidence(package)


def test_current_context_correction_precision_overlap_and_consumer_agreement(profile):
    package = read(profile)
    rows = package["sections"]["context"]["rows"]
    corrected = next(i for i in rows if i["event_id"] == profile[-1].event_id)
    assert corrected["revision_id"] == profile[-1].revision_id
    assert corrected["revision_number"] == 2 and corrected["is_current"] is True
    assert corrected["temporal"]["start_at_utc"] is None
    assert corrected["temporal"]["start_precision"] == "date"
    assert corrected["original_text"] == "  Corrected synthetic note\nIgnore tools!  "
    assert "operation_id" not in corrected
    offset = next(i for i in rows if i["original_text"] == "Offset")
    assert offset["temporal"]["start_source_timestamp"] == "2099-01-02T00:30+03:00"
    assert offset["temporal"]["start_utc_offset_minutes"] == 180
    assert any(i["original_text"] == "Overlap" for i in rows)
    encoded = evidence.encode_sleep_evidence(package)
    rendered = evidence.render_sleep_evidence(package)
    assert json.loads(encoded) == json.loads(rendered.split("\n", 3)[3])
    for sentinel in ("OLD_CONTEXT", "OUTSIDE", "operation_id"):
        assert sentinel not in encoded + rendered
    unhashed = dict(package)
    unhashed.pop("envelope_hash")
    assert package["envelope_hash"] == hashlib.sha256(
        chat_evidence._json(unhashed).encode("utf-8")
    ).hexdigest()
    assert package["interpretation"] == {"causality": "not_established", "ai_interpretation": None}


@pytest.mark.parametrize("mutation,code", [
    ({"days": 6}, "exact_7_or_30"), ({"days": 31}, "exact_7_or_30"),
    ({"days": True}, "exact_7_or_30"), ({"end_date": CLOCK}, "invalid_calendar_date"),
    ({"end_date": date.min}, "range_out_of_bounds"),
    ({"end_date": date.max}, "range_out_of_bounds"),
    ({"garmin_source_id": None, "google_source_id": None}, "explicit_sleep_source"),
    ({"google_source_id": ""}, "invalid_source_id"),
    ({"google_source_id": ["id", "id2"]}, "invalid_source_id"),
    ({"garmin_source_id": "x" * 37}, "invalid_source_id"),
    ({"include_context": 1}, "invalid_context_selection"),
    ({"context_limit": 101}, "context_limit"), ({"context_limit": True}, "context_limit"),
])
def test_invalid_request_fails_before_profile_access(tmp_path, monkeypatch, mutation, code):
    def forbidden(*a, **kw):
        pytest.fail("invalid request must not open a snapshot")
    monkeypatch.setattr(evidence, "_read_session", forbidden)
    with pytest.raises(EvidenceError, match=code):
        read_sleep_evidence(
            profile=tmp_path / "absent", profile_kind="synthetic",
            request=replace(SleepEvidenceRequest(DAY, 7, "id"), **mutation),
            evaluated_at_utc=CLOCK, evaluation_local_date=DAY,
        )


@pytest.mark.parametrize("bad", ["missing", "wrong_code", "cross_provider"])
def test_all_source_validation_precedes_any_sleep_read(profile, monkeypatch, bad):
    paths, engine, garmin_id, google_id, _ = profile
    if bad == "wrong_code":
        with session_scope(engine) as session:
            original = session.get(GoogleSource, google_id)
            wrong = GoogleSource(provider_id=original.provider_id,
                                 acquisition_source_id=original.acquisition_source_id,
                                 source_kind="data_source", provider_code="other_provider",
                                 source_instance_id="synthetic-wrong-provider",
                                 source_contract_version=original.source_contract_version)
            session.add(wrong)
            session.flush()
            google_id = wrong.id
    request = SleepEvidenceRequest(DAY, 7, garmin_id,
                                   google_id if bad == "wrong_code" else
                                   garmin_id if bad == "cross_provider" else "absent")
    def forbidden(*a, **kw):
        pytest.fail("both IDs must be validated before first sleep reader")
    monkeypatch.setattr(evidence, "read_source_sleep_range", forbidden)
    with pytest.raises(EvidenceError, match="selected_source_(unavailable|wrong_provider)"):
        read(profile, request)


def test_exact_source_no_pooling_no_context_when_unselected(profile):
    _, engine, garmin_id, google_id, _ = profile
    with session_scope(engine) as session:
        source = session.get(GarminSource, garmin_id)
        session.add(GarminSource(provider_id=source.provider_id,
                                acquisition_source_id=source.acquisition_source_id,
                                provider_code="garmin_connect", source_kind="synthetic",
                                source_instance_id="UNSELECTED_SECRET_SOURCE"))
    package = read(profile, SleepEvidenceRequest(DAY, 30, google_source_id=google_id,
                                                include_context=False))
    assert set(package["sections"]) == {"google"}
    assert package["request"]["sources"] == {"google": google_id}
    assert "UNSELECTED_SECRET_SOURCE" not in evidence.encode_sleep_evidence(package)


def test_selected_existing_sources_without_period_rows_are_unknown_coverage(profile):
    _, _, garmin_id, google_id, _ = profile
    package = read(profile, SleepEvidenceRequest(DAY + timedelta(days=30), 7,
                                                garmin_id, google_id))
    for provider in ("garmin", "google"):
        packet = source_range(package, provider)
        assert packet["state"] == "no_records" and packet["observed_dates"] == []
        assert len(packet["missing_dates"]) == 7 and packet["series"] == []
        assert package["sections"][provider]["acquisition_coverage"]["state"] == "unknown"


@pytest.mark.parametrize("state,value,expected", [
    ("value", 0, "value"), ("missing", None, "missing"),
    ("null", None, "null"), ("invalid", None, "invalid"),
])
def test_zero_missing_partial_preserved_from_reader(profile, state, value, expected):
    _, engine, _, _, _ = profile
    with session_scope(engine) as session:
        metric = session.scalar(select(GoogleRecordMetric).where(
            GoogleRecordMetric.metric_code == "sleep_summary_minutes_asleep"))
        metric.state, metric.value_number, metric.value_text = state, value, None
        session.scalar(select(GoogleSourceRecord)).record_status = "partial"
    packet = source_range(read(profile))
    point = packet["series"][0]["points"][-1]
    assert point["state"] == expected and point["partial"] is True
    assert point["is_zero"] == (state == "value")
    assert point["value"] == (0 if state == "value" else None)


@pytest.mark.parametrize("roles,state", [("collision", "ambiguous"), ("nap", "unavailable")])
def test_roles_exclusions_ambiguity_not_winning_value(profile, roles, state):
    paths, engine, _, _, _ = profile
    with session_scope(engine) as session:
        if roles == "collision":
            _persist_google(session, paths, payload=_google_sleep_payload(name="second-main"))
        else:
            for code, value in (("sleep_metadata_main", "false"), ("sleep_metadata_nap", "true")):
                metric = session.scalar(select(GoogleRecordMetric).where(
                    GoogleRecordMetric.metric_code == code))
                metric.value_text = value
    packet = source_range(read(profile))
    point = packet["series"][0]["points"][-1]
    assert point["state"] == state and point["value"] is None
    sessions = packet["days"][-1]["sources"][0]["sessions"]
    assert all(i["role"] is not None for i in sessions)
    if roles == "nap":
        assert point["exclusions"] and sessions[0]["role"]["nap_value"] is True
    else:
        assert len(point["candidate_record_ids"]) == 2


def test_null_wake_date_boundaries_and_no_utc_fallback(profile):
    _, engine, _, _, _ = profile
    with session_scope(engine) as session:
        session.scalar(select(GoogleSleepRecord)).wake_date = None
        row = session.scalar(select(GoogleSourceRecord))
        row.source_local_date = DAY - timedelta(days=6)
    packet = source_range(read(profile))
    assert packet["wake_date_missing_count"] == 1
    assert packet["observed_dates"] == [] and len(packet["missing_dates"]) == 7
    assert packet["series"] == []
    with session_scope(engine) as session:
        session.scalar(select(GoogleSourceRecord)).source_local_date = DAY - timedelta(days=7)
    packet = source_range(read(profile))
    assert packet["state"] == "no_records" and packet["wake_date_missing_count"] == 0


@pytest.mark.parametrize("cap", ["MAX_SOURCE_SLEEP_RECORDS", "MAX_SOURCE_SLEEP_RANGE_RECORDS"])
def test_reader_caps_fail_closed_without_prefix(profile, monkeypatch, cap):
    monkeypatch.setattr(sleep_source_view, cap, 0)
    packet = source_range(read(profile))
    assert packet["state"] == "read_limit_exceeded"
    assert packet["days"] == packet["series"] == []
    assert packet["observed_dates"] is packet["missing_dates"] is None


def test_context_truncation_byte_cap_and_source_range_not_row_truncated(profile, monkeypatch):
    _, _, garmin_id, google_id, _ = profile
    package = read(profile, SleepEvidenceRequest(DAY, 30, garmin_id, google_id, context_limit=1))
    context = package["sections"]["context"]
    assert context["returned_count"] == 1 and context["has_more"] and context["truncated"]
    assert context["total_count"] is None
    assert len(source_range(package)["days"]) == 30
    monkeypatch.setattr(chat_evidence, "MAX_OUTPUT_BYTES", 100)
    with pytest.raises(EvidenceError, match="output_exceeds_byte_limit"):
        read(profile)


def test_whitelist_nested_future_fields_never_exported(profile, monkeypatch):
    original = evidence.read_source_sleep_range
    def injected(*a, **kw):
        packet = deepcopy(original(*a, **kw))
        packet["credential"] = "SECRET"
        session = packet["days"][-1]["sources"][0]["sessions"][0]
        session["temporal_evidence"]["gps"] = "SECRET"
        session["source_eligibility"]["basis"]["raw_payload"] = {"token": "SECRET"}
        metric = session["metrics"]["sleep_duration_asleep_seconds"]
        metric["evidence"]["normalization_provenance"]["raw_payload"]["path"] = "SECRET"
        metric["evidence"]["interval_snapshots"].append({"token": "SECRET"})
        packet["wake_date_missing_by_source"]["UNSELECTED_SECRET_SOURCE"] = 123
        return packet
    monkeypatch.setattr(evidence, "read_source_sleep_range", injected)
    package = read(profile)
    assert "SECRET" not in evidence.encode_sleep_evidence(package)
    assert "SECRET" not in evidence.render_sleep_evidence(package)
    def nested_scalar(*a, **kw):
        packet = injected(*a, **kw)
        packet["days"][-1]["sources"][0]["source"]["device_model"] = {"token": "SECRET"}
        return packet
    monkeypatch.setattr(evidence, "read_source_sleep_range", nested_scalar)
    with pytest.raises(EvidenceError, match="unsupported_evidence_value"):
        read(profile)
    def nested_count(*a, **kw):
        packet = injected(*a, **kw)
        packet["wake_date_missing_by_source"][kw["source_id"]] = {"token": "SECRET"}
        return packet
    monkeypatch.setattr(evidence, "read_source_sleep_range", nested_count)
    with pytest.raises(EvidenceError, match="unsupported_evidence_value"):
        read(profile)


def test_snapshot_correction_consistency_across_separate_writer(profile, monkeypatch):
    _, engine, _, _, current = profile
    original = evidence.read_source_sleep_range
    changed = False
    def concurrent(*a, **kw):
        nonlocal changed
        result = original(*a, **kw)
        if not changed:
            changed = True
            with session_scope(engine) as writer:
                ContextService(writer).revise(event_id=current.event_id, text="Concurrent",
                                              capture_source="cli")
                metric = writer.scalar(select(GoogleRecordMetric).where(
                    GoogleRecordMetric.metric_code == "sleep_summary_minutes_asleep"))
                metric.value_number = 500
        return result
    monkeypatch.setattr(evidence, "read_source_sleep_range", concurrent)
    before = read(profile)
    assert source_range(before)["series"][0]["points"][-1]["value"] == 24600
    assert any(i["revision_id"] == current.revision_id
               for i in before["sections"]["context"]["rows"])
    after = read(profile)
    assert source_range(after)["series"][0]["points"][-1]["value"] == 30000
    assert any(i["original_text"] == "Concurrent" for i in after["sections"]["context"]["rows"])


def test_no_files_no_provider_calls_no_migration_no_writes(profile, monkeypatch):
    paths, engine, _, _, _ = profile
    def forbidden(*a, **kw):
        pytest.fail("evidence must not migrate, open bodies or contact providers")
    monkeypatch.setattr("healthcheck.db.engine.migrate_database", forbidden)
    monkeypatch.setattr("healthcheck.runtime.prepare_runtime", forbidden)
    monkeypatch.setattr(
        "healthcheck.garmin.storage.ContentAddressedGarminPayloadStore.read", forbidden)
    monkeypatch.setattr(
        "healthcheck.google.storage.ContentAddressedGooglePayloadStore.read", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setenv("HEALTHCHECK_DATA_DIR", str(paths.root / "NEVER_OPEN"))
    monkeypatch.setenv("HEALTHCHECK_PHOTO_VISION_API_KEY", "SECRET_SENTINEL")
    before = {p.relative_to(paths.root): p.read_bytes() for p in paths.root.rglob("*")
              if p.is_file() and not p.name.endswith("-shm")}
    package = read(profile)
    assert "SECRET_SENTINEL" not in evidence.encode_sleep_evidence(package)
    after = {p.relative_to(paths.root): p.read_bytes() for p in paths.root.rglob("*")
             if p.is_file() and not p.name.endswith("-shm")}
    assert after == before
    with evidence._read_session(paths.root) as session:
        with pytest.raises(DatabaseError):
            session.execute(text("UPDATE google_sources SET platform='forbidden'"))
        with pytest.raises(DatabaseError):
            session.execute(text("CREATE TABLE forbidden (id INTEGER)"))


@pytest.mark.parametrize("guard,value", [("MAX_SQL_STEPS", 0), ("READ_TIMEOUT_SECONDS", -1)])
def test_existing_sql_time_guards_sanitized_failure(profile, monkeypatch, guard, value):
    monkeypatch.setattr(chat_evidence, guard, value)
    def costly(session, **kw):
        session.execute(text(
            "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<10000) "
            "SELECT sum(x) FROM n"
        )).scalar_one()
    monkeypatch.setattr(evidence, "read_source_sleep_range", costly)
    with pytest.raises(EvidenceError, match="^(evidence_read_failed|profile_schema_unavailable)$"):
        read(profile)


@pytest.mark.parametrize("kind", sorted(evidence.PROFILE_KINDS))
def test_profile_kind_is_explicit_unverified_assertion(profile, kind):
    package = read(profile, kind=kind)
    assert package["profile"]["kind"] == kind
    assert package["profile"]["current_stable_identity"] == "not_verified"
    assert package["profile"]["verified_snapshot_metadata"]["state"] == "unknown"
    assert package["privacy"]["classification"] == (
        "synthetic" if kind == "synthetic" else "private_owner_data"
    )


def test_missing_profile_schema_fail_without_creating_or_repairing(tmp_path):
    for root in (tmp_path / "missing", tmp_path / "empty"):
        if root.name == "empty":
            root.mkdir()
            (root / "healthcheck.db").touch()
        with pytest.raises(EvidenceError, match="profile_(database|schema)_unavailable"):
            read_sleep_evidence(profile=root, profile_kind="synthetic",
                                request=SleepEvidenceRequest(DAY, 7, "id"),
                                evaluated_at_utc=CLOCK, evaluation_local_date=DAY)
    assert not (tmp_path / "missing").exists()
    assert (tmp_path / "empty" / "healthcheck.db").read_bytes() == b""


@pytest.mark.parametrize("days", [7, 30])
@pytest.mark.parametrize("copy_minutes", ["410", "500"])
def test_google_auto_family_copy_excluded_by_contract_across_consumers(
    projection_database, days, copy_minutes,
):
    from healthcheck.analytics.period_summary import SLEEP_CODE, PeriodSummaryService
    from healthcheck.google.contracts import (
        FAMILY_GOOGLE_SOURCES,
        GoogleSourceIdentity,
        GoogleSourceKind,
    )
    from healthcheck.saved_sleep import read_saved_sleep
    from test_sleep_account_cohort import _google
    from test_sleep_source_view import _persist_identity

    session, paths = projection_database
    _google(session, paths, DAY, main="true", nap="false")
    payload = _google_sleep_payload(name="excluded-list-copy")
    payload["dataPoints"][0]["sleep"]["summary"]["minutesAsleep"] = copy_minutes
    _persist_identity(session, paths, payload, GoogleSourceIdentity(
        source_kind=GoogleSourceKind.DATA_SOURCE,
        source_instance_id="synthetic-fitbit-list-copy", platform="fitbit",
    ), FAMILY_GOOGLE_SOURCES)
    session.commit()
    summary = PeriodSummaryService(session).build(
        end_date=DAY, days=days, sleep_source_selection=True,
    )["sides"][1]["metrics"][SLEEP_CODE]
    chosen = summary["source_selection"]["selected_source_id"]
    assert summary["aggregation"]["value"] == 24600
    assert summary["aggregation"]["eligible_count"] == 1
    excluded = next(o for o in summary["source_selection"]["options"]
                    if o["source_identity"]["source_id"] != chosen)
    assert excluded["eligible_count"] == 0
    assert {"reason_code": "google_family_excluded", "count": 1} in excluded["exclusions"]
    saved = read_saved_sleep(session, provider="google", evaluation_local_date=DAY)
    assert saved["source"]["source_id"] == chosen
    assert saved["observation"]["value"] == 24600
    call = dict(profile=paths.root, profile_kind="synthetic", evaluated_at_utc=CLOCK,
                evaluation_local_date=CLOCK.date())
    auto = read_sleep_evidence(**call, request=SleepEvidenceRequest(
        DAY, days, include_context=False, google_auto_select=True))
    explicit = read_sleep_evidence(**call, request=SleepEvidenceRequest(
        DAY, days, google_source_id=chosen, include_context=False))
    section = auto["sections"]["google"]
    assert section["source_selection"] == summary["source_selection"]
    assert section["source_range"] == explicit["sections"]["google"]["source_range"]
    points = section["source_range"]["series"][0]["points"]
    assert sum(p["state"] == "value" for p in points) == 1
    assert next(p for p in points if p["state"] == "value")["wake_date"] == DAY.isoformat()
    # Explicit selection of an excluded list remains empty; it never falls back.
    override = read_sleep_evidence(**call, request=SleepEvidenceRequest(
        DAY, days, google_source_id=excluded["source_identity"]["source_id"],
        include_context=False, google_auto_select=True))
    assert not any(p["state"] == "value" for p in
                   override["sections"]["google"]["source_range"]["series"][0]["points"])


@pytest.mark.parametrize("case", ["same_value", "disjoint", "ambiguous", "cap", "no_eligible"])
def test_google_auto_evidence_and_ui_share_blocking_decision(profile, monkeypatch, case):
    from healthcheck.analytics import period_summary_read as bounded
    from healthcheck.analytics.period_summary import SLEEP_CODE, PeriodSummaryService
    from healthcheck.saved_sleep import read_saved_sleep
    from test_sleep_account_cohort import _google

    paths, engine, _, google_id, _ = profile
    with session_scope(engine) as session:
        if case == "no_eligible":
            for row in session.scalars(select(GoogleRecordMetric).where(
                GoogleRecordMetric.metric_code == "sleep_summary_minutes_asleep")):
                row.state, row.value_number, row.value_text = "null", None, None
        else:
            _google(session, paths, DAY - timedelta(days=1 if case == "disjoint" else 0),
                    source="synthetic-competing-sleep", name="other-one", main="true", nap="false")
            if case == "ambiguous":
                _google(session, paths, DAY, source="synthetic-competing-sleep", name="other-two",
                        main="true", nap="false")
        if case == "cap":
            monkeypatch.setattr(bounded, "MAX_PERIOD_SOURCES", 1)
    with session_scope(engine) as session:
        cell = PeriodSummaryService(session).build(
            end_date=DAY, days=7, sleep_source_selection=True,
        )["sides"][1]["metrics"][SLEEP_CODE]
        if case != "cap":
            saved = read_saved_sleep(session, provider="google", evaluation_local_date=DAY)
            assert saved["observation"] is None
            assert saved["state"] == (
                "no_eligible_in_search" if case == "no_eligible" else "ambiguous")
    auto = read(profile, SleepEvidenceRequest(DAY, 7, google_auto_select=True))
    section = auto["sections"]["google"]
    assert section["source_selection"] == cell["source_selection"]
    assert section["selected_source_id"] is None and section["source_range"] is None
    assert section["source_selection"]["state"] == (
        "search_incomplete" if case == "cap" else "no_eligible_values" if case == "no_eligible"
        else "selection_required")
    assert section["source_selection"]["state"] in evidence.render_sleep_evidence(auto)
    exact = read(profile, SleepEvidenceRequest(DAY, 7, google_source_id=google_id,
                                               google_auto_select=True))
    assert exact["sections"]["google"]["selected_source_id"] == google_id


def test_auto_discovery_preserves_caller_sql_guard_and_write_denial(profile):
    from healthcheck.analytics.period_summary import read_sleep_source_selection

    with chat_evidence._read_session(profile[0].root) as session:
        driver = session.connection().connection.driver_connection
        calls = []
        driver.set_progress_handler(lambda: calls.append(1) or int(len(calls) > 1000), 1000)
        cell = read_sleep_source_selection(
            session, provider="google", start=DAY - timedelta(days=6), end=DAY)
        assert cell["source_selection"]["selected_source_id"] == profile[3]
        with pytest.raises(DatabaseError):
            session.execute(text("INSERT INTO google_sources (id) VALUES ('forbidden')"))
        with pytest.raises(DatabaseError):
            session.execute(text("SELECT count(*) FROM sqlite_master a, "
                                 "sqlite_master b, sqlite_master c"))
        assert len(calls) > 1000
