"""Separate ingest-only ASGI application composition."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.app import create_base_app
from healthcheck.config import Settings
from healthcheck.ingestion.openscale.errors import OpenScaleIngestError
from healthcheck.logging import log_event
from healthcheck.web.openscale import router as openscale_router


def create_ingest_app(settings: Settings | None = None) -> tuple[FastAPI, object]:
    resolved = settings or Settings()
    warning = resolved.ingest_binding_warning()
    if warning is not None:
        log_event(
            "ingest_plain_lan_warning",
            operation="serve",
            service="ingest",
            status="warning",
            reason="trusted_private_lan_http",
        )
    app, paths = create_base_app(
        resolved,
        service="ingest",
        title="Health-Check ingest listener",
    )
    app.include_router(openscale_router)

    @app.exception_handler(OpenScaleIngestError)
    async def openscale_error_handler(_request: Request, exc: OpenScaleIngestError) -> JSONResponse:
        log_event(
            "openscale_ingest_error",
            operation="openscale_ingest",
            status="error",
            reason=exc.code,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_error_handler(_request: Request, _exc: SQLAlchemyError) -> JSONResponse:
        log_event(
            "persistence_error",
            operation="openscale_ingest",
            status="error",
            reason="persistence_error",
        )
        return JSONResponse(
            status_code=500,
            content={"code": "persistence_error", "message": "request failed"},
        )

    return app, paths


app, _runtime_paths = create_ingest_app()
