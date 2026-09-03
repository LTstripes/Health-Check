"""Shared loopback-UI helpers.  Not imported by the ingest listener."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import Request
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from healthcheck.db.engine import create_sqlite_engine

BIA_UNCERTAINTY = (
    "Consumer bioimpedance (BIA) is non-clinical and method-sensitive. "
    "This dashboard does not diagnose, claim causation, or report precise tissue change. "
    "Small BIA movements may reflect hydration, glycogen, or method noise."
)
ALGORITHM_BOUNDARY_WARNING = (
    "Incompatible body-composition algorithms are shown as separate series. "
    "Xiaomi-app and openScale values are not mixed, converted, or compared across "
    "an algorithm boundary."
)


def request_engine(request: Request) -> Engine:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        engine = create_sqlite_engine(request.app.state.runtime_paths)
        request.app.state.engine = engine
    return engine


def parse_optional_date(value: str | None) -> date | None:
    if value is None or not str(value).strip():
        return None
    return date.fromisoformat(str(value).strip()[:10])


def iso_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def wants_html(request: Request) -> bool:
    path = request.url.path
    if path.startswith("/api/") or path == "/healthz":
        return False
    accept = request.headers.get("accept", "")
    if "application/json" in accept and "text/html" not in accept:
        return False
    return True


def database_unavailable(exc: BaseException) -> bool:
    if isinstance(exc, OperationalError):
        return True
    message = str(exc).lower()
    return "no such table" in message or "unable to open database" in message


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value
