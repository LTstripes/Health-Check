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
from healthcheck.garmin.observed_steps_read import read_observed_steps_window
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
    "search_incomplete": "Поиск сохранённых данных не завершён",
    "observed": "По сохранённым значениям",
    "confirmed_empty": "Подтверждено отсутствие активностей",
    "no_eligible_values": "Нет допустимых значений",
    "not_collected": "Не собирается",
    "source_missing": "Источник отсутствует",
    "selection_required": "Выбери источник",
    "selected": "Источник выбран",
}

STEPS_STATE_LABELS = {
    "value": "Сохранённое наблюдение",
    "missing": "Поле шагов отсутствует в сохранённом наблюдении",
    "null": "Источник вернул null",
    "invalid": "Недопустимое значение шагов",
    "ambiguous": "Неоднозначно: сохранены разные значения",
    "unavailable": "Нет допустимого значения; разные состояния наблюдений",
    "projection_unavailable": "Нет подтверждённого сохранённого значения на эту дату",
    "search_incomplete": "Поиск сохранённых данных не завершён",
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
    days: int | None = Query(default=None),
    period: str | None = Query(default=None),
    calendar_year: int | None = Query(default=None),
    end_date: date | None = Query(default=None),
    garmin_source_id: str | None = Query(default=None),
    google_source_id: str | None = Query(default=None),
):
    try:
        selected_period = period or str(days if days is not None else 7)
        if period is not None and days is not None:
            raise ValueError("competing period selectors")
        evaluated_date = end_date or date.today()
        selected_year = calendar_year if calendar_year is not None else evaluated_date.year
        if selected_period in {"7", "30"}:
            window = {"days": int(selected_period), "end_date": evaluated_date}
        elif selected_period == "calendar_year":
            window = {"period_type": selected_period, "calendar_year": selected_year}
        elif selected_period in {"trailing365", "year_to_date"}:
            window = {"period_type": selected_period, "end_date": evaluated_date}
        else:
            raise ValueError("unsupported period")
        with session_scope(request_engine(request)) as session:
            ensure_read_snapshot(session)
            selected_google = google_source_id or None
            if selected_google is None and selected_period in {"7", "30"}:
                inventory = read_sleep_source_inventory(session)
                if len(inventory["sources"]) > 1 and not inventory["truncated"]:
                    timeline = build_sleep_timeline(
                        {"google": read_source_sleep_range(
                            session, provider="google", wake_date=evaluated_date,
                            days=int(selected_period),
                        )},
                        days=int(selected_period), end_date=evaluated_date,
                        google_inventory=inventory,
                    )
                    selection = timeline["google_selection"]
                    # Reuse #343's exact-source rule, only for the approved sleep family.
                    if selection["status"] == "sole_google_wearables":
                        selected_google = selection["selected_source_id"]
            packet = PeriodSummaryService(session).build(
                **window,
                garmin_source_id=garmin_source_id or None,
                google_source_id=selected_google,
            )
            # A sole source chosen by the older period packet is not an explicit
            # Steps selection. Use the request identity and the packet's exact window.
            steps = None
            if garmin_source_id:
                steps = read_observed_steps_window(
                    session,
                    source_id=garmin_source_id,
                    start_date=date.fromisoformat(packet["requested_window"]["start_date"]),
                    end_date=date.fromisoformat(packet["requested_window"]["end_date"]),
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
            "steps": steps,
            "steps_state_labels": STEPS_STATE_LABELS,
            "selected_garmin_source_id": garmin_source_id or None,
            "selected_period": selected_period,
            "selected_year": selected_year,
            "control_end_date": evaluated_date.isoformat(),
            "period_labels": {
                "7": "7 дней", "30": "30 дней", "trailing365": "Последние 365 дней",
                "calendar_year": "Календарный год", "year_to_date": "С начала года",
            },
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
