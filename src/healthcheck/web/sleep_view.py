"""Owner sleep presentation over existing Garmin scalar results; no analytics.

The Google daily-vitals block is a read-only presentation of the frozen R297
source-explicit projection (``healthcheck.google.daily_vitals``).  It never
pools Garmin and Google values, never picks a canonical source and never
reinterprets persisted states.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from math import isfinite
from typing import Any

from healthcheck.google.contracts import (
    FAMILY_ALL_SOURCES,
    FAMILY_GOOGLE_SOURCES,
    FAMILY_GOOGLE_WEARABLES,
)
from healthcheck.google.daily_vitals import (
    GOOGLE_DAILY_VITALS_CONTRACT_VERSION,
    GoogleDailyVitalPoint,
    GoogleDailyVitalSource,
    GoogleDailyVitalsResult,
)

SLEEP_METRICS = {
    "sleep_duration_seconds": ("Длительность сна", "с"),
    "sleep_score": ("Оценка сна Garmin", "баллы"),
}

GOOGLE_VITALS_DEFAULT_WINDOW_DAYS = 30
GOOGLE_VITALS_WINDOWS = (7, 30, 90)
GOOGLE_VITAL_METRICS: tuple[tuple[str, str, str], ...] = (
    ("daily_hrv_average_ms", "Вариабельность пульса (HRV)", "мс"),
    ("daily_resting_heart_rate_bpm", "Пульс в покое", "уд/мин"),
    ("daily_oxygen_saturation_average_percentage", "Кислород в крови", "%"),
    ("daily_respiratory_rate_breaths_per_minute", "Частота дыхания", "вдохов/мин"),
)

# Mirrors healthcheck.google.sync.UNATTRIBUTED_SOURCE_INSTANCE without
# importing the provider-sync layer into the read/presentation path.
_UNATTRIBUTED_SOURCE_INSTANCE = "unattributed"

_FAMILY_LABELS = {
    FAMILY_GOOGLE_WEARABLES: "Google · семейство устройств",
    FAMILY_GOOGLE_SOURCES: "Google · источники Google",
    FAMILY_ALL_SOURCES: "Google · все источники",
}


def google_vitals_window_days(value: str | None) -> int:
    """Accept only the frozen 7/30/90-day Owner windows; default is 30."""

    if value is None:
        return GOOGLE_VITALS_DEFAULT_WINDOW_DAYS
    try:
        days = int(value)
    except (TypeError, ValueError):
        return GOOGLE_VITALS_DEFAULT_WINDOW_DAYS
    return days if days in GOOGLE_VITALS_WINDOWS else GOOGLE_VITALS_DEFAULT_WINDOW_DAYS


def _friendly_source_name(value: str) -> str | None:
    """Return a human-readable dataSource tail or None for URI/id-shaped names."""

    tail = value.rsplit("/", 1)[-1].strip()
    if not tail or ":" in tail:
        return None
    return tail


def google_vital_source_label(source: GoogleDailyVitalSource) -> str:
    """Owner-friendly source label; exact identity stays in disclosure."""

    if source.source_kind == "family_aggregate":
        return _FAMILY_LABELS.get(
            source.source_instance_id,
            "Google · семейство источников",
        )
    if source.device_attributed:
        manufacturer = source.device_manufacturer or ""
        model = source.device_model or ""
        if manufacturer and model and not model.lower().startswith(manufacturer.lower()):
            device = f"{manufacturer} {model}"
        else:
            device = model or source.device_code or manufacturer
        return f"Google · {device or 'устройство'}"
    friendly_name = (
        _friendly_source_name(source.data_source_name) if source.data_source_name else None
    )
    if friendly_name:
        return f"Google · {friendly_name}"
    if source.platform:
        return f"Google · {source.platform}"
    if source.source_instance_id == _UNATTRIBUTED_SOURCE_INSTANCE:
        return "Google · источник без атрибуции"
    return "Google · источник данных"


def google_vital_owner_state(point: GoogleDailyVitalPoint | None) -> str:
    """Map the frozen point state to the shared Owner state vocabulary."""

    if point is None:
        return "unknown"
    if point.eligible:
        return "present"
    if point.state == "ambiguous":
        return "unknown"
    return "unavailable"


def google_vital_value_text(point: GoogleDailyVitalPoint) -> str:
    """Format one eligible number without rounding or inventing units."""

    number = point.value
    if number is None:
        return "—"
    if float(number).is_integer():
        return str(int(number))
    return str(number)


_GOOGLE_VITAL_EXCLUSION_NOTES = {
    "metric_row_missing": "За эту дату нет записи показателя.",
    "metric_state_missing": "Источник не передал значение за эту дату.",
    "metric_state_null": "Источник передал пустое значение за эту дату.",
    "metric_state_invalid": "Запись показателя непригодна.",
    "metric_value_invalid": "Запись содержит непригодное число.",
    "metric_unit_mismatch": "Единица измерения записи не совпадает с ожидаемой.",
}


def google_vital_ineligible_note(point: GoogleDailyVitalPoint) -> str:
    """Owner-facing explanation for one ineligible (non-ambiguous) point."""

    return _GOOGLE_VITAL_EXCLUSION_NOTES.get(
        point.exclusion_basis or "",
        "Значение непригодно для показа; подробности в технических деталях.",
    )


def google_vitals_view(
    results: Sequence[GoogleDailyVitalsResult],
) -> dict[str, Any]:
    """Merge per-metric results for presentation, keeping every source separate.

    Metrics are merged only within one ``google_sources.id``; sources are never
    collapsed into a single Google value.  Each cell keeps the newest point
    (state honesty) and the latest eligible point (the displayed value).
    """

    by_source: dict[str, dict[str, Any]] = {}
    for result in results:
        for source in result.sources:
            item = by_source.setdefault(
                source.source_id, {"source": source, "metrics": {}}
            )
            newest = source.points[-1] if source.points else None
            item["metrics"][result.metric_code] = {
                "latest": source.latest,
                "newest": newest,
            }
    sources = sorted(
        by_source.values(),
        key=lambda item: (
            item["source"].source_kind,
            item["source"].source_instance_id,
            item["source"].source_id,
        ),
    )
    return {
        "contract_version": GOOGLE_DAILY_VITALS_CONTRACT_VERSION,
        "start_date": results[0].start_date if results else None,
        "end_date": results[0].end_date if results else None,
        "window_state": "records_in_window" if sources else "no_current_record_in_window",
        "sources": sources,
    }


def google_vital_cell_state(cell: Mapping[str, Any] | None) -> str:
    """Owner state for one merged metric cell (value or newest stored state)."""

    if not cell:
        return "unknown"
    latest = cell.get("latest")
    if latest is not None and latest.eligible:
        return "present"
    newest = cell.get("newest")
    if newest is None:
        return "unknown"
    return google_vital_owner_state(newest)



def metric_value(code: str, number: int | float) -> str:
    """Format whole seconds as hours/minutes without rounding or new metrics."""
    if code == "sleep_duration_seconds" and number >= 0 and float(number).is_integer():
        hours, remainder = divmod(int(number), 3600)
        minutes, seconds = divmod(remainder, 60)
        text = f"{hours} ч {minutes} мин"
        return f"{text} {seconds} с" if seconds else text
    return f"{number} {SLEEP_METRICS[code][1]}"


def point_state(point: Mapping[str, Any] | None) -> str:
    if point is None:
        return "unavailable"
    status = point.get("status")
    number = point.get("value")
    if status in {"usable", "zero", "partial"}:
        if isinstance(number, (int, float)) and not isinstance(number, bool) and isfinite(number):
            return "partial" if status == "partial" else "present"
        return "unknown"
    if status in {"missing", "null", "excluded", "invalid", "not_computable"}:
        return "unavailable"
    return "unknown"


def night_metric(result: Mapping[str, Any], wake_date: date) -> dict[str, Any]:
    """Never borrow a previous night or combine multiple session values."""
    points = [
        point
        for point in result.get("points", [])
        if point.get("analytic_date") == wake_date.isoformat()
    ]
    if len(points) > 1:
        return {"state": "unknown", "value": None, "ambiguous": True}
    point = points[0] if points else None
    state = point_state(point)
    return {
        "state": state,
        "value": point["value"] if state in {"present", "partial"} else None,
        "ambiguous": False,
    }
