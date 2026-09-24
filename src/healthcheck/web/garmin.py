"""Loopback GET-only Garmin analytics JSON routes under /api/garmin/..."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.db.engine import session_scope
from healthcheck.logging import log_event
from healthcheck.web.common import database_unavailable, request_engine
from healthcheck.web.garmin_query import (
    PROVIDER_NATIVE_SCORE_LABELS,
    GarminQueryError,
    GarminQueryService,
    unavailable_dashboard_payload,
)
from healthcheck.web.garmin_training_overview import (
    DEFAULT_RECENT_ACTIVITIES,
    MAX_RECENT_ACTIVITIES,
    unavailable_training_overview,
)

router = APIRouter()


def _json(payload: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(payload), status_code=status_code)


def _error(exc: GarminQueryError) -> JSONResponse:
    return _json({"code": exc.code, "message": exc.message}, status_code=exc.status_code)


def _unavailable_dashboard() -> dict[str, Any]:
    return unavailable_dashboard_payload(reason="database_unavailable")


def _parse_csv_ids(raw: str | None) -> list[str]:
    if raw is None or not str(raw).strip():
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def _parse_lag_days(raw: str | None) -> list[int]:
    if raw is None or not str(raw).strip():
        raise GarminQueryError("empty_lag_days", "lag_days must be non-empty")
    values: list[int] = []
    for part in str(raw).split(","):
        token = part.strip()
        if not token:
            continue
        try:
            values.append(int(token, 10))
        except ValueError as exc:
            raise GarminQueryError(
                "invalid_lag_days",
                "lag_days must be comma-separated integers",
            ) from exc
    if not values:
        raise GarminQueryError("empty_lag_days", "lag_days must be non-empty")
    return values


@router.get("/api/garmin/sources")
def garmin_sources(request: Request) -> JSONResponse:
    try:
        with session_scope(request_engine(request)) as session:
            service = GarminQueryService(session, request.app.state.settings)
            return _json({"sources": service.list_sources()})
    except SQLAlchemyError as exc:
        if database_unavailable(exc):
            return _json({"sources": [], "unavailable_reason": "database_unavailable"})
        log_event(
            "persistence_error",
            operation="garmin_sources",
            status="error",
            reason="persistence_error",
        )
        return _json({"code": "persistence_error", "message": "request failed"}, status_code=500)


@router.get("/api/garmin/metrics")
def garmin_metrics(request: Request) -> JSONResponse:
    try:
        with session_scope(request_engine(request)) as session:
            service = GarminQueryService(session, request.app.state.settings)
            return _json(
                {
                    "scalar_metrics": service.list_scalar_metrics(),
                    "lag_eligible_metrics": service.list_lag_eligible_metrics(),
                    "activity_comparison_metrics": service.list_activity_comparison_metrics(),
                    "native_score_labels": service.native_score_labels(),
                }
            )
    except SQLAlchemyError as exc:
        if database_unavailable(exc):
            return _json(
                {
                    "scalar_metrics": [],
                    "lag_eligible_metrics": [],
                    "activity_comparison_metrics": [],
                    "native_score_labels": {
                        code: dict(label)
                        for code, label in sorted(PROVIDER_NATIVE_SCORE_LABELS.items())
                    },
                    "unavailable_reason": "database_unavailable",
                }
            )
        log_event(
            "persistence_error",
            operation="garmin_metrics",
            status="error",
            reason="persistence_error",
        )
        return _json({"code": "persistence_error", "message": "request failed"}, status_code=500)


@router.get("/api/garmin/activities")
def garmin_activities(
    request: Request,
    garmin_source_id: str = Query(...),
    limit: int = Query(default=50, ge=1, le=100),
) -> JSONResponse:
    try:
        with session_scope(request_engine(request)) as session:
            service = GarminQueryService(session, request.app.state.settings)
            return _json(
                {
                    "garmin_source_id": garmin_source_id.strip(),
                    "activities": service.list_activities(
                        garmin_source_id=garmin_source_id,
                        limit=limit,
                    ),
                }
            )
    except GarminQueryError as exc:
        return _error(exc)
    except SQLAlchemyError as exc:
        if database_unavailable(exc):
            return _json(
                {
                    "garmin_source_id": garmin_source_id,
                    "activities": [],
                    "unavailable_reason": "database_unavailable",
                }
            )
        log_event(
            "persistence_error",
            operation="garmin_activities",
            status="error",
            reason="persistence_error",
        )
        return _json({"code": "persistence_error", "message": "request failed"}, status_code=500)


@router.get("/api/garmin/series")
def garmin_series(
    request: Request,
    garmin_source_id: str = Query(...),
    metric_code: str = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
) -> JSONResponse:
    try:
        with session_scope(request_engine(request)) as session:
            service = GarminQueryService(session, request.app.state.settings)
            return _json(
                service.scalar_series(
                    garmin_source_id=garmin_source_id,
                    metric_code=metric_code,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
    except GarminQueryError as exc:
        return _error(exc)
    except SQLAlchemyError as exc:
        if database_unavailable(exc):
            return _json(
                {
                    "code": "database_unavailable",
                    "message": "database is not ready",
                    "available": False,
                },
                status_code=503,
            )
        log_event(
            "persistence_error",
            operation="garmin_series",
            status="error",
            reason="persistence_error",
        )
        return _json({"code": "persistence_error", "message": "request failed"}, status_code=500)


@router.get("/api/garmin/activity-comparison")
def garmin_activity_comparison(
    request: Request,
    garmin_source_id: str = Query(...),
    activity_record_ids: str = Query(..., description="Comma-separated activity record IDs"),
    reference_activity_id: str = Query(...),
    metric_codes: str | None = Query(default=None),
) -> JSONResponse:
    try:
        ids = _parse_csv_ids(activity_record_ids)
        codes = _parse_csv_ids(metric_codes) or None
        with session_scope(request_engine(request)) as session:
            service = GarminQueryService(session, request.app.state.settings)
            return _json(
                service.activity_comparison(
                    garmin_source_id=garmin_source_id,
                    activity_record_ids=ids,
                    reference_activity_id=reference_activity_id,
                    metric_codes=codes,
                )
            )
    except GarminQueryError as exc:
        return _error(exc)
    except SQLAlchemyError as exc:
        if database_unavailable(exc):
            return _json(
                {
                    "code": "database_unavailable",
                    "message": "database is not ready",
                    "available": False,
                },
                status_code=503,
            )
        log_event(
            "persistence_error",
            operation="garmin_activity_comparison",
            status="error",
            reason="persistence_error",
        )
        return _json({"code": "persistence_error", "message": "request failed"}, status_code=500)


@router.get("/api/garmin/lagged-association")
def garmin_lagged_association(
    request: Request,
    garmin_source_id: str = Query(...),
    x_metric_code: str = Query(...),
    y_metric_code: str = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    lag_days: str = Query(..., description="Comma-separated non-negative lag days"),
) -> JSONResponse:
    try:
        lags = _parse_lag_days(lag_days)
        with session_scope(request_engine(request)) as session:
            service = GarminQueryService(session, request.app.state.settings)
            return _json(
                service.lagged_association(
                    garmin_source_id=garmin_source_id,
                    x_metric_code=x_metric_code,
                    y_metric_code=y_metric_code,
                    start_date=start_date,
                    end_date=end_date,
                    lag_days=lags,
                )
            )
    except GarminQueryError as exc:
        return _error(exc)
    except SQLAlchemyError as exc:
        if database_unavailable(exc):
            return _json(
                {
                    "code": "database_unavailable",
                    "message": "database is not ready",
                    "available": False,
                },
                status_code=503,
            )
        log_event(
            "persistence_error",
            operation="garmin_lagged_association",
            status="error",
            reason="persistence_error",
        )
        return _json({"code": "persistence_error", "message": "request failed"}, status_code=500)




@router.get("/api/garmin/training-overview")
def garmin_training_overview(
    request: Request,
    garmin_source_id: str | None = Query(default=None),
    activity_limit: int = Query(
        default=DEFAULT_RECENT_ACTIVITIES,
        ge=1,
        le=MAX_RECENT_ACTIVITIES,
    ),
) -> JSONResponse:
    """Read-only Training & recovery overview from persisted #180 evidence."""

    try:
        with session_scope(request_engine(request)) as session:
            service = GarminQueryService(session, request.app.state.settings)
            return _json(
                service.training_overview(
                    garmin_source_id=garmin_source_id,
                    activity_limit=activity_limit,
                )
            )
    except GarminQueryError as exc:
        return _error(exc)
    except SQLAlchemyError as exc:
        if database_unavailable(exc):
            return _json(unavailable_training_overview(reason="database_unavailable"))
        log_event(
            "persistence_error",
            operation="garmin_training_overview",
            status="error",
            reason="persistence_error",
        )
        return _json({"code": "persistence_error", "message": "request failed"}, status_code=500)

@router.get("/api/garmin/dashboard")
def garmin_dashboard_api(
    request: Request,
    garmin_source_id: str | None = Query(default=None),
    metric_code: str | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
) -> JSONResponse:
    try:
        with session_scope(request_engine(request)) as session:
            service = GarminQueryService(session, request.app.state.settings)
            return _json(
                service.dashboard(
                    garmin_source_id=garmin_source_id,
                    metric_code=metric_code,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
    except GarminQueryError as exc:
        return _error(exc)
    except SQLAlchemyError as exc:
        if database_unavailable(exc):
            return _json(_unavailable_dashboard())
        log_event(
            "persistence_error",
            operation="garmin_dashboard",
            status="error",
            reason="persistence_error",
        )
        return _json({"code": "persistence_error", "message": "request failed"}, status_code=500)
