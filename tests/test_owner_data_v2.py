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


def _sleep_get(app, **override):
    params = {"evaluated_at_utc": "2099-01-05T23:00:00Z", "evaluation_local_date": "2099-01-05"}
    params.update(override)
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        return client.get("/api/imports/saved-sleep", params=params)


def test_data_saved_sleep_exact_reader_snapshot_no_db_change(data_ui, monkeypatch):
    from datetime import date
    from hashlib import sha256

    from sqlalchemy import text

    from healthcheck.db.models import GoogleSleepRecord, SyncStreamState
    from healthcheck.saved_sleep import read_saved_sleep
    from healthcheck.web import imports
    from test_sleep_metrics import _google_sleep_payload, _persist_garmin, _persist_google

    app, settings, paths = data_ui
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            _persist_garmin(session, paths)
            _persist_google(session, paths, payload=_google_sleep_payload())
            session.scalar(select(GoogleSleepRecord)).wake_date = date(2099, 1, 1)
        with session_scope(engine) as session:
            expected = [read_saved_sleep(
                session, provider=p, evaluation_local_date=date(2099, 1, 5),
            ) for p in ("garmin", "google")]
        # Neither credentials failure nor disabled collection removes saved sleep.
        from healthcheck.collection_policy import set_collection_policy
        from healthcheck.db.models import GarminSource
        with session_scope(engine) as session:
            source = session.scalar(select(GarminSource))
            session.add(SyncStreamState(
                provider_id=source.provider_id, stream_code="sleep",
                diagnostic_status="reauth_required",
            ))
        set_collection_policy(settings, stream="google:heart_rate", state="off")
    finally:
        engine.dispose()
    connections = []
    reader = imports.read_saved_sleep
    def inspect(session, **kwargs):
        connection = session.connection().connection.driver_connection
        assert connection.in_transaction and session.scalar(text("PRAGMA query_only")) == 1
        connections.append(connection)
        return reader(session, **kwargs)
    monkeypatch.setattr(imports, "read_saved_sleep", inspect)
    before = sha256(paths.database.read_bytes()).hexdigest()
    response = _sleep_get(app)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["items"] == expected
    assert connections[0] is connections[1] and len(connections) == 2
    assert sha256(paths.database.read_bytes()).hexdigest() == before
    assert [i["observation"]["observation_age_days"] for i in expected] == [3, 4]


def test_data_saved_sleep_safe_clock_database_and_read_failure(data_ui, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from healthcheck.web import imports
    app, _, paths = data_ui
    assert _sleep_get(app, evaluated_at_utc="2099-01-05T12:00:00").status_code == 422
    assert _sleep_get(app, google_source_id=" ").status_code == 422
    def fail(*args, **kwargs):
        raise OperationalError("synthetic-secret", {}, Exception("private-path"))
    monkeypatch.setattr(imports, "read_saved_sleep", fail)
    response = _sleep_get(app)
    assert response.status_code == 503
    assert response.json() == {"code": "saved_sleep_read_unavailable"}
    paths.database.unlink()
    assert _sleep_get(app).json() == {"code": "database_unavailable"}


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
    expected = read_saved_rhr(
        session, _query(stored, source_id=None),
        google_auto_select=source.provider_code == "google_health",
    ).as_dict()
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
def test_data_saved_rhr_metric_first_choice_and_exact_override_keep_provider_dates(data_saved):
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
    assert body["items"][1]["source_selection"]["state"] == "unique_eligible_source"
    assert body["items"][1]["source_identity"]["source_id"] == stored[2].id
    assert body["items"][1]["query"]["source_id"] is None
    assert len(body["items"][1]["available_sources"]) == 2
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

    def inspect(session, query, **kwargs):
        connection = session.connection().connection.driver_connection
        assert connection.in_transaction
        assert session.scalar(text("PRAGMA query_only")) == 1
        connections.append(connection)
        return reader(session, query, **kwargs)

    monkeypatch.setattr(imports, "read_saved_rhr", inspect)
    assert _saved_get(app).status_code == 200
    assert len(connections) == 2 and connections[0] is connections[1]


@pytest.mark.parametrize("data_saved", ["google_health"], indirect=True)
def test_data_google_candidates_share_snapshot_write_denial_and_sql_deadline(
    data_saved, monkeypatch,
):
    import sqlite3
    from types import SimpleNamespace

    from sqlalchemy import text

    from healthcheck import saved_values
    from healthcheck.web import imports
    from test_saved_values import GoogleSourceRepository, _family_identity, _seed

    app, _, paths, stored = data_saved
    _seed(stored)
    GoogleSourceRepository(stored[0]).get_or_create(_family_identity())
    stored[0].commit()
    original = saved_values._read_saved_rhr
    connections, exact_sources = [], []

    def inspect(session, query, *args, **kwargs):
        driver = session.connection().connection.driver_connection
        assert driver.in_transaction and session.scalar(text("PRAGMA query_only")) == 1
        connections.append(driver)
        if query.source_id:
            exact_sources.append(query.source_id)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            driver.execute("CREATE TABLE synthetic_forbidden (id INTEGER)")
        return original(session, query, *args, **kwargs)

    monkeypatch.setattr(saved_values, "_read_saved_rhr", inspect)
    from hashlib import sha256
    before = sha256(paths.database.read_bytes()).hexdigest()
    assert _saved_get(app).json()["items"][1]["observation"]["value"] == 61
    assert len(set(map(id, connections))) == 1 and len(set(exact_sources)) == 2
    assert sha256(paths.database.read_bytes()).hexdigest() == before

    # Exercise the installed production SQL progress handler, not a mock error.
    clock = [0]
    monkeypatch.setattr(imports, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    def deadline_probe(session, query, **kwargs):
        clock[0] = 11
        try:
            session.connection().connection.driver_connection.execute(
                "SELECT count(*) FROM sqlite_master a CROSS JOIN sqlite_master b "
                "CROSS JOIN sqlite_master c"
            ).fetchone()
        except sqlite3.OperationalError as exc:
            assert str(exc) == "interrupted"
            raise
        pytest.fail("Data SQL deadline did not interrupt work")
    monkeypatch.setattr(imports, "read_saved_rhr", deadline_probe)
    response = _saved_get(app)
    assert response.status_code == 503 and response.json() == {"code": "database_unavailable"}


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
    import re
    import subprocess
    from pathlib import Path

    app, _settings, _paths = _ui(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        packet = client.get("/api/source-freshness", params={
            "evaluated_at_utc": "2099-01-01T12:00:00Z",
            "evaluation_local_date": "2099-01-01",
        }).json()
        html = client.get("/imports").text
        sources = html.split('id="data-status"', 1)[1].split("</section>", 1)[0]
        disclosure = re.search(r"<details\b([^>]*)>(.*?)</details>", sources, re.S)
        assert disclosure is not None
        assert "owner-info" in disclosure[1]
        assert not re.search(r"\bopen\b", disclosure[1])
        assert "О проверке источников" in disclosure[2]
        assert "не проверяет подключение к Garmin или Google в этой сессии" in disclosure[2]
        assert "возраст снимка отдельно не определяется" in disclosure[2]
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
