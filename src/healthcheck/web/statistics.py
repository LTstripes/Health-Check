"""Desktop presentation of the accepted read-only source-period packet (#347 B2)."""

from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.templating import Jinja2Templates

from healthcheck.analytics.period_summary import PeriodSummaryService
from healthcheck.db.engine import session_scope
from healthcheck.web.common import request_engine

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
METRIC_LABELS = {
    "sleep_duration_asleep_seconds": "Средняя длительность сна",
    "activity_session_count": "Сохранённые активности",
    "activity_type_counts": "Виды активностей",
    "cycling_distance_meters": "Дистанция велотренировок",
    "tennis_session_count": "Теннис: активности",
    "tennis_duration_seconds": "Теннис: длительность",
}
UNIT_LABELS = {"seconds": "с", "meters": "м", "sessions": "сессий"}
STATE_LABELS = {
    "observed": "По сохранённым значениям",
    "confirmed_empty": "Подтверждено отсутствие активностей",
    "no_eligible_values": "Нет допустимых значений",
    "not_collected": "Не собирается",
    "source_missing": "Источник отсутствует",
    "selection_required": "Выбери источник",
    "selected": "Источник выбран",
}


@router.get("/statistics")
def statistics(
    request: Request,
    days: int = Query(default=7),
    end_date: date | None = Query(default=None),
    garmin_source_id: str | None = Query(default=None),
    google_source_id: str | None = Query(default=None),
):
    try:
        with session_scope(request_engine(request)) as session:
            packet = PeriodSummaryService(session).build(
                end_date=end_date or date.today(),
                days=days,
                garmin_source_id=garmin_source_id or None,
                google_source_id=google_source_id or None,
            )
    except (ValueError, OverflowError) as exc:
        raise HTTPException(status_code=400, detail="invalid_statistics_selection") from exc
    return templates.TemplateResponse(
        request=request,
        name="statistics.html",
        context={
            "page": "statistics",
            "packet": packet,
            "metric_labels": METRIC_LABELS,
            "unit_labels": UNIT_LABELS,
            "state_labels": STATE_LABELS,
        },
        headers={"Cache-Control": "no-store"},
    )
