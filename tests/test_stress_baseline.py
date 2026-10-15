"""#357 synthetic source-specific comparison, evidence and completion gates."""

import copy
import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import InvalidRequestError

from healthcheck.analytics import stress_baseline as adapter
from healthcheck.analytics.garmin_baselines import GarminSeriesPointCapError
from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
from healthcheck.db.models import (
    GarminPayloadObservation,
    GarminRecordMetric,
    IngestBatch,
    IngestEvent,
    Provider,
    RawArtifact,
    SyncRun,
)
from healthcheck.db.repositories import repositories_for
from healthcheck.garmin.normalization import GarminSourceIdentity, normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.runtime import prepare_runtime
from healthcheck.web.garmin_query import GarminQueryService

D = date(2099, 1, 29)
NOW = datetime(2099, 2, 1, tzinfo=UTC)
ABSENT = object()


@pytest.fixture
def database(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            yield (
                paths,
                engine,
                session,
                ContentAddressedGarminPayloadStore(paths.root / "artifacts"),
            )
    finally:
        engine.dispose()


def acquire(
    database,
    day,
    value=13,
    *,
    zone="Europe/Moscow",
    at=None,
    kind="garmin_incremental",
    status="succeeded",
    account="synthetic-stress-account",
    version="v2",
    extra=None,
    filename="stress.json",
    record_id=None,
    original=None,
):
    _paths, _engine, session, store = database
    payload = {"calendarDate": day.isoformat(), "recordId": record_id or f"stress-{day}"}
    if value is not ABSENT:
        payload["avgStressLevel"] = value
    if zone is not None:
        payload["timeZoneId"] = zone
    payload.update(extra or {})
    try:
        fixture_zone = ZoneInfo(zone) if zone is not None else ZoneInfo("Europe/Moscow")
    except ZoneInfoNotFoundError:
        fixture_zone = ZoneInfo("Europe/Moscow")
    at = at or datetime.combine(day + timedelta(days=1), time(), fixture_zone)
    at = at.astimezone(UTC)
    identity = GarminSourceIdentity(
        source_kind="provider",
        provider_code="garmin_connect",
        device_attributed=False,
        source_instance_id=account,
    )
    repos = repositories_for(session)
    provider = repos.providers.get_or_create("garmin_connect", "Garmin Connect", "wearable")
    run = repos.sync.create_run(provider_id=provider.id, stream_code=kind)
    run.started_at = at - timedelta(minutes=1)
    normalized = normalize_garmin_payload(payload, stream="intraday", source_identity=identity)
    normalized = replace(
        normalized, contract_version=f"r02-garmin-normalization-contract-{version}"
    )
    saved = GarminPersistenceRepository(session, payload_store=store).persist_result(
        normalized,
        payload=payload if original is None else original,
        received_at=at,
        sync_run_id=run.id,
        source_filename=filename,
        source_window_start_utc=datetime.combine(day, time(), UTC),
        source_window_end_utc=datetime.combine(day + timedelta(days=1), time(), UTC),
    )
    repos.sync.finish_run(run.id, status=status)
    run.completed_at = at + timedelta(seconds=1) if status != "running" else None
    session.commit()
    return saved


def seed(database, *, n=21, current=13, current_at=None, **kwargs):
    history = [acquire(database, D - timedelta(days=28 - i), i, **kwargs) for i in range(n)]
    current = acquire(database, D, current, at=current_at, **kwargs)
    return current, history


def read(database, source_id, *, day=D, now=NOW):
    paths, _engine, session, _store = database
    return GarminQueryService(session, Settings(data_dir=paths.root)).stress_baseline(
        garmin_source_id=source_id,
        selected_date=day,
        evaluated_at=now,
    )


def metric(session, saved):
    return session.scalar(
        select(GarminRecordMetric).where(
            GarminRecordMetric.record_id == saved.records[0].id,
            GarminRecordMetric.metric_code == adapter.METRIC_CODE,
        )
    )


@pytest.mark.parametrize(
    "current,delta,direction", [(13, 3, "above"), (10, 0, "equal"), (7, -3, "below")]
)
def test_success_reuses_frozen_history_and_allows_unrelated_record_partial(
    database,
    current,
    delta,
    direction,
):
    saved, history = seed(database, current=current)
    assert all(row.records[0].record_status == "partial" for row in [saved, *history])
    result = read(database, saved.source.id)
    assert result["comparison"] == {
        "status": "available",
        "reason": None,
        "median": 10.0,
        "p25": 5.0,
        "p75": 15.0,
        "delta_points": delta,
        "direction": direction,
    }
    assert result["history"]["eligible_days"] == result["history"]["observed_nonpartial_days"] == 21
    assert result["history"]["denominator"] == 28
    assert len(result["history"]["unobserved_dates"]) == 7
    assert len(result["proofs"]) == 22
    assert result["source"]["device_attributed"] is False
    assert result["evidence"]["history"]["availability"]["partial_count"] == 0
    assert "deviation" not in json.dumps(result)
    assert result == read(database, saved.source.id)


def test_current_change_does_not_change_history_and_freeze_survives_correction(database):
    saved, _history = seed(database)
    original = copy.deepcopy(read(database, saved.source.id))
    frozen = copy.deepcopy(original)
    acquire(database, D, 99, at=datetime(2099, 1, 31, tzinfo=UTC))
    rebuilt = read(database, saved.source.id)
    assert rebuilt["comparison"]["delta_points"] == 89
    assert rebuilt["evidence"]["history"] == original["evidence"]["history"]
    assert (
        rebuilt["evidence"]["current"]["result_hash"]
        != original["evidence"]["current"]["result_hash"]
    )
    assert rebuilt["result_hash"] != original["result_hash"]
    assert original == frozen


@pytest.mark.parametrize("n", [0, 20, 21, 28])
def test_history_gate_is_21_observations_not_full_calendar_coverage(database, n):
    saved, _history = seed(database, n=n)
    result = read(database, saved.source.id)
    assert result["history"]["eligible_days"] == n
    assert result["comparison"]["reason"] == (None if n >= 21 else "insufficient_eligible_history")
    if n == 28:
        assert result["comparison"]["median"] == 13.5
        assert result["comparison"]["p25"] == 6.75
        assert result["comparison"]["p75"] == 20.25


@pytest.mark.parametrize(
    "value,state",
    [(0, "zero"), (None, "null"), (ABSENT, "missing"), (True, "invalid"), ("13", "invalid")],
)
def test_zero_missing_null_invalid_current_are_distinct(database, value, state):
    saved, _history = seed(database, current=value)
    result = read(database, saved.source.id)
    assert result["current"]["status"] == state
    assert result["comparison"]["status"] == ("available" if state == "zero" else "unavailable")
    assert result["current"]["value"] == (0 if state == "zero" else None)


def test_missing_current_never_uses_latest_and_source_selection_is_explicit(database):
    saved = acquire(database, D - timedelta(days=1), 77)
    assert read(database, saved.source.id)["current"]["value"] is None
    assert read(database, None)["comparison"]["reason"] == "source_selection_required"
    assert read(database, "foreign")["comparison"]["reason"] == "selected_garmin_source_not_found"
    other = acquire(database, D, 99, account="other-synthetic-account")
    assert read(database, saved.source.id)["current"]["value"] is None
    assert read(database, other.source.id)["current"]["value"] == 99


@pytest.mark.parametrize("scope", ["current", "history"])
def test_ambiguous_daily_group_is_never_a_value_winner(database, scope):
    saved, _history = seed(database, n=22)
    day = D if scope == "current" else D - timedelta(days=28)
    acquire(database, day, 777, record_id=f"duplicate-{day}")
    result = read(database, saved.source.id)
    assert result["evidence"][scope]["availability"]["excluded_count"] == 2
    if scope == "current":
        assert result["comparison"]["reason"] == "selected_day_not_uniquely_usable"
    else:
        assert result["history"]["eligible_days"] == 21
        assert result["comparison"]["status"] == "available"
        assert result["comparison"]["median"] == 11


@pytest.mark.parametrize("scope", ["current", "history"])
def test_participating_metric_partial_blocks_without_subset_recompute(database, monkeypatch, scope):
    saved, _history = seed(database, n=22)
    real = adapter.analyze_garmin_metric_series

    def partial(session, query):
        result = real(session, query)
        if (query.start_date == D) == (scope == "current"):
            result = replace(
                result, points=(replace(result.points[0], status="partial"), *result.points[1:])
            )
        return result

    monkeypatch.setattr(adapter, "analyze_garmin_metric_series", partial)
    result = read(database, saved.source.id)
    assert result["comparison"]["reason"] == "participating_metric_partial"
    assert result["comparison"]["status"] == "method_dependent"
    assert result["comparison"]["median"] is result["comparison"]["delta_points"] is None
    assert result["current"]["value"] == 13


@pytest.mark.parametrize("scope", ["current", "history"])
@pytest.mark.parametrize("change", ["unit", "field", "attribution", "version", "date"])
def test_one_incompatible_participant_withholds_whole_frozen_sample(database, scope, change):
    _paths, _engine, session, _store = database
    saved, history = seed(database, n=22)
    target = saved if scope == "current" else history[0]
    row = metric(session, target)
    if change == "unit":
        row.unit = "percent"
    elif change == "field":
        row.field_path = "payload.maxStressLevel"
    elif change == "attribution":
        row.source_device_attributed = True
    elif change == "version":
        target.records[0].normalization_contract_version = "unknown-stress-method"
    else:
        # Still in history bounds but not the original returned calendarDate.
        target.records[0].source_local_date = D - timedelta(days=1)
    session.commit()
    result = read(database, saved.source.id)
    assert result["comparison"]["status"] == (
        "unavailable" if change == "date" and scope == "current" else "method_dependent"
    )
    assert result["comparison"]["median"] is result["comparison"]["delta_points"] is None


def test_stress_equivalent_v1_v2_mix_not_global_version_equality(database):
    saved, _history = seed(database, version="v1")
    acquire(database, D, 13, version="v2", at=datetime(2099, 1, 31, tzinfo=UTC))
    result = read(database, saved.source.id)
    assert result["comparison"]["status"] == "available"
    assert {p["normalization_contract_version"] for p in result["proofs"]} == {
        "r02-garmin-normalization-contract-v1",
        "r02-garmin-normalization-contract-v2",
    }


@pytest.mark.parametrize(
    "zone,extra,reason",
    [
        (None, None, "confirmed_source_timezone_missing"),
        ("not-a-zone", None, "confirmed_source_timezone_invalid"),
        ("Europe/Moscow", {"timezone": "America/New_York"}, "source_timezone_conflict"),
    ],
)
def test_unknown_or_conflicting_timezone_preserves_current(database, zone, extra, reason):
    saved, _history = seed(database)
    acquire(database, D, 13, zone=zone, extra=extra, at=datetime(2099, 1, 31, tzinfo=UTC))
    result = read(database, saved.source.id)
    assert result["current"]["value"] == 13
    assert result["comparison"]["reason"] == reason


@pytest.mark.parametrize("scope", ["current", "history"])
@pytest.mark.parametrize("clock", ["contradictory_stamp", "contradictory_offset", "coherent"])
def test_named_zone_must_agree_with_referenced_local_clock(database, scope, clock):
    saved, history = seed(database, zone="Asia/Tokyo")
    day = D if scope == "current" else history[0].records[0].source_local_date
    value = 13 if scope == "current" else 0
    extra = {"startTimeLocal": f"{day}T00:00:00+09:00"}
    if clock == "contradictory_stamp":
        extra["startTimeLocal"] = f"{day}T00:00:00-05:00"
    elif clock == "contradictory_offset":
        extra["sourceUtcOffsetMinutes"] = -300
    acquire(
        database,
        day,
        value,
        zone="Asia/Tokyo",
        extra=extra,
        at=datetime.combine(day, time(16), UTC),
    )
    result = read(database, saved.source.id)
    assert result["current"]["value"] == 13
    if clock == "coherent":
        assert result["comparison"]["status"] == "available"
    else:
        assert result["comparison"]["reason"] == "source_timezone_conflict"
        assert result["comparison"]["delta_points"] is None


def test_source_offset_is_checked_at_stamp_not_next_midnight():
    record = SimpleNamespace(
        source_utc_offset_minutes=-300,
        source_timestamp_utc=datetime(2026, 3, 8, 5, tzinfo=UTC),
        local_wall_time="2026-03-08T00:00:00",
    )
    assert adapter._source_clock_reason(record, {}, ZoneInfo("America/New_York")) is None


@pytest.mark.parametrize("scope", ["current", "history"])
def test_malformed_selected_observation_window_withholds_without_throwing(database, scope):
    _paths, _engine, session, _store = database
    saved, history = seed(database)
    target = saved if scope == "current" else history[0]
    obs = target.observation
    event = session.get(IngestEvent, obs.ingest_event_id)
    new_key, new_event_id = "malformed-window-" + uuid4().hex, str(uuid4())
    event_values = {c.name: getattr(event, c.name) for c in IngestEvent.__table__.columns}
    event_values.update(
        id=new_event_id,
        deduplication_key=uuid4().hex,
        semantic_fingerprint=f"garmin-observation:{new_key}",
    )
    session.execute(insert(IngestEvent).values(**event_values))
    values = {c.name: getattr(obs, c.name) for c in GarminPayloadObservation.__table__.columns}
    values.update(
        id=str(uuid4()),
        observation_key=new_key,
        ingest_event_id=new_event_id,
        source_window_end_utc=obs.source_window_start_utc,
    )
    session.execute(insert(GarminPayloadObservation).values(**values))
    target.records[0].ingest_event_id = new_event_id
    session.commit()
    result = read(database, saved.source.id)
    assert result["current"]["value"] == 13
    assert result["comparison"]["reason"] == "acquisition_identity_mismatch"
    assert result["comparison"]["delta_points"] is None


@pytest.mark.parametrize("seconds,available", [(-1, False), (0, True), (1, True)])
def test_actual_acquisition_boundary_not_host_day(database, seconds, available):
    boundary = datetime(2099, 1, 29, 21, tzinfo=UTC)
    saved, _history = seed(database, current_at=boundary + timedelta(seconds=seconds))
    result = read(database, saved.source.id)
    assert (result["comparison"]["status"] == "available") is available
    assert result["current"]["value"] == 13
    assert result["proofs"][0]["completion_boundary_utc"] == boundary.isoformat()


@pytest.mark.parametrize(
    "kind,status,filename,reason",
    [
        ("garmin_reprocess", "succeeded", "stress.json", "ordinary_acquisition_unproven"),
        ("garmin_incremental", "partial", "stress.json", "successful_acquisition_unproven"),
        ("garmin_incremental", "failed", "stress.json", "successful_acquisition_unproven"),
        ("garmin_incremental", "running", "stress.json", "successful_acquisition_unproven"),
        ("garmin_incremental", "succeeded", "spo2.json", "acquisition_provenance_mismatch"),
    ],
)
def test_late_replay_or_unproven_acquisition_is_not_completion(
    database, kind, status, filename, reason
):
    saved, _history = seed(database)
    acquire(
        database,
        D,
        13,
        kind=kind,
        status=status,
        filename=filename,
        at=datetime(2099, 1, 31, tzinfo=UTC),
    )
    result = read(database, saved.source.id)
    assert result["comparison"]["reason"] == reason
    assert result["current"]["value"] == 13


@pytest.mark.parametrize(
    "tamper", ["event", "batch", "run_provider", "observation_key", "artifact"]
)
def test_exact_selected_provenance_not_success_label_alone(database, tamper):
    _paths, _engine, session, store = database
    saved, _history = seed(database)
    obs = saved.observation
    if tamper == "event":
        session.get(IngestEvent, obs.ingest_event_id).semantic_fingerprint = "unproven"
    elif tamper == "batch":
        event = session.get(IngestEvent, obs.ingest_event_id)
        session.get(IngestBatch, event.ingest_batch_id).parser_name = "garmin-reprocess"
    elif tamper == "run_provider":
        provider = repositories_for(session).providers.get_or_create("other", "Other", "wearable")
        session.get(SyncRun, obs.sync_run_id).provider_id = provider.id
    elif tamper == "observation_key":
        # Keep immutable originals. An extra conflicting observation makes the
        # selected event's provenance ambiguous, which R03 must reject.
        values = {c.name: getattr(obs, c.name) for c in GarminPayloadObservation.__table__.columns}
        values.update(id=str(uuid4()), observation_key="conflicting-selected-event-provenance")
        session.execute(insert(GarminPayloadObservation).values(**values))
    else:
        artifact = session.get(RawArtifact, saved.raw_payload.raw_artifact_id)
        artifact_path = store.artifacts_root / artifact.relative_storage_path
        artifact_path.write_bytes(b"{}")
    session.commit()
    result = read(database, saved.source.id)
    assert result["comparison"]["status"] == (
        "unavailable" if tamper == "observation_key" else "method_dependent"
    )
    assert result["comparison"]["delta_points"] is None


def test_no_mean_substitution_and_flat_history_mad_zero(database):
    saved, history = seed(database, current=0)
    for entry in history:
        acquire(
            database, entry.records[0].source_local_date, 0, at=datetime(2099, 1, 31, tzinfo=UTC)
        )
    result = read(database, saved.source.id)
    assert result["comparison"]["median"] == result["comparison"]["delta_points"] == 0
    acquire(
        database,
        D,
        ABSENT,
        extra={"maxStressLevel": 99, "stress": 50, "lastSevenDaysAvgSpO2": 98},
        at=datetime(2099, 1, 31, tzinfo=UTC),
    )
    assert read(database, saved.source.id)["current"]["status"] == "missing"


@pytest.mark.parametrize(
    "day,expected",
    [
        (date(2026, 3, 8), datetime(2026, 3, 9, 4, tzinfo=UTC)),
        (date(2026, 11, 1), datetime(2026, 11, 2, 5, tzinfo=UTC)),
    ],
)
def test_source_calendar_boundary_respects_dst(day, expected):
    assert adapter._day_end(day, ZoneInfo("America/New_York")) == expected


def test_unknown_midnight_and_ambiguous_midnight_are_conservative():
    assert adapter._day_end(date(2018, 11, 3), ZoneInfo("America/Sao_Paulo")) is None
    # Havana repeats midnight; completion must use the second midnight.
    assert adapter._day_end(date(2026, 10, 31), ZoneInfo("America/Havana")) == datetime(
        2026, 11, 1, 5, tzinfo=UTC
    )


def test_replay_after_boundary_cannot_upgrade_pre_boundary_acquisition(database):
    before = datetime(2099, 1, 29, 20, 59, tzinfo=UTC)
    original, _history = seed(database, current=12, current_at=before)
    replay = acquire(database, D, 12, kind="garmin_reprocess", at=datetime(2099, 1, 31, tzinfo=UTC))
    assert original.raw_payload.id == replay.raw_payload.id
    result = read(database, original.source.id)
    assert result["current"]["value"] == 12
    assert result["comparison"]["reason"] == "ordinary_acquisition_unproven"


def test_later_evaluation_does_not_make_an_early_receipt_complete(database):
    saved, _history = seed(
        database, current=12, current_at=datetime(2099, 1, 29, 20, 59, tzinfo=UTC)
    )
    result = read(database, saved.source.id, now=datetime(2100, 1, 1, tzinfo=UTC))
    assert result["comparison"]["reason"] == "acquisition_before_source_day_end"


def test_one_snapshot_across_both_r03_reads_and_evidence_checks(database, monkeypatch):
    _paths, engine, session, _store = database
    saved, history = seed(database)
    row_id = metric(session, history[0]).id
    session.rollback()
    real = adapter.analyze_garmin_metric_series
    commits = []

    def read_then_write(session, query):
        result = real(session, query)
        if query.start_date == D:
            with create_session_factory(engine)() as writer:
                writer.get(GarminRecordMetric, row_id).value_number = 1000
                writer.commit()
                commits.append(True)
        return result

    monkeypatch.setattr(adapter, "analyze_garmin_metric_series", read_then_write)
    before = read(database, saved.source.id)
    assert commits == [True]
    assert before["comparison"]["status"] == "available"
    assert before["comparison"]["median"] == 10
    session.rollback()
    monkeypatch.setattr(adapter, "analyze_garmin_metric_series", real)
    after = read(database, saved.source.id)
    assert after["comparison"]["reason"] == "original_stress_value_mismatch"


def test_original_byte_bound_preserves_current_without_partial_statistics(database, monkeypatch):
    saved, _history = seed(database)
    monkeypatch.setattr(adapter, "MAX_ARTIFACT_BYTES", 10)
    result = read(database, saved.source.id)
    assert result["current"]["value"] == 13
    assert result["comparison"]["reason"] == "referenced_artifact_exceeds_byte_bound"
    assert result["comparison"]["delta_points"] is None


def test_requested_date_cannot_stand_in_for_original_source_date(database):
    saved, _history = seed(database)
    acquire(
        database,
        D,
        12,
        at=datetime(2099, 1, 31, tzinfo=UTC),
        original={"avgStressLevel": 12, "timeZoneId": "Europe/Moscow"},
    )
    result = read(database, saved.source.id)
    assert result["current"]["value"] == 12
    assert result["comparison"]["reason"] == "original_source_local_date_unproven"


def test_future_receipt_and_run_finish_do_not_prove_current_completion(database):
    saved, _history = seed(database)
    result = read(database, saved.source.id, now=datetime(2099, 1, 29, 20, tzinfo=UTC))
    assert result["current"]["value"] == 13
    assert result["comparison"]["reason"] == "acquisition_chronology_unproven"


def test_work_is_two_bounded_r03_reads_and_only_referenced_originals(database, monkeypatch):
    saved, _history = seed(database)
    _paths, _engine, session, store = database
    acquire(database, D, 999, account="unselected", extra={"timeZoneId": "bad"})
    acquire(database, D - timedelta(days=100), 999)
    calls = []
    real = adapter.analyze_garmin_metric_series
    original_read = ContentAddressedGarminPayloadStore.read
    artifacts = []

    def query(session, query):
        calls.append(query)
        return real(session, query)

    def read_original(self, path, **kwargs):
        artifacts.append(path)
        return original_read(self, path, **kwargs)

    monkeypatch.setattr(adapter, "analyze_garmin_metric_series", query)
    monkeypatch.setattr(ContentAddressedGarminPayloadStore, "read", read_original)
    result = read(database, saved.source.id)
    assert result["comparison"]["status"] == "available"
    assert [(q.start_date, q.end_date) for q in calls] == [
        (D, D),
        (D - timedelta(days=28), D - timedelta(days=1)),
    ]
    assert len(artifacts) == 22
    assert session.connection().connection.driver_connection.in_transaction
    assert store.artifacts_root.is_dir()


def test_point_cap_failure_keeps_current_and_never_returns_truncated_delta(database, monkeypatch):
    saved, _history = seed(database)
    real = adapter.analyze_garmin_metric_series

    def capped(session, query):
        if query.start_date != D:
            raise GarminSeriesPointCapError("synthetic over-cap history")
        return real(session, query)

    monkeypatch.setattr(adapter, "analyze_garmin_metric_series", capped)
    result = read(database, saved.source.id)
    assert result["current"]["value"] == 13
    assert result["comparison"]["reason"] == "selected_points_exceed_max"
    assert result["comparison"]["delta_points"] is None


def test_dirty_session_rejected_before_any_read(database):
    _paths, _engine, session, _store = database
    session.add(Provider(code="pending", display_name="Pending", provider_kind="wearable"))
    with pytest.raises(InvalidRequestError):
        read(database, None)


@pytest.mark.parametrize(
    "day,now", [(datetime(2099, 1, 29), NOW), (date.min, NOW), (D, datetime(2099, 1, 30))]
)
def test_explicit_civil_date_and_aware_evaluation_required(database, day, now):
    with pytest.raises(ValueError):
        read(database, None, day=day, now=now)
