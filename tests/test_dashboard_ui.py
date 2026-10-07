"""API/UI smoke for the local dashboard and photo-review queue.

Fixtures are synthetic.  No owner screenshots, live health values, or secrets
enter this file.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from healthcheck.canonical import (
    DASHBOARD_WEIGHT_SCOPE,
    CanonicalCandidate,
    CanonicalSelectionService,
    dashboard_composition_scope,
)
from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import (
    CanonicalRuleSet,
    CanonicalSelection,
    CanonicalSelectionRun,
    ImportCandidate,
    IngestBatch,
    IngestEvent,
    MeasurementSession,
    RunStatus,
    ScalarMeasurement,
)
from healthcheck.db.repositories import repositories_for
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.ingestion.photo.provenance import ensure_photo_acquisition_source
from healthcheck.ingestion.photo.service import PhotoImportService
from healthcheck.ingestion.photo.synthetic import (
    encode_synthetic_png,
    six_month_synthetic_batch,
    weigh_in_payload,
)
from healthcheck.runtime import prepare_runtime
from healthcheck.web.ingest_app import create_ingest_app
from healthcheck.web.ui_app import create_ui_app


class _OwnerShellParser(HTMLParser):
    """Inspect rendered semantics without depending on whitespace or CSS classes."""

    def __init__(self, html):
        super().__init__()
        self.in_nav = False
        self.in_h1 = False
        self.links = []
        self.headings = []
        self.details = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "nav" and attributes.get("aria-label") in {
            "Primary navigation",
            "Основная навигация",
            "Основные разделы",
        }:
            self.in_nav = True
        if tag == "a" and self.in_nav:
            self.links.append([attributes, ""])
        if tag == "h1":
            self.in_h1 = True
            self.headings.append("")
        if tag == "details":
            self.details.append(attributes)

    def handle_endtag(self, tag):
        if tag == "nav":
            self.in_nav = False
        if tag == "h1":
            self.in_h1 = False

    def handle_data(self, data):
        if self.in_nav and self.links:
            self.links[-1][1] += data.strip()
        if self.in_h1:
            self.headings[-1] += data


def _ui(tmp_path, **settings_values):
    settings = Settings(data_dir=tmp_path / "runtime", **settings_values)
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())
    return app, settings, paths


def _upload_batch(client, batch=None):
    items = batch if batch is not None else six_month_synthetic_batch()
    return client.post(
        "/api/imports/photos",
        files=[("files", (name, content, "image/png")) for name, content, _payload in items],
    )


def _confirm_all_pending(client, batch_id):
    detail = client.get(f"/api/imports/{batch_id}")
    assert detail.status_code == 200
    pending = [
        item["id"]
        for item in detail.json()["candidates"]
        if item["user_decision"] == "pending"
    ]
    if not pending:
        return []
    confirmed = client.post("/api/import-candidates/confirm", json={"candidate_ids": pending})
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()["confirmed"]


def test_empty_dashboard_does_not_fabricate_zeros(tmp_path):
    app, _settings, _paths = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "text/html" in page.headers["content-type"]
        assert "Потребительский биоимпеданс" in page.text
        assert "не ставит диагнозы" in page.text
        assert "Текущий подтверждённый вес" in page.text
        assert "Это не означает ноль" in page.text
        assert "Consumer bioimpedance" in page.text  # exact backend wording stays in technical JSON
        series = client.get("/api/weight/series")
        assert series.status_code == 200
        body = series.json()
        assert body["raw_points"] == []
        assert body["trend_available"] is False
        assert body["trend_reason"] == "no_data"
        assert body["current"]["value_kg"] is None
        assert body["current"]["reason"] == "no_data"
        summary = client.get("/api/weight/summary").json()
        assert summary["rate"]["available"] is False
        assert summary["rate"]["slope_kg_per_week"] is None
        assert summary["rate"]["reason"] in {
            "no_data",
            "insufficient_observations",
            "insufficient_span",
        }
        primary = page.text.split("Технические детали")[0]
        assert "0 кг" not in primary or "Текущий подтверждённый вес" in page.text
        assert 'data-owner-state="unavailable"' in page.text


def test_pending_extraction_is_not_confirmed_or_canonical(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        uploaded = _upload_batch(client, six_month_synthetic_batch()[:3])
        assert uploaded.status_code == 200
        assert uploaded.json()["status"] == "pending-confirmation"
        series = client.get("/api/weight/series").json()
        assert series["raw_points"] == []
        assert series["canonical"]["selection_count"] == 0
        page = client.get("/")
        assert "Нет подтверждённых измерений" in page.text
        assert 'data-owner-state="unavailable"' in page.text
        engine = create_sqlite_engine(paths)
        try:
            with session_scope(engine) as session:
                assert session.scalar(select(func.count(MeasurementSession.id))) == 0
                assert session.scalar(select(func.count(ScalarMeasurement.id))) == 0
                assert session.scalar(select(func.count(CanonicalSelection.id))) == 0
                assert session.scalar(select(func.count(CanonicalSelectionRun.id))) == 0
                assert session.scalar(select(func.count(ImportCandidate.id))) >= 6
        finally:
            engine.dispose()


def test_review_edit_reject_confirm_and_dashboard_points(tmp_path):
    app, _settings, _paths = _ui(tmp_path)
    png = encode_synthetic_png(
        weigh_in_payload(source_local_date=date(2026, 3, 4), weight_kg=81.2, body_fat_pct=24.4)
    )
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        uploaded = client.post(
            "/api/imports/photos", files=[("files", ("one.png", png, "image/png"))]
        )
        batch_id = uploaded.json()["id"]
        review = client.get(f"/imports/{batch_id}")
        assert review.status_code == 200
        assert "Что будет сохранено" in review.text
        assert "81.2" in review.text
        assert "До подтверждения кандидаты не попадают в измерения" in review.text
        candidates = uploaded.json()["candidates"]
        weight = next(item for item in candidates if item["metric_code"] == "weight")
        fat = next(item for item in candidates if item["metric_code"] == "body_fat_pct")
        review_provenance = weight["provenance"]
        assert review_provenance["provider_code"] == "xiaomi_home"
        assert review_provenance["provider_display_name"] == "Xiaomi Home"
        assert review_provenance["input_method"] == "photo_import"
        assert review_provenance["device_code"] == "xiaomi_s400"
        assert review_provenance["device_model"] == "S400"
        assert review_provenance["algorithm_compatibility_state"] == "not_evidenced"
        assert review_provenance["temporal_precision"] == "date"
        assert "Provider/source" in review.text
        assert "Xiaomi Home" in review.text
        assert "Input method" in review.text
        assert "photo_import" in review.text
        assert "Physical device" in review.text
        assert "xiaomi_s400" in review.text
        assert "Algorithm" in review.text
        assert "unknown / not evidenced" in review.text
        assert "not evidenced (date-only)" in review.text
        assert "authorization" not in review.text.lower()
        assert "token" not in review.text.lower()
        edited = client.post(
            f"/imports/{batch_id}/edit",
            data={
                "candidate_id": weight["id"],
                "edited_value": "80.4",
                "edited_unit": "kg",
                "edited_source_local_date": "2026-03-04",
            },
            follow_redirects=True,
        )
        assert edited.status_code == 200
        assert "80.4" in edited.text
        rejected = client.post(
            f"/imports/{batch_id}/reject",
            data={"candidate_ids": fat["id"], "reason": "unreadable"},
            follow_redirects=True,
        )
        assert rejected.status_code == 200
        confirmed = client.post(
            f"/imports/{batch_id}/confirm",
            data={"candidate_ids": weight["id"]},
            follow_redirects=True,
        )
        assert confirmed.status_code == 200
        series = client.get("/api/weight/series").json()
        assert len(series["raw_points"]) == 1
        assert series["raw_points"][0]["value_kg"] == 80.4
        assert series["raw_points"][0]["metric_origin"] == "source-provider"
        provenance = series["raw_points"][0]["provenance"]
        assert provenance["provider_code"]
        assert provenance["device_code"]
        assert provenance["input_method"] == "photo_import"
        assert provenance["algorithm_code"]
        assert "token" not in str(provenance).lower()
        assert "authorization" not in str(provenance).lower()
        assert "configuration_snapshot" not in provenance
        dashboard = client.get("/")
        assert "80.4" in dashboard.text
        assert "21-дневное взвешенное среднее" in dashboard.text
        assert "Текущий подтверждённый вес" in dashboard.text
        summary = client.get("/api/weight/summary").json()
        assert summary["latest_composition"]["available"] is False
        assert summary["latest_composition"]["reason"]


def test_six_month_history_dashboard_smoke(tmp_path):
    app, settings, _paths = _ui(tmp_path, weight_goal_kg=76.0)
    del settings
    batch = six_month_synthetic_batch()
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        uploaded = _upload_batch(client, batch)
        assert uploaded.status_code == 200
        _confirm_all_pending(client, uploaded.json()["id"])
        series = client.get("/api/weight/series").json()
        assert len(series["raw_points"]) == 26
        assert series["trend_available"] is True
        assert series["goal_kg"] == 76.0
        assert series["current"]["available"] is True
        assert series["canonical"]["available"] is True
        assert series["canonical"]["selection_count"] == 26
        assert sum(1 for point in series["raw_points"] if point["canonical_selected"]) == 26
        summary = client.get("/api/weight/summary").json()
        assert summary["rate"]["available"] is True
        assert summary["rate"]["slope_kg_per_week"] is not None
        assert summary["coverage"]["observed_dates"]
        assert summary["coverage"]["freshness_days"] is not None
        assert summary["latest_composition"]["available"] is True
        assert summary["latest_composition"]["estimated_fat_mass_kg"] is not None
        assert "healthcheck-derived" in str(series["composition_by_group"])
        page = client.get("/")
        html = page.text
        assert page.status_code == 200
        assert "data-series" in html or "weight-chart" in html
        assert "Theil–Sen" in html or "Theil" in html
        assert "76.0" in html or "76" in html
        assert "Текущий подтверждённый вес" in html
        assert "Изменение за последнее время" in html
        assert "Покрытие и свежесть" in html
        assert "Состав тела во времени" in html
        assert "Оценки жира и сухой массы" in html
        assert "Мышцы источника" in html
        assert "Потребительский биоимпеданс" in html
        # Exact backend wording stays in technical JSON, not primary copy.
        assert "Estimated fat mass" in html
        assert "Source muscle" in html
        assert "Consumer bioimpedance" in html
        primary = html.split("Технические детали", 1)[0]
        assert "Estimated fat mass" not in primary
        assert "Source muscle" not in primary
        assert "Consumer bioimpedance" not in primary
        assert "Проверить состояние источников" in html
        assert 'href="/imports' in html
        static_css = client.get("/static/dashboard.css")
        static_js = client.get("/static/dashboard.js")
        assert static_css.status_code == 200
        assert static_js.status_code == 200


def test_incompatible_composition_groups_are_separated(tmp_path):
    app, settings, paths = _ui(tmp_path)
    from healthcheck.db.repositories import repositories_for

    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            repos = repositories_for(session)
            xiaomi = repos.providers.get_or_create("xiaomi_home", "Xiaomi Home", "scale_app")
            openscale = repos.providers.get_or_create("openscale", "openScale", "scale_app")
            device = repos.physical_devices.get_or_create(
                "xiaomi_s400", manufacturer="Xiaomi", model="S400"
            )
            x_source = repos.acquisition_sources.get_or_create(
                provider_id=xiaomi.id, physical_device_id=device.id, input_method="photo_import"
            )
            o_source = repos.acquisition_sources.get_or_create(
                provider_id=openscale.id, physical_device_id=device.id, input_method="webhook"
            )
            x_alg = repos.measurement_algorithms.get_or_create(
                code="xiaomi_home_s400_unknown_version",
                version="unknown",
                metric_family="body_composition",
                producer="xiaomi",
                compatibility_group="xiaomi-home-unknown",
            )
            o_alg = repos.measurement_algorithms.get_or_create(
                code="openscale_brozek",
                version="2",
                metric_family="body_composition",
                producer="openscale",
                compatibility_group="openscale-brozek",
            )
            w_alg = repos.measurement_algorithms.get_or_create(
                code="xiaomi_s400_weight",
                version="1",
                metric_family="weight",
                producer="xiaomi",
                compatibility_group="xiaomi-s400-weight",
            )
            for index, (source, fat_alg, group) in enumerate(
                ((x_source, x_alg, "xiaomi"), (o_source, o_alg, "openscale"))
            ):
                measured = repos.measurement_sessions.create_confirmed(
                    acquisition_source_id=source.id,
                    semantic_key=f"{group}-weigh-in",
                    source_local_date=date(2026, 4, 1 + index),
                    temporal_precision="date",
                )
                repos.scalar_measurements.create(
                    measurement_session_id=measured.id,
                    metric_code="weight",
                    normalized_value=80.0,
                    normalized_unit="kg",
                    measurement_algorithm_id=w_alg.id,
                )
                repos.scalar_measurements.create(
                    measurement_session_id=measured.id,
                    metric_code="body_fat_pct",
                    normalized_value=24.0 + index,
                    normalized_unit="%",
                    measurement_algorithm_id=fat_alg.id,
                )
            CanonicalSelectionService(session).recompute_dashboard()
    finally:
        engine.dispose()

    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        series = client.get("/api/weight/series").json()
        groups = series["composition_by_group"]
        assert "xiaomi-home-unknown" in groups
        assert "openscale-brozek" in groups
        assert series["algorithm_boundary"]["present"] is True
        page = client.get("/")
        assert "Каждый ряд — отдельная группа совместимых методов расчёта" in page.text
        assert "У групп свои даты измерений" in page.text
        assert "Это не общий фильтр по времени" in page.text
        assert "Несовместимые методы показаны отдельно" in page.text
        assert "точки разных групп не соединяются линией" in page.text
        assert "xiaomi-home-unknown" in page.text
        assert "openscale-brozek" in page.text
    del settings


def test_ingest_listener_does_not_expose_dashboard_or_import_routes(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    ingest, _ = create_ingest_app(settings)
    ui, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())
    forbidden = (
        "/",
        "/imports",
        "/imports/demo",
        "/api/imports",
        "/api/imports/photos",
        "/api/weight/series",
        "/api/weight/summary",
        "/api/artifacts/demo",
        "/static/dashboard.js",
        "/static/dashboard.css",
        "/settings",
    )
    with TestClient(ingest) as client:
        assert client.get("/healthz").json() == {"status": "ok", "service": "ingest"}
        assert client.get("/api/ingest/openscale").status_code == 405
        # Without configured credentials the route exists but fails closed.
        assert client.post("/api/ingest/openscale", content=b"{}").status_code in {401, 503}
        for route in forbidden:
            assert client.get(route).status_code == 404
            assert client.post(route).status_code == 404
    with TestClient(ui, base_url="http://127.0.0.1:8120") as client:
        assert client.get("/healthz").json() == {"status": "ok", "service": "loopback-ui"}
        assert client.post("/api/ingest/openscale", content=b"{}").status_code == 404


def test_safe_error_pages_do_not_leak_sql_or_payloads(tmp_path):
    app, _settings, _paths = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        missing = client.get("/imports/not-a-real-batch")
        assert missing.status_code == 404
        assert "text/html" in missing.headers["content-type"]
        assert "sqlalchemy" not in missing.text.lower()
        assert "traceback" not in missing.text.lower()
        assert "SELECT" not in missing.text
        bad = client.post("/api/import-candidates/confirm", json={"candidate_ids": ["nope"]})
        assert bad.status_code in {400, 404}
        body = bad.json()
        assert "code" in body
        assert "sqlalchemy" not in str(body).lower()
        invalid = client.get("/api/weight/series", params={"start_date": "not-a-date"})
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "invalid_request"
        assert "not-a-date" not in invalid.text
        traversal = client.get("/api/artifacts/../../secrets")
        assert traversal.status_code in {400, 404, 422}


def test_artifact_is_served_by_id_not_filesystem_path(tmp_path):
    app, _settings, _paths = _ui(tmp_path)
    png = encode_synthetic_png(weigh_in_payload(source_local_date=date(2026, 5, 6), weight_kg=79.0))
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        uploaded = client.post(
            "/api/imports/photos", files=[("files", ("shot.png", png, "image/png"))]
        )
        artifact_id = uploaded.json()["artifacts"][0]["id"]
        image = client.get(f"/api/artifacts/{artifact_id}")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert image.content.startswith(b"\x89PNG")
        missing = client.get("/api/artifacts/00000000-0000-0000-0000-000000000000")
        assert missing.status_code == 404


def test_unmigrated_dashboard_stays_available(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    prepare_runtime(settings)
    app, _ = create_ui_app(settings)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Потребительский биоимпеданс" in page.text
        series = client.get("/api/weight/series")
        assert series.status_code == 200
        assert series.json()["raw_points"] == []


def _canonical_snapshot(paths):
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            runs = list(
                session.scalars(
                    select(CanonicalSelectionRun).order_by(CanonicalSelectionRun.id)
                )
            )
            selections = list(
                session.scalars(select(CanonicalSelection).order_by(CanonicalSelection.id))
            )
            return {
                "run_count": len(runs),
                "selection_count": len(selections),
                "run_ids": tuple(run.id for run in runs),
                "statuses": tuple(run.status for run in runs),
                "run_selection_counts": tuple(run.selection_count for run in runs),
                "supersedes": tuple(run.supersedes_run_id for run in runs),
                "scope_keys": tuple(run.scope_key for run in runs),
                "input_hashes": tuple(run.input_snapshot_hash for run in runs),
                "completed_at": tuple(
                    None if run.completed_at is None else run.completed_at.isoformat()
                    for run in runs
                ),
            }
    finally:
        engine.dispose()


def test_dashboard_gets_do_not_mutate_canonical_state(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        uploaded = _upload_batch(client, six_month_synthetic_batch()[:8])
        _confirm_all_pending(client, uploaded.json()["id"])
        established = _canonical_snapshot(paths)
        assert established["run_count"] >= 1
        assert established["selection_count"] >= 8
        series = client.get("/api/weight/series").json()
        assert series["canonical"]["available"] is True
        established_run_id = series["canonical"]["run_id"]
        established_count = series["canonical"]["selection_count"]
        assert established_count == 8

        for _ in range(2):
            assert client.get("/").status_code == 200
            series_response = client.get("/api/weight/series")
            summary = client.get("/api/weight/summary")
            assert series_response.status_code == 200
            assert summary.status_code == 200
            body = series_response.json()
            assert body["canonical"]["run_id"] == established_run_id
            assert body["canonical"]["selection_count"] == established_count
            assert len(body["raw_points"]) == 8
            assert summary.json()["canonical"]["run_id"] == established_run_id

        assert _canonical_snapshot(paths) == established

        reads = (
            ("/", None),
            ("/api/weight/series", None),
            ("/api/weight/summary", None),
            ("/api/weight/series", {"start_date": "2026-02-01"}),
            ("/api/weight/summary", {"end_date": "2026-02-01"}),
            ("/api/weight/series", {"compatibility_group": "not-a-real-group"}),
            ("/api/weight/summary", {"start_date": "2026-06-01", "end_date": "2026-07-01"}),
        )
        for path, params in reads:
            for _ in range(2):
                response = client.get(path, params=params)
                assert response.status_code == 200
                if path.startswith("/api/"):
                    body = response.json()
                    assert body["canonical"]["available"] is True
                    assert body["canonical"]["run_id"] == established_run_id
                    assert body["canonical"]["selection_count"] == established_count

        assert _canonical_snapshot(paths) == established
        filtered = client.get(
            "/api/weight/series", params={"start_date": "2026-02-01"}
        ).json()
        empty_filter = client.get(
            "/api/weight/series", params={"compatibility_group": "not-a-real-group"}
        ).json()
        assert filtered["canonical"]["run_id"] == established_run_id
        assert empty_filter["canonical"]["run_id"] == established_run_id
        assert 0 < len(filtered["raw_points"]) < 8
        assert empty_filter["raw_points"] == []
        assert empty_filter["canonical"]["selection_count"] == established_count
        assert empty_filter["trend_available"] is False


def test_competing_source_heads_use_canonical_evidence_for_analytics(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    png = encode_synthetic_png(
        weigh_in_payload(source_local_date=date(2026, 3, 4), weight_kg=81.2, body_fat_pct=24.4)
    )
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        uploaded = client.post(
            "/api/imports/photos", files=[("files", ("one.png", png, "image/png"))]
        )
        _confirm_all_pending(client, uploaded.json()["id"])
        before = client.get("/api/weight/series").json()
        assert before["canonical"]["available"] is True
        photo_point = next(
            point for point in before["raw_points"] if point["canonical_selected"]
        )
        photo_value = photo_point["value_kg"]
        semantic = photo_point["provenance"]["semantic_key"]
        snapshot = _canonical_snapshot(paths)

        engine = create_sqlite_engine(paths)
        try:
            with session_scope(engine) as session:
                from healthcheck.db.repositories import repositories_for

                repos = repositories_for(session)
                provider = repos.providers.get_or_create(
                    "openscale", "openScale", "scale_app"
                )
                device = repos.physical_devices.get_or_create(
                    "xiaomi_s400", manufacturer="Xiaomi", model="S400"
                )
                source = repos.acquisition_sources.get_or_create(
                    provider_id=provider.id,
                    physical_device_id=device.id,
                    input_method="webhook",
                )
                algorithm = repos.measurement_algorithms.get_or_create(
                    code="openscale_weight",
                    version="1",
                    metric_family="weight",
                    producer="openscale",
                    compatibility_group="openscale-weight",
                )
                competing_session = repos.measurement_sessions.create_confirmed(
                    acquisition_source_id=source.id,
                    semantic_key=semantic,
                    source_local_date=date(2026, 3, 4),
                    temporal_precision="instant",
                    source_timestamp_utc=datetime(2026, 3, 4, 12, 0, tzinfo=UTC),
                )
                repos.scalar_measurements.create(
                    measurement_session_id=competing_session.id,
                    metric_code="weight",
                    normalized_value=99.25,
                    normalized_unit="kg",
                    measurement_algorithm_id=algorithm.id,
                )
                CanonicalSelectionService(session).recompute_dashboard()
        finally:
            engine.dispose()

        after_write = _canonical_snapshot(paths)
        assert after_write["run_count"] >= snapshot["run_count"]
        series = client.get("/api/weight/series").json()
        summary = client.get("/api/weight/summary").json()
        assert _canonical_snapshot(paths) == after_write
        raw_values = {point["value_kg"] for point in series["raw_points"]}
        assert photo_value in raw_values
        assert 99.25 in raw_values
        selected_values = {
            point["value_kg"]
            for point in series["raw_points"]
            if point["canonical_selected"]
        }
        assert selected_values == {99.25}
        assert [point["median_kg"] for point in series["daily_points"]] == [99.25]
        assert all(point["median_kg"] == 99.25 for point in series["trend_points"])
        losing = next(point for point in series["raw_points"] if point["value_kg"] == photo_value)
        winning = next(point for point in series["raw_points"] if point["value_kg"] == 99.25)
        assert losing["canonical_selected"] is False
        assert winning["canonical_selected"] is True
        assert losing["provenance"]["provider_code"]
        assert winning["provenance"]["input_method"] == "webhook"
        assert summary["canonical"]["available"] is True
        assert summary["current"]["value_kg"] == 99.25


def test_failed_canonical_recompute_marks_established_success_stale(tmp_path):
    """GET must not present a prior success as fresh after a newer failed run."""

    from healthcheck.db.repositories import repositories_for

    app, _settings, paths = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        uploaded = _upload_batch(client, six_month_synthetic_batch()[:4])
        _confirm_all_pending(client, uploaded.json()["id"])
        before = client.get("/api/weight/series").json()["canonical"]
        assert before["available"] is True
        assert before["fresh"] is True
        assert before["stale"] is False
        assert before["warning"] is None
        success_run_id = before["run_id"]
        snapshot = _canonical_snapshot(paths)
        assert "failed" not in snapshot["statuses"]

    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            repos = repositories_for(session)
            success = repos.canonical_selection_runs.get_by_id(success_run_id)
            assert success is not None
            heads = [
                measurement
                for measurement in repos.scalar_measurements.current_heads()
                if measurement.metric_code == "weight"
            ]
            assert heads
            measurement = heads[0]
            measurement_session = repos.measurement_sessions.get_by_id(
                measurement.measurement_session_id
            )
            assert measurement_session is not None
            assert measurement_session.semantic_key
            # Prefer the real CanonicalSelectionService savepoint failure path so
            # the durable failed run matches production write-side diagnostics.
            result = CanonicalSelectionService(session).select(
                scope_key=DASHBOARD_WEIGHT_SCOPE,
                metric_code="weight",
                candidates=[
                    CanonicalCandidate(
                        metric_code="weight",
                        semantic_key=measurement_session.semantic_key,
                        source_measurement_id=measurement.id,
                    ),
                    CanonicalCandidate(
                        metric_code="weight",
                        semantic_key="synthetic-missing-after-success",
                        source_measurement_id="missing-source-measurement",
                    ),
                ],
            )
            assert result.status == "failed"
            assert result.failure_reason == "canonical_selection_reference_missing"
            assert result.id != success_run_id
            failed_run_id = result.id
    finally:
        engine.dispose()

    after_fail = _canonical_snapshot(paths)
    assert after_fail["run_count"] == snapshot["run_count"] + 1
    assert "failed" in after_fail["statuses"]

    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        series = client.get("/api/weight/series").json()
        summary = client.get("/api/weight/summary").json()
        home = client.get("/")
        assert home.status_code == 200
        html = home.text
        assert 'class="canonical-banner"' in html
        assert 'class="canonical-banner" role="status"' in html
        assert 'class="canonical-banner" role="alert"' not in html
        assert "из последнего удачного расчёта и могут быть устаревшими" in html
        assert "canonical_recompute_failed" in html
        # Embedded dashboard JSON keeps sanitized freshness fields.
        assert '"dashboard-data"' in html or 'id="dashboard-data"' in html
        assert "canonical_selection_reference_missing" in html  # sanitized code in JSON
        assert series["canonical"]["failure_reason"] == "canonical_selection_reference_missing"
        # No SQL/exception/payload/secrets leakage.
        assert "Traceback" not in html
        assert "SELECT " not in html
        assert "password" not in html.lower()
        assert "bearer " not in html.lower()
        for payload in (series, summary):
            canonical = payload["canonical"]
            assert canonical["available"] is True
            assert canonical["run_id"] == success_run_id
            assert canonical["fresh"] is False
            assert canonical["stale"] is True
            assert canonical["warning"] == "canonical_recompute_failed"
            assert canonical["latest_attempt_status"] == "failed"
            assert canonical["latest_attempt_run_id"] == failed_run_id
            assert canonical["failure_reason"] == "canonical_selection_reference_missing"
        # GET must not mutate durable canonical state.
        assert _canonical_snapshot(paths) == after_fail
        client.get("/api/weight/series")
        client.get("/api/weight/summary")
        client.get("/")
        assert _canonical_snapshot(paths) == after_fail


def test_failed_only_composition_scope_marks_weight_success_stale(tmp_path):
    """Composition FAILED before any success must surface overall freshness warning."""

    from healthcheck.db.repositories import repositories_for

    app, _settings, paths = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        uploaded = _upload_batch(client, six_month_synthetic_batch()[:3])
        _confirm_all_pending(client, uploaded.json()["id"])
        before = client.get("/api/weight/series").json()["canonical"]
        assert before["available"] is True
        assert before["fresh"] is True
        weight_run_id = before["run_id"]

    group = "synthetic-comp-failed-only"
    scope = dashboard_composition_scope(group)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            repos = repositories_for(session)
            provider = repos.providers.get_or_create("photo", "Photo", "manual_photo")
            device = repos.physical_devices.get_or_create(
                "synthetic_scale", manufacturer="Synthetic", model="UAT"
            )
            source = repos.acquisition_sources.get_or_create(
                provider_id=provider.id,
                physical_device_id=device.id,
                input_method="photo_import",
            )
            algorithm = repos.measurement_algorithms.get_or_create(
                code="synthetic_body_fat",
                version="1",
                metric_family="body_composition",
                producer="synthetic",
                compatibility_group=group,
            )
            measured = repos.measurement_sessions.create_confirmed(
                acquisition_source_id=source.id,
                semantic_key="synthetic-comp-only-1",
                source_local_date=date(2026, 4, 1),
                temporal_precision="date",
            )
            repos.scalar_measurements.create(
                measurement_session_id=measured.id,
                metric_code="body_fat_pct",
                normalized_value=22.5,
                normalized_unit="%",
                measurement_algorithm_id=algorithm.id,
            )
            weight_success = repos.canonical_selection_runs.get_by_id(weight_run_id)
            assert weight_success is not None
            rule_set = session.get(CanonicalRuleSet, weight_success.rule_set_id)
            assert rule_set is not None
            assert repos.canonical_selection_runs.latest_successful(scope) is None
            failed_run, created = repos.canonical_selection_runs.start_or_get(
                scope_key=scope,
                rule_set=rule_set,
                input_snapshot_hash="synthetic-comp-failed-only-input",
            )
            assert created is True
            repos.canonical_selection_runs.finish(
                failed_run.id,
                status=RunStatus.FAILED,
                failure_reason="canonical_selection_failed",
            )
            failed_run_id = failed_run.id
            assert repos.canonical_selection_runs.latest_successful(scope) is None
            assert repos.canonical_selections.for_run(failed_run.id) == []
            assert scope in repos.canonical_selection_runs.scope_keys_with_prefix(
                prefix="r01-composition:"
            )
    finally:
        engine.dispose()

    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        series = client.get("/api/weight/series").json()
        summary = client.get("/api/weight/summary").json()
        home = client.get("/")
        assert home.status_code == 200
        assert 'class="canonical-banner"' in home.text
        assert 'class="canonical-banner" role="status"' in home.text
        assert 'class="canonical-banner" role="alert"' not in home.text
        assert "могут быть устаревшими" in home.text
        for payload in (series, summary):
            canonical = payload["canonical"]
            assert canonical["available"] is True
            assert canonical["run_id"] == weight_run_id
            assert canonical["fresh"] is False
            assert canonical["stale"] is True
            assert canonical["warning"] == "canonical_recompute_failed"
            assert canonical["latest_attempt_status"] == "failed"
            assert canonical["latest_attempt_run_id"] == failed_run_id
            assert canonical["failure_reason"] == "canonical_selection_failed"
        # Failed composition selections never activate.
        assert group not in series.get("composition_by_group", {})
        mid = _canonical_snapshot(paths)
        client.get("/api/weight/series")
        client.get("/")
        assert _canonical_snapshot(paths) == mid


def test_dashboard_html_shows_canonical_banner_when_stale(tmp_path):
    """HTML regression: banner is visible, not only API JSON fields."""

    from healthcheck.db.repositories import repositories_for

    app, _settings, paths = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        uploaded = _upload_batch(client, six_month_synthetic_batch()[:2])
        _confirm_all_pending(client, uploaded.json()["id"])
        success_run_id = client.get("/api/weight/series").json()["canonical"]["run_id"]

    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            repos = repositories_for(session)
            success = repos.canonical_selection_runs.get_by_id(success_run_id)
            assert success is not None
            rule_set = session.get(CanonicalRuleSet, success.rule_set_id)
            assert rule_set is not None
            failed, created = repos.canonical_selection_runs.start_or_get(
                scope_key=DASHBOARD_WEIGHT_SCOPE,
                rule_set=rule_set,
                input_snapshot_hash="html-banner-failed-input",
                supersedes_run_id=success.id,
            )
            assert created
            repos.canonical_selection_runs.finish(
                failed.id,
                status=RunStatus.FAILED,
                failure_reason="canonical_selection_failed",
            )
    finally:
        engine.dispose()

    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert 'data-canonical-warning="canonical_recompute_failed"' in home.text
        assert 'class="canonical-banner" role="status"' in home.text
        assert "из последнего удачного расчёта и могут быть устаревшими" in home.text
        assert "Traceback" not in home.text
        assert "SELECT " not in home.text
        assert "canonical_recompute_failed" in home.text


def test_stale_success_composition_recompute_keeps_prior_selections(tmp_path):
    """Older composition success + newer failed attempt stays stale, not failed-only."""

    from healthcheck.db.repositories import repositories_for
    from healthcheck.ingestion.photo.provenance import XIAOMI_HOME_COMPOSITION_ALGORITHM

    app, _settings, paths = _ui(tmp_path)
    group = XIAOMI_HOME_COMPOSITION_ALGORITHM
    composition_scope = dashboard_composition_scope(group)

    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        png = encode_synthetic_png(
            weigh_in_payload(
                source_local_date=date(2026, 3, 4), weight_kg=81.2, body_fat_pct=24.4
            )
        )
        uploaded = client.post(
            "/api/imports/photos",
            files=[("files", ("with-fat.png", png, "image/png"))],
        )
        assert uploaded.status_code == 200
        _confirm_all_pending(client, uploaded.json()["id"])
        before = client.get("/api/weight/series").json()
        assert before["canonical"]["available"] is True
        assert before["canonical"]["fresh"] is True
        assert group in before["composition_by_group"]
        selected_before = {
            point["evidence_id"]
            for point in before["raw_points"]
            if point.get("canonical_selected")
        }
        assert selected_before
        weight_run_id = before["canonical"]["run_id"]

    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            repos = repositories_for(session)
            success = repos.canonical_selection_runs.latest_successful(composition_scope)
            assert success is not None
            success_composition_id = success.id
            composition_ids_before = {
                selection.source_measurement_id
                for selection in repos.canonical_selections.for_run(success.id)
                if selection.source_measurement_id
            }
            assert composition_ids_before
            rule_set = session.get(CanonicalRuleSet, success.rule_set_id)
            assert rule_set is not None
            failed_run, created = repos.canonical_selection_runs.start_or_get(
                scope_key=composition_scope,
                rule_set=rule_set,
                input_snapshot_hash="synthetic-stale-composition-recompute",
                supersedes_run_id=success.id,
            )
            assert created is True
            repos.canonical_selection_runs.finish(
                failed_run.id,
                status=RunStatus.FAILED,
                failure_reason="canonical_selection_failed",
            )
            failed_run_id = failed_run.id
    finally:
        engine.dispose()

    after_fail = _canonical_snapshot(paths)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        series = client.get("/api/weight/series").json()
        summary = client.get("/api/weight/summary").json()
        home = client.get("/")
        assert home.status_code == 200
        assert 'class="canonical-banner"' in home.text
        assert 'class="canonical-banner" role="status"' in home.text
        assert 'class="canonical-banner" role="alert"' not in home.text
        assert "из последнего удачного расчёта и могут быть устаревшими" in home.text
        for payload in (series, summary):
            canonical = payload["canonical"]
            assert canonical["available"] is True
            assert canonical["run_id"] == weight_run_id
            assert canonical["fresh"] is False
            assert canonical["stale"] is True
            assert canonical["warning"] == "canonical_recompute_failed"
            assert canonical["latest_attempt_status"] == "failed"
            assert canonical["latest_attempt_run_id"] == failed_run_id
            assert canonical["failure_reason"] == "canonical_selection_failed"
        selected_after = {
            point["evidence_id"]
            for point in series["raw_points"]
            if point.get("canonical_selected")
        }
        assert selected_before <= selected_after
        assert group in series["composition_by_group"]
        # Prior successful composition selections remain active.
        engine = create_sqlite_engine(paths)
        try:
            with session_scope(engine) as session:
                repos = repositories_for(session)
                still = repos.canonical_selection_runs.latest_successful(composition_scope)
                assert still is not None
                assert still.id == success_composition_id
                composition_ids_after = {
                    selection.source_measurement_id
                    for selection in repos.canonical_selections.for_run(still.id)
                    if selection.source_measurement_id
                }
                assert composition_ids_after == composition_ids_before
        finally:
            engine.dispose()
        assert _canonical_snapshot(paths) == after_fail
        client.get("/api/weight/series")
        client.get("/")
        assert _canonical_snapshot(paths) == after_fail


def test_owner_shell_navigation_hierarchy_and_legacy_routes(tmp_path):
    app, _settings, _paths = _ui(tmp_path)
    expected = [
        ("/brief", "Обзор"),
        ("/", "Вес"),
        ("/sleep", "Сон"),
        ("/garmin", "Активность"),
        ("/imports", "Данные"),
    ]
    expected_modes = {
        "Обзор": None,
        "Вес": "Вес и состав тела",
        "Сон": None,
        "Активность": "Тренировки и восстановление",
        "Данные": "Проверка импорта",
    }
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        batch = _upload_batch(client, six_month_synthetic_batch()[:1]).json()["id"]
        for path, section in [*expected, ("/agreement", "Сон"), (f"/imports/{batch}", "Данные")]:
            response = client.get(path)
            assert response.status_code == 200
            parsed = _OwnerShellParser(response.text)
            assert [(attrs["href"], text) for attrs, text in parsed.links] == expected
            assert [text for attrs, text in parsed.links if attrs.get("aria-current")] == [section]
            assert parsed.headings == [section]
            assert 'href="#owner-main"' in response.text
            assert 'id="owner-main" tabindex="-1"' in response.text
            assert parsed.details and all("open" not in attrs for attrs in parsed.details)
            assert '<html lang="ru"' in response.text
            assert "К содержимому" in response.text
            assert 'aria-label="Основные разделы"' in response.text
            if expected_modes[section]:
                assert expected_modes[section] in response.text
            else:
                assert 'class="owner-page-mode"' not in response.text
            if section == "Сон":
                switch = response.text.split('aria-label="Источники сна">', 1)[1].split(
                    "</nav>", 1
                )[0]
                for view, label in (("garmin", "Garmin"), ("google", "Google"),
                                    ("compare", "Сравнить")):
                    assert f'href="/sleep?view={view}' in switch
                    assert f'>{label}</a>' in switch
                selected = "Сравнить" if path == "/agreement" else "Garmin"
                assert f'aria-current="page">{selected}</a>' in switch
            # The thematic pages are Russian; legacy import detail stays English.
            if section in ("Обзор", "Вес", "Сон", "Активность") or path == "/imports":
                assert 'class="owner-page-content" lang="en"' not in response.text
            else:
                assert 'class="owner-page-content" lang="en"' in response.text
        period = client.get("/brief?start_date=2099-02-03&end_date=2099-02-17")
        assert "За период" in period.text
        assert "3 февраля 2099 → 17 февраля 2099" in period.text
        assert 'name="start_date" value="2099-02-03"' in period.text
        assert 'href="/brief">Health-Check</a>' in period.text
        # Frozen shell: paper sticky nav, table-scroll wrappers, no block tables.
        css = client.get("/static/dashboard.css").text
        assert "--bg: #f3f1ec" in css
        assert "--card: #fffcf8" in css
        assert "--accent: #1f5c57" in css
        assert ".top" in css and "position: sticky" in css
        assert ".table-scroll" in css
        assert ".owner-page-content table { display: block" not in css
        assert "border-radius: 999px" not in css
        assert "text-transform: uppercase" not in css
        assert 'class="table-scroll"' in client.get("/imports").text
        assert 'class="table-scroll"' in client.get("/brief").text


def test_owner_shell_errors_keep_context_and_disclose_reason(tmp_path):
    app, _settings, _paths = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        response = client.get("/brief?preset=invalid")
        missing = client.get("/imports/missing-batch")
        unknown = client.get("/unknown-owner-page", headers={"Accept": "text/html"})
    assert response.status_code == 400
    parsed = _OwnerShellParser(response.text)
    assert parsed.headings == ["Обзор"]
    primary, technical = response.text.split('<details class="card owner-details', 1)
    assert 'role="alert"' in primary
    assert 'data-owner-state="error"' in primary
    assert "<code>invalid_period</code>" not in primary
    assert "<code>invalid_period</code>" in technical
    assert all("open" not in attrs for attrs in parsed.details)
    assert "Не удалось показать страницу" in response.text
    assert "Выбери период: 7, 30 или 90 дней." in primary
    assert "preset must be" not in primary
    assert "preset must be 7, 30, or 90 days" in technical
    assert 'href="/brief">Обзор</a>' in response.text or ">Обзор<" in response.text
    assert missing.status_code == 404
    assert _OwnerShellParser(missing.text).headings == ["Данные"]
    assert unknown.status_code == 404
    assert _OwnerShellParser(unknown.text).headings == ["Health-Check"]
    assert "Загрузка не найдена." in missing.text.split("Технические детали", 1)[0]
    assert "Страница не найдена." in unknown.text.split("Технические детали", 1)[0]
    assert not any(
        attrs.get("aria-current") for attrs, _text in _OwnerShellParser(unknown.text).links
    )


def test_owner_validation_error_is_russian_without_changing_api(tmp_path):
    app, _settings, _paths = _ui(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        html = client.get("/garmin?start_date=invalid")
        api = client.get("/api/garmin/series?start_date=invalid")
    assert html.status_code == api.status_code == 422
    primary, technical = html.text.split('<details class="card owner-details', 1)
    assert "Не удалось прочитать параметры запроса." in primary
    assert "request could not be parsed" not in primary
    assert "request could not be parsed" in technical
    assert api.json() == {"code": "invalid_request", "message": "request could not be parsed"}


def test_owner_shell_frozen_visual_system(tmp_path):
    """Frozen tokens, type, state treatments and Russian shell contract."""

    app, _settings, _paths = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        css = client.get("/static/dashboard.css").text
        # Core frozen tokens.
        for token in (
            "--bg: #f3f1ec",
            "--card: #fffcf8",
            "--sunken: #e8e4dc",
            "--ink: #1c1916",
            "--muted: #5e584e",
            "--line: #ddd6cb",
            "--line-strong: #c9c0b3",
            "--accent: #1f5c57",
            "--accent-soft: #e6f1ef",
            "--series-1: #1d4e89",
            "--series-2: #9a4f1a",
            "--series-3: #5c4d86",
            "--series-4: #3f5f73",
        ):
            assert token in css
        # Frozen state fills.
        assert "#f6efe2" in css  # attention
        assert "#f3e4d4" in css  # unavailable
        assert "#f8eceb" in css  # error
        # Radii and surfaces: 8px cards, 6px buttons, 4px chips; no pills/shadows.
        assert "border-radius: 8px" in css
        assert "border-radius: 6px" in css
        assert "border-radius: 4px" in css
        assert "border-radius: 999px" not in css
        assert "box-shadow" not in css.lower()
        assert "linear-gradient" not in css.lower()
        # Ordinary teal stripes and uppercase eyebrows are gone.
        assert "border-left: 6px solid" not in css
        assert "border-left: 5px solid" not in css
        assert "text-transform: uppercase" not in css
        # Paper sticky navigation with hairline and accent underline.
        assert "position: sticky" in css
        assert "border-bottom: 1px solid var(--line)" in css
        assert "border-bottom-color: var(--accent)" in css
        # Tables use dedicated scrollers with real layout and sticky muted headers.
        assert ".table-scroll" in css and "overflow-x: auto" in css
        assert ".owner-page-content table { display: block" not in css
        assert "position: sticky" in css  # thead th
        # Owner-state treatments for all ten keys.
        for selector in (
            ".owner-state.present",
            ".owner-state.confirmed_empty",
            ".owner-state.no_change",
            ".owner-state.not_requested",
            ".owner-state.loading",
            ".owner-state.partial",
            ".owner-state.insufficient",
            ".owner-state.unavailable",
            ".owner-state.unknown",
            ".owner-state.error",
        ):
            assert selector in css
        assert ".owner-state.partial" in css and "solid" in css
        assert ".owner-state.insufficient" in css and "dashed" in css
        # Chart legend samples are 8px squares; goal is a dashed reference sample.
        assert ".swatch" in css and "width: 8px" in css and "height: 8px" in css
        assert "border-radius: 50%" not in css
        assert ".swatch.goal" in css and "dashed" in css
        # Interpretation/status banners use attention treatment, not sunken or error red.
        assert ".bia-banner, .algorithm-banner, .canonical-banner" in css
        assert "background: var(--attention-bg)" in css
        assert ".error-card" in css and "var(--error-bg)" in css
        # Typography freeze: body 1.5, hierarchy stays 600 without 700 presentation.
        assert "line-height: 1.5" in css
        assert "font-weight: 700" not in css
        # Shell is Russian; English bodies stay explicitly English.
        overview = client.get("/brief").text
        weight = client.get("/").text
        assert '<html lang="ru"' in overview
        assert "Обзор" in overview and "За период" in overview
        assert "Интерфейс только на этом компьютере" in overview
        assert "Потребительский BIA — не клиническое измерение" in overview
        assert "К содержимому" in overview
        assert 'aria-label="Основные разделы"' in overview
        assert 'class="owner-page-content" lang="en"' not in weight
        assert "Текущий подтверждённый вес" in weight
        assert "Вес — Health-Check" in weight or "Вес</h1>" in weight
        # Algorithm/canonical banners are status, never errors.
        assert 'class="canonical-banner" role="alert"' not in weight
        assert 'class="algorithm-banner" role="alert"' not in weight
        # Footer state guide stays Russian and closed.
        assert "Как читать состояния данных" in overview


def test_owner_shell_desktop_browser_contract(tmp_path):
    """Desktop shell contract: viewport metadata, focus, targets, scrollers."""

    app, _settings, _paths = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        css = client.get("/static/dashboard.css").text
        # 44px minimum targets and visible focus.
        assert "min-height: 44px" in css
        assert ":focus-visible" in css
        # Horizontal scroll only inside chart/table regions.
        assert ".table-scroll" in css
        assert ".chart" in css
        assert "overflow-x:" in css
        # Real pages expose scrollers and keep evidence.
        for path in ("/brief", "/imports", "/garmin"):
            html = client.get(path).text
            assert 'name="viewport"' in html
            assert 'href="#owner-main"' in html
        assert 'class="table-scroll"' in client.get("/brief").text
        # Empty import queue honestly has no table; populated queue must scroll.
        assert "Загрузок пока нет" in client.get("/imports").text
        batch = _upload_batch(client, six_month_synthetic_batch()[:1]).json()["id"]
        assert 'class="table-scroll"' in client.get("/imports").text
        assert 'class="table-scroll"' in client.get(f"/imports/{batch}").text
        # Garmin tables render when training evidence exists; templates always wrap them.
        from pathlib import Path

        garmin_template = Path("src/healthcheck/web/templates/garmin.html").read_text(
            encoding="utf-8"
        )
        assert garmin_template.count('class="table-scroll"') >= 2
        assert "display: block" not in garmin_template


def test_owner_state_vocabulary_is_distinct_and_fails_closed():
    from healthcheck.web.pages import _brief_owner_state, templates

    shared = templates.get_template("owner_ui.html").module
    labels = shared.state_labels
    assert len(set(labels.values())) == len(labels)
    for state, label in labels.items():
        rendered = str(shared.state_chip(state))
        assert f'data-owner-state="{state}"' in rendered
        assert label in rendered
        if state in {
            "present",
            "confirmed_empty",
            "unknown",
            "unavailable",
            "insufficient",
            "not_requested",
        }:
            assert label == _brief_owner_state(state)
    for state in [None, "", "unsupported", "<script>alert(1)</script>"]:
        rendered = str(shared.state_chip(state))
        assert 'data-owner-state="unknown"' in rendered
        assert labels["unknown"] in rendered
        assert "<script>" not in rendered
        assert labels["confirmed_empty"] not in rendered
        assert labels["no_change"] not in rendered



def test_owner_data_surface_queue_actions_are_scoped_and_read_only(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        empty = client.get("/imports").text
        assert "Источники и свежесть данных" in empty
        assert "Загрузок пока нет" in empty
        assert "В последних загрузках нет кандидатов" in empty
        assert 'class="owner-page-content" lang="en"' not in empty
        assert 'id="data-feedback" role="status"' in empty
        assert 'data-owner-state="not_requested"' in empty
        assert 'src="/static/data_status.js"' in empty
        batch = _upload_batch(client, six_month_synthetic_batch()[:1]).json()["id"]
        before = _canonical_snapshot(paths)
        pending = client.get("/imports").text
        assert "Ожидают проверки: <strong>" in pending
        assert f'href="/imports/{batch}"' in pending
        assert "не более 50" in pending
        assert 'action="/imports/photos" method="post"' in pending
        assert 'name="files"' in pending
        assert 'role="region" aria-label="История загрузок' in pending
        assert 'class="table-scroll"' in pending
        assert _canonical_snapshot(paths) == before
        freshness = client.get("/api/source-freshness", params={
            "evaluated_at_utc": "2099-01-01T12:00:00Z",
            "evaluation_local_date": "2099-01-01",
        })
        assert freshness.status_code == 200
        weight = next(item for item in freshness.json()["components"]
                      if item["scope_key"] == "weight")
        assert weight["state"] == "unknown"  # pending extraction proves no measurement
        assert _canonical_snapshot(paths) == before
        _confirm_all_pending(client, batch)
        confirmed = client.get("/imports").text
        assert "В последних загрузках нет кандидатов" in confirmed
        assert "Ожидают проверки: <strong>" not in confirmed
        weight = next(item for item in client.get("/api/source-freshness", params={
            "evaluated_at_utc": "2099-01-01T12:00:00Z",
            "evaluation_local_date": "2099-01-01",
        }).json()["components"] if item["scope_key"] == "weight")
        assert (weight["state"], weight["reason_code"]) == ("quiet", "voluntary_sampling")


@pytest.mark.parametrize("batch_count", [50, 51, 100, 101])
def test_owner_data_history_outside_queue_window_renders_without_writes(tmp_path, batch_count):
    app, _settings, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    batch_ids = []
    decisions = ("pending", "confirmed", "rejected")
    try:
        with session_scope(engine) as session:
            source = ensure_photo_acquisition_source(repositories_for(session))
            for index in range(batch_count):
                batch = IngestBatch(
                    acquisition_source_id=source.id,
                    batch_kind="photo",
                    started_at=datetime(2099, 1, 1, tzinfo=UTC) + timedelta(minutes=index),
                    status="pending-confirmation",
                )
                session.add(batch)
                session.flush()
                batch_ids.append(batch.id)
                ingest_event = IngestEvent(
                    ingest_batch_id=batch.id,
                    acquisition_source_id=source.id,
                    event_type="photo",
                    deduplication_key=f"{index:064x}",
                    status="pending-confirmation",
                )
                session.add(ingest_event)
                session.flush()
                # Legacy evidence has no metadata origins. Reads must preserve it.
                session.add(
                    ImportCandidate(
                        ingest_event_id=ingest_event.id,
                        candidate_set_key="synthetic-legacy",
                        measurement_group_key="synthetic-group",
                        metric_code="weight",
                        user_decision=decisions[index % 3],
                        metadata_origins_json=None,
                    )
                )
    finally:
        engine.dispose()

    def stored_history():
        with closing(sqlite3.connect(f"{paths.database.as_uri()}?mode=ro", uri=True)) as connection:
            return tuple(connection.iterdump())

    before = stored_history()
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        page = client.get("/imports")
        assert page.status_code == 200, page.text
        assert "text/html" in page.headers["content-type"]
        expected_ids = list(reversed(batch_ids))[:100]
        for batch_id in expected_ids:
            assert f'href="/imports/{batch_id}"' in page.text
        for batch_id in batch_ids[:-100]:
            assert f'href="/imports/{batch_id}"' not in page.text
        assert page.text.count('href="/imports/') == len(expected_ids)
        for decision in decisions:
            expected = sum(
                decisions[index % 3] == decision
                for index in range(max(0, batch_count - 50), batch_count)
            )
            label = {
                "pending": "Ожидают проверки", "confirmed": "Подтверждены", "rejected": "Отклонены"
            }[decision]
            assert f"<dt>{label}</dt><dd>{expected}</dd>" in page.text
        assert "последним 50 загрузкам" in page.text
        assert "В последних загрузках нет кандидатов" not in page.text
    assert stored_history() == before


def test_owner_data_queue_and_history_share_snapshot(tmp_path, monkeypatch):
    app, _settings, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    original = PhotoImportService.list_batches
    commits = []
    try:
        with TestClient(
            app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
        ) as client:
            uploaded = _upload_batch(client, six_month_synthetic_batch()[:1])
            assert uploaded.status_code == 200, uploaded.text
            batch_id = uploaded.json()["id"]

            def change_between_queue_and_history(service, **kwargs):
                if not commits:
                    with session_scope(engine) as writer:
                        repositories_for(writer).ingest_batches.update(batch_id, status="failed")
                    commits.append(True)
                return original(service, **kwargs)

            monkeypatch.setattr(
                PhotoImportService, "list_batches", change_between_queue_and_history
            )
            page = client.get("/imports")
            assert page.status_code == 200
            assert commits == [True]
            assert "Ожидают проверки: <strong>" in page.text
            assert "<code>pending-confirmation</code>" in page.text
            assert "<code>failed</code>" not in page.text
            after = client.get("/imports")
            assert after.status_code == 200
            assert "<code>failed</code>" in after.text
    finally:
        engine.dispose()


def test_owner_data_sql_error_is_not_an_empty_queue(tmp_path, monkeypatch):
    from sqlalchemy import text

    from healthcheck.db.repositories import IngestBatchRepository

    app, _settings, _paths = _ui(tmp_path)

    def invalid_query(repository, **kwargs):
        repository.session.execute(text("SELECT synthetic_missing_column FROM ingest_batches"))

    monkeypatch.setattr(IngestBatchRepository, "list_recent", invalid_query)
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        page = client.get("/imports")
        assert page.status_code == 200
        assert "Число кандидатов неизвестно" in page.text
        assert "История загрузок недоступна" in page.text
        assert "В последних загрузках нет кандидатов" not in page.text
        assert "Загрузок пока нет" not in page.text
        assert "<dd>0</dd>" not in page.text
        assert "synthetic_missing_column" not in page.text


def test_owner_data_unavailable_queue_never_presents_empty_or_zero(tmp_path):
    settings = Settings(data_dir=tmp_path / "uninitialized-runtime")
    app, _paths = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        page = client.get("/imports")
        assert page.status_code == 200
        assert "Число кандидатов неизвестно" in page.text
        assert "История загрузок недоступна" in page.text
        assert "В последних загрузках нет кандидатов" not in page.text
        assert "Загрузок пока нет" not in page.text
        assert 'class="current data-queue-facts"' not in page.text
        assert '<dd>0</dd>' not in page.text


def test_weight_owner_state_mapping_keeps_missing_and_insufficient_distinct():
    from healthcheck.web.pages import _weight_owner_state

    assert _weight_owner_state(True, None) == "present"
    assert _weight_owner_state(False, "insufficient_observations") == "insufficient"
    assert _weight_owner_state(False, "insufficient_span") == "insufficient"
    assert _weight_owner_state(False, "insufficient_gap") == "insufficient"
    assert _weight_owner_state(False, "no_data") == "unavailable"
    assert _weight_owner_state(False, "missing_session") == "unavailable"
    assert _weight_owner_state(False, "database_unavailable") == "unavailable"
    assert _weight_owner_state(False, "future_reason") == "unavailable"
    assert _weight_owner_state(False, None) == "unknown"
    assert _weight_owner_state(False, "") == "unknown"


def test_weight_owner_reason_is_russian_and_keeps_exact_codes_behind():
    from healthcheck.web.pages import _weight_owner_reason

    assert "Нет подтверждённых измерений" in _weight_owner_reason("no_data")
    assert "Недостаточно измерений" in _weight_owner_reason("insufficient_observations")
    assert "Нет принятого расчёта" in _weight_owner_reason("no_canonical_run")
    assert "Локальное хранилище" in _weight_owner_reason("database_unavailable")
    expected_fallback = "Подробности доступны в технических данных."
    assert _weight_owner_reason("future_unknown_reason") == expected_fallback
    # Exact codes are not translated away: caller keeps them for technical disclosure.
    assert _weight_owner_reason("no_data") != "no_data"


def test_weight_page_is_russian_owner_first_with_technical_disclosure(tmp_path):
    app, _settings, _paths = _ui(tmp_path, weight_goal_kg=76.0)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        _confirm_all_pending(client, _upload_batch(client).json()["id"])
        page = client.get("/")
        assert page.status_code == 200
        html = page.text
        # Owner-first Russian primary surface.
        for snippet in (
            "Текущий подтверждённый вес",
            "Текущий вес и цель",
            "Ряд веса",
            "Подтверждённый вес (источник)",
            "Тренд 21 день (расчёт Health-Check)",
            "Настроенная цель",
            "Изменение за последнее время",
            "Покрытие и свежесть",
            "Состав тела во времени",
            "Как изменился состав тела при похожем весе",
            "Состав тела во времени",
            "Происхождение выбранной точки",
            "Выбери точку на графике",
            "Проверить состояние источников",
            "Технические детали",
        ):
            assert snippet in html
        # Interpretation-changing limitations stay visible in Russian.
        assert "Потребительский биоимпеданс" in html
        assert "не ставит диагнозы" in html
        # Exact mechanics/reasons stay behind closed disclosure, not primary.
        assert '<details class="card owner-details' in html
        assert 'class="card owner-details" open' not in html
        primary, technical = html.split("Технические детали", 1)
        assert "weight_trend_taewma_v1" not in primary
        assert "weight_rate_theil_sen_90d_v1" not in primary
        assert "no_data" not in primary or 'data-owner-state' in primary
        assert "weight_trend_taewma_v1" in technical
        assert "canonical" in technical.lower() or "Канонический" in technical
        # Import needs link toward Data, not duplicated source-status UX.
        assert 'href="/imports' in primary
        assert "Нет кандидатов на проверке" not in primary
        # Missing is never zero in primary (exact zero, not goal substring).
        assert " 0 кг" not in primary
        assert ">0 кг" not in primary
        # API semantics unchanged.
        series = client.get("/api/weight/series").json()
        assert series["trend_algorithm"] == "weight_trend_taewma_v1"
        assert series["metric_labels"]["raw_weight"] == "Raw confirmed weight (source)"
        assert series["bia_uncertainty"].startswith("Consumer bioimpedance")


def test_weight_empty_states_use_frozen_chips_and_no_zero(tmp_path):
    app, _settings, _paths = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        html = client.get("/").text
        primary = html.split("Технические детали", 1)[0]
        assert 'data-owner-state="unavailable"' in primary
        assert "Это не означает ноль" in primary
        assert "Нет подтверждённых измерений" in primary
        assert "Не настроена" in primary
        assert "Нет кандидатов на проверке" not in primary
        assert "Проверка импорта" not in primary
        assert "Настройки и контекст" in primary
        assert "Как изменился состав тела при похожем весе" not in primary
        assert "0 кг" not in primary
        assert "<dd>0</dd>" not in primary


def test_weight_browser_contract_uses_frozen_surfaces(tmp_path):
    app, _settings, _paths = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        html = client.get("/").text
        js = client.get("/static/dashboard.js").text
        css = client.get("/static/dashboard.css").text
        # Viewport, skip link, focus, chart scroller present.
        assert 'name="viewport"' in html
        assert 'href="#owner-main"' in html
        assert 'id="weight-chart" class="chart"' in html
        assert 'aria-label="График веса"' in html
        assert 'id="trend-status"' in html
        # Legend uses frozen 8px squares (CSS) and Russian labels (HTML).
        assert "Подтверждённый вес (источник)" in html
        assert ".swatch" in css and "width: 8px" in css
        # Tables keep real layout inside dedicated scroller (JS creates wrapper).
        assert "table-scroll" in js
        assert 'aria-label", "Состав тела' in js or "Состав тела, прокрутка таблицы" in js
        assert 'createElement("table")' in js
        assert "display: block" not in js
        # Frozen series colors reused, no page-local palette.
        assert "#1d4e89" in js
        assert "#9a4f1a" in js
        assert "#5c4d86" in js
        assert "#c45c26" not in js
        assert "#6b4ea2" not in js
        # Owner-facing JS copy is Russian; exact reason codes stay in JSON only.
        assert "Тренд доступен" in js or "Тренд недоступен" in js
        assert "кг/нед." in js
        assert "Покрытие" not in js or "Даты наблюдений" in js
        assert "Trend algorithm" not in js
        assert "kg/week" not in js
        # No new visual tokens introduced by Stage 4.
        assert "border-radius: 999px" not in css
        assert "font-weight: 700" not in css


def test_weight_v2_styles_are_served_in_loaded_dashboard_bundle(tmp_path):
    app, _settings, _paths = _ui(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        html = client.get("/").text
        assert '<link rel="stylesheet" href="/static/dashboard.css">' in html
        assert "/static/weight.css" not in html
        stylesheet = client.get("/static/dashboard.css")
        assert stylesheet.status_code == 200
        assert "text/css" in stylesheet.headers["content-type"]
        assert ".weight-view .hero { display: block; }" in stylesheet.text
        assert ".weight-view .chart svg" in stylesheet.text
        assert (
            ".weight-view .chart svg { display: block; width: 100%; min-width: 260px"
            in stylesheet.text
        )
        assert client.get("/static/weight.css").status_code == 404


def test_weight_v2_hierarchy_goal_and_pending_action(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        empty = client.get("/").text
        primary, technical = empty.split('<details class="card owner-details', 1)
        assert "Настройки и контекст" in primary
        assert "Проверка импорта" not in primary
        assert 'class="bia-banner"' not in empty
        assert 'class="algorithm-banner"' not in empty
        assert "Покрытие и свежесть" not in primary
        assert "Покрытие и свежесть" in technical
        assert "Происхождение выбранной точки" in technical
        assert "Как изменился состав тела при похожем весе" not in empty
        assert primary.count('id="composition-groups"') == 1
        assert 'id="composition-latest"' not in empty
        uploaded = _upload_batch(client, six_month_synthetic_batch()[:1]).json()["id"]
        pending = client.get("/").text
        assert "Проверка импорта" in pending
        assert 'href="/imports"' in pending
        assert "на проверке" in pending
        _confirm_all_pending(client, uploaded)
        before = _canonical_snapshot(paths)
        series_before = client.get("/api/weight/series").json()
        confirmed = client.get("/").text
        assert "Проверка импорта" not in confirmed
        assert client.get("/api/weight/series").json() == series_before
        assert _canonical_snapshot(paths) == before


@pytest.mark.parametrize("body_fat_pct", [0.0, 25.0])
def test_weight_v2_exposes_exact_same_session_composition_evidence(tmp_path, body_fat_pct):
    app, _settings, _paths = _ui(tmp_path, weight_goal_kg=76.0)
    fixture = weigh_in_payload(
        source_local_date=date(2020, 1, 1), weight_kg=80.0,
        body_fat_pct=body_fat_pct, muscle_mass_kg=45.0,
    )
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        batch = _upload_batch(client, [("composition.png", encode_synthetic_png(fixture), fixture)])
        assert batch.status_code == 200, batch.text
        _confirm_all_pending(client, batch.json()["id"])
        series = client.get("/api/weight/series").json()
        raw = series["raw_points"][0]
        point = next(iter(series["composition_by_group"].values()))[0]
        assert point["weight_measurement_id"] == raw["evidence_id"]
        assert point["body_fat_pct"] == body_fat_pct
        # Existing derivation rejects zero body-fat; source zero stays explicit.
        assert point["estimated_fat_mass_kg"] == (20.0 if body_fat_pct else None)
        assert point["estimated_lean_mass_kg"] == (60.0 if body_fat_pct else None)
        assert point["source_muscle_mass_kg"] == 45.0
        assert point["metric_origins"]["estimated_lean_mass_kg"] == "healthcheck-derived"
        assert point["metric_origins"]["source_muscle_mass_kg"] == "source-provider"
        html = client.get("/").text
        assert "76.0 кг" in html
        assert "Настройка цели появится" not in html
        assert "Мышцы источника — отдельная оценка, а не остаток веса" in html
