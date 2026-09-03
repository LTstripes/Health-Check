"""Loopback-only UI/read/import application composition."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from healthcheck.app import create_base_app
from healthcheck.config import Settings
from healthcheck.ingestion.photo.errors import PhotoImportError
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.logging import log_event
from healthcheck.web.imports import router as import_router


def create_ui_app(settings: Settings | None = None) -> tuple[FastAPI, object]:
    app, paths = create_base_app(
        settings or Settings(),
        service="loopback-ui",
        title="Health-Check local runtime",
    )
    app.state.photo_extractor = FakeImageMeasurementExtractor()
    app.include_router(import_router)

    @app.exception_handler(PhotoImportError)
    async def photo_import_error_handler(_request: Request, exc: PhotoImportError) -> JSONResponse:
        log_event("photo_import_error", operation="photo_import", status="error", reason=exc.code)
        return JSONResponse(
            status_code=exc.status_code, content={"code": exc.code, "message": exc.message}
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_error_handler(_request: Request, _exc: SQLAlchemyError) -> JSONResponse:
        log_event(
            "persistence_error",
            operation="photo_import",
            status="error",
            reason="persistence_error",
        )
        return JSONResponse(
            status_code=500,
            content={"code": "persistence_error", "message": "request failed"},
        )

    @app.exception_handler(Exception)
    async def unsanitized_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, (PhotoImportError, RequestValidationError, StarletteHTTPException)):
            raise exc
        log_event(
            "unhandled_error",
            operation="request",
            status="error",
            reason=type(exc).__name__,
        )
        return JSONResponse(
            status_code=500, content={"code": "internal_error", "message": "request failed"}
        )

    @app.get("/", response_class=PlainTextResponse)
    def bootstrap_page() -> str:
        return "Health-Check bootstrap runtime is ready."

    return app, paths


app, _runtime_paths = create_ui_app()
