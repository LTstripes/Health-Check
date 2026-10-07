"""Read-only Owner charts over frozen Agreement packets, never new pairing/statistics."""

from collections import Counter, defaultdict
from datetime import date, datetime
from math import isfinite
from typing import Any

from healthcheck.analytics.sleep_metrics import SLEEP_METRIC_DEFINITIONS
from healthcheck.web.owner_presentation import owner_date, owner_number


def comparison_value(value: object, unit: str | None, *, signed: bool = False) -> str:
    if unit not in {"seconds", "bpm", "percentage_points", "%"}:
        return "—"
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value):
        return "—"
    if unit == "seconds":
        # Presentation rounding only. Frozen seconds are retained in disclosure.
        seconds = round(abs(value))
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        parts = ([f"{hours} ч"] if hours else []) + ([f"{minutes} мин"] if minutes else [])
        if seconds or not parts:
            parts.append(f"{seconds} с")
        return ("−" if value < 0 else "+" if signed and value > 0 else "") + " ".join(parts)
    label = {"bpm": "уд/мин", "percentage_points": "п.п.", "%": "%"}.get(unit, "")
    return ("+" if signed and value > 0 else "") + owner_number(value) + f" {label}"


def _chart_number(value: object, unit: str) -> float | None:
    if unit == "UTC instant":
        try:
            instant = datetime.fromisoformat(str(value))
            return instant.timestamp() if instant.utcoffset() is not None else None
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
        return float(value)
    return None


def comparison_charts(group: dict[str, Any], detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Use only accepted paired dates and comparable immutable same-unit sides.

    Keep run, cohort, variant, source identities and normalization bases separate.
    Unknown attribution/variants are inspectable, but do not become device overlays.
    Duplicate same-date inputs fail closed rather than selecting one or averaging.
    """
    definition = SLEEP_METRIC_DEFINITIONS.get(group["metric_code"])
    if definition is None or group["variant"] not in definition.variants:
        return []
    if group["cohort"] not in {"device_pair", "family_pair"}:
        return []
    accepted = {point["wake_date"]: point["difference"] for point in group["chart"]["points"]}
    buckets: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for night in detail.get("nights", []):
        day = night["wake_date"]
        if night["cohort"] != group["cohort"] or day not in accepted:
            continue
        try:
            date.fromisoformat(day)
        except ValueError:
            continue
        for metric in night["metrics"]:
            if (
                metric["metric_code"] != group["metric_code"]
                or metric["variant"] != group["variant"]
                or metric["status"] != "comparable"
                or metric["comparable"] is not True
                or metric["difference"] != accepted[day]
                or metric["difference_unit"] != definition.difference_unit
            ):
                continue
            sides = [metric[provider] for provider in ("garmin", "google")]
            if any(
                side.get("eligible") is not True
                or side.get("unit") != definition.unit
                or side.get("evidence", {}).get("immutable") is not True
                or not side.get("evidence", {}).get("source_id")
                or not side.get("comparison_basis")
                for side in sides
            ):
                continue
            if definition.comparison_kind == "auxiliary_overlay" and any(
                side["comparison_basis"] != "own_daily_record" for side in sides
            ):
                continue
            numbers = [_chart_number(side.get("value"), definition.unit) for side in sides]
            if None in numbers:
                continue
            key = tuple(
                str(value)
                for side in sides
                for value in (side["evidence"]["source_id"], side["comparison_basis"])
            )
            buckets[key].append({
                "wake_date": day, "garmin": numbers[0], "google": numbers[1],
                "garmin_text": (
                    owner_date(sides[0]["value"]) if definition.unit == "UTC instant"
                    else comparison_value(numbers[0], definition.unit)
                ),
                "google_text": (
                    owner_date(sides[1]["value"]) if definition.unit == "UTC instant"
                    else comparison_value(numbers[1], definition.unit)
                ),
            })
    charts = []
    for identity, points in sorted(buckets.items()):
        counts = Counter(point["wake_date"] for point in points)
        unique = sorted(
            (point for point in points if counts[point["wake_date"]] == 1),
            key=lambda point: point["wake_date"],
        )
        if unique:
            charts.append({
                "identity": identity, "points": unique,
                "unit": definition.unit,
                "axis_unit": {"seconds": "ч", "UTC instant": "Дата и время UTC",
                              "bpm": "уд/мин", "%": "%"}[definition.unit],
            })
    return charts
