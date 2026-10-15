"""Selected-day Overview presentation over the accepted #357 reader."""

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from healthcheck.analytics.stress_baseline import (
    ARITHMETIC_MEAN_COMPARISON,
    MEAN_CONTRACT_VERSION,
    MOSCOW_ANALYSIS_DAY_POLICY,
)
from healthcheck.config import Settings
from healthcheck.garmin.analytic_contract import coerce_selected_number
from healthcheck.web.garmin_query import GarminQueryService
from healthcheck.web.overview_view import overview_number

_REASONS = {
    "source_selection_required": "Выберите источник Garmin.",
    "selected_garmin_source_not_found": "Сохранённый источник Garmin не найден.",
    "selected_day_not_uniquely_usable": "За выбранную дату нет однозначного пригодного значения.",
    "insufficient_eligible_history": "Нужно не менее 21 пригодного дня истории из 28.",
    "participating_metric_partial": "В дневных данных есть пропуски или неполные значения.",
    "acquisition_before_analysis_day_end": "Данные одного из дней получены до окончания суток.",
    "acquisition_before_source_day_end": "Данные одного из дней получены до окончания суток.",
    "selected_points_exceed_max": "Достигнут лимит сохранённых записей для сравнения.",
    "daily_participant_bound_exceeded": "Достигнут лимит дневных записей для сравнения.",
    "referenced_artifact_exceeds_byte_bound": "Достигнут лимит размера исходных данных.",
    "frozen_baseline_sample_mismatch": "Состав дневной истории не подтверждён.",
    "r03_statistics_nonfinite": "Среднее по этой истории вычислить не удалось.",
    "frozen_baseline_mean_nonfinite": "Среднее по этой истории вычислить не удалось.",
    "comparison_delta_nonfinite": "Разницу со средним вычислить не удалось.",
}


def _reason_text(reason: str | None) -> str:
    if reason in _REASONS:
        return _REASONS[reason]
    if reason and any(part in reason for part in ("timezone", "clock", "date", "day_end")):
        return "Не удалось подтвердить даты и время дневных данных."
    if reason and any(part in reason for part in ("method", "unit", "attribution")):
        return "Источник, единицы или способ измерения не подтверждены для сравнения."
    return "Не удалось подтвердить исходные дневные данные для сравнения."


def _delta_text(delta: int | float, direction: str) -> str:
    if direction == "equal":
        return "Совпадает со средним"
    direction_text = "выше" if direction == "above" else "ниже"
    if abs(delta) < 0.01:
        return f"Менее чем на 0,01 балла {direction_text} среднего"
    return f"На {overview_number(abs(delta))} балл. {direction_text} среднего"


def read_overview_stress(
    session: Session,
    settings: Settings,
    *,
    selected_date: date,
    garmin_source_id: str | None,
    evaluated_at_utc: datetime,
) -> dict:
    """D is the page's selected end date; the reader owns the independent history."""
    if selected_date < date.min + timedelta(days=28):
        return {
            "current": {
                "state": "unavailable",
                "value": None,
                "date": selected_date.isoformat(),
                "note": None,
            },
            "comparison_state": "unavailable",
            "mean_display": None,
            "delta_text": None,
            "reason": "Для этой даты нельзя построить предыдущие 28 дней.",
            "history_start": None,
            "history_end": None,
            "observed_days": None,
            "result_hash": None,
        }
    result = GarminQueryService(session, settings).stress_baseline(
        garmin_source_id=garmin_source_id,
        selected_date=selected_date,
        evaluated_at=evaluated_at_utc,
        analysis_day_policy=MOSCOW_ANALYSIS_DAY_POLICY,
        comparison_method=ARITHMETIC_MEAN_COMPARISON,
    )
    current, comparison, history = result["current"], result["comparison"], result["history"]
    value = coerce_selected_number(current["value"]) if current["unit"] == "points" else None
    if current["status"] not in {"usable", "zero", "partial"}:
        value = None
    available = (
        result["contract_version"] == MEAN_CONTRACT_VERSION
        and result.get("comparison_method") == ARITHMETIC_MEAN_COMPARISON
        and result.get("analysis_day_policy", {}).get("version") == MOSCOW_ANALYSIS_DAY_POLICY
        and comparison["status"] == "available"
        and coerce_selected_number(comparison.get("mean")) is not None
        and coerce_selected_number(comparison["delta_points"]) is not None
    )
    return {
        "current": {
            "state": "partial"
            if value is not None and current["status"] == "partial"
            else "present"
            if value is not None
            else "unavailable",
            "value": value,
            "date": result["selected_date"],
            "note": None,
        },
        "comparison_state": "available"
        if available
        else "unavailable"
        if comparison["status"] == "available"
        else comparison["status"],
        "mean_display": overview_number(comparison["mean"]) if available else None,
        "delta_text": _delta_text(comparison["delta_points"], comparison["direction"])
        if available
        else None,
        "reason": None if available else _reason_text(comparison["reason"]),
        "history_start": history["start_date"],
        "history_end": history["end_date"],
        "observed_days": history["observed_nonpartial_days"]
        if "history" in result["evidence"]
        else None,
        "result_hash": result["result_hash"],
    }
