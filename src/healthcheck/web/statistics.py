"""Desktop presentation of the accepted read-only source-period packet (#347 B2)."""

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.analytics.cycling_source_discovery import (
    METRIC_CODE,
    CyclingSourceDiscoveryService,
)
from healthcheck.analytics.period_summary import PeriodSummaryService
from healthcheck.db.engine import session_scope
from healthcheck.garmin.completed_steps_read import (
    DISPLAY_ZONE,
    read_completed_steps_all_time,
    read_completed_steps_window,
)
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.google.steps_read import read_saved_steps_window
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
from healthcheck.web.read_snapshot import ensure_read_snapshot
from healthcheck.web.sleep_view import source_sleep_label

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters.update(owner_activity_type=owner_activity_type,
                             owner_activity_count=owner_activity_count,
                             owner_activity_types=owner_activity_types)
templates.env.filters["owner_date"] = owner_date
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


def steps_evaluation_instant() -> datetime:
    return datetime.now(UTC)


def format_statistics_value(code: str, value: int | float | None) -> str:
    """Format accepted nonnegative scalars for headlines only; never mutate the packet."""
    if value is None:
        return "Недоступно"
    if code in {"sleep_duration_asleep_seconds", "tennis_duration_seconds"}:
        return owner_duration(value)
    if code == "cycling_distance_meters":
        return owner_distance(value)
    return owner_activity_count(value)


@router.get("/statistics")
def statistics(
    request: Request,
    days: int | None = Query(default=None),
    period: str | None = Query(default=None),
    calendar_year: int | None = Query(default=None),
    steps_period: str = Query(default="window"),
    end_date: date | None = Query(default=None),
    garmin_source_id: str | None = Query(default=None),
    google_source_id: str | None = Query(default=None),
    google_steps_source_id: str | None = Query(default=None),
    garmin_sleep_source_id: str | None = Query(default=None),
    google_sleep_source_id: str | None = Query(default=None),
):
    from healthcheck.web.activity_period import statistics_session_links

    try:
        if steps_period not in {"window", "all_time"}:
            raise ValueError("unsupported Steps period")
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
            packet = PeriodSummaryService(session).build(
                **window,
                garmin_source_id=garmin_source_id or None,
                google_source_id=google_source_id or None,
                sleep_source_selection=True,
                garmin_sleep_source_id=garmin_sleep_source_id or None,
                google_sleep_source_id=google_sleep_source_id or None,
            )
            cycling_cell = statistics_cycling_cell(
                session, packet, window=window, explicit=garmin_source_id or None,
            )
            steps_now = steps_evaluation_instant()
            steps_start = date.fromisoformat(packet["requested_window"]["start_date"])
            steps_end = date.fromisoformat(packet["requested_window"]["end_date"])
            google_steps = None
            if selected_period in {"7", "30"} and steps_period == "window":
                google_steps = read_saved_steps_window(
                    session, start_date=steps_start, end_date=steps_end,
                    source_id=google_steps_source_id or None,
                )
            # Default rolling Steps windows end yesterday in the explicit Owner
            # display zone. Explicit historical windows and other aggregates stay exact.
            if end_date is None and selected_period in {"7", "30", "trailing365"}:
                steps_end = steps_now.astimezone(ZoneInfo(DISPLAY_ZONE)).date() - timedelta(days=1)
                length = 365 if selected_period == "trailing365" else int(selected_period)
                steps_start = steps_end - timedelta(days=length - 1)
            store = ContentAddressedGarminPayloadStore(
                request.app.state.runtime_paths.root / "artifacts"
            )
            if steps_period == "all_time":
                steps = read_completed_steps_all_time(
                    session, payload_store=store, source_id=garmin_source_id or None,
                    evaluated_at=steps_now, end_date=end_date,
                )
            else:
                steps = read_completed_steps_window(
                    session, payload_store=store, source_id=garmin_source_id or None,
                    start_date=steps_start, end_date=steps_end, evaluated_at=steps_now,
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
            "cycling_cell": cycling_cell,
            "steps": steps,
            "google_steps": google_steps,
            "selected_google_steps_source_id": google_steps_source_id or (
                google_steps["source_id"] if google_steps else None
            ),
            "steps_state_labels": STEPS_STATE_LABELS,
            "selected_garmin_source_id": garmin_source_id or None,
            "selected_google_source_id": google_source_id or None,
            "selected_sleep_source_ids": {
                "left": garmin_sleep_source_id or None,
                "right": google_sleep_source_id or None,
            },
            "selected_period": selected_period,
            "selected_steps_period": steps_period,
            "format_steps_value": format_steps_value,
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
            "source_labels": statistics_source_labels(packet, cycling_cell=cycling_cell),
            "provider_source_choices": {
                side["position"]: statistics_provider_choices(side, cycling_cell)
                for side in packet["sides"]
            },
            "sleep_source_choices": {
                side["position"]: statistics_source_choices(side) for side in packet["sides"]
            },
            "session_links": statistics_session_links(
                packet, period=selected_period, calendar_year=selected_year,
                control_end_date=evaluated_date.isoformat(),
                cycling_cell=cycling_cell,
            ),
        },
        headers={"Cache-Control": "no-store"},
    )


def statistics_cycling_cell(session, packet: dict, *, window: dict, explicit: str | None) -> dict:
    """Project #436 discovery into one UI cell; never alter the shared packet.

    Provider overrides retain their existing exact-source read. Automatic mode
    requires the complete bounded discovery, including every ambiguity check.
    It does not select a provider for Steps, Sleep, tennis or activity counts.
    """
    side = packet["sides"][0]
    cell = deepcopy(side["metrics"][METRIC_CODE])
    cell["source_identity"] = side["source_identity"]
    if explicit:
        cell["cycling_selection"] = {"mode": "explicit", "state": "explicit", "options": []}
        return cell
    discovery = CyclingSourceDiscoveryService(session).discover(**window)
    provider = discovery["providers"][0]
    eligible = [o for o in provider["options"] if o["eligibility"]["has_eligible_values"]]
    chosen = (eligible[0] if provider["search"]["complete"]
              and provider["state"] == "unique_eligible_source"
              and provider["ambiguous_source_count"] == 0 and len(eligible) == 1 else None)
    selection = {"mode": "automatic", **provider,
                 "contract_version": discovery["contract_version"],
                 "read_limits": discovery["read_limits"]}
    if chosen:
        cell.update(deepcopy(chosen["summary"]))
        cell["source_identity"] = chosen["source_identity"]
        start = date.fromisoformat(packet["requested_window"]["start_date"])
        cell["missing_dates"] = [
            day.isoformat() for offset in range(packet["requested_window"]["inclusive_days"])
            if (day := start + timedelta(days=offset)).isoformat()
            not in cell["observed_calendar_dates"]
        ]
        cell["missing_day_count"] = len(cell["missing_dates"])
    else:
        cell["source_identity"] = None
        cell["state"] = ("selection_required" if provider["state"] in {
            "multiple_eligible_sources", "ambiguous_records",
        } else provider["state"])
        cell["aggregation"] = dict.fromkeys(cell["aggregation"])
        for key in ("observed_count", "observed_day_count", "missing_day_count", "missing_dates"):
            cell[key] = None
    cell["search"] = provider["search"]
    cell["cycling_selection"] = selection
    return cell


def statistics_source_choices(side: dict) -> list[dict]:
    sources = {s["source_id"]: s for s in side["available_sources"]}
    sleep = side.get("metrics", {}).get("sleep_duration_asleep_seconds", {})
    for option in sleep.get("source_selection", {}).get("options", []):
        source = option["source_identity"]
        sources[source["source_id"]] = source
    if sleep.get("source_identity"):
        source = sleep["source_identity"]
        sources[source["source_id"]] = source
    return list(sources.values())


def statistics_provider_choices(side: dict, cycling_cell: dict | None) -> list[dict]:
    """Include independently completed cycling identities in presentation only."""
    sources = {s["source_id"]: s for s in side["available_sources"]}
    if side["position"] == "left" and cycling_cell:
        for option in cycling_cell["cycling_selection"]["options"]:
            source = option["source_identity"]
            sources[source["source_id"]] = source
        if source := cycling_cell["source_identity"]:
            sources[source["source_id"]] = source
    return list(sources.values())


def statistics_source_labels(packet: dict, *, cycling_cell: dict | None = None) -> dict[str, str]:
    """Readable labels, disambiguated without exposing opaque IDs in primary UI."""
    labels = {}
    for side in packet["sides"]:
        provider = "garmin" if side["position"] == "left" else "google"
        sources = {s["source_id"]: s for s in statistics_source_choices(side)}
        sources.update({s["source_id"]: s
                        for s in statistics_provider_choices(side, cycling_cell)})
        sources = list(sources.values())
        for index, source in enumerate(sources, 1):
            # B1 identities omit optional Google metadata; no inference from UUIDs.
            label = source_sleep_label(
                dict(data_source_name=None, platform=None, **source), provider,
            )
            labels[source["source_id"]] = (
                f"{label} · источник {index}" if len(sources) > 1 else label
            )
    return labels


def format_steps_value(value: int | Decimal | None) -> str:
    """One decimal for the mean; count totals stay exact integers."""
    if value is None:
        return "Недоступно"
    with localcontext() as context:
        context.rounding = ROUND_HALF_EVEN
        text = f"{value:,.1f}" if isinstance(value, Decimal) else f"{Decimal(value):,f}"
    return text.replace(",", "\u202f").replace(".", ",")
