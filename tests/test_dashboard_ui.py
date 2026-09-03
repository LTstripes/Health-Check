"""API/UI smoke for the local dashboard and photo-review queue.

Fixtures are synthetic.  No owner screenshots, live health values, or secrets
enter this file.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from healthcheck.canonical import CanonicalSelectionService
from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import (
    CanonicalSelection,
    CanonicalSelectionRun,
    ImportCandidate,
    MeasurementSession,
    ScalarMeasurement,
)
from healthcheck.ingestion.photo.synthetic import (
    encode_synthetic_png,
    six_month_synthetic_batch,
    weigh_in_payload,
)
from healthcheck.runtime import prepare_runtime
from healthcheck.web.ingest_app import create_ingest_app
from healthcheck.web.ui_app import create_ui_app


def _ui(tmp_path, **settings_values):
    settings = Settings(data_dir=tmp_path / "runtime", **settings_values)
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ui_app(settings)
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
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "text/html" in page.headers["content-type"]
        assert "Consumer bioimpedance" in page.text
        assert "does not diagnose" in page.text
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
        assert "0 kg" not in page.text or "Current confirmed weight" in page.text
        assert "unavailable" in page.text


def test_pending_extraction_is_not_confirmed_or_canonical(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    with TestClient(app) as client:
        uploaded = _upload_batch(client, six_month_synthetic_batch()[:3])
        assert uploaded.status_code == 200
        assert uploaded.json()["status"] == "pending-confirmation"
        series = client.get("/api/weight/series").json()
        assert series["raw_points"] == []
        assert series["canonical"]["selection_count"] == 0
        page = client.get("/")
        assert "No confirmed weight observations" in page.text or "unavailable" in page.text
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
    with TestClient(app) as client:
        uploaded = client.post(
            "/api/imports/photos", files=[("files", ("one.png", png, "image/png"))]
        )
        batch_id = uploaded.json()["id"]
        review = client.get(f"/imports/{batch_id}")
        assert review.status_code == 200
        assert "Commit preview" in review.text
        assert "81.2" in review.text
        assert "Pending extraction is never treated as confirmed" in review.text
        candidates = uploaded.json()["candidates"]
        weight = next(item for item in candidates if item["metric_code"] == "weight")
        fat = next(item for item in candidates if item["metric_code"] == "body_fat_pct")
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
        assert "21-day time-aware trend" in dashboard.text
        summary = client.get("/api/weight/summary").json()
        assert summary["latest_composition"]["available"] is False
        assert summary["latest_composition"]["reason"]


def test_six_month_history_dashboard_smoke(tmp_path):
    app, settings, _paths = _ui(tmp_path, weight_goal_kg=76.0)
    del settings
    batch = six_month_synthetic_batch()
    with TestClient(app) as client:
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
        assert "Estimated fat mass" in html or "estimated fat mass" in html.lower()
        assert "Source muscle" in html or "source muscle" in html.lower()
        assert "Consumer bioimpedance" in html
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

    with TestClient(app) as client:
        series = client.get("/api/weight/series").json()
        groups = series["composition_by_group"]
        assert "xiaomi-home-unknown" in groups
        assert "openscale-brozek" in groups
        assert series["algorithm_boundary"]["present"] is True
        page = client.get("/")
        assert "Incompatible body-composition algorithms" in page.text
        assert "xiaomi-home-unknown" in page.text
        assert "openscale-brozek" in page.text
    del settings


def test_ingest_listener_does_not_expose_dashboard_or_import_routes(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    ingest, _ = create_ingest_app(settings)
    ui, _ = create_ui_app(settings)
    probes = (
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
        "/api/ingest/openscale",
    )
    with TestClient(ingest) as client:
        assert [route.path for route in ingest.routes] == ["/healthz"]
        for route in probes:
            assert client.get(route).status_code == 404
            assert client.post(route).status_code == 404
    with TestClient(ui) as client:
        assert client.get("/healthz").json() == {"status": "ok", "service": "loopback-ui"}


def test_safe_error_pages_do_not_leak_sql_or_payloads(tmp_path):
    app, _settings, _paths = _ui(tmp_path)
    with TestClient(app) as client:
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
    with TestClient(app) as client:
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
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Consumer bioimpedance" in page.text
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
    with TestClient(app) as client:
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
    with TestClient(app) as client:
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
