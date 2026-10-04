"""Owner sleep presentation over existing Garmin scalar results; no analytics."""

from collections.abc import Mapping
from datetime import date
from math import isfinite
from typing import Any

SLEEP_METRICS = {
    "sleep_duration_seconds": ("Длительность сна", "с"),
    "sleep_score": ("Оценка сна Garmin", "баллы"),
}


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
