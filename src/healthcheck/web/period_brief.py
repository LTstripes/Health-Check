"""Loopback GET-only routes for the #119 deterministic period brief."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.db.engine import session_scope
from healthcheck.logging import log_event
from healthcheck.web.common import database_unavailable, request_engine
from healthcheck.web.period_brief_query import PeriodBriefService

router = APIRouter()


def _json(payload: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(payload), status_code=status_code)


def _brief_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, ValueError):
        return _json({"code": "invalid_period_brief_request", "message": str(exc)}, status_code=400)
    log_event(
        "period_brief_error",
        operation="period_brief",
        status="error",
        reason=type(exc).__name__,
    )
    return _json({"code": "period_brief_error", "message": "request failed"}, status_code=500)


@router.get("/api/period-brief")
def period_brief(
    request: Request,
    start_date: date = Query(...),
    end_date: date = Query(...),
    garmin_source_id: str | None = Query(default=None),
    thin_display: bool = Query(default=False),
) -> JSONResponse:
    try:
        with session_scope(request_engine(request)) as session:
            settings = getattr(request.app.state, "settings", None)
            service = PeriodBriefService(session, settings)
            payload = service.build_with_render(
                start_date=start_date,
                end_date=end_date,
                garmin_source_id=garmin_source_id,
                thin_display=thin_display,
            )
            return _json(payload)
    except SQLAlchemyError as exc:
        if database_unavailable(exc):
            return _json(
                {
                    "available": False,
                    "reason": "database_unavailable",
                    "packet": None,
                    "rendered_text": None,
                }
            )
        return _brief_error(exc)
    except Exception as exc:
        return _brief_error(exc)


@router.get("/api/period-brief.txt", response_model=None)
def period_brief_text(
    request: Request,
    start_date: date = Query(...),
    end_date: date = Query(...),
    garmin_source_id: str | None = Query(default=None),
) -> Any:
    try:
        with session_scope(request_engine(request)) as session:
            settings = getattr(request.app.state, "settings", None)
            service = PeriodBriefService(session, settings)
            payload = service.build_with_render(
                start_date=start_date,
                end_date=end_date,
                garmin_source_id=garmin_source_id,
                thin_display=False,
            )
            return PlainTextResponse(payload["rendered_text"])
    except SQLAlchemyError as exc:
        if database_unavailable(exc):
            return PlainTextResponse("period brief unavailable: database_unavailable\n")
        return _brief_error(exc)
    except Exception as exc:
        return _brief_error(exc)
