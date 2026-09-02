"""Loopback-only UI/read/import application composition."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from healthcheck.app import create_base_app
from healthcheck.config import Settings


def create_ui_app(settings: Settings | None = None) -> tuple[FastAPI, object]:
    app, paths = create_base_app(
        settings or Settings(),
        service="loopback-ui",
        title="Health-Check local runtime",
    )

    @app.get("/", response_class=PlainTextResponse)
    def bootstrap_page() -> str:
        return "Health-Check bootstrap runtime is ready."

    return app, paths


app, _runtime_paths = create_ui_app()
