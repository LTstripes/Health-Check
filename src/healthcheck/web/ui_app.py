"""Loopback-only UI/read/import application composition."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from healthcheck.app import create_base_app
from healthcheck.config import Settings
from healthcheck.ingestion.photo.errors import PhotoImportError
from healthcheck.ingestion.photo.extractor import ImageMeasurementExtractor
from healthcheck.ingestion.photo.vision import build_photo_extractor
from healthcheck.logging import log_event
from healthcheck.web.common import wants_html
from healthcheck.web.imports import router as import_router
from healthcheck.web.pages import html_http_error, render_error
from healthcheck.web.pages import router as pages_router
from healthcheck.web.weight import router as weight_router

WEB_DIR = Path(__file__).resolve().parent


def create_ui_app(
    settings: Settings | None = None,
    *,
    photo_extractor: ImageMeasurementExtractor | None = None,
) -> tuple[FastAPI, object]:
    resolved = settings or Settings()
    app, paths = create_base_app(
        resolved,
        service="loopback-ui",
        title="Health-Check local runtime",
    )
    app.state.photo_extractor = (
        photo_extractor if photo_extractor is not None else build_photo_extractor(resolved)
    )
    app.include_router(import_router)
    app.include_router(weight_router)
    app.include_router(pages_router)
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

    @app.exception_handler(PhotoImportError)
    async def photo_import_error_handler(request: Request, exc: PhotoImportError) -> JSONResponse:
        log_event("photo_import_error", operation="photo_import", status="error", reason=exc.code)
        if wants_html(request):
            return render_error(
                request, code=exc.code, message=exc.message, status_code=exc.status_code
            )
        return JSONResponse(
            status_code=exc.status_code, content={"code": exc.code, "message": exc.message}
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, _exc: RequestValidationError):
        log_event("invalid_request", operation="request", status="error", reason="invalid_request")
        if wants_html(request):
            return render_error(
                request,
                code="invalid_request",
                message="request could not be parsed",
                status_code=422,
            )
        return JSONResponse(
            status_code=422,
            content={"code": "invalid_request", "message": "request could not be parsed"},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        html = html_http_error(request, exc.status_code, str(exc.detail))
        if html is not None:
            return html
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": "http_error", "message": "request failed"},
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
        if isinstance(
            exc, (PhotoImportError, RequestValidationError, StarletteHTTPException, SQLAlchemyError)
        ):
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

    return app, paths


app, _runtime_paths = create_ui_app()
