from __future__ import annotations

import json
from pathlib import Path

import pytest

from healthcheck.config import Settings
from healthcheck.demo import DEMO_MARKER_NAME, DemoSeedError, seed_demo
from healthcheck.uat import (
    _HttpResult,
    format_smoke_results,
    run_smoke,
    smoke_exit_code,
)


def test_seed_demo_is_idempotent_and_exposes_dashboard_data(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "synthetic-demo")

    first = seed_demo(settings)
    second = seed_demo(settings)

    assert first.created is True
    assert first.weigh_in_count == 26
    assert first.candidate_count == 59
    assert second.created is False
    assert second.weigh_in_count == first.weigh_in_count
    assert second.candidate_count == first.candidate_count
    marker = settings.data_dir / DEMO_MARKER_NAME
    assert json.loads(marker.read_text(encoding="utf-8"))["label"] == "synthetic demo data"


def test_seed_demo_reset_requires_owned_marker_and_does_not_touch_unknown_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "existing-profile"
    target.mkdir()
    sentinel = target / "private-looking.txt"
    sentinel.write_text("must remain", encoding="utf-8")

    with pytest.raises(DemoSeedError, match="non-empty"):
        seed_demo(Settings(data_dir=target), reset=True)

    assert sentinel.read_text(encoding="utf-8") == "must remain"


def test_seed_demo_reset_rebuilds_only_marked_profile(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "synthetic-demo")
    seed_demo(settings)
    extra = settings.data_dir / "owner-note.txt"
    extra.write_text("leave this file", encoding="utf-8")

    result = seed_demo(settings, reset=True)

    assert result.created is True
    assert result.reset is True
    assert extra.read_text(encoding="utf-8") == "leave this file"


def test_seed_demo_rejects_checkout_target(tmp_path: Path) -> None:
    del tmp_path
    with pytest.raises(DemoSeedError, match="outside the checkout"):
        seed_demo(Settings(data_dir=Path(__file__).resolve().parents[1]))


def test_smoke_reports_pass_skip_and_never_prints_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = b"Bearer private-token; 80.00 kg"
    responses = {
        ("http://ui/healthz", "GET"): _HttpResult(
            200, "application/json", b'{"status":"ok","service":"loopback-ui"}'
        ),
        ("http://ui/", "GET"): _HttpResult(200, "text/html", secret),
        ("http://ui/api/weight/series", "GET"): _HttpResult(
            200, "application/json", b'{"raw_points":[],"composition_by_group":{}}'
        ),
        ("http://ui/api/weight/summary", "GET"): _HttpResult(
            200, "application/json", b'{"trend":{},"latest_composition":{},"coverage":null}'
        ),
        ("http://ui/api/ingest/openscale", "POST"): _HttpResult(
            404, "application/json", b"private response"
        ),
    }

    def fake_request(url: str, *, method: str = "GET", timeout: float) -> _HttpResult:
        del timeout
        return responses[(url, method)]

    monkeypatch.setattr("healthcheck.uat._request", fake_request)
    results = run_smoke(ui_url="http://ui")
    rendered = format_smoke_results(results)

    assert smoke_exit_code(results) == 0
    assert "OVERALL PASS" in rendered
    assert "SKIP /ingest/healthz" in rendered
    assert "private-token" not in rendered
    assert "80.00" not in rendered


def test_smoke_checks_ingest_liveness_and_route_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = {
        ("http://ui/healthz", "GET"): _HttpResult(
            200, "application/json", b'{"status":"ok","service":"loopback-ui"}'
        ),
        ("http://ui/", "GET"): _HttpResult(200, "text/html", b"synthetic dashboard"),
        ("http://ui/api/weight/series", "GET"): _HttpResult(
            200, "application/json", b'{"raw_points":[],"composition_by_group":{}}'
        ),
        ("http://ui/api/weight/summary", "GET"): _HttpResult(
            200, "application/json", b'{"trend":{},"latest_composition":{},"coverage":null}'
        ),
        ("http://ui/api/ingest/openscale", "POST"): _HttpResult(404, "", b""),
        ("http://ingest/healthz", "GET"): _HttpResult(
            200, "application/json", b'{"status":"ok","service":"ingest"}'
        ),
        ("http://ingest/", "GET"): _HttpResult(404, "", b""),
        ("http://ingest/api/weight/series", "GET"): _HttpResult(404, "", b""),
        ("http://ingest/static/dashboard.js", "GET"): _HttpResult(404, "", b""),
    }

    def fake_request(url: str, *, method: str = "GET", timeout: float) -> _HttpResult:
        del timeout
        return responses[(url, method)]

    monkeypatch.setattr("healthcheck.uat._request", fake_request)
    results = run_smoke(ui_url="http://ui", ingest_url="http://ingest")

    assert smoke_exit_code(results) == 0
    assert all(result.status == "PASS" for result in results)
    assert "/ingest/healthz" in format_smoke_results(results)
