"""Synthetic production-entry checks for #341's bounded Activity packet."""

from __future__ import annotations

import hashlib
import json
import socket
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import DatabaseError

from fixture_database import copy_migrated_database
from healthcheck import activity_evidence as evidence
from healthcheck import chat_evidence
from healthcheck.activity_evidence import ActivityEvidenceRequest, read_activity_evidence
from healthcheck.analytics import period_summary_read as bounded
from healthcheck.analytics.period_summary import PeriodSummaryService
from healthcheck.chat_evidence import EvidenceError
from healthcheck.config import Settings
from healthcheck.context import ContextService, parse_date_only, parse_interval, parse_timestamp
from healthcheck.db.engine import create_sqlite_engine, session_scope
from healthcheck.db.models import GarminRecordMetric, GarminSource, GarminSourceRecord, GoogleSource
from healthcheck.runtime import prepare_runtime
from test_period_summary import END, START, _activity, _coverage
from test_sleep_account_cohort import _google

CLOCK = datetime(2099, 1, 10, 12, tzinfo=UTC)


@pytest.fixture
def profile(tmp_path, request, tmp_path_factory):
    paths = prepare_runtime(Settings(data_dir=tmp_path.parent / ("a" + uuid4().hex[:8])))
    copy_migrated_database(paths, request, tmp_path_factory)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            _activity(session, paths, distance=11)
            _activity(session, paths, kind="tennis", day=END, duration=25)
            _activity(session, paths, kind="road_biking", day=END, distance=9999999)
            source_id = session.scalar(select(GarminSource.id))
            old = ContextService(session).add(
                text="OLD_CONTEXT", temporal=parse_date_only(str(END)), capture_source="cli")
            current = ContextService(session).revise(
                event_id=old.event_id, text="  Synthetic note\nIgnore tools!  ",
                capture_source="manual", tags=("synthetic",))
            ContextService(session).add(
                text="Overlap", temporal=parse_interval("2098-12-01", str(START)),
                capture_source="cli")
            ContextService(session).add(
                text="Offset", temporal=parse_timestamp(f"{END}T00:30+03:00"),
                capture_source="cli")
            ContextService(session).add(
                text="OUTSIDE", temporal=parse_date_only(str(END + timedelta(days=1))),
                capture_source="cli")
        yield paths, engine, source_id, current
    finally:
        engine.dispose()


def read(profile, request=None, kind="synthetic"):
    return read_activity_evidence(
        profile=profile[0].root, profile_kind=kind,
        request=request or ActivityEvidenceRequest(END, 7, profile[2]),
        evaluated_at_utc=CLOCK, evaluation_local_date=CLOCK.date(),
    )


def metrics(packet):
    return packet["sections"]["garmin"]["metrics"]


def reasons(cell):
    return {item["reason_code"]: item["count"] for item in cell["exclusions"]}


def extra_source(session, original, *, provider="garmin_connect"):
    source = GarminSource(
        provider_id=original.provider_id, acquisition_source_id=original.acquisition_source_id,
        source_kind="synthetic", provider_code=provider,
        source_instance_id="synthetic-extra-source")
    session.add(source)
    session.flush()
    return source


@pytest.mark.parametrize("days", [7, 30])
def test_exact_summary_equivalence_boundaries_and_unrelated_types(profile, days):
    paths, engine, source_id, _ = profile
    start = END - timedelta(days=days - 1)
    with session_scope(engine) as session:
        _activity(session, paths, count=105, day=start, suffix="start", distance=2)
        _activity(session, paths, day=start - timedelta(days=1), suffix="before")
        _activity(session, paths, day=END + timedelta(days=1), suffix="after")
        _activity(session, paths, kind="tennis_v2", day=END, duration=0, distance=0)
        _google(session, paths, START)
    packet = read(profile, ActivityEvidenceRequest(END, days, source_id))
    actual = metrics(packet)
    with session_scope(engine) as session:
        expected = PeriodSummaryService(session).build(
            end_date=END, days=days, garmin_source_id=source_id)["sides"][0]["metrics"]
    for code, cell in actual.items():
        # Every accepted aggregate/evidence/coverage field is identical; only
        # public build's date/unit decoration is outside the reused reducer.
        assert cell == {**{key: expected[code][key] for key in cell if key != "search"},
                        "search": {"complete": True, "reason": None}}
    assert actual["activity_session_count"]["aggregation"]["value"] == 109
    assert actual["activity_type_counts"]["aggregation"]["value"] == {
        "cycling": 106, "tennis": 1, "tennis_v2": 1, "road_biking": 1}
    assert actual["cycling_distance_meters"]["aggregation"]["value"] == 221
    assert actual["tennis_duration_seconds"]["aggregation"]["value"] == 25
    assert actual["tennis_session_count"]["aggregation"]["value"] == 2
    assert actual["tennis_duration_seconds"]["availability_counts"]["zero"] == 1
    assert actual["cycling_distance_meters"]["unit"] == "meters"
    assert actual["tennis_duration_seconds"]["unit"] == "seconds"
    assert packet["request"]["requested_range"] == packet["request"]["effective_range"] == {
        "start_date": str(start), "end_date": str(END), "precision": "inclusive_local_date"}
    assert set(packet["sections"]) == {"garmin", "context"}


@pytest.mark.parametrize("state,reason", [
    ("missing", "metric_missing"), ("null", "metric_null"), ("invalid", "metric_invalid"),
    ("wrong_unit", "metric_unit_mismatch"), ("negative", "negative_activity_summary"),
])
def test_tennis_count_independent_of_duration_eligibility(profile, state, reason):
    with session_scope(profile[1]) as session:
        metric = session.scalar(select(GarminRecordMetric).join(GarminSourceRecord).where(
            GarminSourceRecord.activity_type == "tennis",
            GarminRecordMetric.metric_code == "duration_seconds"))
        if state == "wrong_unit":
            metric.unit = "minutes"
        elif state == "negative":
            metric.value_number = -1
        else:
            metric.state, metric.value_number = state, None
    cells = metrics(read(profile))
    assert cells["tennis_session_count"]["aggregation"]["value"] == 1
    assert cells["tennis_duration_seconds"]["aggregation"]["value"] is None
    assert reasons(cells["tennis_duration_seconds"])[reason] == 1


def test_source_local_date_controls_range_without_utc_reinterpretation(profile):
    with session_scope(profile[1]) as session:
        row = session.scalar(select(GarminSourceRecord).where(
            GarminSourceRecord.activity_type == "cycling"))
        # Deliberately different persisted local date and UTC instant.
        row.source_local_date = END + timedelta(days=1)
    assert metrics(read(profile))["cycling_distance_meters"]["aggregation"]["value"] is None


def test_partial_and_duplicate_identity_retirement_are_preserved(profile):
    paths, engine, _, _ = profile
    with session_scope(engine) as session:
        _activity(session, paths, suffix="duplicate", distance=20)
        rows = list(session.scalars(select(GarminSourceRecord).where(
            GarminSourceRecord.activity_type == "cycling").order_by(GarminSourceRecord.id)))
        for row in rows:
            row.external_record_id = "same-synthetic-activity"
    cell = metrics(read(profile))["cycling_distance_meters"]
    assert cell["aggregation"]["value"] is None
    assert reasons(cell)["duplicate_current_identity"] == 2
    with session_scope(engine) as session:
        rows = list(session.scalars(select(GarminSourceRecord).where(
            GarminSourceRecord.activity_type == "cycling").order_by(GarminSourceRecord.id)))
        rows[0].projection_status = "retired"
        rows[0].retired_at = CLOCK
        rows[0].retire_reason = "authoritative_collection_replacement"
        rows[1].record_status = "partial"
    cell = metrics(read(profile))["cycling_distance_meters"]
    assert cell["aggregation"]["value"] in {11, 20}
    assert cell["availability_counts"]["partial"] == 1
    assert cell["availability_counts"]["retired"] == 1
    assert reasons(cell)["retired:authoritative_collection_replacement"] == 1


def test_empty_unknown_proven_empty_and_real_zero_remain_distinct(profile):
    paths, engine, source_id, _ = profile
    request = ActivityEvidenceRequest(END - timedelta(days=40), 7, source_id)
    empty = metrics(read(profile, request))
    assert all(c["aggregation"]["value"] is None for c in empty.values())
    assert all(c["observed_count"] == 0 for c in empty.values())
    assert all(c["coverage"]["complete"] is False for c in empty.values())
    with session_scope(engine) as session:
        for row in session.scalars(select(GarminSourceRecord)):
            row.source_local_date = END + timedelta(days=1)
        _coverage(session, session.get(GarminSource, source_id), status="confirmed_empty")
    cells = metrics(read(profile))
    assert cells["activity_session_count"]["aggregation"]["value"] == 0
    assert cells["activity_type_counts"]["aggregation"]["value"] == {}
    assert cells["tennis_session_count"]["aggregation"]["value"] == 0
    assert cells["cycling_distance_meters"]["aggregation"]["value"] is None
    assert cells["tennis_duration_seconds"]["aggregation"]["value"] is None
    with session_scope(engine) as session:
        _activity(session, paths, suffix="realzero", distance=0)
    cell = metrics(read(profile))["cycling_distance_meters"]
    assert cell["aggregation"]["value"] == 0
    assert cell["availability_counts"]["zero"] == 1
    assert cell["coverage"]["state"] == "contradictory"
    assert cell["coverage"]["observed_on_confirmed_empty_dates"] == [str(START)]


def test_full_stored_presence_is_not_acquisition_coverage(profile):
    with session_scope(profile[1]) as session:
        for offset in range(7):
            _activity(session, profile[0], day=START + timedelta(days=offset), suffix=str(offset))
    cell = metrics(read(profile))["activity_session_count"]
    assert cell["observed_day_count"] == 7
    assert cell["coverage"]["complete"] is False


def test_exact_source_no_pooling_or_unrelated_source_inventory(profile):
    paths, engine, selected, _ = profile
    with session_scope(engine) as session:
        _activity(session, paths, attributed=False, suffix="other", distance=123456789)
        _google(session, paths, START)
        other = session.scalar(select(GarminSource).where(GarminSource.id != selected))
        other_id = other.id
        extra_source(session, session.get(GarminSource, selected))
        _coverage(session, session.get(GarminSource, selected))
    packet = read(profile)
    encoded = evidence.encode_activity_evidence(packet)
    assert other_id not in encoded and "123456789" not in encoded
    assert metrics(packet)["cycling_distance_meters"]["aggregation"]["value"] == 11
    # Shared acquisition identity cannot prove exact-source coverage.
    assert metrics(packet)["cycling_distance_meters"]["coverage"]["complete"] is False
    assert "available_sources" not in encoded


@pytest.mark.parametrize("bad", ["missing", "wrong_code", "cross_provider"])
def test_source_validation_before_summary_or_context(profile, monkeypatch, bad):
    paths, engine, identity, _ = profile
    if bad == "wrong_code":
        with session_scope(engine) as session:
            identity = extra_source(
                session, session.get(GarminSource, identity), provider="other_provider").id
    elif bad == "cross_provider":
        with session_scope(engine) as session:
            _google(session, paths, START)
            identity = session.scalar(select(GoogleSource.id))
    else:
        identity = "unavailable"
    def forbidden(*args, **kwargs):
        pytest.fail("all exact source validation precedes reads")
    monkeypatch.setattr(PeriodSummaryService, "_activities", forbidden)
    monkeypatch.setattr(ContextService, "list", forbidden)
    with pytest.raises(EvidenceError, match="selected_source_(unavailable|wrong_provider)"):
        read(profile, ActivityEvidenceRequest(END, 7, identity))


@pytest.mark.parametrize("mutation,code", [
    ({"days": 6}, "exact_7_or_30"), ({"days": 365}, "exact_7_or_30"),
    ({"days": True}, "exact_7_or_30"), ({"end_date": CLOCK}, "invalid_calendar_date"),
    ({"end_date": date.min}, "range_out_of_bounds"),
    ({"end_date": date.max}, "range_out_of_bounds"),
    ({"garmin_source_id": None}, "explicit_garmin_source"),
    ({"garmin_source_id": " "}, "explicit_garmin_source"),
    ({"garmin_source_id": ["id"]}, "explicit_garmin_source"),
    ({"garmin_source_id": "x" * 37}, "explicit_garmin_source"),
    ({"include_context": 1}, "invalid_context"),
    ({"context_limit": True}, "context_limit"), ({"context_limit": 101}, "context_limit"),
])
def test_invalid_request_precedes_profile_access(tmp_path, monkeypatch, mutation, code):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid request must not access profile")
    monkeypatch.setattr(evidence, "_read_session", forbidden)
    with pytest.raises(EvidenceError, match=code):
        read_activity_evidence(
            profile=tmp_path / "absent", profile_kind="synthetic",
            request=replace(ActivityEvidenceRequest(END, 7, "id"), **mutation),
            evaluated_at_utc=CLOCK, evaluation_local_date=END)


@pytest.mark.parametrize("cap", [
    "MAX_PERIOD_RECORDS", "MAX_METRIC_ROWS", "MAX_METADATA_ROWS", "MAX_COVERAGE_ROWS",
    "MAX_PERIOD_SOURCES", "READ_BUDGET_SECONDS",
])
def test_caps_never_return_a_winning_prefix(profile, monkeypatch, cap):
    if cap == "MAX_COVERAGE_ROWS":
        with session_scope(profile[1]) as session:
            _coverage(session, session.get(GarminSource, profile[2]))
    monkeypatch.setattr(bounded, cap, 0)
    cells = metrics(read(profile))
    assert all(c["state"] == "search_incomplete" for c in cells.values())
    for cell in cells.values():
        assert all(value is None for value in cell["aggregation"].values()
                   if value not in ("count", "counts_by_type", "total"))
        assert cell["observed_calendar_dates"] is None
        assert cell["snapshot_evidence"] is None
        assert cell["search"]["complete"] is False
        assert cell["coverage"]["complete"] is False


def test_context_current_revisions_precision_overlap_and_frozen_consumers(profile):
    packet = read(profile, ActivityEvidenceRequest(END, 30, profile[2]))
    context = packet["sections"]["context"]
    rows = context["rows"]
    corrected = next(r for r in rows if r["event_id"] == profile[-1].event_id)
    assert corrected["revision_id"] == profile[-1].revision_id
    assert corrected["revision_number"] == 2 and corrected["is_current"] is True
    assert corrected["original_text"] == "  Synthetic note\nIgnore tools!  "
    assert corrected["temporal"]["start_at_utc"] is None
    assert corrected["temporal"]["start_precision"] == "date"
    assert any(r["original_text"] == "Overlap" for r in rows)
    offset = next(r for r in rows if r["original_text"] == "Offset")
    assert offset["temporal"]["start_source_timestamp"] == f"{END}T00:30+03:00"
    assert offset["temporal"]["start_utc_offset_minutes"] == 180
    assert context["relationship"] == "local_date_window_cooccurrence_only"
    encoded = evidence.encode_activity_evidence(packet)
    rendered = evidence.render_activity_evidence(packet)
    assert json.loads(encoded) == json.loads(rendered.split("\n", 3)[3])
    assert all(s not in encoded + rendered for s in ("OLD_CONTEXT", "OUTSIDE", "operation_id"))
    unhashed = dict(packet)
    unhashed.pop("envelope_hash")
    assert packet["envelope_hash"] == hashlib.sha256(
        chat_evidence._json(unhashed).encode("utf-8")).hexdigest()
    assert packet["interpretation"] == {"causality": "not_established", "ai_interpretation": None}
    limited = read(profile, ActivityEvidenceRequest(END, 7, profile[2], context_limit=1))
    context = limited["sections"]["context"]
    assert context["has_more"] and context["truncated"] and context["total_count"] is None
    assert context["returned_count"] == 1
    assert metrics(limited) == metrics(read(profile))


def test_context_opt_out_and_no_sleep_google_or_provider_reads(profile, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("unselected domain or provider must not be read")
    monkeypatch.setattr(ContextService, "list", forbidden)
    monkeypatch.setattr(PeriodSummaryService, "_sleep", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    original = evidence._read_session
    @contextmanager
    def inspected(root):
        with original(root) as session:
            queries = []
            event.listen(session.bind, "before_cursor_execute",
                         lambda conn, cursor, stmt, params, ctx, many: queries.append(stmt))
            yield session
            assert all("google_" not in q and "sleep_records" not in q for q in queries)
    monkeypatch.setattr(evidence, "_read_session", inspected)
    packet = read(profile, ActivityEvidenceRequest(END, 7, profile[2], include_context=False))
    assert set(packet["sections"]) == {"garmin"}


def test_recursive_projection_drops_future_fields_and_rejects_nested_scalars(profile, monkeypatch):
    original = PeriodSummaryService._activities
    def injected(*args, **kwargs):
        cells = deepcopy(original(*args, **kwargs))
        cell = cells["cycling_distance_meters"]
        cell["raw_payload"] = "SECRET"
        cell["coverage"]["credentials"] = {"token": "SECRET"}
        cell["aggregation"]["raw_value"] = "SECRET"
        cell["snapshot_evidence"]["storage_path"] = "SECRET"
        return cells
    monkeypatch.setattr(PeriodSummaryService, "_activities", injected)
    assert "SECRET" not in evidence.encode_activity_evidence(read(profile))
    def nested(*args, **kwargs):
        cells = injected(*args, **kwargs)
        cells["activity_type_counts"]["aggregation"]["value"] = {"cycling": {"token": "SECRET"}}
        return cells
    monkeypatch.setattr(PeriodSummaryService, "_activities", nested)
    with pytest.raises(EvidenceError, match="unsupported_evidence_value"):
        read(profile)


def test_one_snapshot_keeps_activity_and_context_coherent(profile, monkeypatch):
    original = evidence._read_activity_summary
    changed = False
    def concurrent(*args, **kwargs):
        nonlocal changed
        result = original(*args, **kwargs)
        if not changed:
            changed = True
            with session_scope(profile[1]) as writer:
                metric = writer.scalar(select(GarminRecordMetric).where(
                    GarminRecordMetric.metric_code == "distance_meters",
                    GarminRecordMetric.value_number == 11))
                metric.value_number = 22
                ContextService(writer).revise(
                    event_id=profile[-1].event_id, text="Concurrent", capture_source="cli")
        return result
    monkeypatch.setattr(evidence, "_read_activity_summary", concurrent)
    before = read(profile)
    after = read(profile)
    assert metrics(before)["cycling_distance_meters"]["aggregation"]["value"] == 11
    assert metrics(after)["cycling_distance_meters"]["aggregation"]["value"] == 22
    assert any(r["revision_id"] == profile[-1].revision_id
               for r in before["sections"]["context"]["rows"])
    assert any(r["original_text"] == "Concurrent" for r in after["sections"]["context"]["rows"])


def test_no_files_runtime_migration_raw_reads_writes_or_config_scan(profile, monkeypatch):
    paths = profile[0]
    def forbidden(*args, **kwargs):
        pytest.fail("read service must not access runtime, raw bodies or providers")
    monkeypatch.setattr("healthcheck.runtime.prepare_runtime", forbidden)
    monkeypatch.setattr("healthcheck.db.engine.migrate_database", forbidden)
    monkeypatch.setattr(
        "healthcheck.garmin.storage.ContentAddressedGarminPayloadStore.read", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setenv("HEALTHCHECK_DATA_DIR", str(paths.root / "NEVER_OPEN"))
    monkeypatch.setenv("HEALTHCHECK_PHOTO_VISION_API_KEY", "SECRET_SENTINEL")
    before = {p.relative_to(paths.root): p.read_bytes() for p in paths.root.rglob("*")
              if p.is_file() and not p.name.endswith("-shm")}
    assert "SECRET_SENTINEL" not in evidence.encode_activity_evidence(read(profile))
    after = {p.relative_to(paths.root): p.read_bytes() for p in paths.root.rglob("*")
             if p.is_file() and not p.name.endswith("-shm")}
    assert before == after
    with evidence._read_session(paths.root) as session:
        for statement in ("UPDATE garmin_sources SET device_code='forbidden'",
                          "CREATE TABLE forbidden (id INTEGER)", "PRAGMA busy_timeout=1"):
            with pytest.raises(DatabaseError):
                session.execute(text(statement))


@pytest.mark.parametrize("guard,value", [("MAX_SQL_STEPS", 0), ("READ_TIMEOUT_SECONDS", -1)])
def test_existing_sql_guards_not_replaced_and_sanitized(profile, monkeypatch, guard, value):
    monkeypatch.setattr(chat_evidence, guard, value)
    def costly(self, source, start, end):
        self.session.execute(text(
            "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<10000) "
            "SELECT sum(x) FROM n")).scalar_one()
    monkeypatch.setattr(PeriodSummaryService, "_activities", costly)
    with pytest.raises(EvidenceError, match="^(evidence_read_failed|profile_schema_unavailable)$"):
        read(profile)


def test_output_guards(profile, monkeypatch):
    packet = read(profile)
    monkeypatch.setattr(chat_evidence, "MAX_OUTPUT_BYTES", 100)
    with pytest.raises(EvidenceError, match="output_exceeds_byte_limit"):
        read(profile)
    monkeypatch.setattr(evidence, "MAX_OUTPUT_BYTES", 100)
    with pytest.raises(EvidenceError, match="output_exceeds_byte_limit"):
        evidence.render_activity_evidence(packet)


def test_missing_profile_never_created(tmp_path):
    root = tmp_path / "absent"
    with pytest.raises(EvidenceError, match="profile_database_unavailable"):
        read_activity_evidence(
            profile=root, profile_kind="synthetic", request=ActivityEvidenceRequest(END, 7, "id"),
            evaluated_at_utc=CLOCK, evaluation_local_date=END)
    assert not root.exists()


@pytest.mark.parametrize("kind", ["running", "indoor_cycling", "road_biking", "padel"])
def test_other_workouts_count_but_never_enter_tennis_or_cycling_scalars(profile, kind):
    with session_scope(profile[1]) as session:
        _activity(session, profile[0], kind=kind, suffix="irrelevant",
                  duration=987654321, distance=987654321)
    cells = metrics(read(profile))
    assert cells["activity_session_count"]["aggregation"]["value"] == 4
    assert cells["tennis_session_count"]["aggregation"]["value"] == 1
    assert cells["tennis_duration_seconds"]["aggregation"]["value"] == 25
    assert cells["cycling_distance_meters"]["aggregation"]["value"] == 11


@pytest.mark.parametrize("kind", sorted(evidence.PROFILE_KINDS))
def test_profile_classification_does_not_claim_snapshot_or_runtime_identity(profile, kind):
    packet = read(profile, kind=kind)
    assert packet["profile"]["kind"] == kind
    assert packet["profile"]["current_stable_identity"] == "not_verified"
    assert packet["profile"]["verified_snapshot_metadata"] == {
        "state": "unknown", "snapshot_id": None}
    assert packet["privacy"]["classification"] == (
        "synthetic" if kind == "synthetic" else "private_owner_data")


@pytest.mark.parametrize("argument,value,code", [
    ("profile_kind", "unknown", "explicit_profile_classification"),
    ("profile_kind", ["synthetic"], "explicit_profile_classification"),
    ("evaluated_at_utc", datetime(2099, 1, 1), "aware_evaluation_clock"),
    ("evaluation_local_date", CLOCK, "evaluation_local_date"),
])
def test_caller_classification_and_clocks_validated_before_profile_access(
    tmp_path, monkeypatch, argument, value, code,
):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid caller metadata must not open a snapshot")
    monkeypatch.setattr(evidence, "_read_session", forbidden)
    args = dict(profile=tmp_path / "absent", profile_kind="synthetic",
                request=ActivityEvidenceRequest(END, 7, "id"),
                evaluated_at_utc=CLOCK, evaluation_local_date=END)
    args[argument] = value
    with pytest.raises(EvidenceError, match=code):
        read_activity_evidence(**args)
