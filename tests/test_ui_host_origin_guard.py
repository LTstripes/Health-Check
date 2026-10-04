"""UI Host / same-origin mutation guard regressions (issue #244).

Synthetic only. Realistic loopback URLs; never weakens production validation.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import ImportCandidate, ScalarMeasurement
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.ingestion.photo.synthetic import (
    encode_synthetic_png,
    six_month_synthetic_batch,
    weigh_in_payload,
)
from healthcheck.logging import configure_logging
from healthcheck.runtime import prepare_runtime
from healthcheck.web.ingest_app import create_ingest_app
from healthcheck.web.ui_app import create_ui_app

EVIL = "http://evil.example"
EVIL_HOST = "http://evil.example:8120"


def _ui(tmp_path, **overrides):
    settings = Settings(data_dir=tmp_path / "runtime", **overrides)
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())
    return app, settings, paths


def _base(settings) -> str:
    return f"http://127.0.0.1:{settings.ui_port}"


def _counts(paths):
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            return (
                int(session.scalar(select(func.count(ImportCandidate.id))) or 0),
                int(session.scalar(select(func.count(ScalarMeasurement.id))) or 0),
            )
    finally:
        engine.dispose()


def test_allows_configured_loopback_authorities(tmp_path):
    app, settings, _ = _ui(tmp_path)
    base = _base(settings)
    local = f"http://localhost:{settings.ui_port}"
    with TestClient(app, base_url=base) as client:
        assert client.get("/healthz").status_code == 200
    with TestClient(app, base_url=local) as client:
        assert client.get("/healthz").status_code == 200


def test_allows_custom_ui_port_derived_from_settings(tmp_path):
    app, settings, _ = _ui(tmp_path, ui_port=9123)
    base = f"http://127.0.0.1:{settings.ui_port}"
    assert settings.ui_port == 9123
    with TestClient(app, base_url=base) as client:
        assert client.get("/healthz").status_code == 200
        ok = client.post(
            "/api/import-candidates/confirm",
            json={"candidate_ids": ["nope"]},
            headers={"Origin": base},
        )
        assert ok.status_code in {400, 404}
    with TestClient(app, base_url="http://127.0.0.1:8120") as stale:
        assert stale.get("/healthz").status_code == 403


def test_rejects_foreign_malformed_host_on_get_and_post(tmp_path):
    app, settings, _ = _ui(tmp_path)
    base = _base(settings)
    bad_hosts = [
        EVIL_HOST,
        "http://testserver",
        "http://testserver:80",
        "http://0.0.0.0:8120",
        "http://127.0.0.1:9999",
        "http://localhost:9999",
    ]
    for bad in bad_hosts:
        with TestClient(app, base_url=bad) as client:
            assert client.get("/healthz").status_code == 403
            assert client.get("/").status_code == 403
            denied = client.post(
                "/api/import-candidates/confirm",
                json={"candidate_ids": ["x"]},
                headers={"Origin": base},
            )
            assert denied.status_code == 403
    with TestClient(app, base_url=base) as client:
        assert client.get("/healthz", headers={"Host": "evil@127.0.0.1:8120"}).status_code == 403
        dup = client.build_request("GET", "/healthz", headers=[("Host", "a"), ("Host", "b")])
        assert client.send(dup).status_code == 403


def test_valid_same_origin_json_and_multipart_mutations(tmp_path):
    app, settings, _ = _ui(tmp_path)
    base = _base(settings)
    pngs = six_month_synthetic_batch()[:2]
    with TestClient(app, base_url=base, headers={"Origin": base}) as client:
        uploaded = client.post(
            "/api/imports/photos",
            files=[("files", (name, content, "image/png")) for name, content, _ in pngs],
        )
        assert uploaded.status_code == 200, uploaded.text
        batch_id = uploaded.json()["id"]
        form = client.post(
            "/imports/photos",
            files=[("files", ("one.png", pngs[0][1], "image/png"))],
        )
        assert form.status_code in {303, 307, 200}
        detail = client.get(f"/api/imports/{batch_id}")
        assert detail.status_code == 200
        pending = detail.json()["candidates"][0]["id"]
        edited = client.post(
            "/api/import-candidates/edit",
            json={"candidate_id": pending, "edited_value": 79.05, "edited_unit": "kg"},
        )
        assert edited.status_code == 200


def test_rejects_foreign_null_malformed_wrong_port_alias_origin(tmp_path):
    app, settings, _ = _ui(tmp_path)
    base = _base(settings)
    local_base = f"http://localhost:{settings.ui_port}"
    bad_origins = [
        "http://evil.example",
        "http://evil.example:8120",
        "null",
        "",
        "http://127.0.0.1:8120/evil",
        "http://127.0.0.1:8120?x=1",
        "https://127.0.0.1:8120",
        "http://127.0.0.1:9999",
        "http://127.0.0.1",
        "http://evil@127.0.0.1:8120",
        "http://127.0.0.1:8120, http://127.0.0.1:8120",
    ]
    with TestClient(app, base_url=base) as client:
        for bad in bad_origins:
            denied = client.post(
                "/api/import-candidates/confirm",
                json={"candidate_ids": ["x"]},
                headers={"Origin": bad},
            )
            assert denied.status_code == 403, bad
        assert (
            client.post("/api/import-candidates/confirm", json={"candidate_ids": ["x"]}).status_code
            == 403
        )
        alias = client.post(
            "/api/import-candidates/confirm",
            json={"candidate_ids": ["x"]},
            headers={"Origin": local_base},
        )
        assert alias.status_code == 403
    with TestClient(app, base_url=local_base) as local_client:
        assert (
            local_client.post(
                "/api/import-candidates/confirm",
                json={"candidate_ids": ["x"]},
                headers={"Origin": base},
            ).status_code
            == 403
        )


def test_sec_fetch_site_contract(tmp_path):
    app, settings, _ = _ui(tmp_path)
    base = _base(settings)
    with TestClient(app, base_url=base) as client:
        for bad in ("cross-site", "same-site", "none", "bogus", ""):
            denied = client.post(
                "/api/import-candidates/confirm",
                json={"candidate_ids": ["x"]},
                headers={"Origin": base, "Sec-Fetch-Site": bad},
            )
            assert denied.status_code == 403, bad
        allowed = client.post(
            "/api/import-candidates/confirm",
            json={"candidate_ids": ["x"]},
            headers={"Origin": base, "Sec-Fetch-Site": "same-origin"},
        )
        assert allowed.status_code in {400, 404}
        no_meta = client.post(
            "/api/import-candidates/confirm",
            json={"candidate_ids": ["x"]},
            headers={"Origin": base},
        )
        assert no_meta.status_code in {400, 404}
        dup = client.build_request(
            "POST",
            "/api/import-candidates/confirm",
            headers=[
                ("Origin", base),
                ("Sec-Fetch-Site", "same-origin"),
                ("Sec-Fetch-Site", "cross-site"),
            ],
            json={"candidate_ids": ["x"]},
        )
        assert client.send(dup).status_code == 403


def test_referer_is_consistency_only(tmp_path):
    app, settings, _ = _ui(tmp_path)
    base = _base(settings)
    with TestClient(app, base_url=base) as client:
        conflict = client.post(
            "/api/import-candidates/confirm",
            json={"candidate_ids": ["x"]},
            headers={"Origin": base, "Referer": "http://evil.example/page"},
        )
        assert conflict.status_code == 403
        malformed = client.post(
            "/api/import-candidates/confirm",
            json={"candidate_ids": ["x"]},
            headers={"Origin": base, "Referer": "not-a-url"},
        )
        assert malformed.status_code == 403
        match = client.post(
            "/api/import-candidates/confirm",
            json={"candidate_ids": ["x"]},
            headers={"Origin": base, "Referer": f"{base}/imports"},
        )
        assert match.status_code in {400, 404}
        absent = client.post(
            "/api/import-candidates/confirm",
            json={"candidate_ids": ["x"]},
            headers={"Origin": base},
        )
        assert absent.status_code in {400, 404}
        no_origin = client.post(
            "/api/import-candidates/confirm",
            json={"candidate_ids": ["x"]},
            headers={"Referer": f"{base}/imports"},
        )
        assert no_origin.status_code == 403


def test_duplicate_origin_rejected(tmp_path):
    app, settings, _ = _ui(tmp_path)
    base = _base(settings)
    with TestClient(app, base_url=base) as client:
        dup = client.build_request(
            "POST",
            "/api/import-candidates/confirm",
            headers=[("Origin", base), ("Origin", base)],
            json={"candidate_ids": ["x"]},
        )
        assert client.send(dup).status_code == 403


def test_all_unsafe_methods_require_origin(tmp_path):
    app, settings, _ = _ui(tmp_path)
    base = _base(settings)
    with TestClient(app, base_url=base) as client:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            denied = client.request(method, "/api/imports", headers={})
            assert denied.status_code == 403, method
        allowed = client.request("PUT", "/api/imports", headers={"Origin": base})
        assert allowed.status_code in {404, 405}
        assert client.request("DELETE", "/api/imports", headers={"Origin": base}).status_code in {
            404,
            405,
        }


def test_rejected_mutations_leave_state_unchanged(tmp_path):
    app, settings, paths = _ui(tmp_path)
    base = _base(settings)
    png = encode_synthetic_png(
        weigh_in_payload(source_local_date=__import__("datetime").date(2026, 3, 4), weight_kg=81.2)
    )
    with TestClient(app, base_url=base, headers={"Origin": base}) as client:
        uploaded = client.post(
            "/api/imports/photos", files=[("files", ("one.png", png, "image/png"))]
        )
        assert uploaded.status_code == 200
        candidate = uploaded.json()["candidates"][0]["id"]
    before = _counts(paths)
    with TestClient(app, base_url=base) as attacker:
        for headers in (
            {"Origin": EVIL},
            {"Origin": "null"},
            {},
            {"Origin": base, "Sec-Fetch-Site": "cross-site"},
            {"Origin": base, "Referer": "http://evil.example/"},
        ):
            assert (
                attacker.post(
                    "/api/import-candidates/confirm",
                    json={"candidate_ids": [candidate]},
                    headers=headers,
                ).status_code
                == 403
            )
            assert (
                attacker.post(
                    "/api/import-candidates/edit",
                    json={"candidate_id": candidate, "edited_value": 1.0},
                    headers=headers,
                ).status_code
                == 403
            )
    assert _counts(paths) == before


def test_legacy_ui_ingest_probe_stays_404_with_valid_host(tmp_path):
    app, settings, _ = _ui(tmp_path)
    base = _base(settings)
    with TestClient(app, base_url=base) as client:
        assert client.post("/api/ingest/openscale", content=b"{}").status_code == 404
    with TestClient(app, base_url=EVIL_HOST) as foreign:
        assert foreign.post("/api/ingest/openscale", content=b"{}").status_code == 403


def test_ingest_listener_unchanged(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    ingest, _ = create_ingest_app(settings)
    with TestClient(ingest) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/ingest/openscale").status_code == 405
        assert client.get("/api/imports").status_code == 404
        assert client.post("/api/ingest/openscale", content=b"{}").status_code in {401, 503}


def test_privacy_canaries(tmp_path):
    app, settings, paths = _ui(tmp_path)
    log_path = configure_logging(paths.logs)
    base = _base(settings)
    evil_origin = "http://evil.example:6666"
    with TestClient(app, base_url=EVIL_HOST) as foreign:
        body = foreign.post(
            "/api/import-candidates/confirm",
            json={"candidate_ids": ["x"]},
            headers={"Origin": evil_origin},
        )
        assert body.status_code == 403
        assert "evil.example" not in body.text
        assert "6666" not in body.text
    with TestClient(app, base_url=base) as client:
        body = client.post(
            "/api/import-candidates/confirm",
            json={"candidate_ids": ["x"]},
            headers={"Origin": evil_origin},
        )
        assert body.status_code == 403
        assert "evil.example" not in body.text
    logs = log_path.read_text(encoding="utf-8")
    assert "evil.example" not in logs
    assert "6666" not in logs
