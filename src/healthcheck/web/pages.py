"""Server-rendered loopback pages for the dashboard and photo review queue."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.db.engine import session_scope
from healthcheck.ingestion.photo.errors import PhotoImportError
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.ingestion.photo.service import PhotoImportService, PhotoUpload
from healthcheck.logging import log_event
from healthcheck.web.common import database_unavailable, request_engine, wants_html
from healthcheck.web.imports import _batch_payload
from healthcheck.web.query import (
    WeightQueryService,
    empty_dashboard_payload,
    group_review_events,
)

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
router = APIRouter()


def render(
    request: Request, name: str, context: dict[str, Any], status_code: int = 200
) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def render_error(
    request: Request, *, code: str, message: str, status_code: int = 400
) -> HTMLResponse:
    return render(
        request,
        "error.html",
        {"code": code, "message": message, "status_code": status_code},
        status_code=status_code,
    )


def _photo_error(request: Request, exc: PhotoImportError) -> HTMLResponse:
    return render_error(request, code=exc.code, message=exc.message, status_code=exc.status_code)


def _persist_error(request: Request, operation: str) -> HTMLResponse:
    log_event("persistence_error", operation=operation, status="error", reason="persistence_error")
    return render_error(
        request, code="persistence_error", message="request failed", status_code=500
    )


def _extractor(request: Request):
    return getattr(request.app.state, "photo_extractor", None) or FakeImageMeasurementExtractor()


@router.get("/", response_class=HTMLResponse)
def dashboard_page(request: Request) -> HTMLResponse:
    try:
        with session_scope(request_engine(request)) as session:
            service = WeightQueryService(session, request.app.state.settings)
            payload = service.dashboard()
    except SQLAlchemyError as exc:
        if not database_unavailable(exc):
            return _persist_error(request, "dashboard")
        payload = empty_dashboard_payload(reason="database_unavailable")
    return render(request, "dashboard.html", {"payload": payload, "page": "dashboard"})


@router.get("/imports", response_class=HTMLResponse)
def imports_page(request: Request) -> HTMLResponse:
    try:
        with session_scope(request_engine(request)) as session:
            service = PhotoImportService(
                session, request.app.state.runtime_paths, _extractor(request)
            )
            batches = service.list_batches()
            queue = WeightQueryService(session, request.app.state.settings).import_queue_summary()
    except SQLAlchemyError as exc:
        if not database_unavailable(exc):
            return _persist_error(request, "imports")
        batches = []
        queue = empty_dashboard_payload(reason="database_unavailable")["imports"]
    return render(
        request,
        "imports.html",
        {"batches": batches, "queue": queue, "page": "imports"},
    )


@router.post("/imports/photos", response_model=None)
async def upload_photos(
    request: Request,
    files: list[UploadFile] = File(...),
) -> RedirectResponse | HTMLResponse:
    uploads: list[PhotoUpload] = []
    for uploaded in files:
        uploads.append(
            PhotoUpload(
                filename=uploaded.filename,
                content=await uploaded.read(),
                declared_media_type=uploaded.content_type,
            )
        )
        await uploaded.close()
    try:
        with session_scope(request_engine(request)) as session:
            service = PhotoImportService(
                session, request.app.state.runtime_paths, _extractor(request)
            )
            result = service.import_photos(uploads)
            batch_id = result.batch.id
        return RedirectResponse(url=f"/imports/{batch_id}", status_code=303)
    except PhotoImportError as exc:
        return _photo_error(request, exc)
    except SQLAlchemyError:
        return _persist_error(request, "photo_import")


@router.get("/imports/{batch_id}", response_class=HTMLResponse)
def import_review_page(request: Request, batch_id: str) -> HTMLResponse:
    try:
        with session_scope(request_engine(request)) as session:
            service = PhotoImportService(
                session, request.app.state.runtime_paths, _extractor(request)
            )
            batch = _batch_payload(service, batch_id)
            groups = group_review_events(batch)
    except PhotoImportError as exc:
        return _photo_error(request, exc)
    except SQLAlchemyError as exc:
        if database_unavailable(exc):
            return render_error(
                request,
                code="database_unavailable",
                message="database is not ready",
                status_code=503,
            )
        return _persist_error(request, "import_review")
    return render(
        request,
        "import_detail.html",
        {"batch": batch, "groups": groups, "page": "imports"},
    )


@router.post("/imports/{batch_id}/edit", response_model=None)
def edit_from_review(
    request: Request,
    batch_id: str,
    candidate_id: str = Form(...),
    edited_value: str | None = Form(default=None),
    edited_unit: str | None = Form(default=None),
    edited_source_local_date: date | None = Form(default=None),
) -> RedirectResponse | HTMLResponse:
    value = None
    if edited_value not in (None, ""):
        try:
            value = float(edited_value)
        except ValueError:
            return render_error(
                request, code="invalid_edit", message="edited value is not a number"
            )
    try:
        with session_scope(request_engine(request)) as session:
            service = PhotoImportService(
                session, request.app.state.runtime_paths, _extractor(request)
            )
            service.edit_pending(
                candidate_id,
                edited_value=value,
                edited_unit=edited_unit or None,
                edited_source_local_date=edited_source_local_date,
            )
        return RedirectResponse(url=f"/imports/{batch_id}", status_code=303)
    except PhotoImportError as exc:
        return _photo_error(request, exc)
    except SQLAlchemyError:
        return _persist_error(request, "photo_edit")


@router.post("/imports/{batch_id}/confirm", response_model=None)
def confirm_from_review(
    request: Request,
    batch_id: str,
    candidate_ids: list[str] = Form(default=[]),
) -> RedirectResponse | HTMLResponse:
    selected = [item for item in candidate_ids if item]
    if not selected:
        return render_error(
            request, code="empty_selection", message="select at least one candidate"
        )
    try:
        with session_scope(request_engine(request)) as session:
            service = PhotoImportService(
                session, request.app.state.runtime_paths, _extractor(request)
            )
            service.confirm(selected)
        return RedirectResponse(url=f"/imports/{batch_id}", status_code=303)
    except PhotoImportError as exc:
        return _photo_error(request, exc)
    except SQLAlchemyError:
        return _persist_error(request, "photo_confirm")


@router.post("/imports/{batch_id}/reject", response_model=None)
def reject_from_review(
    request: Request,
    batch_id: str,
    candidate_ids: list[str] = Form(default=[]),
    reason: str | None = Form(default=None),
) -> RedirectResponse | HTMLResponse:
    selected = [item for item in candidate_ids if item]
    if not selected:
        return render_error(
            request, code="empty_selection", message="select at least one candidate"
        )
    try:
        with session_scope(request_engine(request)) as session:
            service = PhotoImportService(
                session, request.app.state.runtime_paths, _extractor(request)
            )
            service.reject(selected, reason=reason)
        return RedirectResponse(url=f"/imports/{batch_id}", status_code=303)
    except PhotoImportError as exc:
        return _photo_error(request, exc)
    except SQLAlchemyError:
        return _persist_error(request, "photo_reject")


def html_http_error(request: Request, status_code: int, detail: str) -> HTMLResponse | None:
    if not wants_html(request):
        return None
    message = "not found" if status_code == 404 else "request failed"
    code = "not_found" if status_code == 404 else "http_error"
    del detail
    return render_error(request, code=code, message=message, status_code=status_code)
