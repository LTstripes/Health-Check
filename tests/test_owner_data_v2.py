"""Synthetic production-route regressions for Owner Data presentation."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from healthcheck.db.engine import create_sqlite_engine, session_scope
from healthcheck.db.models import IngestBatch
from healthcheck.ingestion.photo.synthetic import six_month_synthetic_batch
from healthcheck.ingestion.photo.vision import UnconfiguredImageMeasurementExtractor
from test_dashboard_ui import _canonical_snapshot, _confirm_all_pending, _ui, _upload_batch


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
