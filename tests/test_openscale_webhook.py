"""R01-07 openScale webhook ingest: auth, durability, replay, isolation, privacy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import (
    IngestBatch,
    IngestEvent,
    MeasurementAlgorithm,
    MeasurementSession,
    ScalarMeasurement,
)
from healthcheck.db.repositories import repositories_for
from healthcheck.ingestion.openscale.binding import evaluate_ingest_binding
from healthcheck.ingestion.openscale.provenance import (
    OPENSCALE_COMPOSITION_GROUP,
    OPENSCALE_WEIGHT_ALGORITHM,
)
from healthcheck.logging import configure_logging
from healthcheck.runtime import prepare_runtime
from healthcheck.web.ingest_app import create_ingest_app
from healthcheck.web.ui_app import create_ui_app

FIXTURES = Path(__file__).parent / "fixtures" / "openscale"
SOURCE_INSTANCE = "11111111-2222-3333-4444-555555555555"
TOKEN = "synthetic-bearer-token-001"
TOKEN_ROTATED = "synthetic-bearer-token-002"


def load_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _settings(tmp_path, **overrides):
    values = {
        "data_dir": tmp_path / "runtime",
        "openscale_source_instance_id": SOURCE_INSTANCE,
        "openscale_ingest_token": TOKEN,
    }
    values.update(overrides)
    return Settings(**values)


def _client(tmp_path, **overrides):
    settings = _settings(tmp_path, **overrides)
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ingest_app(settings)
    return TestClient(app), settings, paths


def _auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _count(session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def test_auth_missing_wrong_malformed(tmp_path):
    client, _settings_obj, paths = _client(tmp_path)
    body = load_fixture("insert_single.json")
    with client:
        assert client.post("/api/ingest/openscale", content=body).status_code == 401
        assert (
            client.post(
                "/api/ingest/openscale",
                content=body,
                headers={"Authorization": "Bearer wrong-token"},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/ingest/openscale",
                content=body,
                headers={"Authorization": "Token not-bearer"},
            ).status_code
            == 401
        )
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            assert _count(session, IngestBatch) == 0
            assert _count(session, MeasurementSession) == 0
    finally:
        engine.dispose()


def test_secret_rotation_keeps_source_instance_identity(tmp_path):
    client, settings, paths = _client(tmp_path)
    body = load_fixture("insert_single.json")
    with client:
        first = client.post("/api/ingest/openscale", content=body, headers=_auth())
        assert first.status_code == 200, first.text
        session_id = first.json()["items"][0]["session_id"]

    rotated_settings = _settings(
        tmp_path,
        openscale_ingest_token=TOKEN_ROTATED,
        data_dir=settings.data_dir,
    )
    app, _ = create_ingest_app(rotated_settings)
    with TestClient(app) as rotated:
        assert (
            rotated.post("/api/ingest/openscale", content=body, headers=_auth(TOKEN)).status_code
            == 401
        )
        retry = rotated.post("/api/ingest/openscale", content=body, headers=_auth(TOKEN_ROTATED))
        assert retry.status_code == 200
        assert retry.json()["items"][0]["status"] == "duplicate"
        assert retry.json()["items"][0]["session_id"] == session_id

    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            repos = repositories_for(session)
            source = repos.acquisition_sources.get_by_sender_instance_id(SOURCE_INSTANCE)
            assert source is not None
            assert source.source_instance_id == SOURCE_INSTANCE
            assert _count(session, MeasurementSession) == 1
            assert _count(session, ScalarMeasurement) >= 1
    finally:
        engine.dispose()


def test_malformed_json_and_envelope_rejected_without_batch(tmp_path):
    client, _settings_obj, paths = _client(tmp_path)
    with client:
        assert (
            client.post("/api/ingest/openscale", content=b"{not-json", headers=_auth()).status_code
            == 400
        )
        assert (
            client.post(
                "/api/ingest/openscale",
                content=b'{"event":"nope"}',
                headers=_auth(),
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/ingest/openscale",
                content=b'{"event":"insert","measurements":[]}',
                headers=_auth(),
            ).status_code
            == 400
        )
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            assert _count(session, IngestBatch) == 0
    finally:
        engine.dispose()


def test_single_and_batch_insert(tmp_path):
    client, _settings_obj, paths = _client(tmp_path)
    with client:
        single = client.post(
            "/api/ingest/openscale", content=load_fixture("insert_single.json"), headers=_auth()
        )
        assert single.status_code == 200
        assert single.json()["acknowledged"] is True
        assert single.json()["items"][0]["status"] == "committed"
        batch = client.post(
            "/api/ingest/openscale", content=load_fixture("batch_mixed.json"), headers=_auth()
        )
        assert batch.status_code == 200
        assert len(batch.json()["items"]) == 2
        assert all(item["status"] == "committed" for item in batch.json()["items"])
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            assert _count(session, MeasurementSession) == 3
            weights = list(
                session.scalars(
                    select(ScalarMeasurement).where(ScalarMeasurement.metric_code == "weight")
                )
            )
            assert len(weights) == 3
    finally:
        engine.dispose()


def test_mixed_valid_invalid_batch_is_durable(tmp_path):
    client, _settings_obj, paths = _client(tmp_path)
    payload = {
        "event": "insert",
        "measurements": [
            {
                "id": "ok-1",
                "userId": "synthetic-user-1",
                "date": "2026-03-01",
                "values": [
                    {
                        "key": "weight",
                        "name": "Weight",
                        "unit": "kg",
                        "value": 70.5,
                        "isDerived": False,
                    }
                ],
            },
            {"id": "bad-1", "date": "2026-03-02", "values": []},
            {
                "id": "ok-2",
                "userId": "synthetic-user-1",
                "date": "2026-03-03",
                "values": [
                    {
                        "key": "weight",
                        "name": "Weight",
                        "unit": "kg",
                        "value": 71.0,
                        "isDerived": False,
                    }
                ],
            },
        ],
    }
    with client:
        response = client.post(
            "/api/ingest/openscale",
            content=json.dumps(payload).encode("utf-8"),
            headers=_auth(),
        )
        assert response.status_code == 200
        statuses = [item["status"] for item in response.json()["items"]]
        assert statuses.count("committed") == 2
        assert statuses.count("failed") == 1
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            assert _count(session, MeasurementSession) == 2
            failed = list(
                session.scalars(select(IngestEvent).where(IngestEvent.status == "failed"))
            )
            assert len(failed) == 1
            assert failed[0].diagnostic_code is not None
            assert "70.5" not in (failed[0].diagnostic_reason or "")
    finally:
        engine.dispose()


def test_values_authoritative_and_missing_not_zero(tmp_path):
    client, _settings_obj, paths = _client(tmp_path)
    body = load_fixture("convenience_zero_no_weight_item.json")
    with client:
        response = client.post("/api/ingest/openscale", content=body, headers=_auth())
        assert response.status_code == 200
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            metrics = {
                row.metric_code: row.normalized_value
                for row in session.scalars(select(ScalarMeasurement))
            }
            assert "weight" not in metrics
            assert metrics.get("body_fat_pct") == pytest.approx(24.5)
    finally:
        engine.dispose()


def test_unknown_fields_retained_in_raw_evidence(tmp_path):
    client, _settings_obj, paths = _client(tmp_path)
    payload = {
        "event": "insert",
        "id": "unknown-fields-1",
        "userId": "synthetic-user-1",
        "date": "2026-04-01T10:00:00+03:00",
        "mysteryTop": "keep-me",
        "values": [
            {"key": "weight", "name": "Weight", "unit": "kg", "value": 80.0, "isDerived": False},
            {
                "key": "mysteryMetric",
                "name": "Mystery",
                "unit": "xyz",
                "value": 3.5,
                "isDerived": True,
            },
        ],
    }
    raw = json.dumps(payload).encode("utf-8")
    with client:
        assert client.post("/api/ingest/openscale", content=raw, headers=_auth()).status_code == 200
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            repos = repositories_for(session)
            digest = __import__("hashlib").sha256(raw).hexdigest()
            artifact = repos.raw_artifacts.get_by_content_hash(digest)
            assert artifact is not None
            stored = (paths.root / "artifacts" / artifact.relative_storage_path).read_bytes()
            assert b"mysteryTop" in stored
            assert b"mysteryMetric" in stored
            assert _count(session, ScalarMeasurement) == 1
    finally:
        engine.dispose()


def test_exact_duplicate_retry_and_lost_response(tmp_path):
    client, _settings_obj, paths = _client(tmp_path)
    body = load_fixture("insert_single.json")
    with client:
        first = client.post("/api/ingest/openscale", content=body, headers=_auth())
        second = client.post("/api/ingest/openscale", content=body, headers=_auth())
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["items"][0]["status"] == "duplicate"
        assert second.json()["items"][0]["session_id"] == first.json()["items"][0]["session_id"]
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            assert _count(session, MeasurementSession) == 1
            weights = list(
                session.scalars(
                    select(ScalarMeasurement).where(ScalarMeasurement.metric_code == "weight")
                )
            )
            assert len(weights) == 1
    finally:
        engine.dispose()


def test_update_replay_and_out_of_order(tmp_path):
    client, _settings_obj, paths = _client(tmp_path)
    insert = {
        "event": "insert",
        "id": "record-order-1",
        "userId": "synthetic-user-1",
        "date": "2026-05-01T08:00:00+03:00",
        "values": [
            {"key": "weight", "name": "Weight", "unit": "kg", "value": 70.0, "isDerived": False}
        ],
    }
    update = {
        "event": "update",
        "id": "record-order-1",
        "userId": "synthetic-user-1",
        "date": "2026-05-01T08:00:00+03:00",
        "values": [
            {"key": "weight", "name": "Weight", "unit": "kg", "value": 70.4, "isDerived": False}
        ],
    }
    older = {
        "event": "insert",
        "id": "record-order-0",
        "userId": "synthetic-user-1",
        "date": "2026-04-01T08:00:00+03:00",
        "values": [
            {"key": "weight", "name": "Weight", "unit": "kg", "value": 69.5, "isDerived": False}
        ],
    }
    with client:
        assert (
            client.post(
                "/api/ingest/openscale",
                content=json.dumps(insert).encode(),
                headers=_auth(),
            ).status_code
            == 200
        )
        updated = client.post(
            "/api/ingest/openscale",
            content=json.dumps(update).encode(),
            headers=_auth(),
        )
        assert updated.status_code == 200
        assert updated.json()["items"][0]["status"] == "committed"
        replay = client.post(
            "/api/ingest/openscale",
            content=json.dumps(update).encode(),
            headers=_auth(),
        )
        assert replay.status_code == 200
        assert replay.json()["items"][0]["status"] == "duplicate"
        assert (
            client.post(
                "/api/ingest/openscale",
                content=json.dumps(older).encode(),
                headers=_auth(),
            ).status_code
            == 200
        )
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            repos = repositories_for(session)
            source = repos.acquisition_sources.get_by_sender_instance_id(SOURCE_INSTANCE)
            assert source is not None
            heads = repos.measurement_sessions.current_heads(acquisition_source_id=source.id)
            assert len(heads) == 2
            head_ids = {head.id for head in heads}
            values = {
                row.normalized_value
                for row in session.scalars(select(ScalarMeasurement))
                if row.measurement_session_id in head_ids
            }
            assert 70.4 in values
            assert 69.5 in values
    finally:
        engine.dispose()


def test_idless_fingerprint_cases(tmp_path):
    client, _settings_obj, paths = _client(tmp_path)
    base = {
        "event": "insert",
        "userId": "synthetic-user-1",
        "date": "2026-06-01T09:00:00+03:00",
        "values": [
            {"key": "weight", "name": "Weight", "unit": "kg", "value": 72.0, "isDerived": False}
        ],
    }
    changed = {
        **base,
        "values": [
            {"key": "weight", "name": "Weight", "unit": "kg", "value": 72.5, "isDerived": False}
        ],
    }
    with client:
        first = client.post(
            "/api/ingest/openscale", content=json.dumps(base).encode(), headers=_auth()
        )
        retry = client.post(
            "/api/ingest/openscale", content=json.dumps(base).encode(), headers=_auth()
        )
        other = client.post(
            "/api/ingest/openscale", content=json.dumps(changed).encode(), headers=_auth()
        )
        assert first.status_code == 200
        assert retry.json()["items"][0]["status"] == "duplicate"
        assert other.json()["items"][0]["status"] == "committed"
        assert other.json()["items"][0]["session_id"] != first.json()["items"][0]["session_id"]
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            assert _count(session, MeasurementSession) == 2
    finally:
        engine.dispose()


def test_delete_and_clear_tombstones_with_canonical_reconsideration(tmp_path):
    client, _settings_obj, paths = _client(tmp_path)
    insert = load_fixture("insert_single.json")
    with client:
        created = client.post("/api/ingest/openscale", content=insert, headers=_auth())
        assert created.status_code == 200, created.text
        session_id = created.json()["items"][0]["session_id"]
        deleted = client.post(
            "/api/ingest/openscale", content=load_fixture("delete_fallback.json"), headers=_auth()
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["items"][0]["status"] == "committed"
        revived = client.post("/api/ingest/openscale", content=insert, headers=_auth())
        assert revived.status_code == 200, revived.text
        cleared = client.post(
            "/api/ingest/openscale", content=load_fixture("clear.json"), headers=_auth()
        )
        assert cleared.status_code == 200, cleared.text
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            repos = repositories_for(session)
            source = repos.acquisition_sources.get_by_sender_instance_id(SOURCE_INSTANCE)
            assert source is not None
            heads = repos.measurement_sessions.current_heads(acquisition_source_id=source.id)
            assert heads == []
            all_sessions = list(session.scalars(select(MeasurementSession)))
            assert all_sessions
            assert any(row.confirmation_status == "rejected" for row in all_sessions)
            assert any(row.id == session_id for row in all_sessions)
            assert _count(session, IngestEvent) >= 3
    finally:
        engine.dispose()


def test_test_event_acks_without_measurement_mutation(tmp_path):
    client, _settings_obj, paths = _client(tmp_path)
    with client:
        response = client.post(
            "/api/ingest/openscale", content=load_fixture("test.json"), headers=_auth()
        )
        assert response.status_code == 200
        assert response.json()["event"] == "test"
        assert response.json()["items"][0]["status"] == "committed"
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            assert _count(session, MeasurementSession) == 0
            assert _count(session, ScalarMeasurement) == 0
            assert _count(session, IngestBatch) == 1
    finally:
        engine.dispose()


def test_log_privacy_no_secret_or_payload_values(tmp_path):
    settings = _settings(tmp_path)
    paths = prepare_runtime(settings)
    migrate_database(paths)
    log_path = configure_logging(paths.logs)
    app, _ = create_ingest_app(settings)
    body = load_fixture("insert_single.json")
    with TestClient(app) as client:
        client.post("/api/ingest/openscale", content=body, headers=_auth())
        client.post(
            "/api/ingest/openscale",
            content=body,
            headers={"Authorization": "Bearer wrong-secret-value"},
        )
    text = log_path.read_text(encoding="utf-8")
    assert TOKEN not in text
    assert "wrong-secret-value" not in text
    assert "76.4" not in text
    assert "24.5" not in text


def test_route_isolation_ui_does_not_mount_openscale(tmp_path):
    settings = _settings(tmp_path)
    ui, _ = create_ui_app(settings)
    ingest, _ = create_ingest_app(settings)
    with TestClient(ui) as client:
        assert (
            client.post("/api/ingest/openscale", content=b"{}", headers=_auth()).status_code == 404
        )
    with TestClient(ingest) as client:
        for route in ("/", "/api/imports", "/api/weight/series", "/static/dashboard.js"):
            assert client.get(route).status_code == 404


def test_plain_lan_opt_in_and_unsafe_binding_probes():
    denied = evaluate_ingest_binding("192.168.0.5", trusted_private_lan_http=False)
    assert denied.allowed is False
    assert denied.reason_code == "plain_lan_opt_in_required"
    allowed = evaluate_ingest_binding("192.168.0.5", trusted_private_lan_http=True)
    assert allowed.allowed is True
    assert allowed.requires_plain_http_warning is True
    public = evaluate_ingest_binding("0.0.0.0", trusted_private_lan_http=True)
    assert public.allowed is False
    assert public.reason_code == "public_bind_unsupported"
    with pytest.raises(ValidationError):
        Settings(ingest_host="0.0.0.0", trusted_private_lan_http=True)
    with pytest.raises(ValidationError):
        Settings(ingest_host="10.0.0.8", trusted_private_lan_http=False)


def test_unconfigured_credential_fails_closed(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "runtime",
        openscale_source_instance_id=SOURCE_INSTANCE,
    )
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ingest_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/ingest/openscale",
            content=load_fixture("test.json"),
            headers=_auth(),
        )
        assert response.status_code == 503
        assert response.json()["code"] == "ingest_not_configured"


def test_mid_batch_invalid_does_not_roll_back_valid(tmp_path):
    client, _settings_obj, paths = _client(tmp_path)
    payload = {
        "event": "insert",
        "measurements": [
            {
                "id": "keep-1",
                "userId": "synthetic-user-1",
                "date": "2026-07-01",
                "values": [
                    {
                        "key": "weight",
                        "name": "Weight",
                        "unit": "kg",
                        "value": 68.0,
                        "isDerived": False,
                    }
                ],
            },
            "not-an-object",
            {
                "id": "keep-2",
                "userId": "synthetic-user-1",
                "date": "2026-07-02",
                "values": [
                    {
                        "key": "weight",
                        "name": "Weight",
                        "unit": "kg",
                        "value": 68.2,
                        "isDerived": False,
                    }
                ],
            },
        ],
    }
    with client:
        response = client.post(
            "/api/ingest/openscale",
            content=json.dumps(payload).encode(),
            headers=_auth(),
        )
        assert response.status_code == 200
        body = response.json()
        assert sum(1 for item in body["items"] if item["status"] == "committed") == 2
        assert sum(1 for item in body["items"] if item["status"] == "failed") == 1
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            assert _count(session, MeasurementSession) == 2
            assert _count(session, IngestEvent) == 3
    finally:
        engine.dispose()


def test_openscale_algorithm_group_distinct_from_xiaomi(tmp_path):
    client, _settings_obj, paths = _client(tmp_path)
    body = load_fixture("insert_single.json")
    with client:
        assert (
            client.post("/api/ingest/openscale", content=body, headers=_auth()).status_code == 200
        )
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            rows = list(session.scalars(select(MeasurementAlgorithm)))
            assert rows
            assert any(row.code == OPENSCALE_WEIGHT_ALGORITHM for row in rows)
            assert any(row.compatibility_group == OPENSCALE_COMPOSITION_GROUP for row in rows)
            assert all(
                not str(row.compatibility_group).startswith("xiaomi")
                for row in rows
                if row.producer == "openscale"
            )
    finally:
        engine.dispose()


def test_item_warnings_persist_duplicate_conflict_with_surviving_metrics(tmp_path):
    """Repro A: conflicting weight + usable fat keeps durable conflict diagnostic."""

    client, _settings_obj, paths = _client(tmp_path)
    payload = {
        "event": "insert",
        "measurements": [
            {
                "id": "conflict-with-fat",
                "userId": "synthetic-user-1",
                "date": "2026-03-01T08:00:00+03:00",
                "values": [
                    {
                        "key": "weight",
                        "name": "Weight",
                        "unit": "kg",
                        "value": 80.0,
                        "isDerived": False,
                    },
                    {
                        "key": "weight",
                        "name": "Weight",
                        "unit": "kg",
                        "value": 81.0,
                        "isDerived": False,
                    },
                    {
                        "key": "fat",
                        "name": "Body fat",
                        "unit": "%",
                        "value": 20.0,
                        "isDerived": False,
                    },
                ],
            }
        ],
    }
    with client:
        response = client.post(
            "/api/ingest/openscale",
            content=json.dumps(payload).encode(),
            headers={**_auth(), "Content-Type": "application/json"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["items"][0]["status"] == "committed"
        assert body["items"][0]["diagnostic_code"] == "duplicate_conflicting_values"
        assert body["items"][0]["measurement_session_id"]
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            repos = repositories_for(session)
            events = list(session.scalars(select(IngestEvent)))
            assert len(events) == 1
            assert events[0].diagnostic_code == "duplicate_conflicting_values"
            assert "80" not in (events[0].diagnostic_reason or "")
            assert "81" not in (events[0].diagnostic_reason or "")
            heads = repos.measurement_sessions.current_heads()
            assert len(heads) == 1
            metrics = {
                row.metric_code: row.normalized_value
                for row in repos.scalar_measurements.list_for_session(heads[0].id)
            }
            assert "weight" not in metrics
            assert metrics["body_fat_pct"] == pytest.approx(20.0)
    finally:
        engine.dispose()


def test_conflict_only_weight_keeps_precise_diagnostic(tmp_path):
    """Repro B: conflict-only weight fails with duplicate_conflicting_values, not generic."""

    client, _settings_obj, paths = _client(tmp_path)
    payload = {
        "event": "insert",
        "measurements": [
            {
                "id": "conflict-only",
                "userId": "synthetic-user-1",
                "date": "2026-03-01T09:00:00+03:00",
                "values": [
                    {
                        "key": "weight",
                        "name": "Weight",
                        "unit": "kg",
                        "value": 80.0,
                        "isDerived": False,
                    },
                    {
                        "key": "weight",
                        "name": "Weight",
                        "unit": "kg",
                        "value": 81.0,
                        "isDerived": False,
                    },
                ],
            }
        ],
    }
    with client:
        response = client.post(
            "/api/ingest/openscale",
            content=json.dumps(payload).encode(),
            headers={**_auth(), "Content-Type": "application/json"},
        )
        assert response.status_code == 200, response.text
        item = response.json()["items"][0]
        assert item["status"] == "failed"
        assert item["diagnostic_code"] == "duplicate_conflicting_values"
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            events = list(session.scalars(select(IngestEvent)))
            assert len(events) == 1
            assert events[0].status == "failed"
            assert events[0].diagnostic_code == "duplicate_conflicting_values"
            assert events[0].diagnostic_reason == "duplicate_conflicting_values"
            assert "80" not in (events[0].diagnostic_reason or "")
            assert repositories_for(session).measurement_sessions.current_heads() == []
    finally:
        engine.dispose()


def test_single_mode_conflict_persists_envelope_failures(tmp_path):
    client, _settings_obj, paths = _client(tmp_path)
    payload = {
        "event": "insert",
        "id": "single-conflict",
        "userId": "synthetic-user-1",
        "date": "2026-03-01T10:00:00+03:00",
        "values": [
            {"key": "weight", "name": "Weight", "unit": "kg", "value": 70.0, "isDerived": False},
            {"key": "weight", "name": "Weight", "unit": "kg", "value": 71.0, "isDerived": False},
            {"key": "fat", "name": "Body fat", "unit": "%", "value": 18.0, "isDerived": False},
        ],
    }
    with client:
        response = client.post(
            "/api/ingest/openscale",
            content=json.dumps(payload).encode(),
            headers={**_auth(), "Content-Type": "application/json"},
        )
        assert response.status_code == 200, response.text
        item = response.json()["items"][0]
        assert item["status"] == "committed"
        assert item["diagnostic_code"] == "duplicate_conflicting_values"
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            events = list(session.scalars(select(IngestEvent)))
            assert events[0].diagnostic_code == "duplicate_conflicting_values"
            heads = repositories_for(session).measurement_sessions.current_heads()
            metrics = {
                row.metric_code: row.normalized_value
                for row in repositories_for(session).scalar_measurements.list_for_session(
                    heads[0].id
                )
            }
            assert "weight" not in metrics
            assert metrics["body_fat_pct"] == pytest.approx(18.0)
    finally:
        engine.dispose()
