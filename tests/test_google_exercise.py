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
from healthcheck.google.exercise_import import ExerciseImportPlan, acquire_exercise
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


@pytest.mark.parametrize(
    "exercise_type,label",
    [
        ("RUNNING", "Бег"),
        ("BIKING", "Велосипед"),
        ("WALKING", "Ходьба"),
        ("FUTURE_UNKNOWN_TYPE", "Другой вид активности"),
    ],
)
def test_ui_reads_saved_source_separately_and_null_is_unavailable(tmp_path, exercise_type, label):
    from fastapi.testclient import TestClient

    from healthcheck.db.engine import create_sqlite_engine, session_scope
    from healthcheck.google.storage import ContentAddressedGooglePayloadStore
    from test_garmin_training_owner_view import _ui

    app, _, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            raw = payload(duration=None)
            exercise = raw["dataPoints"][0]["exercise"]
            exercise["exerciseType"] = exercise_type
            exercise["interval"].update(
                startTime="2099-01-02T22:45:17Z", endTime="2099-01-02T23:20:18Z"
            )
            persist_exercise_page(
                session,
                payload_store=ContentAddressedGooglePayloadStore(paths.root / "artifacts"),
                payload=raw,
            )
            saved = read_saved_exercise(session)["sessions"][0]
            assert saved["type"] == exercise_type and saved["start_local"].endswith("01:45:17")
        with TestClient(
            app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
        ) as client:
            response = client.get("/google/exercise")
            assert response.status_code == 200
            assert label in response.text and exercise_type not in response.text
            assert "Не предоставлено" in response.text
            assert "3 января 2099, 01:45" in response.text
            assert "3 января 2099, 02:20" in response.text
            assert "UTC+03:00" in response.text
            assert "01:45:17" not in response.text and "02:20:18" not in response.text
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


class ExerciseMockAuth:
    def __init__(self, transport, *, missing=False, refresh_failure=False, on_refresh=None):
        self.transport = transport
        self.missing = missing
        self.refresh_failure = refresh_failure
        self.calls = []
        self.on_refresh = on_refresh

    def load_steps_access_token(self, *, refresh_if_needed=False):
        from healthcheck.google.auth import GoogleAuthResult, GoogleAuthStatus

        self.calls.append(refresh_if_needed)
        if refresh_if_needed and self.on_refresh:
            self.on_refresh()
        fail = self.missing or (refresh_if_needed and self.refresh_failure)
        return ("" if fail else "synthetic-access-never-display"), GoogleAuthResult(
            status=GoogleAuthStatus.REAUTH_REQUIRED if fail else GoogleAuthStatus.AUTHENTICATED,
            refresh_attempted=refresh_if_needed,
            refresh_succeeded=refresh_if_needed and not fail,
        )


def import_plan():
    return ExerciseImportPlan.build("2099-01-03", "2099-01-03", "google-wearables")


def http_response(raw, status=200):
    from healthcheck.google.auth import GoogleHttpResponse

    return GoogleHttpResponse(status, raw if isinstance(raw, bytes) else json.dumps(raw).encode())


def acquire(database, *responses, auth=None):
    from healthcheck.config import Settings
    from test_google_steps_acquisition import Transport

    paths, session, _ = database
    session.commit()
    transport = Transport(*responses)
    request = transport.request

    def request_with_interrupt(method, url, **kwargs):
        if transport.responses and isinstance(transport.responses[0], KeyboardInterrupt):
            transport.calls.append((method, url, kwargs))
            raise transport.responses.pop(0)
        return request(method, url, **kwargs)

    transport.request = request_with_interrupt
    service = auth or ExerciseMockAuth(transport)
    waits = []
    report = acquire_exercise(
        Settings(data_dir=paths.root),
        import_plan(),
        auth_service=service,
        transport=transport,
        sleeper=waits.append,
    )
    session.expire_all()
    return report, transport, service, waits


def test_scoped_cli_fetches_two_pages_with_existing_transport(database, monkeypatch, capsys):
    from urllib.parse import parse_qs, urlparse

    from healthcheck import cli
    from healthcheck.google import auth as auth_module
    from test_google_steps_acquisition import Transport

    paths, session, _ = database
    first = payload(duration=None)
    token = "synthetic-next&?=/opaque-token"
    first["nextPageToken"] = token
    transport = Transport(
        http_response(first), http_response(payload(name="second", duration="0s"))
    )
    constructed = []

    def existing_transport(*, max_response_bytes):
        assert max_response_bytes == 1024 * 1024
        return transport

    def auth_factory(settings, **kwargs):
        assert settings.data_dir == paths.root
        assert kwargs["include_steps"] is True and kwargs["transport"] is transport
        service = ExerciseMockAuth(transport)
        constructed.append(service)
        return service

    monkeypatch.setattr(auth_module, "UrllibGoogleHttpTransport", existing_transport)
    monkeypatch.setattr(cli, "GoogleAuthService", auth_factory)
    args = [
        "google-exercise",
        "--start",
        "2099-01-03",
        "--end",
        "2099-01-03",
        "--family",
        "google-wearables",
        "--apply",
        "--data-dir",
        str(paths.root),
    ]
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["query_exhausted"] and report["page_count"] == 2
    assert report["observed_count"] == report["inserted_count"] == 2
    assert report["partial_record_count"] == 1
    assert not report["provider_history_complete"]
    assert constructed[0].calls == [False, True]
    assert len(transport.calls) == 2
    for method, url, kwargs in transport.calls:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        assert (method, parsed.netloc, parsed.path) == (
            "GET",
            "health.googleapis.com",
            "/v4/users/me/dataTypes/exercise/dataPoints",
        )
        assert query["pageSize"] == ["25"]
        assert query["filter"] == [
            'exercise.interval.civil_start_time >= "2099-01-03" AND '
            'exercise.interval.civil_start_time < "2099-01-04"'
        ]
        assert kwargs["timeout"] == 30 and "json_body" not in kwargs and "form" not in kwargs
    assert parse_qs(urlparse(transport.calls[1][1]).query)["pageToken"] == [token]
    assert token not in output and "synthetic-access" not in output and "2099" not in output
    session.expire_all()
    packet = read_saved_exercise(session)
    assert len(packet["sessions"]) == 2
    assert {r["active_seconds"] for r in packet["sessions"]} == {None, 0}
    from fastapi.testclient import TestClient

    from healthcheck.config import Settings
    from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
    from healthcheck.web.ui_app import create_ui_app

    app, _ = create_ui_app(
        Settings(data_dir=paths.root), photo_extractor=FakeImageMeasurementExtractor()
    )
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        page = client.get("/google/exercise")
        assert page.status_code == 200 and page.text.count("data-google-exercise=") == 2
    repeat, _, _, _ = acquire(
        database, http_response(first), http_response(payload(name="second", duration="0s"))
    )
    assert repeat["inserted_count"] == repeat["updated_count"] == 0
    assert repeat["observed_count"] == 2


@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--dry-run", "--apply"],
        ["--apply"],
        ["--dry-run", "--force-reauth"],
        ["--dry-run", "--stream", "sleep"],
        ["--dry-run", "--reset"],
        ["--dry-run", "--query-mode", "reconcile"],
    ],
)
def test_cli_rejects_unscoped_requests_without_auth(extra, monkeypatch, capsys):
    from healthcheck import cli

    monkeypatch.setattr(cli, "GoogleAuthService", lambda *a, **k: pytest.fail("unexpected auth"))
    assert (
        cli.main(
            [
                "google-exercise",
                "--start",
                "2099-01-03",
                "--end",
                "2099-01-03",
                "--family",
                "google-wearables",
                *extra,
            ]
        )
        == 2
    )
    assert "invalid_exercise_request" in capsys.readouterr().out


def test_dry_run_and_invalid_window_never_create_runtime(tmp_path, monkeypatch, capsys):
    from healthcheck import cli

    monkeypatch.setattr(cli, "GoogleAuthService", lambda *a, **k: pytest.fail("unexpected auth"))
    root = tmp_path / "not-created"
    args = [
        "google-exercise",
        "--start",
        "2099-01-01",
        "--end",
        "2099-01-14",
        "--family",
        "google-wearables",
        "--dry-run",
        "--data-dir",
        str(root),
    ]
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["window_days"] == 14
    assert not root.exists()
    args[args.index("2099-01-14")] = "2099-01-15"
    assert cli.main(args) == 2
    assert not root.exists()


def test_page_budget_and_continuation_cycle_are_partial(database):
    first = payload()
    responses = []
    for index in range(4):
        page = copy.deepcopy(first)
        page["nextPageToken"] = f"synthetic-{index}"
        responses.append(http_response(page))
    report, transport, _, _ = acquire(database, *responses)
    assert (report["reason"], report["page_count"], len(transport.calls)) == ("page_limit", 4, 4)
    assert report["status"] == "partial" and not report["query_exhausted"]
    first["nextPageToken"] = "same-synthetic-token"
    report, transport, _, _ = acquire(database, http_response(first), http_response(first))
    assert report["reason"] == "continuation_cycle" and len(transport.calls) == 2
    assert not report["query_exhausted"]


@pytest.mark.parametrize(
    "status,reason,count",
    [
        (401, "provider_rejected", 1),
        (403, "provider_rejected", 1),
        (429, "rate_limited", 1),
        (500, "retry_exhausted", 3),
        (302, "provider_failed", 1),
    ],
)
def test_terminal_http_and_retry_budget_never_auth_recover(database, status, reason, count):
    report, transport, auth, _ = acquire(database, *[http_response(b"secret-body", status)] * count)
    assert report["reason"] == reason and report["request_count"] == len(transport.calls) == count
    assert not report["query_exhausted"]
    assert auth.calls == [False, True]
    assert "secret-body" not in json.dumps(report)


def test_transport_retry_and_rate_limit_after_saved_page(database):
    from healthcheck.google.auth import GoogleOAuthError

    first = payload()
    first["nextPageToken"] = "synthetic-next"
    report, transport, _, waits = acquire(
        database,
        GoogleOAuthError("provider", "provider_unavailable"),
        http_response(first),
        http_response(b"ignored", 429),
    )
    assert report["status"] == "partial" and report["page_count"] == 1
    assert report["reason"] == "rate_limited" and report["request_count"] == 3
    assert waits == [0.25] and len(transport.calls) == 3
    assert len(read_saved_exercise(database[1])["sessions"]) == 1


def test_missing_grant_or_old_schema_stops_before_http_refresh(database):
    from alembic import command

    from healthcheck.db.engine import _alembic_config

    paths, _, _ = database
    missing = ExerciseMockAuth(None, missing=True)
    report, transport, _, _ = acquire(database, auth=missing)
    assert report["reason"] == "activity_grant_required" and missing.calls == [False]
    assert not transport.calls
    command.downgrade(_alembic_config(paths), "0019_garmin_summary_date_proofs")
    report, transport, auth, _ = acquire(database)
    assert report["reason"] == "current_schema_required" and auth.calls == [False]
    assert not transport.calls


def test_invalid_profile_and_failed_refresh_do_not_query_provider(database, tmp_path):
    from healthcheck.config import Settings

    service = ExerciseMockAuth(None)
    root = tmp_path / "missing-profile"
    report = acquire_exercise(Settings(data_dir=root), import_plan(), auth_service=service)
    assert report["reason"] == "established_profile_required"
    assert not service.calls and not root.exists()
    failed = ExerciseMockAuth(None, refresh_failure=True)
    report, transport, _, _ = acquire(database, auth=failed)
    assert report["reason"] == "startup_auth_failed" and failed.calls == [False, True]
    assert not transport.calls


def test_request_window_validation_covers_all_source_partitions_and_replay(database):
    from sqlalchemy import func, select

    from healthcheck.db.models import GooglePayloadObservation, GoogleSourceRecord

    _, session, store = database
    first = payload()
    other = payload(name="out-of-window")["dataPoints"][0]
    other["dataSource"]["name"] = "users/me/dataSources/other-source"
    other["exercise"]["interval"].update(
        startTime="2099-01-01T12:00:00Z", endTime="2099-01-01T12:35:00Z"
    )
    first["dataPoints"].append(other)
    report, _, _, _ = acquire(database, http_response(first))
    assert report["reason"] == "response_invalid" and not report["query_exhausted"]
    assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 0
    observations = list(session.scalars(select(GooglePayloadObservation)))
    assert len(observations) == 2
    for observation in observations:
        replay_google_observations(session, payload_store=store, observation_ids=[observation.id])
    session.commit()
    assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 0


def test_acquired_replay_requires_context_without_offline_fallback(database):
    from healthcheck.google.exercise_import import normalize_acquired_exercise
    from healthcheck.google.persistence import GooglePersistenceRepository

    _, session, store = database
    raw = payload()
    result = normalize_acquired_exercise(
        json.dumps(raw).encode(), identity=IDENTITY, context=import_plan().context(1, 1)
    )
    outcome = GooglePersistenceRepository(session, payload_store=store).persist_result(
        result, payload=raw
    )  # deliberately missing immutable acquisition context
    session.commit()
    with pytest.raises(ValueError, match="immutable context"):
        replay_google_observations(
            session, payload_store=store, observation_ids=[outcome.observation.id]
        )


def test_acquired_replay_and_manual_attempt_have_no_coverage_checkpoint(database):
    from sqlalchemy import func, select

    from healthcheck.db.models import (
        CoverageInterval,
        GooglePayloadObservation,
        SyncRun,
        SyncStreamState,
    )

    _, session, store = database
    report, _, _, _ = acquire(database, http_response(payload()))
    assert report["query_exhausted"]
    observation = session.scalar(select(GooglePayloadObservation))
    replay_google_observations(session, payload_store=store, observation_ids=[observation.id])
    session.commit()
    run = session.scalar(select(SyncRun))
    assert run.requested_start is None and run.requested_end is None
    assert run.status == "succeeded"
    assert session.scalar(select(func.count()).select_from(CoverageInterval)) == 0
    assert session.scalar(select(func.count()).select_from(SyncStreamState)) == 0
    assert len(read_saved_exercise(session)["sessions"]) == 1


def test_interrupted_page_chain_restarts_idempotently(database):
    first = payload()
    first["nextPageToken"] = "synthetic-next"
    report, _, _, _ = acquire(database, http_response(first), KeyboardInterrupt())
    assert report["reason"] == "interrupted" and report["status"] == "partial"
    assert not report["query_exhausted"] and report["page_count"] == 1
    report, _, _, _ = acquire(database, http_response(first), http_response(payload(name="second")))
    assert report["query_exhausted"] and report["inserted_count"] == 1
    assert len(read_saved_exercise(database[1])["sessions"]) == 2


def test_shared_lock_covers_refresh_http_and_persistence(database, monkeypatch):
    from healthcheck.external_runtime_lock import (
        ExternalRuntimeOperationBusyError,
        ExternalRuntimeOperationLock,
    )
    from healthcheck.google.persistence import GooglePersistenceRepository
    from test_google_steps_acquisition import Transport

    paths, _, _ = database
    phases = []

    def probe(phase):
        phases.append(phase)
        with pytest.raises(ExternalRuntimeOperationBusyError):
            with ExternalRuntimeOperationLock(paths, allow_reentrant=False):
                pytest.fail("profile lock released too soon")

    transport = Transport(http_response(payload()))
    request = transport.request
    transport.request = lambda *a, **k: (probe("http"), request(*a, **k))[1]
    auth = ExerciseMockAuth(transport, on_refresh=lambda: probe("refresh"))
    persist_result = GooglePersistenceRepository.persist_result

    def persist_locked(self, *args, **kwargs):
        probe("persist")
        return persist_result(self, *args, **kwargs)

    monkeypatch.setattr(GooglePersistenceRepository, "persist_result", persist_locked)
    from healthcheck.config import Settings

    result = acquire_exercise(Settings(data_dir=paths.root), import_plan(), auth_service=auth)
    assert result["query_exhausted"] and phases == ["refresh", "http", "persist"]


def test_complete_query_reports_current_conflict_as_unavailable(database):
    from sqlalchemy import select

    from healthcheck.db.models import SyncRun

    persist(database, payload())
    report, _, _, _ = acquire(database, http_response(payload(duration="1700s")))
    assert report["query_exhausted"] and report["status"] == "partial"
    assert report["observed_count"] == report["current_record_count"] == 1
    assert report["current_unavailable_count"] == 1 and report["current_usable_count"] == 0
    run = database[1].scalar(select(SyncRun))
    assert run.status == "partial" and run.accepted_count == 0


def test_full_attempt_budget_is_bounded_to_twelve_data_requests(database):
    responses = []
    for index in range(4):
        page = payload()
        page["nextPageToken"] = f"synthetic-page-{index}"
        responses.extend(
            [http_response(b"ignored", 503), http_response(b"ignored", 500), http_response(page)]
        )
    report, transport, _, waits = acquire(database, *responses)
    assert report["reason"] == "page_limit" and len(transport.calls) == 12
    assert report["request_count"] == 12 and waits == [0.25, 0.5] * 4
    assert report["current_record_count"] == 1 and report["observed_count"] == 4


def test_oversize_response_and_cursor_reject_without_typed_prefix(database):
    from sqlalchemy import func, select

    from healthcheck.db.models import GoogleSourceRecord

    report, _, _, _ = acquire(database, http_response(b"x" * (1024 * 1024 + 1)))
    assert report["reason"] == "response_limit" and report["page_count"] == 0
    raw = payload()
    raw["nextPageToken"] = "\u00e9" * 5000
    report, _, _, _ = acquire(database, http_response(raw))
    assert report["reason"] == "response_invalid" and not report["query_exhausted"]
    assert database[1].scalar(select(func.count()).select_from(GoogleSourceRecord)) == 0


def test_invalid_immutable_context_never_authorizes_replay():
    from healthcheck.google.exercise_import import replay_context

    context = import_plan().context(1, 1)
    with pytest.raises(ValueError):
        replay_context(json.dumps([context, context]))
    context["pageToken"] = "synthetic-cursor-must-not-enter-context"
    with pytest.raises(ValueError):
        replay_context(json.dumps([context]))


def test_second_page_persistence_failure_keeps_prior_commit(database, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    from healthcheck.google.persistence import GooglePersistenceRepository

    first = payload()
    first["nextPageToken"] = "synthetic-next"
    persist_result = GooglePersistenceRepository.persist_result

    def fail_second(self, *args, **kwargs):
        if b"fail-page" in kwargs["payload"]:
            raise SQLAlchemyError("synthetic-storage-error-never-display")
        return persist_result(self, *args, **kwargs)

    monkeypatch.setattr(GooglePersistenceRepository, "persist_result", fail_second)
    report, _, _, _ = acquire(
        database, http_response(first), http_response(payload(name="fail-page"))
    )
    assert report["status"] == "partial" and report["reason"] == "persistence_failed"
    assert report["page_count"] == 1 and not report["query_exhausted"]
    assert len(read_saved_exercise(database[1])["sessions"]) == 1
    assert "synthetic-storage-error" not in json.dumps(report)


def test_failed_current_count_read_stays_null_in_receipt_and_attempt(database, monkeypatch):
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError

    from healthcheck.db.models import SyncRun
    from healthcheck.google import exercise_import

    def unavailable(*args, **kwargs):
        raise SQLAlchemyError("synthetic-current-read-failure")

    monkeypatch.setattr(exercise_import, "select", unavailable)
    report, _, _, _ = acquire(database, http_response(payload()))
    assert report["query_exhausted"] and report["status"] == "partial"
    assert report["current_usable_count"] is None and report["current_unavailable_count"] is None
    run = database[1].scalar(select(SyncRun))
    assert run.accepted_count is None
