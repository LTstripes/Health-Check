"""Synthetic exercise sessions; no provider, OAuth or personal profile access."""

import copy
import json
from datetime import date

import pytest

from healthcheck.google.contracts import GOOGLE_STREAMS
from healthcheck.google.exercise import (
    QUERY,
    normalize_exercise_payload,
    persist_exercise_page,
    revision_key,
)
from healthcheck.google.exercise_read import read_saved_exercise
from healthcheck.google.replay import replay_google_observations
from healthcheck.google.sync import source_identity_from_point
from test_google_steps_countsum import database as database

IDENTITY = source_identity_from_point(
    {"dataSource": {"platform": "GOOGLE_FITBIT", "recordingMethod": "ACTIVELY_MEASURED"}}, QUERY
)


def payload(*, name="synthetic-session-1", update="2099-01-03T12:00:00Z", duration="1800s"):
    return {
        "dataPoints": [
            {
                "name": f"users/me/dataTypes/exercise/dataPoints/{name}",
                "dataSource": {"platform": "GOOGLE_FITBIT", "recordingMethod": "ACTIVELY_MEASURED"},
                "exercise": {
                    "exerciseType": "RUNNING",
                    "updateTime": update,
                    "interval": {
                        "startTime": "2099-01-02T22:45:00Z",
                        "startUtcOffset": "10800s",
                        "endTime": "2099-01-02T23:20:00Z",
                        "endUtcOffset": "10800s",
                    },
                    "activeDuration": duration,
                    "metricsSummary": {"caloriesKcal": 999},
                },
            }
        ]
    }


def normalize(raw):
    return normalize_exercise_payload(raw, source_identity=IDENTITY)


def metric(result, code):
    return next(m for m in result.records[0].metrics if m.metric_code == code)


def test_type_active_elapsed_and_local_day_are_distinct():
    result = normalize(payload())
    assert result.status.value == "ok"
    row = result.records[0]
    assert row.temporal.local_date == date(2099, 1, 3)
    assert row.temporal.source_timezone is None
    assert metric(result, "exercise_type").value_text == "RUNNING"
    assert metric(result, "exercise_active_duration_seconds").value_number == 1800
    assert metric(result, "exercise_elapsed_seconds").value_number == 2100
    assert all("calor" not in m.metric_code for m in row.metrics)
    assert "exercise" not in GOOGLE_STREAMS


@pytest.mark.parametrize(
    "duration,state,value",
    [
        (None, "null", None),
        ("0s", "value", 0),
        ("0.123456789s", "value", 0.123456789),
        ("-1s", "invalid", None),
        ("2101s", "invalid", None),
        (True, "invalid", None),
        ("NaNs", "invalid", None),
    ],
)
def test_duration_states(duration, state, value):
    got = metric(normalize(payload(duration=duration)), "exercise_active_duration_seconds")
    assert (got.state.value, got.value_number) == (state, value)


def test_missing_duration_never_uses_elapsed():
    raw = payload()
    del raw["dataPoints"][0]["exercise"]["activeDuration"]
    got = metric(normalize(raw), "exercise_active_duration_seconds")
    assert got.state.value == "missing" and got.value_number is None


def test_identity_survives_time_correction_and_order():
    raw = payload()
    before = normalize(raw).records[0]
    raw["dataPoints"][0]["exercise"]["interval"]["startTime"] = "2099-01-02T22:44:00Z"
    after = normalize(raw).records[0]
    assert before.idempotency_key == after.idempotency_key
    raw["dataPoints"].append(payload(name="another-session")["dataPoints"][0])
    assert len(normalize(raw).records) == 2
    assert (
        normalize(raw).projection_fingerprint
        == normalize({"dataPoints": raw["dataPoints"][::-1]}).projection_fingerprint
    )


@pytest.mark.parametrize("change", ["name", "update", "interval", "precision", "civil", "offset"])
def test_invalid_required_evidence_rejects_entire_page(change):
    raw = payload()
    point = raw["dataPoints"][0]
    interval = point["exercise"]["interval"]
    if change == "name":
        del point["name"]
    elif change == "update":
        del point["exercise"]["updateTime"]
    elif change == "interval":
        interval["endTime"] = interval["startTime"]
    elif change == "precision":
        interval["startTime"] = "2099-01-02T22:45:00.000000001Z"
    elif change == "civil":
        interval["civilStartTime"] = {
            "date": {"year": 2099, "month": 1, "day": 2},
            "time": {"hours": 1},
        }
    else:
        interval["startUtcOffset"] = "3.5s"
    raw["dataPoints"].insert(0, payload(name="valid-prefix")["dataPoints"][0])
    result = normalize(raw)
    assert result.status.value == "invalid" and not result.records


def test_changing_offsets_and_midnight_use_physical_elapsed():
    raw = payload()
    interval = raw["dataPoints"][0]["exercise"]["interval"]
    interval.update(
        startTime="2099-10-25T00:45:00Z",
        startUtcOffset="7200s",
        endTime="2099-10-25T01:20:00Z",
        endUtcOffset="3600s",
    )
    record = normalize(raw).records[0]
    assert record.interval.start.local_wall_time == "2099-10-25T02:45:00"
    assert record.interval.end.local_wall_time == "2099-10-25T02:20:00"
    assert metric(normalize(raw), "exercise_elapsed_seconds").value_number == 2100


def test_revision_nanoseconds_and_offsets_order_exactly():
    assert revision_key("2099-01-02T00:00:00.000000001Z") < revision_key(
        "2099-01-02T00:00:00.000000002Z"
    )
    assert revision_key("2099-01-02T00:00:00Z") == revision_key("2099-01-02T03:00:00+03:00")


def test_envelope_limits_duplicate_names_and_duplicate_json_keys():
    raw = payload()
    raw["dataPoints"] *= 26
    assert normalize(raw).status.value == "invalid"
    raw["dataPoints"] = raw["dataPoints"][:2]
    assert normalize(raw).status.value == "invalid"
    assert normalize(b'{"dataPoints":[],"dataPoints":[]}').status.value == "invalid"
    assert normalize({"dataPoints": [], "nextPageToken": None}).status.value == "invalid"
    assert normalize({"dataPoints": [], "extra": True}).status.value == "invalid"
    assert (
        normalize({"dataPoints": [], "nextPageToken": "x" * (1024 * 1024)}).status.value
        == "invalid"
    )


def test_empty_and_paged_evidence_are_not_zero_workouts():
    assert normalize({}).status.value == "empty"
    raw = payload()
    raw["nextPageToken"] = "synthetic-continuation"
    result = normalize(json.dumps(raw).encode())
    assert result.next_page_token_state.value == "value"
    assert "synthetic-continuation" not in json.dumps(result.as_dict())
    assert normalize(copy.deepcopy(raw)).records == result.records


def test_explicit_sources_are_partitioned_without_family_merge():
    raw = payload()
    point = payload(name="another-source")["dataPoints"][0]
    point["dataSource"]["name"] = "users/me/dataSources/synthetic-other"
    raw["dataPoints"].append(point)
    assert len(normalize(raw).records) == 1
    other = source_identity_from_point(point, QUERY)
    got = normalize_exercise_payload(raw, source_identity=other)
    assert len(got.records) == 1
    assert got.records[0].external_record_id.endswith("another-source")
    assert got.source_identity.source_instance_id != IDENTITY.source_instance_id


def persist(database, raw):
    _, session, store = database
    result = persist_exercise_page(session, payload_store=store, payload=raw)
    session.commit()
    return result


def test_persistence_idempotency_and_stale_replay(database):
    _, session, store = database
    raw = payload()
    first = persist(database, raw)[0]
    same = persist(database, raw)[0]
    assert first.observation.id == same.observation.id
    assert first.records[0].id == same.records[0].id
    correction = payload(update="2099-01-04T12:00:00Z", duration="1700s")
    correction["dataPoints"][0]["exercise"]["interval"].update(
        startTime="2099-01-02T22:40:00Z", endTime="2099-01-02T23:30:00Z"
    )
    persist(database, correction)
    replay_google_observations(session, payload_store=store, observation_ids=[first.observation.id])
    session.commit()
    packet = read_saved_exercise(session)
    assert len(packet["sessions"]) == 1
    row = packet["sessions"][0]
    assert row["active_seconds"] == 1700 and row["elapsed_seconds"] == 3000
    assert row["start_local"] == "2099-01-03T01:40:00"
    assert not packet["provider_history_complete"]


def test_equal_revision_conflict_barrier_then_newer_resolution(database):
    _, session, store = database
    original = persist(database, payload())[0]
    persist(database, payload(duration="1700s"))
    assert read_saved_exercise(session)["sessions"][0]["state"] == "unavailable"
    replay_google_observations(
        session, payload_store=store, observation_ids=[original.observation.id]
    )
    session.commit()
    assert read_saved_exercise(session)["sessions"][0]["active_seconds"] is None
    persist(database, payload(update="2099-01-03T12:00:00.000000001Z", duration="0s"))
    assert read_saved_exercise(session)["sessions"][0]["active_seconds"] == 0


def test_missing_correction_clears_old_duration(database):
    _, session, _ = database
    persist(database, payload())
    correction = payload(update="2099-01-04T12:00:00Z")
    del correction["dataPoints"][0]["exercise"]["activeDuration"]
    persist(database, correction)
    assert read_saved_exercise(session)["sessions"][0]["active_seconds"] is None


def test_previously_unseen_older_revision_cannot_replace_newer(database):
    _, session, _ = database
    persist(database, payload(update="2099-01-04T12:00:00Z", duration="1700s"))
    persist(database, payload(update="2099-01-03T12:00:00Z", duration="1500s"))
    assert read_saved_exercise(session)["sessions"][0]["active_seconds"] == 1700


def test_corrected_local_start_date_moves_window_without_duplicate(database):
    _, session, _ = database
    persist(database, payload())
    correction = payload(update="2099-01-04T12:00:00Z")
    correction["dataPoints"][0]["exercise"]["interval"].update(
        startTime="2099-01-03T22:45:00Z", endTime="2099-01-03T23:20:00Z"
    )
    persist(database, correction)
    assert not read_saved_exercise(session, start_date=date(2099, 1, 3), end_date=date(2099, 1, 3))[
        "sessions"
    ]
    assert (
        len(
            read_saved_exercise(session, start_date=date(2099, 1, 4), end_date=date(2099, 1, 4))[
                "sessions"
            ]
        )
        == 1
    )


def test_multi_source_partition_page_token_and_replay(database):
    _, session, store = database
    raw = payload()
    other = payload(name="same-date-other")["dataPoints"][0]
    other["dataSource"]["name"] = "users/me/dataSources/synthetic-other"
    raw["dataPoints"].append(other)
    raw["nextPageToken"] = "synthetic-page-two"
    outcomes = persist(database, raw)
    assert len(outcomes) == 2
    packet = read_saved_exercise(session)
    assert packet["reason"] == "selection_required" and not packet["sessions"]
    for outcome in outcomes:
        replay_google_observations(
            session, payload_store=store, observation_ids=[outcome.observation.id]
        )
        session.commit()
        selected = read_saved_exercise(session, source_id=outcome.source.id)
        assert len(selected["sessions"]) == 1
        assert selected["pagination"] == "unknown"
        assert not selected["provider_history_complete"]


def test_atomic_rollback_and_next_page_import(database):
    from sqlalchemy import func, select

    from healthcheck.db.models import GooglePayloadObservation, GoogleSourceRecord

    _, session, store = database
    raw = payload()
    raw["nextPageToken"] = "synthetic-next"
    persist_exercise_page(session, payload_store=store, payload=raw)
    session.rollback()
    assert session.scalar(select(func.count()).select_from(GooglePayloadObservation)) == 0
    assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 0
    first = persist(database, raw)[0]
    persist(database, payload(name="page-two-session"))
    persist(database, raw)
    rows = read_saved_exercise(session, source_id=first.source.id)["sessions"]
    assert len(rows) == 2


def test_reader_bound_returns_incomplete_without_prefix(database, monkeypatch):
    import healthcheck.google.exercise_read as reader

    _, session, _ = database
    raw = payload()
    raw["dataPoints"].append(payload(name="other-session")["dataPoints"][0])
    persist(database, raw)
    monkeypatch.setattr(reader, "MAX_SESSIONS", 1)
    packet = read_saved_exercise(session)
    assert not packet["search_complete"] and not packet["sessions"]
    assert packet["reason"] == "session_search_incomplete"


def test_ui_reads_saved_source_separately_and_null_is_unavailable(tmp_path):
    from fastapi.testclient import TestClient

    from healthcheck.db.engine import create_sqlite_engine, session_scope
    from healthcheck.google.storage import ContentAddressedGooglePayloadStore
    from test_garmin_training_owner_view import _ui

    app, _, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            persist_exercise_page(
                session,
                payload_store=ContentAddressedGooglePayloadStore(paths.root / "artifacts"),
                payload=payload(duration=None),
            )
        with TestClient(
            app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
        ) as client:
            response = client.get("/google/exercise")
            assert response.status_code == 200
            assert "RUNNING" in response.text and "Не предоставлено" in response.text
            assert "Полнота истории неизвестна" in response.text
            assert "999" not in response.text
            assert client.get("/google/exercise?source_id=unknown").status_code == 400
    finally:
        engine.dispose()


def test_migration_refuses_downgrade_with_exercise_and_retains_append_only(database):
    from alembic import command
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from healthcheck.db.engine import _alembic_config

    paths, session, _ = database
    outcome = persist(database, payload())[0]
    with pytest.raises(IntegrityError, match="append-only"):
        session.execute(
            text("UPDATE google_raw_payloads SET record_count=0 WHERE id=:id"),
            {"id": outcome.raw_payload.id},
        )
    session.rollback()
    with pytest.raises(RuntimeError, match="immutable exercise evidence"):
        command.downgrade(_alembic_config(paths), "0019_garmin_summary_date_proofs")
    assert read_saved_exercise(session)["sessions"][0]["active_seconds"] == 1800


@pytest.mark.parametrize("stamp", ["2099-01-02T00:00:00+00:60", "2099-01-02T00:00:00+24:00"])
def test_invalid_revision_offsets(stamp):
    assert normalize(payload(update=stamp)).status.value == "invalid"


def test_civil_precision_and_deep_json_fail_closed():
    raw = payload()
    raw["dataPoints"][0]["exercise"]["interval"]["civilStartTime"] = {
        "date": {"year": 2099, "month": 1, "day": 3},
        "time": {"hours": 1, "minutes": 45, "nanos": 1},
    }
    assert normalize(raw).status.value == "invalid"
    assert normalize(b"[" * 10000 + b"]" * 10000).status.value == "invalid"


def test_upgrade_preserves_existing_steps_and_safe_empty_downgrade(database):
    from alembic import command
    from sqlalchemy import select, text

    from healthcheck.db.engine import _alembic_config
    from healthcheck.db.models import GoogleRawPayload
    from test_google_steps_countsum import payload as steps_payload
    from test_google_steps_countsum import persist as persist_steps

    paths, session, _ = database
    persist_steps(database, steps_payload("123"))
    before = [(r.id, r.content_hash) for r in session.scalars(select(GoogleRawPayload))]
    session.commit()
    config = _alembic_config(paths)
    command.downgrade(config, "0019_garmin_summary_date_proofs")
    command.upgrade(config, "head")
    after = [(r.id, r.content_hash) for r in session.scalars(select(GoogleRawPayload))]
    assert after == before
    assert not session.execute(text("PRAGMA foreign_key_check")).all()
    assert session.scalar(text("PRAGMA integrity_check")) == "ok"
    persist(database, payload())


def test_backup_restore_retains_exercise_and_raw_evidence(database, tmp_path):
    from healthcheck.config import Settings
    from healthcheck.db.engine import create_sqlite_engine, session_scope
    from healthcheck.google.storage import ContentAddressedGooglePayloadStore
    from healthcheck.profile_backup import create_backup, restore_profile, verify_backup
    from healthcheck.runtime import prepare_runtime

    paths, _, _ = database
    outcome = persist(database, payload())[0]
    archive = tmp_path / "exercise-backup.zip"
    create_backup(paths.root, archive, scratch=tmp_path)
    assert verify_backup(archive, scratch=tmp_path).migration_revision == "0020_google_exercise"
    target = tmp_path / "restored-exercise"
    restore_profile(archive, target, scratch=tmp_path)
    restored_paths = prepare_runtime(Settings(data_dir=target))
    restored_engine = create_sqlite_engine(restored_paths)
    try:
        with session_scope(restored_engine) as session:
            packet = read_saved_exercise(session)
            assert packet["sessions"][0]["record_id"] == outcome.records[0].id
            assert packet["sessions"][0]["active_seconds"] == 1800
            replay_google_observations(
                session,
                payload_store=ContentAddressedGooglePayloadStore(target / "artifacts"),
                observation_ids=[outcome.observation.id],
            )
    finally:
        restored_engine.dispose()


def test_partial_source_metadata_is_independent_of_page_order():
    raw = payload()
    second = payload(name="valid-other")["dataPoints"][0]
    raw["dataPoints"][0]["dataSource"]["recordingMethod"] = 123
    raw["dataPoints"].append(second)
    result = normalize(raw)
    reversed_result = normalize({"dataPoints": raw["dataPoints"][::-1]})
    assert result.status == reversed_result.status
    assert result.status.value == "partial"
    assert result.projection_fingerprint == reversed_result.projection_fingerprint


def test_fallback_and_explicit_source_page_replay(database):
    _, session, store = database
    raw = payload()
    del raw["dataPoints"][0]["dataSource"]
    other = payload(name="explicit-other")["dataPoints"][0]
    raw["dataPoints"].append(other)
    outcomes = persist(database, raw)
    assert len(outcomes) == 2
    for outcome in outcomes:
        replay_google_observations(
            session, payload_store=store, observation_ids=[outcome.observation.id]
        )
        session.commit()
        assert len(read_saved_exercise(session, source_id=outcome.source.id)["sessions"]) == 1
