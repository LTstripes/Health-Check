"""Server-rendered loopback pages for the dashboard and photo review queue."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.analytics.sleep_agreement_report import (
    SleepAgreementReportService,
    unavailable_report,
)
from healthcheck.analytics.sleep_metrics import get_sleep_metric_definition
from healthcheck.analytics.sleep_source_view import (
    read_source_sleep_night,
    read_source_sleep_range,
)
from healthcheck.collection_policy import resolve_profile_collection_policy
from healthcheck.db.engine import session_scope
from healthcheck.db.models import ImportCandidate, IngestEvent
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.google.daily_vitals import (
    GOOGLE_DAILY_VITALS,
    read_google_daily_vitals,
)
from healthcheck.ingestion.photo.errors import PhotoImportError
from healthcheck.ingestion.photo.service import PhotoImportService, PhotoUpload
from healthcheck.ingestion.photo.vision import UnconfiguredImageMeasurementExtractor
from healthcheck.logging import log_event
from healthcheck.source_freshness_consumer import read_consumer_freshness_projection
from healthcheck.web.common import database_unavailable, request_engine, wants_html
from healthcheck.web.garmin_query import GarminQueryError, GarminQueryService
from healthcheck.web.imports import _batch_payload
from healthcheck.web.overview_charts import read_overview_charts
from healthcheck.web.overview_view import overview_number, read_overview_values
from healthcheck.web.owner_presentation import owner_date, owner_number
from healthcheck.web.period_brief_query import PeriodBriefService
from healthcheck.web.query import (
    WeightQueryService,
    empty_dashboard_payload,
    group_review_events,
)
from healthcheck.web.read_snapshot import ensure_read_snapshot
from healthcheck.web.sleep_comparison import comparison_charts, comparison_value
from healthcheck.web.sleep_timeline import (
    SLEEP_TIMELINE_PROVIDERS,
    build_sleep_timeline,
    sleep_timeline_days,
    sleep_timeline_technical,
)
from healthcheck.web.sleep_view import (
    GOOGLE_VITAL_METRICS,
    GOOGLE_VITALS_WINDOWS,
    SLEEP_METRICS,
    SOURCE_SLEEP_DETAILS,
    SOURCE_SLEEP_PRIMARY,
    google_vital_cell_state,
    google_vital_ineligible_note,
    google_vital_source_label,
    google_vital_value_text,
    google_vitals_view,
    google_vitals_window_days,
    metric_value,
    night_metric,
    nightly_rows,
    point_state,
    source_night_metric,
    source_sleep_label,
    source_sleep_note,
    source_sleep_value,
)

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
templates.env.filters.update(owner_date=owner_date, owner_number=owner_number)
router = APIRouter()


_BRIEF_STATE_LABELS = {
    "present": "Данные доступны",
    "confirmed_empty": "За период записей нет",
    "unknown": "Состояние данных не определено",
    "unavailable": "Источник данных недоступен",
    "insufficient": "Недостаточно данных",
    "not_requested": "Не запрашивалось",
    "partial": "Данные доступны частично",
    "loading": "Загрузка данных",
    "error": "Не удалось выполнить запрос",
    "no_change": "Изменений не обнаружено",
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
    "sleep_primary_duration_seconds": "Последняя длительность сна",
    "sleep_primary_nights_with_duration": "Ночей с длительностью",
    "sleep_primary_score": "Последняя оценка сна Garmin",
    "sleep_primary_nights_with_score": "Ночей с оценкой сна",
    "pending_import_candidates": "Ожидают проверки",
}
_BRIEF_REASON_LABELS = {
    "database_unavailable": "Локальное хранилище данных не готово.",
    "garmin_source_missing": "Источник Garmin за этот период не найден.",
    "insufficient_evidence": "Принятых данных недостаточно для этого показателя.",
    "not_enough_points": "Недостаточно измерений для надёжного показателя.",
    "no_canonical_weight_run": "Нет принятого расчёта веса.",
}
_BRIEF_UNIT_LABELS = {
    "count": "шт.",
    "kg/week": "кг/нед.",
    "kg": "кг",
    "seconds": "с",
    "bpm": "уд/мин",
    "percentage_points": "п.п.",
    "%": "%",
    "ms": "мс",
    "points": "баллы",
    "meters": "м",
    "m/s": "м/с",
    "watts": "Вт",
    "rpm": "об/мин",
}
_BRIEF_ACTIVITY_LABELS = {
    "cycling": "Велосипед",
    "running": "Бег",
    "walking": "Ходьба",
    "swimming": "Плавание",
    "strength_training": "Силовая тренировка",
    "tennis": "Теннис",
    "tennis_v2": "Теннис",
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
    # Measured deviations lead the owner-facing list; status and uncertainty
    # notes remain visible as context below them.
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


_WEIGHT_OWNER_REASONS = {
    "no_data": "Нет подтверждённых измерений.",
    "no_data_in_window": "В выбранном окне нет подтверждённых измерений.",
    "insufficient_observations": "Недостаточно измерений для надёжного показателя.",
    "insufficient_span": "Недостаточно охвата по времени для надёжного показателя.",
    "insufficient_evidence": "Принятых данных недостаточно для этого показателя.",
    "not_enough_points": "Недостаточно измерений для надёжного показателя.",
    "no_canonical_run": "Нет принятого расчёта.",
    "no_canonical_weight_run": "Нет принятого расчёта веса.",
    "canonical_selection_failed": "Принятый расчёт недоступен после неудачного пересчёта.",
    "canonical_selection_in_progress": "Принятый расчёт ещё не готов.",
    "canonical_recompute_failed": "Последний пересчёт не удался.",
    "canonical_recompute_in_progress": "Идёт пересчёт.",
    "database_unavailable": "Локальное хранилище данных не готово.",
    "missing_session": "Нет подходящей сессии измерений.",
    "missing_weight": "Нет веса для сравнения.",
    "missing_composition_evidence": "Нет подходящих данных состава тела.",
    "missing_observed_date": "Нет даты измерения.",
    "missing_value": "Нет пригодного значения.",
    "missing_compatibility_group": "Группа алгоритма не определена.",
    "cross_session": "Измерения из разных сессий нельзя объединять.",
    "conflicting_observed_date": "Даты измерений не совпадают.",
    "incompatible_algorithm_group": "Другой алгоритм; сравнение через границу недоступно.",
    "insufficient_gap": "Интервал между измерениями меньше 28 дней.",
    "weight_diff_exceeds_threshold": "Вес отличается более чем на 1%.",
    "invalid_weight_value": "Значение веса непригодно.",
    "invalid_body_fat_value": "Значение жира непригодно.",
    "invalid_weight_metric": "Показатель веса непригоден.",
    "invalid_body_fat_metric": "Показатель жира непригоден.",
    "invalid_unit": "Единицы измерения непригодны.",
    "non_positive_weight": "Значение веса непригодно.",
    "not_confirmed": "Измерение не подтверждено.",
    "superseded": "Есть более новое измерение.",
    "source_muscle_not_lean": "Мышцы источника — не сухая масса.",
}

_WEIGHT_INSUFFICIENT_REASONS = frozenset(
    {
        "insufficient_observations",
        "insufficient_span",
        "insufficient_evidence",
        "not_enough_points",
        "insufficient_gap",
    }
)


def _weight_owner_reason(reason: object) -> str:
    """Translate a weight analytic reason without changing packet semantics."""

    token = str(reason or "")
    if token in _WEIGHT_OWNER_REASONS:
        return _WEIGHT_OWNER_REASONS[token]
    if token.startswith("missing_"):
        return "Нет подходящих данных."
    if token.startswith("invalid_"):
        return "Данные непригодны для этого показателя."
    return "Подробности доступны в технических данных."


def _weight_owner_state(available: object, reason: object) -> str:
    """Map weight availability to a frozen owner state key only."""

    if available is True:
        return "present"
    token = str(reason or "unknown")
    if token in _WEIGHT_INSUFFICIENT_REASONS:
        return "insufficient"
    if token in {"unknown", "", "none", "None"}:
        return "unknown"
    return "unavailable"


def _brief_owner_activity(activity_type: object) -> str:
    token = str(activity_type or "unknown")
    return _BRIEF_ACTIVITY_LABELS.get(token, "Другая активность")


def _brief_owner_cohort(label: object) -> str:
    text = str(label or "Группа сна")
    for source, translated in _BRIEF_COHORT_LABELS.items():
        if text.startswith(source):
            return translated
    return "Группа сна"


def _brief_owner_uncertainty(_: object) -> str:
    return (
        "Принадлежность устройству и роль записи сна могут быть неизвестны. "
        "Это не сравнение Garmin и Fitbit/устройств, не оценка точности и не основание "
        "для выбора основного источника."
    )


def _brief_source_label(source: object) -> str:
    """Return a short owner label without leaking source identity fields."""

    if not isinstance(source, Mapping):
        return "Garmin Connect"
    provider_code = str(source.get("provider_code") or "").strip().casefold()
    provider_label = _BRIEF_PROVIDER_LABELS.get(provider_code, "Garmin Connect")
    # A model is useful only when the persisted source explicitly proves that
    # the device is attributed. Unknown and false attribution stay generic.
    model = source.get("device_model") if source.get("device_attributed") is True else None
    model_text = str(model or "").strip()
    return f"{provider_label} · {model_text}" if model_text else provider_label


def _brief_sleep_uncertainty(groups: object) -> str | None:
    """Collapse repeated uncertain cohort notices into one period warning."""

    if not isinstance(groups, (list, tuple)):
        return None
    if any(
        isinstance(group, Mapping) and group.get("exploratory_label_required") for group in groups
    ):
        return _brief_owner_uncertainty(None)
    return None


def _brief_coverage_warning(brief: object) -> str | None:
    """Summarize relevant coverage warnings without changing packet states."""

    if not isinstance(brief, Mapping):
        return None
    sections = brief.get("sections")
    if not isinstance(sections, Mapping):
        return None
    warnings: list[str] = []
    quality = sections.get("data_quality")
    coverage = quality.get("coverage") if isinstance(quality, Mapping) else None
    for provider in (coverage or {}).get("provider_states") or []:
        if not isinstance(provider, Mapping):
            continue
        state = str(provider.get("state") or "unknown")
        if state not in {"present", "confirmed_empty", "not_requested"}:
            provider_name = {"garmin_connect": "Garmin", "google": "Google"}.get(
                provider.get("provider_code"), "Источник"
            )
            warnings.append(f"{provider_name}: {_brief_owner_state(state)}")
    sparse_note = (coverage or {}).get("weight_sparse_note")
    if sparse_note:
        warnings.append(
            "Нерегулярные измерения веса сами по себе не означают сбой источника; "
            "обновление источника не означает новое измерение."
        )
    return " · ".join(dict.fromkeys(warnings)) or None


_FRESHNESS_PROVIDER_STATES = {
    "fresh": "present",
    "quiet": "present",
    "stale": "partial",
    "unavailable": "unavailable",
    "unknown": "unknown",
    "not_requested": "not_requested",
}


def _brief_source_status(brief: object) -> str | None:
    """Project provider freshness source-explicitly; Google is never pooled (#291)."""

    if not isinstance(brief, Mapping):
        return None
    quality = (brief.get("sections") or {}).get("data_quality")
    coverage = quality.get("coverage") if isinstance(quality, Mapping) else None
    freshness = coverage.get("freshness") if isinstance(coverage, Mapping) else None
    providers = freshness.get("providers") if isinstance(freshness, Mapping) else None
    if not isinstance(providers, Mapping):
        return None
    parts: list[str] = []
    for code, label in (("garmin", "Garmin"), ("google", "Google")):
        provider = providers.get(code)
        state = provider.get("state") if isinstance(provider, Mapping) else None
        mapped = _FRESHNESS_PROVIDER_STATES.get(str(state))
        if mapped:
            parts.append(f"{label}: {_brief_owner_state(mapped)}")
    return " · ".join(parts) or None


def _brief_notable_changes(notes: object) -> list[dict[str, Any]]:
    """Select measured observations, then deduplicate the Owner summary only."""

    if not isinstance(notes, (list, tuple)):
        return []
    unique: dict[tuple[str, ...], dict[str, Any]] = {}
    for note in notes:
        if not isinstance(note, Mapping):
            continue
        code = str(note.get("code") or "")
        if not code:
            continue
        # Availability and Agreement uncertainty already live in their own
        # sections. Only measured observations belong in "Что заметно".
        if code != "personal_baseline_deviation" and not (
            code == "weight_rate" and note.get("value") is not None
        ):
            continue
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
            return (
                ", ".join(
                    f"{_brief_owner_activity(key)}: {count}" for key, count in sorted(value.items())
                )
                or "Нет записей"
            )
        return "Детали доступны"
    if isinstance(value, (list, tuple)):
        return "Детали доступны"
    if isinstance(value, str) and value in _BRIEF_STATE_LABELS:
        return _brief_owner_state(value)
    if (
        fact_code == "sleep_primary_duration_seconds"
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    ):
        return metric_value("sleep_duration_seconds", value)
    rendered_unit = _BRIEF_UNIT_LABELS.get(str(unit), str(unit or ""))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = overview_number(value)
    return f"{value} {rendered_unit}".strip()


def _brief_owner_note(note: object) -> str:
    code = str((note or {}).get("code") or "") if isinstance(note, dict) else ""
    text = {
        "weight_rate": "Изменение веса в неделю:",
        "weight_trend": "Тренд веса доступен.",
        "sleep_exploratory_agreement": "Доступна исследовательская оценка согласованности сна.",
        "uncertain_account_cohort": (
            "Есть исследовательские данные сна с неопределённой атрибуцией."
        ),
        "personal_baseline_deviation": "Обнаружено отклонение от личной базовой линии Garmin.",
        "activity_comparison": "Доступно сравнение активностей за период.",
    }.get(code, "Есть важное изменение в данных периода.")
    if code == "sleep_exploratory_agreement":
        metric = str(note.get("metric_code") or "")
        if metric in _BRIEF_SLEEP_METRICS:
            return f"{_BRIEF_SLEEP_METRICS[metric][1]}: доступно исследовательское сравнение."
    if code == "personal_baseline_deviation":
        metric = str(note.get("fact_code") or "")
        for prefix in ("garmin_sleep_baseline_", "garmin_activity_related_baseline_"):
            if metric.startswith(prefix):
                label = _BRIEF_BASELINE_LABELS.get(metric.removeprefix(prefix))
                return f"{label or 'Показатель Garmin'}: отклонение от личной базовой линии."
    return text


_BRIEF_BASELINE_LABELS = {
    "sleep_duration_seconds": "Длительность сна",
    "sleep_score": "Оценка сна Garmin",
    "stress_daily_average": "Средний стресс Garmin",
    "stress_daily_maximum": "Максимальный стресс Garmin",
    "spo2_daily_average": "Средний кислород в крови",
    "spo2_trailing_7d_average": "Кислород в крови за 7 дней",
    "duration_seconds": "Длительность активности",
    "distance_meters": "Расстояние",
    "speed_mps": "Скорость",
    "heart_rate_bpm": "Пульс",
    "power_watts": "Мощность",
    "cadence_rpm": "Каденс",
    "training_effect": "Эффект тренировки Garmin",
    "acute_training_load": "Нагрузка Garmin",
}


def _brief_note_value(note: Mapping[str, Any], brief: Mapping[str, Any]) -> str:
    if note.get("value") is None:
        return ""
    unit = note.get("unit")
    if note.get("code") == "personal_baseline_deviation":
        # The notice omits its unit; recover only from its exact packet fact.
        for section in brief.get("sections", {}).values():
            for fact in section.get("summary_facts") or []:
                if fact.get("code") == note.get("fact_code"):
                    unit = fact.get("unit")
    if not unit:
        return "Значение и единицы доступны в технических деталях."
    return _brief_owner_value(note["value"], unit, "present")


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


_BRIEF_SLEEP_METRICS = {
    "sleep_duration_asleep_seconds": ("Длительность и время", "Длительность сна"),
    "sleep_time_in_bed_seconds": ("Длительность и время", "Время в постели"),
    "sleep_start_at": ("Длительность и время", "Начало сна"),
    "sleep_end_at": ("Длительность и время", "Окончание сна"),
    "sleep_stage_light_seconds": ("Стадии сна", "Лёгкий сон"),
    "sleep_stage_deep_seconds": ("Стадии сна", "Глубокий сон"),
    "sleep_stage_rem_seconds": ("Стадии сна", "Быстрый сон (REM)"),
    "sleep_awake_waso_seconds": ("Стадии сна", "Бодрствование внутри сна"),
    "resting_heart_rate_bpm": ("Сопутствующие показатели за день", "Пульс в покое"),
    "spo2_daily_average_pct": ("Сопутствующие показатели за день", "Средний кислород в крови"),
}


def _brief_sleep_groups(groups: object) -> list[dict[str, Any]]:
    """Arrange packet rows by meaning; never pool samples or recompute statistics."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for group in groups if isinstance(groups, (list, tuple)) else []:
        if not isinstance(group, Mapping):
            continue
        code = str(group.get("metric_code") or "")
        category, label = _BRIEF_SLEEP_METRICS.get(code, ("Другие сравнения", "Другой показатель"))
        # Only a frozen metric definition proves the unit. Unknown metrics stay
        # inspectable in disclosure without inventing comparable owner values.
        unit = (
            get_sleep_metric_definition(code).difference_unit
            if code in _BRIEF_SLEEP_METRICS
            else None
        )
        variant = {
            "STAGES": "Со стадиями сна",
            "CLASSIC": "Без стадий сна",
            "DAILY": "За день",
        }.get(
            group.get("variant"),
            "Вариант не указан" if group.get("variant") is None else "Другой вариант",
        )
        buckets.setdefault(category, []).append(
            {
                "label": label,
                "variant": variant,
                "unit": unit,
                "group": group,
            }
        )
    return [{"label": label, "rows": rows} for label, rows in buckets.items()]


def _brief_owner_actions(actions: object) -> list[dict[str, Any]]:
    """Deduplicate instructions by source and meaning, retaining every input in the packet."""
    unique: dict[tuple[str, ...], dict[str, Any]] = {}
    for action in actions if isinstance(actions, (list, tuple)) else []:
        if not isinstance(action, Mapping):
            continue
        code = str(action.get("code") or "")
        reason = str(action.get("reason_code") or "")
        short_text = ""
        if code == "source_freshness_attention":
            scope = str(action.get("scope_key") or "")
            provider = (
                "Garmin"
                if scope.startswith("garmin:")
                else "Google"
                if scope.startswith("google:")
                else "Источник"
            )
            family, text = {
                "reauth_required": (
                    "login",
                    "Повторите вход в источник через локальный процесс сбора.",
                ),
                "refresh_overdue": (
                    "collection",
                    "Проверьте выполнение локального сбора и его последний отчёт.",
                ),
                "expected_evidence_absent": (
                    "collection",
                    "Проверьте выполнение локального сбора и его последний отчёт.",
                ),
                "refresh_failed": (
                    "failure",
                    "Проверьте ошибку в последнем отчёте локального сбора.",
                ),
            }.get(reason, ("inspect", "Проверьте сведения об источнике в разделе «Данные»."))
            key = (code, provider, family)
            text = f"{provider}: {text}"
            short_text = f"{provider}: " + {
                "login": "нужен повторный вход",
                "collection": "проверьте сбор данных",
                "failure": "ошибка обновления",
                "inspect": "проверьте состояние",
            }[family]
            context = {
                "stale": "Данные устарели",
                "unknown": "Свежесть неизвестна",
                "unavailable": "Данные недоступны",
                "not_requested": "Данные не запрашивались",
            }.get(str(action.get("state")), "Состояние требует проверки")
        elif code == "investigate_provider_sync":
            provider = {"garmin_connect": "Garmin", "google": "Google"}.get(
                action.get("provider_code"), "Источник"
            )
            key = (code, str(action.get("provider_code") or ""))
            text, context = (
                f"{provider}: проверьте последний отчёт локального сбора.",
                "Данные недоступны",
            )
            short_text = f"{provider}: проверьте отчёт сбора"
        else:
            key = (code,)
            text, context = _brief_owner_action(dict(action)), ""
        item = unique.setdefault(
            key,
            {
                "short_text": short_text,
                "text": text,
                "contexts": [],
                "link": "/imports" if code == "confirm_pending_imports" else "/imports#data-status",
                "link_label": "Проверить измерения"
                if code == "confirm_pending_imports"
                else "Открыть данные",
            },
        )
        if context and context not in item["contexts"]:
            item["contexts"].append(context)
    return list(unique.values())


def _brief_primary_facts(section: object) -> list[dict[str, Any]]:
    codes = {
        "weight_observation_count",
        "weight_rate_kg_per_week",
        "weight_first_daily_median_kg",
        "weight_last_daily_median_kg",
        "sleep_primary_duration_seconds",
        "sleep_primary_nights_with_duration",
        "sleep_primary_score",
        "activity_session_count",
        "activity_type_counts",
    }
    if not isinstance(section, Mapping):
        return []
    return [
        fact
        for fact in section.get("summary_facts") or []
        if isinstance(fact, dict) and fact.get("code") in codes
    ]


def _brief_section_has_usable_evidence(name: str, section: object) -> bool:
    """Inspect actual section evidence instead of only the aggregate state (#291)."""

    if not isinstance(section, Mapping):
        return False
    if name == "weight":
        if section.get("display_points"):
            return True
        return any(
            isinstance(fact, Mapping)
            and fact.get("code") == "weight_observation_count"
            and fact.get("availability") == "present"
            and fact.get("value")
            for fact in section.get("summary_facts") or []
        )
    if name == "activity":
        return bool(section.get("sessions"))
    if name == "sleep":
        coverage = section.get("coverage")
        primary = coverage.get("primary") if isinstance(coverage, Mapping) else None
        metrics = primary.get("metrics") if isinstance(primary, Mapping) else None
        if isinstance(metrics, (list, tuple)) and any(
            isinstance(metric, Mapping) and (metric.get("usable_count") or 0) > 0
            for metric in metrics
        ):
            return True
        return any(
            isinstance(fact, Mapping)
            and fact.get("code")
            in {"sleep_primary_duration_seconds", "sleep_primary_score"}
            and fact.get("value") is not None
            for fact in section.get("summary_facts") or []
        )
    return False


def _brief_has_usable_evidence(brief: object) -> bool:
    if not isinstance(brief, dict):
        return False
    sections = brief.get("sections") or {}
    for name in ("weight", "sleep", "activity"):
        section = sections.get(name)
        if not isinstance(section, Mapping):
            continue
        if section.get("state") in {"present", "confirmed_empty"}:
            return True
        if _brief_section_has_usable_evidence(name, section):
            return True
    return False


def render(
    request: Request, name: str, context: dict[str, Any], status_code: int = 200
) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def render_error(
    request: Request, *, code: str, message: str, status_code: int = 400
) -> HTMLResponse:
    # HTML presentation only. API errors and exact diagnostic text stay unchanged.
    owner_message = {
        "unknown_batch": "Загрузка не найдена. Открой список загрузок в разделе «Данные».",
        "unknown_garmin_source_id": "Источник Garmin не найден. Выбери доступный источник.",
    }.get(code) or {
        "choose a preset or enter both custom period dates":
            "Выбери готовый период или укажи обе даты своего периода.",
        "preset must be 7, 30, or 90 days": "Выбери период: 7, 30 или 90 дней.",
        "custom period requires both start_date and end_date": "Укажи начало и окончание периода.",
        "custom period dates must use YYYY-MM-DD": "Укажи даты периода в формате ГГГГ-ММ-ДД.",
        "end_date cannot precede start_date": "Окончание периода не может быть раньше начала.",
        "request could not be parsed":
            "Не удалось прочитать параметры запроса. Проверь их и повтори.",
        "request failed": "Не удалось выполнить запрос. Попробуй повторить его.",
        "not found": "Страница не найдена. Открой нужный раздел через навигацию.",
        "database is not ready": "Локальное хранилище данных не готово.",
    }.get(message, message)
    return render(
        request,
        "error.html",
        {"code": code, "message": owner_message, "technical_message": message,
         "status_code": status_code},
        status_code=status_code,
    )


def _photo_error(request: Request, exc: PhotoImportError) -> HTMLResponse:
    return render_error(
        request, code=exc.code, message=exc.message, status_code=exc.status_code
    )


def _persist_error(request: Request, operation: str) -> HTMLResponse:
    log_event("persistence_error", operation=operation, status="error", reason="persistence_error")
    return render_error(
        request,
        code="persistence_error",
        message=(
            "Не удалось прочитать данные сна."
            if operation in {"sleep_page", "agreement_report"} else "request failed"
        ),
        status_code=500,
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
    return render(
        request,
        "dashboard.html",
        {
            "payload": payload,
            "page": "dashboard",
            "weight_owner_reason": _weight_owner_reason,
            "weight_owner_state": _weight_owner_state,
        },
    )


@router.get("/sleep", response_class=HTMLResponse)
def sleep_page(
    request: Request,
    wake_date: str | None = None,
    garmin_source_id: str | None = None,
    vitals_window: str | None = None,
    view: str = "timeline",
    days: str | None = None,
) -> HTMLResponse:
    try:
        end = date.fromisoformat(wake_date) if wake_date is not None else date.today()
    except ValueError:
        return render_error(
            request, code="invalid_sleep_date",
            message="Укажите дату пробуждения в формате ГГГГ-ММ-ДД.",
        )
    vitals_days = google_vitals_window_days(vitals_window)
    if end < date.min + timedelta(days=max(29, vitals_days - 1)):
        return render_error(
            request, code="invalid_sleep_date",
            message="Дата не позволяет показать 30 дней истории.",
        )
    start = end - timedelta(days=29)
    view = view if view in {"timeline", "garmin", "google", "compare"} else "timeline"
    if view == "compare":
        return _render_comparison(request, start=start, end=end, vitals_days=vitals_days)
    if view == "timeline":
        return _render_sleep_timeline(
            request, end=end, days=sleep_timeline_days(days), vitals_days=vitals_days
        )
    vitals_start = end - timedelta(days=vitals_days - 1)
    results: dict[str, Any] = {}
    selection: dict[str, Any] = {"status": "no_data", "sources": []}
    google_vitals: dict[str, Any] | None = google_vitals_view(())
    google_vitals_technical: list[dict[str, Any]] | None = []
    source_sleep: dict[str, Any] | None = {"state": "no_records", "sources": []}
    try:
        with session_scope(request_engine(request)) as session:
            ensure_read_snapshot(session)
            service = GarminQueryService(session, request.app.state.settings)
            selection = service.resolve_source(garmin_source_id)
            if selection["status"] == "selected":
                for code in SLEEP_METRICS:
                    results[code] = service.scalar_series(
                        garmin_source_id=selection["selected_source_id"],
                        metric_code=code, start_date=start, end_date=end,
                    )
            if view == "google" or selection["status"] == "selected":
                source_sleep = read_source_sleep_night(
                    session, provider=view, wake_date=end,
                    source_id=selection["selected_source_id"] if view == "garmin" else None,
                )
            google_results = [
                read_google_daily_vitals(
                    session,
                    metric_code=definition.metric_code,
                    start_date=vitals_start,
                    end_date=end,
                )
                for definition in GOOGLE_DAILY_VITALS
            ]
            google_vitals = google_vitals_view(google_results)
            google_vitals_technical = [result.as_dict() for result in google_results]
    except GarminQueryError as exc:
        return render_error(
            request, code=exc.code, message="Не удалось показать данные сна для этого выбора.",
            status_code=exc.status_code,
        )
    except SQLAlchemyError as exc:
        if not database_unavailable(exc):
            return _persist_error(request, "sleep_page")
        results = {}
        selection = {"status": "no_data", "reason": "database_unavailable", "sources": []}
        google_vitals = None
        google_vitals_technical = None
        source_sleep = None
    return render(request, "sleep.html", {
        "page": "sleep", "wake_date": end, "start_date": start,
        "sleep_view": view, "history_rows": nightly_rows(results),
        "selection": selection, "results": results, "sleep_metrics": SLEEP_METRICS,
        "night_metric": night_metric, "point_state": point_state,
        "metric_value": metric_value,
        "source_label": _brief_source_label,
        "source_sleep": source_sleep,
        "source_night_metric": source_night_metric,
        "source_sleep_primary": SOURCE_SLEEP_PRIMARY,
        "source_sleep_details": SOURCE_SLEEP_DETAILS,
        "source_sleep_value": source_sleep_value,
        "source_sleep_note": source_sleep_note,
        "source_sleep_label": source_sleep_label,
        "google_vitals": google_vitals,
        "google_vitals_technical": google_vitals_technical,
        "google_vitals_metrics": GOOGLE_VITAL_METRICS,
        "google_vitals_windows": GOOGLE_VITALS_WINDOWS,
        "google_vitals_window_days": vitals_days,
        "google_vital_source_label": google_vital_source_label,
        "google_vital_cell_state": google_vital_cell_state,
        "google_vital_value_text": google_vital_value_text,
        "google_vital_ineligible_note": google_vital_ineligible_note,
    })


def _render_sleep_timeline(
    request: Request, *, end: date, days: int, vitals_days: int
) -> HTMLResponse:
    """Primary #343 desktop view: independent 7/30 source ranges in one SSR snapshot.

    The range packets (including per-night disclosure) are embedded in the
    existing page snapshot; no separate endpoint is added. A failed refresh is
    never conflated with removed saved history.
    """

    timeline: dict[str, Any] | None = None
    timeline_technical: dict[str, Any] | None = None
    try:
        with session_scope(request_engine(request)) as session:
            ensure_read_snapshot(session)
            ranges = {
                provider: read_source_sleep_range(
                    session, provider=provider, wake_date=end, days=days
                )
                for provider in SLEEP_TIMELINE_PROVIDERS
            }
            settings = request.app.state.settings
            evaluated_at_utc = datetime.now(UTC)
            timeline = build_sleep_timeline(
                ranges,
                days=days,
                end_date=end,
                freshness=read_consumer_freshness_projection(
                    session,
                    evaluated_at_utc=evaluated_at_utc,
                    evaluation_local_date=evaluated_at_utc.astimezone().date(),
                    weight_cadence_days=settings.weight_cadence_days,
                    collection_policy=resolve_profile_collection_policy(settings),
                ),
            )
            timeline_technical = sleep_timeline_technical(timeline)
    except SQLAlchemyError as exc:
        if not database_unavailable(exc):
            return _persist_error(request, "sleep_page")
    return render(request, "sleep.html", {
        "page": "sleep", "wake_date": end, "start_date": end - timedelta(days=days - 1),
        "sleep_view": "timeline", "sleep_timeline_days": days,
        "selection": {"status": "no_data", "sources": []},
        "google_vitals_window_days": vitals_days,
        "timeline": timeline,
        "timeline_freshness": timeline["freshness"] if timeline else None,
        "timeline_technical": timeline_technical,
        "metric_value": metric_value,
    })


@router.get("/agreement", response_class=HTMLResponse)
def agreement_page(request: Request) -> HTMLResponse:
    return _render_comparison(request)


def _render_comparison(
    request: Request, *, start: date | None = None, end: date | None = None,
    vitals_days: int = 30,
) -> HTMLResponse:
    details: dict[str, Any] = {}
    try:
        with session_scope(request_engine(request)) as session:
            ensure_read_snapshot(session)
            service = SleepAgreementReportService(session)
            payload = service.report(start_date=start, end_date=end)
            for run in payload["runs"]:
                details[run["run_id"]] = service.night_detail(run["run_id"])
    except SQLAlchemyError as exc:
        if not database_unavailable(exc):
            return _persist_error(request, "agreement_report")
        payload = unavailable_report(reason="database_unavailable")
        details = {}
    except ValueError:
        return render_error(
            request, code="invalid_report_request", message="Не удалось прочитать сравнение сна.",
            status_code=400,
        )
    return render(request, "agreement.html", {
        "payload": payload, "page": "agreement", "sleep_groups": _brief_sleep_groups,
        "owner_cohort": _brief_owner_cohort, "owner_units": _BRIEF_UNIT_LABELS,
        "sleep_view": "compare", "wake_date": end, "start_date": start,
        "google_vitals_window_days": vitals_days,
        "comparison_charts": comparison_charts, "comparison_value": comparison_value,
        "comparison_details": details,
    })


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
            ensure_read_snapshot(session)
            service = PeriodBriefService(session, request.app.state.settings)
            source_selection = service.garmin.resolve_source(garmin_source_id)
            result = service.build_with_render(
                start_date=start,
                end_date=end,
                garmin_source_id=garmin_source_id,
                thin_display=True,
            )
            overview = read_overview_values(
                session, start=start, end=end,
                selected_id=source_selection.get("selected_source_id"),
            )
            charts = read_overview_charts(
                session, request.app.state.settings, packet=result["packet"],
                selected_id=source_selection.get("selected_source_id"),
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
            "brief_has_usable_evidence": _brief_has_usable_evidence(result["display"])
            or any(cell["value"] is not None for cell in overview["garmin"].values())
            or any(
                cell["latest"] is not None
                for item in overview["google"]["sources"] for cell in item["metrics"].values()
            ) or overview["training"]["status"] == "available",
            "overview": overview,
            "charts": charts,
            "metric_value": metric_value,
            "overview_number": overview_number,
            "google_vital_source_label": google_vital_source_label,
            "google_vital_cell_state": google_vital_cell_state,
            "google_vital_ineligible_note": google_vital_ineligible_note,
            "brief_owner_action": _brief_owner_action,
            "brief_owner_actions": _brief_owner_actions,
            "brief_sleep_groups": _brief_sleep_groups,
            "brief_primary_facts": _brief_primary_facts,
            "brief_owner_activity": _brief_owner_activity,
            "brief_owner_cohort": _brief_owner_cohort,
            "brief_owner_fact": _brief_owner_fact,
            "brief_owner_note": _brief_owner_note,
            "brief_note_value": _brief_note_value,
            "brief_owner_reason": _brief_owner_reason,
            "brief_owner_state": _brief_owner_state,
            "brief_owner_uncertainty": _brief_owner_uncertainty,
            "brief_owner_value": _brief_owner_value,
            "brief_notable_changes": _brief_notable_changes,
            "brief_coverage_warning": _brief_coverage_warning,
            "brief_source_status": _brief_source_status,
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
    queue_available = True
    history = []
    try:
        with session_scope(request_engine(request)) as session:
            service = PhotoImportService(
                session, request.app.state.runtime_paths, _extractor(request)
            )
            queue = WeightQueryService(session, request.app.state.settings).import_queue_summary()
            # The queue expires cached ORM state and reloads only 50 batches.
            # Load the 100-row history afterwards in the same read snapshot so
            # every batch remains available when rendered outside the session.
            batches = service.list_batches()
            pending_counts = dict(
                session.execute(
                    select(IngestEvent.ingest_batch_id, func.count(ImportCandidate.id))
                    .join(ImportCandidate, ImportCandidate.ingest_event_id == IngestEvent.id)
                    .where(
                        IngestEvent.ingest_batch_id.in_([batch.id for batch in batches]),
                        ImportCandidate.user_decision == "pending",
                    )
                    .group_by(IngestEvent.ingest_batch_id)
                ).all()
            )
            for batch in batches:
                pending = pending_counts.get(batch.id, 0)
                history.append(
                    {
                        "batch": batch,
                        "pending": pending,
                        "started_at": restore_stored_utc(batch.started_at),
                        "action_required": pending > 0
                        or batch.failed_count is None
                        or batch.failed_count > 0
                        or batch.status not in {"committed", "rejected", "duplicate"},
                    }
                )
    except SQLAlchemyError as exc:
        if not database_unavailable(exc):
            return _persist_error(request, "imports")
        batches = []
        queue_available = False
        queue = empty_dashboard_payload(reason="database_unavailable")["imports"]
    return render(
        request,
        "imports.html",
        {
            "batches": batches,
            "queue": queue,
            "queue_available": queue_available,
            "action_imports": sorted(
                (row for row in history if row["action_required"]),
                key=lambda row: not bool(row["pending"]),
            ),
            "completed_imports": [row for row in history if not row["action_required"]],
            "photo_extraction_configured": not isinstance(
                _extractor(request), UnconfiguredImageMeasurementExtractor
            ),
            "page": "imports",
        },
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
