"""Read-only local smoke probes for owner UAT preparation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class SmokeResult:
    status: str
    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class _HttpResult:
    status_code: int | None
    content_type: str
    body: bytes


def run_smoke(
    *,
    ui_url: str = "http://127.0.0.1:8120",
    ingest_url: str | None = None,
    timeout: float = 3.0,
) -> list[SmokeResult]:
    """Run deterministic status/shape probes without printing response bodies."""

    results: list[SmokeResult] = []
    ui_base = ui_url.rstrip("/")
    _check_health(
        results,
        ui_base,
        "/healthz",
        expected_service="loopback-ui",
        display_path="/healthz",
        timeout=timeout,
    )
    _check_html(results, ui_base, "/", timeout=timeout)
    _check_weight_api(
        results,
        ui_base,
        "/api/weight/series",
        required=("raw_points", "composition_by_group"),
        timeout=timeout,
    )
    _check_weight_api(
        results,
        ui_base,
        "/api/weight/summary",
        required=("trend", "latest_composition", "coverage"),
        timeout=timeout,
    )
    _check_status(
        results,
        ui_base,
        "/api/ingest/openscale",
        method="POST",
        expected=404,
        timeout=timeout,
    )

    if ingest_url is None:
        results.append(SmokeResult("SKIP", "/ingest/healthz", "ingest URL not supplied"))
        results.append(SmokeResult("SKIP", "/ingest route isolation", "ingest URL not supplied"))
    else:
        ingest_base = ingest_url.rstrip("/")
        _check_health(
            results,
            ingest_base,
            "/healthz",
            expected_service="ingest",
            display_path="/ingest/healthz",
            timeout=timeout,
        )
        for path in ("/", "/api/weight/series", "/static/dashboard.js"):
            _check_status(
                results,
                ingest_base,
                path,
                method="GET",
                expected=404,
                display_path=f"/ingest{path}",
                timeout=timeout,
            )

    return results


def smoke_exit_code(results: list[SmokeResult]) -> int:
    return 1 if any(result.status == "FAIL" for result in results) else 0


def format_smoke_results(results: list[SmokeResult]) -> str:
    lines = [f"{result.status} {result.path}: {result.reason}" for result in results]
    lines.append(f"OVERALL {'FAIL' if smoke_exit_code(results) else 'PASS'}")
    return "\n".join(lines)


def _check_health(
    results: list[SmokeResult],
    base: str,
    path: str,
    *,
    expected_service: str,
    display_path: str,
    timeout: float,
) -> None:
    response = _request(base + path, timeout=timeout)
    if response.status_code != 200:
        _append_http_failure(results, display_path, response, expected="HTTP 200")
        return
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, ValueError):
        results.append(SmokeResult("FAIL", display_path, "invalid JSON"))
        return
    if (
        not isinstance(payload, dict)
        or payload.get("status") != "ok"
        or payload.get("service") != expected_service
    ):
        results.append(SmokeResult("FAIL", display_path, "unexpected health response"))
        return
    results.append(SmokeResult("PASS", display_path, "service ready"))


def _check_html(results: list[SmokeResult], base: str, path: str, *, timeout: float) -> None:
    response = _request(base + path, timeout=timeout)
    if response.status_code != 200:
        _append_http_failure(results, path, response, expected="HTTP 200")
    elif "text/html" not in response.content_type.lower():
        results.append(SmokeResult("FAIL", path, "unexpected content type"))
    else:
        results.append(SmokeResult("PASS", path, "dashboard reachable"))


def _check_weight_api(
    results: list[SmokeResult],
    base: str,
    path: str,
    *,
    required: tuple[str, ...],
    timeout: float,
) -> None:
    response = _request(base + path, timeout=timeout)
    if response.status_code != 200:
        _append_http_failure(results, path, response, expected="HTTP 200")
        return
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, ValueError):
        results.append(SmokeResult("FAIL", path, "invalid JSON"))
        return
    if not isinstance(payload, dict) or any(key not in payload for key in required):
        results.append(SmokeResult("FAIL", path, "unexpected API shape"))
        return
    results.append(SmokeResult("PASS", path, "API shape valid"))


def _check_status(
    results: list[SmokeResult],
    base: str,
    path: str,
    *,
    method: str,
    expected: int,
    display_path: str | None = None,
    timeout: float,
) -> None:
    response = _request(base + path, method=method, timeout=timeout)
    result_path = display_path or path
    if response.status_code == expected:
        results.append(SmokeResult("PASS", result_path, f"route returned HTTP {expected}"))
    else:
        _append_http_failure(results, result_path, response, expected=f"HTTP {expected}")


def _append_http_failure(
    results: list[SmokeResult], path: str, response: _HttpResult, *, expected: str
) -> None:
    if response.status_code is None:
        results.append(SmokeResult("FAIL", path, "endpoint unreachable"))
    else:
        results.append(
            SmokeResult("FAIL", path, f"expected {expected}, got HTTP {response.status_code}")
        )


def _request(url: str, *, method: str = "GET", timeout: float) -> _HttpResult:
    request = Request(url, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return _HttpResult(
                status_code=response.status,
                content_type=response.headers.get("content-type", ""),
                body=response.read(256 * 1024),
            )
    except HTTPError as exc:
        return _HttpResult(status_code=exc.code, content_type="", body=b"")
    except (OSError, URLError, TimeoutError, ValueError):
        return _HttpResult(status_code=None, content_type="", body=b"")
