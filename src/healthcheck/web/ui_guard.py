"""UI-only Host / same-origin mutation guard (issue #244)."""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse

from healthcheck.logging import log_event

ALLOWED_UI_HOSTS = frozenset({"127.0.0.1", "localhost"})
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
COMPAT_INGEST_PROBE_PATH = "/api/ingest/openscale"

_HOST_FORBIDDEN = "host_forbidden"
_ORIGIN_FORBIDDEN = "origin_forbidden"


def _raw_counts(raw_headers: list[tuple[bytes, bytes]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, _ in raw_headers:
        key = bytes(name).decode("latin-1").lower()
        counts[key] = counts.get(key, 0) + 1
    return counts


def _raw_values(raw_headers: list[tuple[bytes, bytes]], name: str) -> list[str]:
    wanted = name.lower()
    values: list[str] = []
    for raw_name, raw_value in raw_headers:
        if bytes(raw_name).decode("latin-1").lower() == wanted:
            values.append(bytes(raw_value).decode("latin-1"))
    return values


def _effective_ui_port(request: Request) -> int | None:
    try:
        settings = getattr(request.app.state, "settings", None)
        port = getattr(settings, "ui_port", None)
        if isinstance(port, int) and 1 <= port <= 65535:
            return port
        return None
    except Exception:
        return None


def _parse_host(value: str, effective_port: int) -> str | None:
    """Return normalized host if valid, else None. Strict, no aliasing."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if "," in text or any(ch.isspace() for ch in text):
        return None
    if "@" in text or "/" in text or "?" in text or "#" in text:
        return None
    host: str
    port: int
    if text.startswith("["):
        return None
    if ":" in text:
        name, _, port_text = text.rpartition(":")
        if not name or not port_text or not port_text.isdigit():
            return None
        port = int(port_text)
        if not 1 <= port <= 65535:
            return None
        host = name.strip().lower()
    else:
        host = text.lower()
        port = 80
    if host not in ALLOWED_UI_HOSTS:
        return None
    if port != effective_port:
        return None
    return host


def _origin_parts(value: str) -> tuple[str, str, int] | None:
    if value is None:
        return None
    text = value.strip()
    if not text or text == "null":
        return None
    if "," in text or any(ch.isspace() for ch in text):
        return None
    try:
        parsed = urlparse(text)
    except Exception:
        return None
    if parsed.scheme != "http":
        return None
    netloc = parsed.netloc
    if not netloc or "@" in netloc:
        return None
    if parsed.path not in ("",) or parsed.query or parsed.fragment:
        return None
    hostname = (parsed.hostname or "").lower()
    if hostname not in ALLOWED_UI_HOSTS:
        return None
    try:
        port = parsed.port if parsed.port is not None else 80
    except ValueError:
        return None
    if not 1 <= port <= 65535:
        return None
    return (parsed.scheme, hostname, port)


def _referer_origin(value: str) -> tuple[str, str, int] | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = urlparse(text)
    except Exception:
        return None
    if parsed.scheme != "http":
        return None
    if "@" in (parsed.netloc or ""):
        return None
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return None
    try:
        port = parsed.port if parsed.port is not None else 80
    except ValueError:
        return None
    return (parsed.scheme, hostname, port)


def _forbidden(code: str) -> JSONResponse:
    log_event("ui_request_forbidden", operation="ui_guard", status="error", reason=code)
    return JSONResponse(status_code=403, content={"code": code, "message": "request failed"})


async def ui_guard_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    raw = list(request.scope.get("headers", []))
    counts = _raw_counts(raw)
    effective_port = _effective_ui_port(request)
    if effective_port is None:
        return _forbidden(_HOST_FORBIDDEN)
    if counts.get("host", 0) != 1:
        return _forbidden(_HOST_FORBIDDEN)
    host_value = _raw_values(raw, "host")[0]
    validated_host = _parse_host(host_value, effective_port)
    if validated_host is None:
        return _forbidden(_HOST_FORBIDDEN)

    method = str(request.scope.get("method", "")).upper()
    if method not in UNSAFE_METHODS:
        return await call_next(request)
    path = str(request.scope.get("path", ""))
    if method == "POST" and path == COMPAT_INGEST_PROBE_PATH:
        return await call_next(request)

    if counts.get("origin", 0) != 1:
        return _forbidden(_ORIGIN_FORBIDDEN)
    if counts.get("sec-fetch-site", 0) > 1:
        return _forbidden(_ORIGIN_FORBIDDEN)
    if counts.get("referer", 0) > 1:
        return _forbidden(_ORIGIN_FORBIDDEN)

    origin_value = _raw_values(raw, "origin")[0]
    origin = _origin_parts(origin_value)
    if origin is None:
        return _forbidden(_ORIGIN_FORBIDDEN)
    _, origin_host, origin_port = origin
    if origin_host != validated_host or origin_port != effective_port:
        return _forbidden(_ORIGIN_FORBIDDEN)

    fetch_values = _raw_values(raw, "sec-fetch-site")
    if fetch_values:
        if fetch_values[0].strip().lower() != "same-origin":
            return _forbidden(_ORIGIN_FORBIDDEN)

    referer_values = _raw_values(raw, "referer")
    if referer_values:
        referer = _referer_origin(referer_values[0])
        if referer is None:
            return _forbidden(_ORIGIN_FORBIDDEN)
        _, referer_host, referer_port = referer
        if referer_host != validated_host or referer_port != effective_port:
            return _forbidden(_ORIGIN_FORBIDDEN)

    return await call_next(request)
