"""Read-only saved Garmin activity session detail page (#345).

One explicit persisted ``garmin_source_id`` plus one current activity record id.
The page renders only existing typed evidence from the accepted read contract; a
missing, unknown, retired, non-activity or cross-source record returns a bounded
error instead of another session. No live endpoint, provider, schema or write.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.db.engine import session_scope
from healthcheck.web.common import database_unavailable, request_engine
from healthcheck.web.garmin_query import GarminQueryError, GarminQueryService
from healthcheck.web.owner_presentation import owner_date, owner_number
from healthcheck.web.pages import _persist_error, render_error

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
templates.env.filters.update(owner_date=owner_date, owner_number=owner_number)

_SESSION_NOT_FOUND_CODES = frozenset(
    {
        "unknown_activity_record_id",
        "wrong_source_activity_record",
        "non_current_activity_record",
        "non_activity_record",
    }
)
_SELECTION_MESSAGES = {
    "missing_garmin_source_id": (
        "Источник не указан. Открой сессию из журнала на странице «Активность»."
    ),
    "missing_activity_record_id": (
        "Сохранённая сессия не выбрана. Открой её из журнала на странице «Активность»."
    ),
}
_SESSION_NOT_FOUND_MESSAGE = (
    "Сохранённая сессия не найдена в выбранном источнике. "
    "Вернись к журналу активности и открой сессию заново."
)


def _back_href(
    detail: dict[str, Any],
    metric_code: str | None,
    start_date: date | None,
    end_date: date | None,
) -> str:
    """Journal return link preserving the exact selected source and period parameters."""

    source = detail.get("source") or {}
    params: list[tuple[str, str]] = []
    source_id = source.get("id")
    if source_id:
        params.append(("garmin_source_id", str(source_id)))
    if metric_code:
        params.append(("metric_code", metric_code))
    if start_date is not None:
        params.append(("start_date", start_date.isoformat()))
    if end_date is not None:
        params.append(("end_date", end_date.isoformat()))
    query = urlencode(params)
    return f"/garmin?{query}#activity-journal" if query else "/garmin#activity-journal"


@router.get("/garmin/session", response_class=HTMLResponse)
def garmin_session_detail_page(
    request: Request,
    garmin_source_id: str | None = None,
    record_id: str | None = None,
    metric_code: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> HTMLResponse:
    try:
        with session_scope(request_engine(request)) as session:
            service = GarminQueryService(session, request.app.state.settings)
            detail = service.activity_session_detail(
                garmin_source_id=garmin_source_id or "",
                activity_record_id=record_id or "",
            )
    except GarminQueryError as exc:
        if exc.code in _SESSION_NOT_FOUND_CODES:
            return render_error(
                request,
                code="activity_session_not_found",
                message=_SESSION_NOT_FOUND_MESSAGE,
                status_code=404,
            )
        message = _SELECTION_MESSAGES.get(exc.code, exc.message)
        return render_error(request, code=exc.code, message=message, status_code=exc.status_code)
    except SQLAlchemyError as exc:
        # Owner read-failure parity with the other HTML pages (#347): the shared
        # 503 document for uninitialized storage, the Russian 500 alert otherwise.
        if not database_unavailable(exc):
            return _persist_error(request, "garmin_session_detail")
        return render_error(
            request,
            code="database_unavailable",
            message="database is not ready",
            status_code=503,
        )
    return templates.TemplateResponse(
        request=request,
        name="activity_detail.html",
        context={
            "page": "garmin",
            "detail": detail,
            "back_href": _back_href(detail, metric_code, start_date, end_date),
        },
        headers={"Cache-Control": "no-store"},
    )
