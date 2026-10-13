"""Synthetic production-route regressions for Owner Data presentation."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from healthcheck.db.engine import create_sqlite_engine, session_scope
from healthcheck.db.models import IngestBatch
from healthcheck.ingestion.photo.synthetic import six_month_synthetic_batch
from healthcheck.ingestion.photo.vision import UnconfiguredImageMeasurementExtractor
from test_dashboard_ui import _canonical_snapshot, _confirm_all_pending, _ui, _upload_batch


@pytest.fixture(scope="module")
def data_schema(tmp_path_factory):
    # Migrate once, then give every scenario its own disposable synthetic DB.
    return _ui(tmp_path_factory.mktemp("data-rhr-schema"))[2].database


@pytest.fixture
def data_ui(tmp_path, data_schema):
    import sqlite3
    from contextlib import closing

    from healthcheck.config import Settings
    from healthcheck.runtime import prepare_runtime
    from healthcheck.web.ui_app import create_ui_app

    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    with closing(sqlite3.connect(f"file:{data_schema.as_posix()}?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(paths.database)) as target:
            source.backup(target)
    app, _ = create_ui_app(settings)
    return app, settings, paths


@pytest.fixture
def data_saved(data_ui, request):
    from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
    from healthcheck.google.storage import ContentAddressedGooglePayloadStore
    from test_saved_values import (
        GARMIN_IDENTITY,
        GarminSourceRepository,
        GoogleSourceRepository,
        _fitbit_identity,
    )

    app, settings, paths = data_ui
    engine = create_sqlite_engine(paths)
    with session_scope(engine) as session:
        garmin = GarminSourceRepository(session).get_or_create(GARMIN_IDENTITY)
        google = GoogleSourceRepository(session).get_or_create(_fitbit_identity())
        session.flush()
        provider = request.param
        stored = (session, ContentAddressedGarminPayloadStore(paths.root / "garmin"),
                  garmin, "resting_heart_rate_bpm") if provider == "garmin_connect" else (
            session, ContentAddressedGooglePayloadStore(paths.root / "google"),
            google, "daily_resting_heart_rate_bpm")
        yield app, settings, paths, stored
    engine.dispose()


def _saved_get(app, **override):
    params = {"evaluated_at_utc": "2099-01-03T23:00:00Z", "evaluation_local_date": "2099-01-03"}
    params.update(override)
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        return client.get("/api/imports/saved-rhr", params=params)


@pytest.mark.parametrize("data_saved", ["garmin_connect", "google_health"], indirect=True)
@pytest.mark.parametrize("scenario", [
    "today", "old", "zero", "missing", "null", "invalid", "ambiguous", "retired",
    "correction", "partial", "empty", "cap", "reauth", "disabled",
])
def test_saved_rhr_data_route_keeps_exact_reader_dto(data_saved, scenario):
    from datetime import timedelta

    from healthcheck.collection_policy import set_collection_policy
    from healthcheck.db.models import SyncStreamState
    from healthcheck.saved_values import read_saved_rhr
    from test_saved_values import DAY, NOW, _copy, _query, _seed

    app, settings, paths, stored = data_saved
    session, _, source, _ = stored
    if scenario != "empty":
        _seed(stored, day=DAY - timedelta(days=3), value=58)
    if scenario not in {"old", "empty", "reauth", "disabled"}:
        record, metric = _seed(stored, value=0 if scenario == "zero" else 61)
        if scenario in {"missing", "null", "invalid"}:
            metric.state, metric.value_number = scenario, None
        elif scenario in {"ambiguous", "cap"}:
            for index in range(256 if scenario == "cap" else 1):
                copied = _copy(stored, record, metric)
                copied.idempotency_key = f"data-cap-{index}"
                session.flush()
                record = copied
        elif scenario == "retired":
            record.projection_status, record.retired_at = "retired", NOW
            record.retire_reason = "synthetic-correction"
        elif scenario == "correction":
            metric.value_number = 59
        elif scenario == "partial":
            record.record_status = "partial"
    if scenario == "reauth":
        session.add(SyncStreamState(
            provider_id=source.provider_id,
            stream_code="resting_heart_rate" if source.provider_code == "garmin_connect"
            else "google:refresh:daily_resting_hr:list:any",
            last_attempt_at=NOW, diagnostic_status="reauth_required",
        ))
    session.commit()
    expected = read_saved_rhr(session, _query(stored, source_id=None)).as_dict()
    if scenario == "disabled":
        set_collection_policy(settings, stream="google:heart_rate", state="off")
    from hashlib import sha256
    before = sha256(paths.database.read_bytes()).hexdigest()
    response = _saved_get(app)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    body = response.json()
    dto = next(item for item in body["items"]
               if item["query"]["provider_code"] == source.provider_code)
    assert dto == expected
    assert sha256(paths.database.read_bytes()).hexdigest() == before
    assert dto["origin_state"] == "unknown" and dto["age_policy"] == "not_configured"
    if scenario == "cap":
        assert dto["state"] == "search_incomplete" and dto["observation"] is None
        assert dto["search"]["incomplete_group_date"] == DAY.isoformat()
    if scenario in {"reauth", "disabled"}:
        assert dto["observation"]["value"] == 58
    if scenario == "reauth":
        assert dto["refresh"]["terminal_status"] == "reauth_required"
    if scenario == "disabled":
        assert body["collection_policy"]["disabled_streams"] == ["google:heart_rate"]


@pytest.mark.parametrize("data_saved", ["google_health"], indirect=True)
def test_data_saved_rhr_requires_explicit_identity_and_keeps_provider_dates(data_saved):
    from datetime import timedelta

    from test_saved_values import (
        DAY,
        GARMIN_IDENTITY,
        GarminSourceRepository,
        GoogleSourceRepository,
        _family_identity,
        _seed,
    )

    app, _, _, stored = data_saved
    session = stored[0]
    _seed(stored, day=DAY - timedelta(days=4), value=59)
    second = GoogleSourceRepository(session).get_or_create(_family_identity())
    garmin = GarminSourceRepository(session).get_or_create(GARMIN_IDENTITY)
    from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
    _seed((session, ContentAddressedGarminPayloadStore(app.state.runtime_paths.root / "garmin"),
           garmin, "resting_heart_rate_bpm"), day=DAY, value=62)
    session.commit()
    body = _saved_get(app).json()
    assert body["items"][0]["observation"]["source_local_date"] == DAY.isoformat()
    assert body["items"][1]["reason"] == "source_selection_required"
    assert body["items"][1]["observation"] is None
    selected = _saved_get(app, google_source_id=stored[2].id).json()["items"][1]
    assert selected["observation"]["source_local_date"] == (DAY - timedelta(days=4)).isoformat()
    assert selected["observation"]["observation_age_days"] == 4
    assert _saved_get(app, google_source_id=second.id).json()["items"][1]["observation"] is None
    unknown = _saved_get(app, google_source_id="unknown").json()["items"][1]
    crossed = _saved_get(app, garmin_source_id=stored[2].id).json()["items"][0]
    assert unknown["reason"] == crossed["reason"] == "source_not_found"


def test_data_saved_rhr_invalid_clock_and_missing_db_are_safe(data_ui):
    app, _, paths = data_ui
    assert _saved_get(app, evaluated_at_utc="2099-01-03T12:00:00").status_code == 422
    assert _saved_get(app, google_source_id=" ").status_code == 422
    paths.database.unlink()
    response = _saved_get(app)
    assert response.status_code == 503 and response.json() == {"code": "database_unavailable"}


def test_data_saved_rhr_reuses_one_physical_read_only_snapshot(data_ui, monkeypatch):
    from sqlalchemy import text

    from healthcheck.web import imports
    app, _, _ = data_ui
    reader = imports.read_saved_rhr
    connections = []

    def inspect(session, query):
        connection = session.connection().connection.driver_connection
        assert connection.in_transaction
        assert session.scalar(text("PRAGMA query_only")) == 1
        connections.append(connection)
        return reader(session, query)

    monkeypatch.setattr(imports, "read_saved_rhr", inspect)
    assert _saved_get(app).status_code == 200
    assert len(connections) == 2 and connections[0] is connections[1]


@pytest.mark.parametrize("data_saved", ["google_health"], indirect=True)
def test_data_saved_rhr_inventory_cap_and_read_failure(data_saved, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from healthcheck import saved_values
    from test_saved_values import GoogleSourceRepository, _family_identity

    app, _, _, stored = data_saved
    GoogleSourceRepository(stored[0]).get_or_create(_family_identity())
    stored[0].commit()
    monkeypatch.setattr(saved_values, "MAX_SOURCE_IDENTITIES", 1)
    dto = _saved_get(app).json()["items"][1]
    assert dto["state"] == "search_incomplete" and dto["reason"] == "source_inventory_cap"
    assert dto["available_sources"] == [] and dto["observation"] is None

    def fail(*args, **kwargs):
        raise OperationalError("synthetic-secret", {}, Exception("private-path"))

    monkeypatch.setattr(saved_values, "_read_saved_rhr", fail)
    body = _saved_get(app).json()
    assert all(item["reason"] == "saved_value_read_failed" for item in body["items"])
    assert "synthetic-secret" not in str(body) and "private-path" not in str(body)


def test_data_saved_rhr_production_script_synthetic_dom(data_ui):
    import json
    import subprocess
    from pathlib import Path

    app, _, _ = data_ui
    packet = _saved_get(app).json()
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", str(repo / "scripts/check_data_saved_rhr.cjs")], cwd=repo,
        input=json.dumps(packet), capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert result.stdout.startswith("PASS:")


def test_data_provider_summary_synthetic_dom(tmp_path):
    import json
    import subprocess
    from pathlib import Path

    app, _settings, _paths = _ui(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        packet = client.get("/api/source-freshness", params={
            "evaluated_at_utc": "2099-01-01T12:00:00Z",
            "evaluation_local_date": "2099-01-01",
        }).json()
        html = client.get("/imports").text
        assert "не проверяет подключение к ним сейчас" in html
        assert "дата снимка профиля здесь не определяется" in html
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", str(repo / "scripts/check_data_status.cjs")], cwd=repo,
        input=json.dumps(packet), capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert result.stdout.startswith("PASS:")


def test_pending_candidates_precede_newer_completed_history_without_writes(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        pending = _upload_batch(client, six_month_synthetic_batch()[:1]).json()["id"]
        completed = _upload_batch(client, six_month_synthetic_batch()[1:2]).json()["id"]
        _confirm_all_pending(client, completed)
        engine = create_sqlite_engine(paths)
        try:
            with session_scope(engine) as session:
                session.scalar(select(IngestBatch).where(IngestBatch.id == pending)).status = (
                    "committed"
                )
        finally:
            engine.dispose()
        before = _canonical_snapshot(paths)
        html = client.get("/imports").text
        assert html.index(f'href="/imports/{pending}"') < html.index('id="completed-imports"')
        assert html.index('id="completed-imports"') < html.index(f'href="/imports/{completed}"')
        assert '<details class="owner-details" id="completed-imports">' in html
        assert "Проверить измерения" in html and "Открыть детали" in html
        assert 'class="import-started" datetime="' in html
        assert "UTC</time>" in html
        assert _canonical_snapshot(paths) == before


def test_unconfigured_extraction_disables_upload_but_keeps_existing_review(tmp_path):
    app, _settings, _paths = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        batch = _upload_batch(client, six_month_synthetic_batch()[:1]).json()["id"]
        configured = client.get("/imports").text
        assert 'data-configured="true"' in configured
        assert "Работа на твоих снимках здесь не подтверждена" in configured
        app.state.photo_extractor = UnconfiguredImageMeasurementExtractor()
        html = client.get("/imports").text
        assert 'data-configured="false"' in html
        assert "Распознавание фото не настроено" in html
        assert 'multiple required disabled' in html
        assert f'href="/imports/{batch}"' in html
        review = client.get(f"/imports/{batch}").text
        assert "Подтвердить выбранные" in review and "Отклонить выбранные" in review


def test_freshness_missing_database_returns_only_safe_code(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    paths.database.unlink()
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        response = client.get("/api/source-freshness", params={
            "evaluated_at_utc": "2099-01-01T12:00:00Z",
            "evaluation_local_date": "2099-01-01",
        })
        assert response.status_code == 503
        assert response.json() == {"code": "database_unavailable"}


def test_freshness_internal_failure_never_returns_exception_details(tmp_path, monkeypatch):
    app, _settings, _paths = _ui(tmp_path)

    def fail_read(*args, **kwargs):
        raise ValueError("synthetic-private-path token=synthetic-secret")

    monkeypatch.setattr("healthcheck.web.source_freshness.read_facts", fail_read)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", raise_server_exceptions=False
    ) as client:
        response = client.get("/api/source-freshness", params={
            "evaluated_at_utc": "2099-01-01T12:00:00Z",
            "evaluation_local_date": "2099-01-01",
        })
        assert response.status_code == 500
        assert response.json() == {"code": "internal_error", "message": "request failed"}
