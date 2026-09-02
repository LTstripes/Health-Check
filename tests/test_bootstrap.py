from __future__ import annotations

import json

from fastapi.testclient import TestClient

from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine
from healthcheck.logging import configure_logging, log_event
from healthcheck.runtime import prepare_runtime
from healthcheck.web.ingest_app import create_ingest_app
from healthcheck.web.ui_app import create_ui_app


def test_runtime_override_creates_external_layout(tmp_path, monkeypatch):
    runtime = tmp_path / "Health-Check"
    monkeypatch.setenv("HEALTHCHECK_DATA_DIR", str(runtime))

    paths = prepare_runtime(Settings())

    assert paths.root == runtime.resolve()
    assert paths.config.is_file()
    assert paths.photos.is_dir()
    assert paths.payloads.is_dir()
    assert paths.logs.is_dir()
    assert not (tmp_path / "healthcheck.db").exists()


def test_listener_health_endpoints_are_non_sensitive(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    ui_app, _ = create_ui_app(settings)
    ingest_app, _ = create_ingest_app(settings)

    with TestClient(ui_app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "loopback-ui"}
        assert client.get("/").status_code == 200

    with TestClient(ingest_app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "ingest"}
        routes = ("/", "/api/imports", "/api/weight/series", "/settings", "/api/ingest/openscale")
        for route in routes:
            assert client.get(route).status_code == 404


def test_ingest_app_has_only_liveness_route(tmp_path):
    app, _ = create_ingest_app(Settings(data_dir=tmp_path / "runtime"))
    assert [route.path for route in app.routes] == ["/healthz"]


def test_sqlite_bootstrap_enables_wal_and_foreign_keys(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    engine = create_sqlite_engine(paths)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    engine.dispose()
    assert paths.database.is_file()


def test_structured_log_drops_arbitrary_health_and_secret_fields(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    log_path = configure_logging(paths.logs)
    log_event("synthetic_request", token="secret-token", measurement="72.4", status="ok")

    record = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert record == {
        "event": "synthetic_request",
        "level": "INFO",
        "status": "ok",
        "timestamp": record["timestamp"],
    }
    assert "secret-token" not in log_path.read_text(encoding="utf-8")
    assert "72.4" not in log_path.read_text(encoding="utf-8")


def test_no_database_is_created_by_health_only(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    app, _ = create_ui_app(settings)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
    assert not (tmp_path / "runtime" / "healthcheck.db").exists()
