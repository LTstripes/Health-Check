"""Loopback GET-only routes for the R05 owner agreement report."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.analytics.sleep_agreement_report import (
    SleepAgreementReportService,
    unavailable_report,
)
from healthcheck.db.engine import session_scope
from healthcheck.logging import log_event
from healthcheck.web.common import database_unavailable, request_engine

router = APIRouter()


def _json(payload: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(payload), status_code=status_code)


def _report_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, ValueError):
        return _json({"code": "invalid_report_request", "message": str(exc)}, status_code=400)
    log_event(
        "agreement_report_error",
        operation="agreement_report",
        status="error",
        reason=type(exc).__name__,
    )
    return _json({"code": "agreement_report_error", "message": "request failed"}, status_code=500)


@router.get("/api/agreement/report")
def agreement_report(
    request: Request,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    cohort: str = Query(default="all"),
    run_id: str | None = Query(default=None),
) -> JSONResponse:
    try:
        with session_scope(request_engine(request)) as session:
            payload = SleepAgreementReportService(session).report(
                start_date=start_date,
                end_date=end_date,
                cohort=cohort,
                run_id=run_id,
            )
            return _json(payload)
    except SQLAlchemyError as exc:
        if database_unavailable(exc):
            return _json(unavailable_report(reason="database_unavailable"))
        return _report_error(exc)
    except Exception as exc:
        return _report_error(exc)


@router.get("/api/agreement/report/{run_id}/nights")
def agreement_report_nights(
    request: Request,
    run_id: str,
    wake_date: date | None = Query(default=None),
    metric_code: str | None = Query(default=None),
) -> JSONResponse:
    try:
        with session_scope(request_engine(request)) as session:
            return _json(
                SleepAgreementReportService(session).night_detail(
                    run_id, wake_date=wake_date, metric_code=metric_code
                )
            )
    except SQLAlchemyError as exc:
        if database_unavailable(exc):
            return _json({"available": False, "reason": "database_unavailable", "nights": []})
        return _report_error(exc)
    except Exception as exc:
        return _report_error(exc)
