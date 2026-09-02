"""Separate ingest-only ASGI application composition."""

from __future__ import annotations

from fastapi import FastAPI

from healthcheck.app import create_base_app
from healthcheck.config import Settings


def create_ingest_app(settings: Settings | None = None) -> tuple[FastAPI, object]:
    return create_base_app(
        settings or Settings(),
        service="ingest",
        title="Health-Check ingest listener",
    )


app, _runtime_paths = create_ingest_app()
