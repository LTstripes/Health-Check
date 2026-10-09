"""Bounded dashboard adapter over Context v0; no providers or migrations."""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import parse_qs
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.context import (
    ContextConflictError,
    ContextService,
    ContextValidationError,
    parse_date_only,
    parse_interval,
    parse_timestamp,
)
from healthcheck.context.service import ContextRevisionView, TemporalValue
from healthcheck.db.engine import session_scope
from healthcheck.db.models import ContextEventHead, ContextEventRevision
from healthcheck.web.common import request_engine
from healthcheck.web.pages import templates
from healthcheck.web.read_snapshot import ensure_read_snapshot

router = APIRouter()
FORM_FIELDS = frozenset(
    {
        "original_text",
        "event_date",
        "event_time",
        "offset",
        "timezone_name",
        "end_date",
        "end_time",
        "end_offset",
        "operation_id",
        "expected_revision_id",
    }
)
MAX_FORM_BYTES = 64 * 1024
LIST_LIMIT = 50
ERRORS = {
    422: "Проверь текст (1–4000 символов), даты и время. Для времени укажи UTC-смещение; "
    "часовой пояс IANA должен ему соответствовать. Границы интервала должны иметь "
    "одинаковую точность. Несуществующее время не принимается.",
    409: "Запись уже изменена или ключ повтора использован для другого ввода. "
    "Черновик сохранён ниже. Открой актуальную запись и сравни изменения перед повтором.",
    404: "Запись не найдена.",
    503: "Хранилище комментариев недоступно. Черновик можно сохранить и повторить позже.",
}


def _render(request: Request, *, status: int = 200, **context):
    response = templates.TemplateResponse(
        request, "context.html", {"page": "context", **context}, status_code=status
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _blank():
    return {"event_date": date.today().isoformat(), "operation_id": str(uuid4())}


def _identifier(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ContextValidationError("invalid identifier") from exc


def _temporal(form: dict[str, str]) -> TemporalValue:
    start_date = form.get("event_date", "")
    clock = form.get("event_time", "")
    offset = form.get("offset", "")
    zone = form.get("timezone_name", "") or None
    end_date = form.get("end_date", "")
    end_clock = form.get("end_time", "")
    end_offset = form.get("end_offset", "")
    if not clock:
        if offset or zone or end_clock or end_offset:
            raise ContextValidationError("date only must not carry time context")
        return parse_interval(start_date, end_date) if end_date else parse_date_only(start_date)
    if not offset:
        raise ContextValidationError("explicit offset required")
    start = f"{start_date}T{clock}{offset}"
    if end_date:
        if not end_clock or not end_offset:
            raise ContextValidationError("complete interval endpoint required")
        return parse_interval(start, f"{end_date}T{end_clock}{end_offset}", timezone_name=zone)
    if end_clock or end_offset:
        raise ContextValidationError("end date required")
    return parse_timestamp(start, timezone_name=zone)


def _form_for(view: ContextRevisionView) -> dict[str, str]:
    value = view.temporal
    form = _blank()
    form.update(
        original_text=view.original_text,
        event_date=value.start_local_date.isoformat(),
        expected_revision_id=view.revision_id,
    )
    for prefix, timestamp in (
        ("", value.start_source_timestamp),
        ("end_", value.end_source_timestamp),
    ):
        if timestamp:
            clock = timestamp.split("T", 1)[1]
            offset = "Z" if clock.endswith("Z") else clock[-6:]
            form["event_time" if not prefix else "end_time"] = clock[: -len(offset)]
            form["offset" if not prefix else "end_offset"] = offset
    if value.end_local_date:
        form["end_date"] = value.end_local_date.isoformat()
    form["timezone_name"] = value.start_timezone or ""
    return form


def _view(service: ContextService, event_id: str) -> ContextRevisionView | None:
    # The adapter selects one head; the existing v0 projection preserves time/tag provenance.
    head = service.session.get(ContextEventHead, event_id)
    row = service.session.get(ContextEventRevision, head.revision_id) if head else None
    return service._view(row) if row else None


@router.get("/context")
def context_list(request: Request):
    form = _blank()
    start = request.query_params.get("from_date", (date.today() - timedelta(days=30)).isoformat())
    end = request.query_params.get("to_date", date.today().isoformat())
    try:
        from_date = parse_date_only(start).start_local_date
        to_date = parse_date_only(end).start_local_date
        with session_scope(request_engine(request)) as session:
            ensure_read_snapshot(session)
            items = ContextService(session).list(
                from_date=from_date, to_date=to_date, limit=LIST_LIMIT + 1
            )
        return _render(
            request,
            form=form,
            items=items[:LIST_LIMIT],
            has_more=len(items) > LIST_LIMIT,
            from_date=start,
            to_date=end,
        )
    except ContextValidationError:
        return _render(
            request, status=422, form=form, error=ERRORS[422], from_date=start, to_date=end
        )
    except SQLAlchemyError:
        return _render(request, status=503, form=form, error=ERRORS[503])


@router.get("/context/{event_id}")
def context_event(request: Request, event_id: str):
    try:
        event_id = _identifier(event_id)
        with session_scope(request_engine(request)) as session:
            ensure_read_snapshot(session)
            service = ContextService(session)
            current = _view(service, event_id)
            if current is None:
                return _render(request, status=404, error=ERRORS[404])
            history = ()
            has_more = False
            if request.query_params.get("history") == "1":
                rows = session.scalars(
                    select(ContextEventRevision)
                    .where(ContextEventRevision.event_id == event_id)
                    .order_by(ContextEventRevision.revision_number.desc())
                    .limit(LIST_LIMIT + 1)
                )
                views = tuple(service._view(row) for row in rows)
                history, has_more = views[:LIST_LIMIT], len(views) > LIST_LIMIT
        saved = request.query_params.get("saved")
        return _render(
            request,
            current=current,
            form=_form_for(current),
            history=history,
            has_more=has_more,
            saved=saved if saved == current.revision_id else None,
            saved_older=bool(saved and saved != current.revision_id),
        )
    except ContextValidationError:
        return _render(request, status=422, error=ERRORS[422])
    except SQLAlchemyError:
        return _render(request, status=503, error=ERRORS[503])


async def _read_form(request: Request) -> dict[str, str]:
    if (
        request.headers.get("content-type", "").split(";", 1)[0]
        != "application/x-www-form-urlencoded"
    ):
        raise ContextValidationError("unsupported form encoding")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_FORM_BYTES:
            raise ContextValidationError("form too large")
        body.extend(chunk)
    try:
        parsed = parse_qs(
            body.decode("utf-8", errors="strict"),
            keep_blank_values=True,
            max_num_fields=len(FORM_FIELDS),
            encoding="utf-8",
            errors="strict",
        )
    except (ValueError, UnicodeError) as exc:
        raise ContextValidationError("invalid form") from exc
    if parsed.keys() - FORM_FIELDS or any(len(values) != 1 for values in parsed.values()):
        raise ContextValidationError("unsupported or duplicate fields")
    form = {key: values[0] for key, values in parsed.items()}
    # The service enforces 4000 code points; retain a bounded invalid text draft for correction.
    if any(len(value) > 100 for key, value in form.items() if key != "original_text"):
        raise ContextValidationError("field too large")
    return form


async def _save(request: Request, event_id: str | None = None):
    form = None
    try:
        form = await _read_form(request)
        temporal = _temporal(form)
        operation_id = form.get("operation_id", "")
        with session_scope(request_engine(request)) as session:
            # Serialize optimistic head check + service write, including simultaneous retries.
            session.execute(text("BEGIN IMMEDIATE"))
            service = ContextService(session)
            if event_id:
                event_id = _identifier(event_id)
                existing = session.scalar(
                    select(ContextEventRevision).where(
                        ContextEventRevision.operation_id == operation_id
                    )
                )
                if existing is None:
                    current = _view(service, event_id)
                    if current is None:
                        return _render(request, status=404, error=ERRORS[404], form=form)
                    if current.revision_id != form.get("expected_revision_id"):
                        raise ContextConflictError("stale editor")
                result = service.revise(
                    event_id,
                    text=form.get("original_text", ""),
                    temporal=temporal,
                    capture_source="dashboard",
                    operation_id=operation_id,
                )
            else:
                result = service.add(
                    text=form.get("original_text", ""),
                    temporal=temporal,
                    capture_source="dashboard",
                    operation_id=operation_id,
                )
        response = RedirectResponse(
            f"/context/{result.event_id}?saved={result.revision_id}", status_code=303
        )
        response.headers["Cache-Control"] = "no-store"
        return response
    except ContextConflictError:
        status = 409
    except ContextValidationError:
        status = 422
    except SQLAlchemyError:
        status = 503
    return _render(
        request, status=status, error=ERRORS[status], form=form, editing_event_id=event_id
    )


@router.post("/context")
async def context_add(request: Request):
    return await _save(request)


@router.post("/context/{event_id}")
async def context_revise(request: Request, event_id: str):
    return await _save(request, event_id)
