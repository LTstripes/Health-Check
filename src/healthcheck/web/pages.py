"""Server-rendered loopback pages for the dashboard and photo review queue."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.analytics.sleep_agreement_report import (
    SleepAgreementReportService,
    unavailable_report,
)
from healthcheck.db.engine import session_scope
from healthcheck.ingestion.photo.errors import PhotoImportError
from healthcheck.ingestion.photo.service import PhotoImportService, PhotoUpload
from healthcheck.ingestion.photo.vision import UnconfiguredImageMeasurementExtractor
from healthcheck.logging import log_event
from healthcheck.web.common import database_unavailable, request_engine, wants_html
from healthcheck.web.garmin_query import GarminQueryError, GarminQueryService
from healthcheck.web.imports import _batch_payload
from healthcheck.web.period_brief_query import PeriodBriefService
from healthcheck.web.query import (
    WeightQueryService,
    empty_dashboard_payload,
    group_review_events,
)

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
router = APIRouter()


_BRIEF_STATE_LABELS = {
    "present": "Данные доступны",
    "confirmed_empty": "За период записей нет",
    "unknown": "Состояние данных не определено",
    "unavailable": "Источник данных недоступен",
    "insufficient": "Недостаточно данных",
    "not_requested": "Не запрашивалось",
}
_BRIEF_FACT_LABELS = {
    "weight_observation_count": "Измерения веса",
    "weight_rate_kg_per_week": "Изменение веса в неделю",
    "weight_trend_available": "Тренд веса",
    "weight_first_daily_median_kg": "Первое значение веса",
    "weight_last_daily_median_kg": "Последнее значение веса",
    "weight_current_kg": "Текущий вес",
    "body_composition_available": "Состав тела",
    "sleep_agreement_mode": "Режим сравнения сна",
    "sleep_agreement_available": "Сравнение сна",
    "sleep_agreement_group_count": "Группы сна",
    "sleep_exploratory_uncertain_cohort_present": "Неопределённая когорта сна",
    "activity_session_count": "Активности",
    "activity_type_counts": "Типы активностей",
    "activity_comparison_state": "Сравнение активностей",
    "weight_coverage_state": "Полнота данных веса",
    "sleep_coverage_state": "Полнота данных сна",
    "activity_coverage_state": "Полнота данных активностей",
    "pending_import_candidates": "Ожидают проверки",
}
_BRIEF_REASON_LABELS = {
    "database_unavailable": "Локальное хранилище данных не готово.",
    "garmin_source_missing": "Источник Garmin за этот период не найден.",
    "insufficient_evidence": "Принятых данных недостаточно для этого показателя.",
    "not_enough_points": "Недостаточно измерений для надёжного показателя.",
    "no_canonical_weight_run": "Нет принятого канонического расчёта веса.",
}
_BRIEF_UNIT_LABELS = {"count": "шт.", "kg/week": "кг/нед.", "kg": "кг"}
_BRIEF_ACTIVITY_LABELS = {
    "cycling": "Велосипед",
    "running": "Бег",
    "walking": "Ходьба",
    "swimming": "Плавание",
    "strength_training": "Силовая тренировка",
    "unknown": "Другая активность",
}
_BRIEF_COHORT_LABELS = {
    "Fitbit device pair": "Пара устройств Fitbit",
    "Google wearable family pair": "Семейство устройств Google",
    "Uncertain Garmin account / Google source or family observations": (
        "Неопределённые наблюдения Garmin и Google"
    ),
}

_BRIEF_PROVIDER_LABELS = {
    "garmin_connect": "Garmin Connect",
    "garmin": "Garmin Connect",
}
_BRIEF_NOTABLE_PRIORITY = {
    # A measured deviation is an actual change.  Availability/status notes are
    # useful context, but should not lead the owner-facing list.
    "personal_baseline_deviation": 0,
    "weight_rate": 1,
    "weight_trend": 1,
    "sleep_exploratory_agreement": 2,
    "activity_comparison": 2,
    "uncertain_account_cohort": 3,
}


def _brief_owner_state(state: object) -> str:
    return _BRIEF_STATE_LABELS.get(str(state or "unknown"), "Состояние данных не определено")


def _brief_owner_fact(code: object) -> str:
    token = str(code or "fact")
    if token.startswith("garmin_sleep_baseline_"):
        return "Базовая линия сна"
    if token.startswith("garmin_activity_related_baseline_"):
        return "Базовая линия активностей"
    if token.startswith("provider_") and token.endswith("_dq_state"):
        return "Состояние источника данных"
    return _BRIEF_FACT_LABELS.get(token, "Показатель периода")


def _brief_owner_reason(reason: object) -> str:
    token = str(reason or "")
    return _BRIEF_REASON_LABELS.get(token, "Подробности доступны в технических данных.")


def _brief_owner_activity(activity_type: object) -> str:
    token = str(activity_type or "unknown")
    return _BRIEF_ACTIVITY_LABELS.get(token, token.replace("_", " ").capitalize())


def _brief_owner_cohort(label: object) -> str:
    text = str(label or "Группа сна")
    for source, translated in _BRIEF_COHORT_LABELS.items():
        if text.startswith(source):
            return translated
    return "Группа сна"


def _brief_owner_uncertainty(_: object) -> str:
    return (
        "Это исследовательская когорта с неопределённой атрибуцией; "
        "это не сравнение Garmin и Fitbit/устройств и не основание для выбора "
        "канонического источника."
    )


def _brief_source_label(source: object) -> str:
    """Return a short owner label without leaking source identity fields."""

    if not isinstance(source, Mapping):
        return "Garmin Connect"
    provider_code = str(source.get("provider_code") or "").strip().casefold()
    provider_label = _BRIEF_PROVIDER_LABELS.get(provider_code, "Garmin Connect")
    # Persisted source payloads carry ``device_attributed``.  Treat an omitted
    # flag as legacy/read-model input, but never show a model explicitly marked
    # as unattributed.
    model = (
        source.get("device_model")
        if source.get("device_attributed") is not False
        else None
    )
    model_text = str(model or "").strip()
    return f"{provider_label} · {model_text}" if model_text else provider_label


def _brief_sleep_uncertainty(groups: object) -> str | None:
    """Collapse repeated uncertain cohort notices into one period warning."""

    if not isinstance(groups, (list, tuple)):
        return None
    if any(
        isinstance(group, Mapping) and group.get("exploratory_label_required")
        for group in groups
    ):
        return _brief_owner_uncertainty(None)
    return None


def _brief_notable_changes(notes: object) -> list[dict[str, Any]]:
    """Deduplicate and order packet notices for the owner-facing summary only."""

    if not isinstance(notes, (list, tuple)):
        return []
    unique: dict[tuple[str, ...], dict[str, Any]] = {}
    for note in notes:
        if not isinstance(note, Mapping):
            continue
        code = str(note.get("code") or "")
        if not code:
            continue
        # Account-level uncertainty is a period warning, not one notice per
        # metric/group.  Other metric-specific deviations retain their detail.
        if code == "uncertain_account_cohort":
            key = (code,)
        else:
            key = (
                str(note.get("section") or ""),
                code,
                str(note.get("metric_code") or ""),
                str(note.get("fact_code") or ""),
                str(note.get("cohort") or ""),
            )
        unique.setdefault(key, dict(note))
    return sorted(
        unique.values(),
        key=lambda note: (
            _BRIEF_NOTABLE_PRIORITY.get(str(note.get("code") or ""), 99),
            str(note.get("section") or ""),
            str(note.get("code") or ""),
            str(note.get("metric_code") or ""),
            str(note.get("fact_code") or ""),
            str(note.get("cohort") or ""),
        ),
    )


def _brief_owner_value(
    value: object,
    unit: object = None,
    availability: object = None,
    fact_code: object = None,
) -> str:
    state = str(availability or "unknown")
    if value is None:
        return _brief_owner_state(state)
    if isinstance(value, bool):
        if not value and state != "present":
            return _brief_owner_state(state)
        return "Да" if value else "Нет"
    if isinstance(value, dict):
        if fact_code == "activity_type_counts":
            return ", ".join(
                f"{_brief_owner_activity(key)}: {count}"
                for key, count in sorted(value.items())
            ) or "Нет записей"
        return "Детали доступны"
    if isinstance(value, (list, tuple)):
        return "Детали доступны"
    if isinstance(value, str) and value in _BRIEF_STATE_LABELS:
        return _brief_owner_state(value)
    rendered_unit = _BRIEF_UNIT_LABELS.get(str(unit), str(unit or ""))
    return f"{value} {rendered_unit}".strip()


def _brief_owner_note(note: object) -> str:
    code = str((note or {}).get("code") or "") if isinstance(note, dict) else ""
    return {
        "weight_rate": "Темп изменения веса доступен.",
        "weight_trend": "Тренд веса доступен.",
        "sleep_exploratory_agreement": "Доступна исследовательская оценка согласованности сна.",
        "uncertain_account_cohort": (
            "Есть исследовательские данные сна с неопределённой атрибуцией."
        ),
        "personal_baseline_deviation": "Обнаружено отклонение от личной базовой линии Garmin.",
        "activity_comparison": "Доступно детерминированное сравнение активностей.",
    }.get(code, "Есть важное изменение в данных периода.")


def _brief_owner_action(action: object) -> str:
    code = str((action or {}).get("code") or "") if isinstance(action, dict) else ""
    return {
        "confirm_pending_imports": "Есть измерения, ожидающие подтверждения.",
        "investigate_provider_sync": (
            "Проверьте синхронизацию источника: данные за период недоступны."
        ),
        "restore_weight_canonical_or_coverage": (
            "Данные веса недоступны: проверьте источник и покрытие периода."
        ),
    }.get(code, "Для этого периода требуется проверить данные.")


def _brief_has_usable_evidence(brief: object) -> bool:
    if not isinstance(brief, dict):
        return False
    sections = brief.get("sections") or {}
    return any(
        (sections.get(name) or {}).get("state") in {"present", "confirmed_empty"}
        for name in ("weight", "sleep", "activity")
    )


def render(
    request: Request, name: str, context: dict[str, Any], status_code: int = 200
) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def render_error(
    request: Request, *, code: str, message: str, status_code: int = 400
) -> HTMLResponse:
    return render(
        request,
        "error.html",
        {"code": code, "message": message, "status_code": status_code},
        status_code=status_code,
    )


def _photo_error(request: Request, exc: PhotoImportError) -> HTMLResponse:
    return render_error(
        request, code=exc.code, message=exc.message, status_code=exc.status_code
    )


def _persist_error(request: Request, operation: str) -> HTMLResponse:
    log_event("persistence_error", operation=operation, status="error", reason="persistence_error")
    return render_error(
        request, code="persistence_error", message="request failed", status_code=500
    )


def _extractor(request: Request):
    return getattr(request.app.state, "photo_extractor", None) or (
        UnconfiguredImageMeasurementExtractor()
    )


@router.get("/", response_class=HTMLResponse)
def dashboard_page(request: Request) -> HTMLResponse:
    try:
        with session_scope(request_engine(request)) as session:
            service = WeightQueryService(session, request.app.state.settings)
            payload = service.dashboard()
    except SQLAlchemyError as exc:
        if not database_unavailable(exc):
            return _persist_error(request, "dashboard")
        payload = empty_dashboard_payload(reason="database_unavailable")
    return render(request, "dashboard.html", {"payload": payload, "page": "dashboard"})


@router.get("/agreement", response_class=HTMLResponse)
def agreement_page(request: Request) -> HTMLResponse:
    try:
        with session_scope(request_engine(request)) as session:
            payload = SleepAgreementReportService(session).report()
    except SQLAlchemyError as exc:
        if not database_unavailable(exc):
            return _persist_error(request, "agreement_report")
        payload = unavailable_report(reason="database_unavailable")
    except ValueError as exc:
        return render_error(
            request, code="invalid_report_request", message=str(exc), status_code=400
        )
    return render(request, "agreement.html", {"payload": payload, "page": "agreement"})


def _brief_period(
    *, preset: str | None, start_date: str | None, end_date: str | None
) -> tuple[date, date, str | None]:
    """Resolve UI period controls without changing stored evidence semantics."""

    if preset is not None:
        if start_date is not None or end_date is not None:
            raise ValueError("choose a preset or enter both custom period dates")
        try:
            days = {"7": 7, "30": 30, "90": 90}[preset]
        except KeyError as exc:
            raise ValueError("preset must be 7, 30, or 90 days") from exc
        end = date.today()
        return end - timedelta(days=days - 1), end, preset

    if start_date is None and end_date is None:
        end = date.today()
        return end - timedelta(days=29), end, "30"
    if start_date is None or end_date is None:
        raise ValueError("custom period requires both start_date and end_date")
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ValueError("custom period dates must use YYYY-MM-DD") from exc
    if end < start:
        raise ValueError("end_date cannot precede start_date")
    return start, end, None


@router.get("/brief", response_class=HTMLResponse)
def period_brief_page(
    request: Request,
    preset: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    garmin_source_id: str | None = None,
) -> HTMLResponse:
    try:
        start, end, selected_preset = _brief_period(
            preset=preset, start_date=start_date, end_date=end_date
        )
        with session_scope(request_engine(request)) as session:
            service = PeriodBriefService(session, request.app.state.settings)
            source_selection = service.garmin.resolve_source(garmin_source_id)
            result = service.build_with_render(
                start_date=start,
                end_date=end,
                garmin_source_id=garmin_source_id,
                thin_display=True,
            )
    except GarminQueryError as exc:
        return render_error(
            request, code=exc.code, message=exc.message, status_code=exc.status_code
        )
    except ValueError as exc:
        return render_error(
            request, code="invalid_period", message=str(exc), status_code=400
        )
    except SQLAlchemyError as exc:
        if not database_unavailable(exc):
            return _persist_error(request, "period_brief_page")
        return render_error(
            request,
            code="database_unavailable",
            message="database is not ready",
            status_code=503,
        )
    return render(
        request,
        "period_brief.html",
        {
            "brief": result["display"],
            "packet": result["packet"],
            "source_selection": source_selection,
            "selected_preset": selected_preset,
            "brief_has_usable_evidence": _brief_has_usable_evidence(result["display"]),
            "brief_owner_action": _brief_owner_action,
            "brief_owner_activity": _brief_owner_activity,
            "brief_owner_cohort": _brief_owner_cohort,
            "brief_owner_fact": _brief_owner_fact,
            "brief_owner_note": _brief_owner_note,
            "brief_owner_reason": _brief_owner_reason,
            "brief_owner_state": _brief_owner_state,
            "brief_owner_uncertainty": _brief_owner_uncertainty,
            "brief_owner_value": _brief_owner_value,
            "brief_notable_changes": _brief_notable_changes,
            "brief_sleep_uncertainty": _brief_sleep_uncertainty,
            "brief_source_label": _brief_source_label,
            "page": "brief",
        },
    )


@router.get("/garmin", response_class=HTMLResponse)
def garmin_dashboard_page(
    request: Request,
    garmin_source_id: str | None = None,
    metric_code: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> HTMLResponse:
    try:
        with session_scope(request_engine(request)) as session:
            service = GarminQueryService(session, request.app.state.settings)
            payload = service.dashboard(
                garmin_source_id=garmin_source_id,
                metric_code=metric_code,
                start_date=start_date,
                end_date=end_date,
            )
    except GarminQueryError as exc:
        return render_error(
            request, code=exc.code, message=exc.message, status_code=exc.status_code
        )
    except SQLAlchemyError as exc:
        if not database_unavailable(exc):
            return _persist_error(request, "garmin_dashboard")
        from healthcheck.web.garmin_query import unavailable_dashboard_payload

        payload = unavailable_dashboard_payload(reason="database_unavailable")
    return render(request, "garmin.html", {"payload": payload, "page": "garmin"})


@router.get("/imports", response_class=HTMLResponse)
def imports_page(request: Request) -> HTMLResponse:
    try:
        with session_scope(request_engine(request)) as session:
            service = PhotoImportService(
                session, request.app.state.runtime_paths, _extractor(request)
            )
            batches = service.list_batches()
            queue = WeightQueryService(
                session, request.app.state.settings
            ).import_queue_summary()
    except SQLAlchemyError as exc:
        if not database_unavailable(exc):
            return _persist_error(request, "imports")
        batches = []
        queue = empty_dashboard_payload(reason="database_unavailable")["imports"]
    return render(
        request,
        "imports.html",
        {"batches": batches, "queue": queue, "page": "imports"},
    )


@router.post("/imports/photos", response_model=None)
async def upload_photos(
    request: Request,
    files: list[UploadFile] = File(...),
) -> RedirectResponse | HTMLResponse:
    uploads: list[PhotoUpload] = []
    for uploaded in files:
        uploads.append(
            PhotoUpload(
                filename=uploaded.filename,
                content=await uploaded.read(),
                declared_media_type=uploaded.content_type,
            )
        )
        await uploaded.close()
    try:
        with session_scope(request_engine(request)) as session:
            service = PhotoImportService(
                session, request.app.state.runtime_paths, _extractor(request)
            )
            result = service.import_photos(uploads)
            batch_id = result.batch.id
        return RedirectResponse(url=f"/imports/{batch_id}", status_code=303)
    except PhotoImportError as exc:
        return _photo_error(request, exc)
    except SQLAlchemyError:
        return _persist_error(request, "photo_import")


@router.get("/imports/{batch_id}", response_class=HTMLResponse)
def import_review_page(request: Request, batch_id: str) -> HTMLResponse:
    try:
        with session_scope(request_engine(request)) as session:
            service = PhotoImportService(
                session, request.app.state.runtime_paths, _extractor(request)
            )
            batch = _batch_payload(service, batch_id)
            groups = group_review_events(batch)
    except PhotoImportError as exc:
        return _photo_error(request, exc)
    except SQLAlchemyError as exc:
        if database_unavailable(exc):
            return render_error(
                request,
                code="database_unavailable",
                message="database is not ready",
                status_code=503,
            )
        return _persist_error(request, "import_review")
    return render(
        request,
        "import_detail.html",
        {"batch": batch, "groups": groups, "page": "imports"},
    )


@router.post("/imports/{batch_id}/edit", response_model=None)
def edit_from_review(
    request: Request,
    batch_id: str,
    candidate_id: str = Form(...),
    edited_value: str | None = Form(default=None),
    edited_unit: str | None = Form(default=None),
    edited_source_local_date: date | None = Form(default=None),
) -> RedirectResponse | HTMLResponse:
    value = None
    if edited_value not in (None, ""):
        try:
            value = float(edited_value)
        except ValueError:
            return render_error(
                request, code="invalid_edit", message="edited value is not a number"
            )
    try:
        with session_scope(request_engine(request)) as session:
            service = PhotoImportService(
                session, request.app.state.runtime_paths, _extractor(request)
            )
            service.edit_pending(
                candidate_id,
                edited_value=value,
                edited_unit=edited_unit or None,
                edited_source_local_date=edited_source_local_date,
            )
        return RedirectResponse(url=f"/imports/{batch_id}", status_code=303)
    except PhotoImportError as exc:
        return _photo_error(request, exc)
    except SQLAlchemyError:
        return _persist_error(request, "photo_edit")


@router.post("/imports/{batch_id}/confirm", response_model=None)
def confirm_from_review(
    request: Request,
    batch_id: str,
    candidate_ids: list[str] = Form(default=[]),
) -> RedirectResponse | HTMLResponse:
    selected = [item for item in candidate_ids if item]
    if not selected:
        return render_error(
            request, code="empty_selection", message="select at least one candidate"
        )
    try:
        with session_scope(request_engine(request)) as session:
            service = PhotoImportService(
                session, request.app.state.runtime_paths, _extractor(request)
            )
            service.confirm(selected)
        return RedirectResponse(url=f"/imports/{batch_id}", status_code=303)
    except PhotoImportError as exc:
        return _photo_error(request, exc)
    except SQLAlchemyError:
        return _persist_error(request, "photo_confirm")


@router.post("/imports/{batch_id}/reject", response_model=None)
def reject_from_review(
    request: Request,
    batch_id: str,
    candidate_ids: list[str] = Form(default=[]),
    reason: str | None = Form(default=None),
) -> RedirectResponse | HTMLResponse:
    selected = [item for item in candidate_ids if item]
    if not selected:
        return render_error(
            request, code="empty_selection", message="select at least one candidate"
        )
    try:
        with session_scope(request_engine(request)) as session:
            service = PhotoImportService(
                session, request.app.state.runtime_paths, _extractor(request)
            )
            service.reject(selected, reason=reason)
        return RedirectResponse(url=f"/imports/{batch_id}", status_code=303)
    except PhotoImportError as exc:
        return _photo_error(request, exc)
    except SQLAlchemyError:
        return _persist_error(request, "photo_reject")


def html_http_error(request: Request, status_code: int, detail: str) -> HTMLResponse | None:
    if not wants_html(request):
        return None
    message = "not found" if status_code == 404 else "request failed"
    code = "not_found" if status_code == 404 else "http_error"
    del detail
    return render_error(request, code=code, message=message, status_code=status_code)
