"""Display formatting only; retain source date/time precision and timezone."""

import re
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from math import isfinite

_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def owner_date(value: object, precision: str | None = None) -> str:
    """Humanize ISO dates, wall times and offset timestamps without conversion."""
    if not value:
        return "Дата не указана"
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, date):
            parsed = value
        elif len(str(value)) == 10:
            parsed = date.fromisoformat(str(value))
        else:
            parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return "Дата не указана"
    text = f"{parsed.day} {_MONTHS[parsed.month - 1]} {parsed.year}"
    if isinstance(parsed, datetime):
        text += f", {parsed:%H:%M}"
        if precision in {"second", "microsecond", "source"}:
            # Source strings retain even explicit zero seconds/fraction digits.
            clock = re.search(r"[T ]\d{2}:\d{2}(:\d{2}(?:[.,]\d+)?)?", str(value))
            if clock and clock[1] and not isinstance(value, datetime):
                text += clock[1]
            elif precision in {"second", "microsecond"}:
                text += f":{parsed.second:02d}"
                if precision == "microsecond":
                    text += f".{parsed.microsecond:06d}"
        offset = parsed.utcoffset()
        if offset is not None:
            text += " UTC" if offset == timedelta(0) else f" UTC{parsed:%z}"
    return text


def owner_duration(value: object) -> str:
    """Reuse Statistics' display rounding; positive sub-minute values stay visible."""
    number = _nonnegative(value)
    if number is None:
        return "Недоступно"
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
        parts.append(f"{_decimal_text(seconds)} с")
    return " ".join(parts)


def owner_distance(value: object) -> str:
    """Native metres in, kilometres for display only (including tiny positives)."""
    number = _nonnegative(value)
    if number is None:
        return "Недоступно"
    km = (number / 1000).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if number > 0 and km == 0:
        return "<0,01 км"
    return f"{_decimal_text(km)} км"


def _nonnegative(value: object) -> Decimal | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if not isfinite(value) or value < 0:
        return None
    return Decimal(str(value))


def _decimal_text(value: Decimal) -> str:
    return format(value, "f").rstrip("0").rstrip(".").replace(".", ",") or "0"


def owner_number(value: object) -> str:
    """One decimal for Owner activity numbers; zero and missing stay distinct."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
        return f"{value:.1f}"
    return "Не предоставлено"
