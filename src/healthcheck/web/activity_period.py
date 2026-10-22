"""Statistics selection → saved sessions → unchanged #345 detail."""

from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.analytics.activity_period_sessions import read_activity_period_sessions
from healthcheck.db.engine import session_scope
from healthcheck.web.common import database_unavailable, request_engine
from healthcheck.web.owner_presentation import (
    owner_activity_count,
    owner_activity_type,
    owner_activity_types,
    owner_date,
    owner_distance,
    owner_duration,
)
from healthcheck.web.pages import _persist_error, render_error
from healthcheck.web.statistics import METRIC_LABELS

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters.update(owner_activity_type=owner_activity_type,
                             owner_activity_count=owner_activity_count,
                             owner_activity_types=owner_activity_types)
templates.env.filters.update(
    owner_date=owner_date, owner_distance=owner_distance, owner_duration=owner_duration
)
SPORT_LABELS = {"all": "Все виды", "cycling": "Велотренировки", "tennis": "Теннис"}


def statistics_session_links(packet, *, period, calendar_year, control_end_date, cycling_cell=None):
    side = packet["sides"][0]
    source = side["source_identity"]
    origin = {
        "origin_period": period,
        "origin_calendar_year": calendar_year,
        "origin_end_date": control_end_date,
        "google_source_id": (packet["sides"][1]["source_identity"] or {}).get("source_id", ""),
    }
    links = {}
    for code in METRIC_LABELS:
        if code == "sleep_duration_asleep_seconds":
            continue
        cell = (cycling_cell if code == "cycling_distance_meters" and cycling_cell is not None
                else side["metrics"][code])
        metric_source = cell.get("source_identity", source)
        if metric_source is None or cell["state"] in {"search_incomplete", "selection_required"}:
            continue
        metric_origin = dict(origin)
        if cell.get("cycling_selection", {}).get("mode") == "automatic":
            metric_origin["origin_garmin_source_id"] = ""
        links[code] = "/statistics/sessions?" + urlencode(
            {
                "garmin_source_id": metric_source["source_id"],
                "start_date": packet["requested_window"]["start_date"],
                "end_date": packet["requested_window"]["end_date"],
                "metric_code": code,
                "sport": "cycling"
                if code == "cycling_distance_meters"
                else "tennis"
                if code.startswith("tennis_")
                else "all",
                **metric_origin,
            }
        )
    return links


@router.get("/statistics/sessions")
def activity_period_page(
    request: Request,
    garmin_source_id: str,
    start_date: date,
    end_date: date,
    metric_code: str,
    sport: str,
    origin_period: str = "7",
    origin_calendar_year: int | None = None,
    origin_end_date: date | None = None,
    google_source_id: str = "",
    origin_garmin_source_id: str | None = None,
):
    if origin_period not in {"7", "30", "trailing365", "calendar_year", "year_to_date"}:
        return render_error(
            request, code="invalid_activity_period", message="Неверный период.", status_code=400
        )
    try:
        with session_scope(request_engine(request)) as session:
            packet = read_activity_period_sessions(
                session,
                source_id=garmin_source_id,
                start_date=start_date,
                end_date=end_date,
                metric_code=metric_code,
                sport=sport,
            )
    except ValueError:
        return render_error(
            request,
            code="invalid_activity_period",
            message="Выбор источника, вида или периода недоступен.",
            status_code=400,
        )
    except SQLAlchemyError as exc:
        if not database_unavailable(exc):
            return _persist_error(request, "activity_period")
        return render_error(
            request, code="database_unavailable", message="database is not ready", status_code=503
        )
    origin = {
        "period": origin_period,
        "calendar_year": origin_calendar_year or end_date.year,
        "end_date": (origin_end_date or end_date).isoformat(),
        "garmin_source_id": (garmin_source_id if origin_garmin_source_id is None
                             else origin_garmin_source_id),
        "google_source_id": google_source_id,
    }
    context_params = {
        "garmin_source_id": garmin_source_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "metric_code": metric_code,
        "origin_period": origin_period,
        "origin_calendar_year": origin["calendar_year"],
        "origin_end_date": origin["end_date"],
        "google_source_id": google_source_id,
    }
    if origin_garmin_source_id is not None:
        context_params["origin_garmin_source_id"] = origin_garmin_source_id
    for item in packet["sessions"]:
        item["detail_href"] = "/garmin/session?" + urlencode(
            {
                "garmin_source_id": garmin_source_id,
                "record_id": item["record_id"],
                # #345's metric_code belongs to the Activity scalar selector,
                # not the originating Statistics aggregate. Keep that contract.
                "origin_metric_code": metric_code,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
    return templates.TemplateResponse(
        request=request,
        name="activity_period.html",
        context={
            "page": "statistics",
            "packet": packet,
            "metric_label": METRIC_LABELS[metric_code],
            "sport_labels": SPORT_LABELS,
            "context_params": context_params,
            "can_filter": metric_code in {"activity_session_count", "activity_type_counts"},
            "back_href": "/statistics?" + urlencode(origin) + "#metric-" + metric_code,
        },
        headers={"Cache-Control": "no-store"},
    )
