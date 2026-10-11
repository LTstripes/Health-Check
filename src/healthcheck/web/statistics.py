"""Desktop presentation of the accepted read-only source-period packet (#347 B2)."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.analytics.period_summary import PeriodSummaryService
from healthcheck.analytics.sleep_source_view import read_source_sleep_range
from healthcheck.db.engine import session_scope
from healthcheck.web.common import database_unavailable, request_engine
from healthcheck.web.pages import _persist_error, render_error
from healthcheck.web.read_snapshot import ensure_read_snapshot
from healthcheck.web.sleep_timeline import build_sleep_timeline, read_sleep_source_inventory
from healthcheck.web.sleep_view import source_sleep_label

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


def format_statistics_value(code: str, value: int | float | None) -> str:
    """Format accepted nonnegative scalars for headlines only; never mutate the packet."""
    if value is None:
        return "Недоступно"
    number = Decimal(str(value))
    if code in {"sleep_duration_asleep_seconds", "tennis_duration_seconds"}:
        seconds = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if number > 0 and seconds == 0:
            return "<0,01 с"
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        parts = []
        if hours:
            parts.append(f"{int(hours)} ч")
        if hours or minutes or not seconds:
            parts.append(f"{int(minutes)} мин")
        if seconds:
            text = format(seconds, "f").rstrip("0").rstrip(".").replace(".", ",")
            parts.append(f"{text} с")
        return " ".join(parts)
    if code == "cycling_distance_meters":
        km = (number / 1000).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if number > 0 and km == 0:
            return "<0,01 км"
        text = format(km, "f").rstrip("0").rstrip(".").replace(".", ",")
        return f"{text} км"
    return f"{int(number)} сессий"


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
            ensure_read_snapshot(session)
            evaluated_date = end_date or date.today()
            selected_google = google_source_id or None
            if selected_google is None:
                inventory = read_sleep_source_inventory(session)
                if len(inventory["sources"]) > 1 and not inventory["truncated"]:
                    timeline = build_sleep_timeline(
                        {"google": read_source_sleep_range(
                            session, provider="google", wake_date=evaluated_date, days=days,
                        )},
                        days=days, end_date=evaluated_date, google_inventory=inventory,
                    )
                    selection = timeline["google_selection"]
                    # Reuse #343's exact-source rule, only for the approved sleep family.
                    if selection["status"] == "sole_google_wearables":
                        selected_google = selection["selected_source_id"]
            packet = PeriodSummaryService(session).build(
                end_date=evaluated_date,
                days=days,
                garmin_source_id=garmin_source_id or None,
                google_source_id=selected_google,
            )
    except (ValueError, OverflowError) as exc:
        raise HTTPException(status_code=400, detail="invalid_statistics_selection") from exc
    except SQLAlchemyError as exc:
        # Owner read-failure parity with the other HTML pages: never the raw
        # API JSON 500. Uninitialized storage keeps the accepted 503 document;
        # any other read failure keeps the shared Russian 500 alert document.
        if not database_unavailable(exc):
            return _persist_error(request, "statistics_page")
        return render_error(
            request,
            code="database_unavailable",
            message="database is not ready",
            status_code=503,
        )
    return templates.TemplateResponse(
        request=request,
        name="statistics.html",
        context={
            "page": "statistics",
            "packet": packet,
            "metric_labels": METRIC_LABELS,
            "unit_labels": UNIT_LABELS,
            "state_labels": STATE_LABELS,
            "format_value": format_statistics_value,
            "source_labels": statistics_source_labels(packet),
        },
        headers={"Cache-Control": "no-store"},
    )


def statistics_source_labels(packet: dict) -> dict[str, str]:
    """Readable labels, disambiguated without exposing opaque IDs in primary UI."""
    labels = {}
    for side in packet["sides"]:
        provider = "garmin" if side["position"] == "left" else "google"
        for index, source in enumerate(side["available_sources"], 1):
            # B1 identities omit optional Google metadata; no inference from UUIDs.
            label = source_sleep_label(
                dict(data_source_name=None, platform=None, **source), provider,
            )
            labels[source["source_id"]] = (
                f"{label} · источник {index}" if len(side["available_sources"]) > 1 else label
            )
    return labels
