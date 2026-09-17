"""Synthetic route/template coverage for the #127 Period Brief page."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from healthcheck.config import Settings
from healthcheck.db.engine import migrate_database
from healthcheck.runtime import prepare_runtime
from healthcheck.web.ui_app import create_ui_app


def _ui(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ui_app(settings)
    return app


def test_period_brief_page_defaults_to_bounded_local_period_and_exposes_nav(tmp_path):
    app = _ui(tmp_path)
    end = date.today()
    start = end - timedelta(days=29)

    with TestClient(app) as client:
        page = client.get("/brief")
        home = client.get("/")

    assert page.status_code == 200
    assert "Period Brief" in page.text
    assert f"{start.isoformat()} → {end.isoformat()}" in page.text
    assert 'href="/brief"' in home.text
    assert "No Garmin source" in page.text
    assert "unavailable" in page.text
    assert "period-brief-v1" in page.text
    assert "Traceback" not in page.text
    assert "SELECT " not in page.text
    assert "password" not in page.text.lower()


def test_period_brief_page_supports_presets_and_custom_period(tmp_path):
    app = _ui(tmp_path)
    with TestClient(app) as client:
        for days in (7, 30, 90):
            end = date.today()
            start = end - timedelta(days=days - 1)
            response = client.get("/brief", params={"preset": str(days)})
            assert response.status_code == 200
            assert f"{start.isoformat()} → {end.isoformat()}" in response.text
            assert f'name="start_date" value="{start.isoformat()}"' in response.text
            assert f'name="end_date" value="{end.isoformat()}"' in response.text

        custom = client.get(
            "/brief",
            params={"start_date": "2099-02-03", "end_date": "2099-02-17"},
        )

    assert custom.status_code == 200
    assert "2099-02-03 → 2099-02-17" in custom.text
    assert "15 days" in custom.text


def test_period_brief_page_rejects_invalid_period_controls(tmp_path):
    app = _ui(tmp_path)
    with TestClient(app) as client:
        bad_preset = client.get("/brief", params={"preset": "14"})
        bad_date = client.get(
            "/brief", params={"start_date": "not-a-date", "end_date": "2099-01-01"}
        )
        reversed_period = client.get(
            "/brief", params={"start_date": "2099-02-01", "end_date": "2099-01-01"}
        )

    for response in (bad_preset, bad_date, reversed_period):
        assert response.status_code == 400
        assert "invalid_period" in response.text
        assert "request failed" not in response.text
