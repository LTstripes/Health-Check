"""Loopback GET-only trip/event passport (#463) over the accepted period export."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.chat_evidence import EvidenceError
from healthcheck.context import ContextService, ContextValidationError
from healthcheck.db.engine import session_scope
from healthcheck.db.models import ContextEventHead, ContextEventRevision, GarminSource
from healthcheck.logging import log_event
from healthcheck.owner_time import owner_zone
from healthcheck.trip_passport import (
    MAX_PASSPORT_DAYS,
    MAX_PLACE_LENGTH,
    MAX_TITLE_LENGTH,
    PassportError,
    PassportRequest,
    build_passport,
    encode_passport_bundle,
    read_passport_exports,
    render_passport_markdown,
)
from healthcheck.web.common import request_engine
from healthcheck.web.owner_presentation import owner_activity_type, owner_date, owner_duration
from healthcheck.web.pages import templates
from healthcheck.web.read_snapshot import ensure_read_snapshot

router = APIRouter()
NO_STORE = {"Cache-Control": "no-store"}
EVENT_CHOICES = 50
EVENT_LOOKBACK_DAYS = 400
MAX_SOURCES = 32

MESSAGES = {
    "period_exceeds_export_cap": (
        f"Паспорт строится из существующего экспорта, а он читает не больше {MAX_PASSPORT_DAYS} "
        "дней подряд. Разбейте поездку на части не длиннее {cap} дней. Склейка периодов "
        "пока не поддерживается: для неё нужно отдельное правило полноты (#380)."),
    "start_after_end": "Дата начала позже даты окончания.",
    "title_required": f"Укажите название (до {MAX_TITLE_LENGTH} символов).",
    "place_too_long": f"Место — не длиннее {MAX_PLACE_LENGTH} символов.",
    "garmin_source_required": "Выберите источник Garmin.",
    "no_garmin_source": "Нет сохранённого источника Garmin — паспорт строить не из чего.",
    "invalid_calendar_date": "Проверьте даты.",
    "range_out_of_bounds": "Даты вне поддерживаемого диапазона.",
    "context_event_not_found": "Комментарий не найден.",
    "selected_context_revision_unavailable": (
        "Выбранный комментарий изменился или не попал в выборку за эти даты. "
        "Откройте его заново либо выберите период вручную."),
    "source_inventory_exceeds_limit": (
        "Источников больше предела списка. Выбор источника недоступен."),
    "output_exceeds_byte_limit": (
        "Выборка за этот период больше предела экспорта по объёму. Паспорт не строится из "
        "урезанных данных — выберите более короткий период."),
    "steps_search_incomplete": (
        "Поиск шагов упёрся в предел выборки. Паспорт не строится из неполного поиска — "
        "выберите более короткий период."),
}
LIMIT_CODES = {"output_exceeds_byte_limit", "steps_search_incomplete",
               "google_steps_search_incomplete"}


def _message(code: str) -> str:
    if code in MESSAGES:
        return MESSAGES[code].replace("{cap}", str(MAX_PASSPORT_DAYS))
    if code.endswith("_exceed_max") or code in LIMIT_CODES:
        return ("Сохранённых записей за период больше предела выборки экспорта. Паспорт не "
                "строится из неполных данных — выберите более короткий период.")
    return "Экспорт периода не удалось прочитать. Повторите позже."


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        raise PassportError("invalid_calendar_date") from None


def _event_label(view) -> str:
    temporal = view.temporal
    when = owner_date(temporal.start_local_date)
    if temporal.end_local_date and temporal.end_local_date != temporal.start_local_date:
        when += " — " + owner_date(temporal.end_local_date)
    text = " ".join(view.original_text.split())
    return f"{when}: {text[:60]}{'…' if len(text) > 60 else ''}"


def _default_title(view) -> str:
    first = view.original_text.strip().splitlines()[0] if view.original_text.strip() else ""
    return " ".join(first.split())[:MAX_TITLE_LENGTH]


def _inputs(request: Request) -> dict[str, Any]:
    query = request.query_params
    return {
        "event_id": (query.get("event_id") or "").strip() or None,
        "start_date": query.get("start_date") or "",
        "end_date": query.get("end_date") or "",
        "title": query.get("title") or "",
        "place": query.get("place") or "",
        "garmin_source_id": (query.get("garmin_source_id") or "").strip(),
        "compare": query.get("compare") == "1",
    }


def _choices(request: Request, form: dict[str, Any]) -> dict[str, Any]:
    """Bounded Garmin inventory and Context chooser; never pick between sources silently."""
    settings = request.app.state.settings
    today = datetime.now(UTC).astimezone(owner_zone(settings)).date()
    with session_scope(request_engine(request)) as session:
        ensure_read_snapshot(session)
        sources = list(session.scalars(
            select(GarminSource).where(GarminSource.provider_code == "garmin_connect")
            .order_by(GarminSource.id).limit(MAX_SOURCES + 1)))
        if len(sources) > MAX_SOURCES:
            raise PassportError("source_inventory_exceeds_limit")
        events = ContextService(session).list(
            from_date=today - timedelta(days=EVENT_LOOKBACK_DAYS),
            to_date=today + timedelta(days=EVENT_LOOKBACK_DAYS), limit=EVENT_CHOICES + 1)
        event = None
        if form["event_id"]:
            event = next((view for view in events if view.event_id == form["event_id"]), None)
            if event is None:
                event = _event_by_id(session, form["event_id"])
    selected_events = list(events[:EVENT_CHOICES])
    if event is not None and all(view.event_id != event.event_id for view in selected_events):
        selected_events.append(event)
    return {
        "sources": [{"id": row.id, "label": (row.device_model if row.device_attributed
                                             else "Garmin Connect") + f" · {row.id[:8]}"}
                    for row in sources[:MAX_SOURCES]],
        "events": [{"id": view.event_id, "label": _event_label(view)}
                   for view in selected_events],
        "events_truncated": len(events) > EVENT_CHOICES,
        "event": event,
        "today": today,
    }


def _event_by_id(session, event_id: str):
    """Current revision of one event, also when it is outside the chooser window."""
    head = session.get(ContextEventHead, event_id)
    row = session.get(ContextEventRevision, head.revision_id) if head is not None else None
    return ContextService(session)._view(row, is_current=True) if row is not None else None


def _passport_request(form: dict[str, Any], choices: dict[str, Any]) -> PassportRequest | None:
    event = choices["event"]
    if form["event_id"] and event is None:
        raise PassportError("context_event_not_found")
    start, end = _date(form["start_date"]), _date(form["end_date"])
    if event is not None and start is None and end is None:
        start = event.temporal.start_local_date
        end = event.temporal.end_local_date or start
        form["start_date"], form["end_date"] = start.isoformat(), end.isoformat()
    if event is not None and not form["title"].strip():
        form["title"] = _default_title(event)
    if start is None or end is None:
        if start is not None or end is not None:
            raise PassportError("invalid_calendar_date")
        return None
    source = form["garmin_source_id"]
    if not source:
        if not choices["sources"]:
            raise PassportError("no_garmin_source")
        if len(choices["sources"]) > 1:
            raise PassportError("garmin_source_required")
        source = choices["sources"][0]["id"]
    return PassportRequest(
        start_date=start, end_date=end, title=form["title"], place=form["place"],
        garmin_source_id=source, compare_previous=form["compare"],
        context_event_id=event.event_id if event is not None else None,
        context_revision_id=event.revision_id if event is not None else None,
    )


def _read(request: Request, passport_request: PassportRequest):
    clock = datetime.now(UTC)
    packets = read_passport_exports(
        profile=request.app.state.runtime_paths.root, profile_kind="durable_owner_runtime",
        request=passport_request, evaluated_at_utc=clock,
        evaluation_local_date=clock.astimezone(owner_zone(request.app.state.settings)).date())
    return packets, build_passport(passport_request, packets)


def _downloads(passport: dict, packets: dict) -> dict:
    # Validate both bounded serializers before displaying the result. The page's
    # links download these frozen strings, never re-read a changing database.
    return {
        "filename": (f"trip-passport-{passport['period']['start_date']}-"
                     f"{passport['period']['end_date']}-{passport['passport_hash'][:12]}"),
        "json": encode_passport_bundle(passport, packets),
        "md": render_passport_markdown(passport),
    }


@router.get("/passport")
def passport_page(request: Request):
    form = _inputs(request)
    context: dict[str, Any] = {"page": "passport", "form": form, "passport": None,
                               "error": None, "max_days": MAX_PASSPORT_DAYS}
    status = 200
    try:
        choices = _choices(request, form)
        context.update(choices)
        passport_request = _passport_request(form, choices)
        if passport_request is not None:
            passport_request.validate()
            packets, passport = _read(request, passport_request)
            context["downloads"] = _downloads(passport, packets)
            context["passport"] = passport
    except PassportError as exc:
        context["error"] = _message(exc.code)
        status = 422
    except EvidenceError as exc:
        context["error"] = _message(str(exc))
        status = 422 if (str(exc).endswith("_exceed_max") or str(exc) in LIMIT_CODES) else 503
    except (SQLAlchemyError, ContextValidationError) as exc:
        log_event("trip_passport_error", operation="trip_passport", status="error",
                  reason=type(exc).__name__)
        context["error"] = "Хранилище недоступно. Повторите позже."
        status = 503
    context.setdefault("sources", [])
    context.setdefault("events", [])
    return templates.TemplateResponse(request, "trip_passport.html", context,
                                      status_code=status, headers=NO_STORE)


def _download(request: Request, kind: str) -> Response:
    form = _inputs(request)
    try:
        choices = _choices(request, form)
        passport_request = _passport_request(form, choices)
        if passport_request is None:
            raise PassportError("invalid_calendar_date")
        passport_request.validate()
        packets, passport = _read(request, passport_request)
        downloads = _downloads(passport, packets)
        name = downloads["filename"]
        body = downloads[kind]
        media = "application/json" if kind == "json" else "text/markdown"
        return Response(body.encode("utf-8"), media_type=f"{media}; charset=utf-8", headers={
            **NO_STORE, "Content-Disposition": f'attachment; filename="{name}.{kind}"'})
    except PassportError as exc:
        return JSONResponse({"code": exc.code, "message": _message(exc.code)},
                            status_code=422, headers=NO_STORE)
    except EvidenceError as exc:
        return JSONResponse({"code": str(exc), "message": _message(str(exc))},
                            status_code=422, headers=NO_STORE)
    except (SQLAlchemyError, ContextValidationError):
        return JSONResponse({"code": "passport_unavailable"}, status_code=503, headers=NO_STORE)


@router.get("/passport/export.json")
def passport_json(request: Request) -> Response:
    return _download(request, "json")


@router.get("/passport/export.md")
def passport_markdown(request: Request) -> Response:
    return _download(request, "md")


templates.env.globals.update(
    passport_activity=owner_activity_type, passport_duration=owner_duration)

# ---------------------------------------------------------------------------
# Presentation helpers (display only; facts come from the passport unchanged)
# ---------------------------------------------------------------------------

_RECOVERY_LABELS = {
    ("rhr", "garmin"): ("Пульс покоя, Garmin", "уд/мин"),
    ("rhr", "google"): ("Пульс покоя, Google", "уд/мин"),
    ("hrv", "garmin"): ("HRV, Garmin (среднее за неделю)", "мс"),
    ("hrv", "google"): ("HRV, Google", "мс"),
    ("body_battery", "garmin"): ("Body Battery, максимум сохранённых значений", "баллов"),
}


def passport_steps(value: object) -> str:
    if type(value) is not int:
        return "—"
    return f"{value:,}".replace(",", " ")


def passport_mean(value: str | None) -> str:
    if value is None:
        return "—"
    return passport_steps(int(Decimal(value).quantize(Decimal(1), ROUND_HALF_UP)))


def passport_offset(zone: dict) -> str:
    parts = [zone.get("timezone"), zone.get("utc_offset")]
    return " ".join(part for part in parts if part) or "пояс не указан"


def passport_workout_time(item: dict) -> str:
    if item.get("start_local"):
        text = str(item["start_local"])
        return text[11:] if len(text) >= 16 else text
    if item.get("start_utc"):
        return str(item["start_utc"])[11:] + " (UTC)"
    return "время не сохранено"


def passport_rows(passport: dict) -> list[dict]:
    sleep = {name: {night["wake_date"]: night for night in provider["nights"]}
             for name, provider in passport["sleep"]["providers"].items()}
    recovery: dict[str, list] = {}
    for domain, providers in passport["recovery"].items():
        for name, provider in providers.items():
            label, unit = _RECOVERY_LABELS.get((domain, name), (f"{domain} {name}", ""))
            for row in provider["values"]:
                if row.get("value") is not None:
                    recovery.setdefault(row["date"], []).append(
                        {"label": label, "value": row["value"], "unit": unit})
    zones = {item["date"]: item for item in passport["zones"]["days"]}
    notes: dict[str, int] = {}
    for row in passport["context"]["rows"]:
        first = row["temporal"].get("start_local_date")
        notes[first] = notes.get(first, 0) + 1
    rows = []
    for steps in passport["steps"]["days"]:
        day = steps["date"]
        rows.append({
            "date": day, "steps": steps,
            "sleep": {name: nights.get(day) for name, nights in sleep.items()},
            "workouts": [w for w in passport["workouts"]["sessions"] if w["date"] == day],
            "recovery": recovery.get(day, []),
            "zones": zones.get(day, {"zones": []})["zones"],
            "notes": notes.get(day, 0),
        })
    return rows


def passport_zone_segments(passport: dict) -> list[dict]:
    """Consecutive known days with the same stored zones; unknown days are not filled."""
    segments: list[dict] = []
    for item in passport["zones"]["days"]:
        if item["state"] != "known":
            continue
        adjacent = (segments and date.fromisoformat(segments[-1]["last"]) + timedelta(days=1)
                    == date.fromisoformat(item["date"]))
        if adjacent and segments[-1]["zones"] == item["zones"]:
            segments[-1]["last"] = item["date"]
            segments[-1]["known_days"] += 1
        else:
            segments.append({"zones": item["zones"], "first": item["date"],
                             "last": item["date"], "known_days": 1})
    return segments


templates.env.globals.update(
    passport_rows=passport_rows, passport_zone_segments=passport_zone_segments,
    passport_steps=passport_steps, passport_mean=passport_mean,
    passport_offset=passport_offset, passport_workout_time=passport_workout_time)
