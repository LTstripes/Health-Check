"""Display formatting only; retain source date/time precision and timezone."""

import re
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
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
    """Minutes for display only; preserve true zero and positive sub-minute values."""
    number = _nonnegative(value)
    if number is None:
        return "Недоступно"
    with localcontext(_display_context(number)):
        if number >= Decimal("3.6e12"):
            return _compact_unit(number / 3600, "ч")
        if 0 < number < 60:
            return "<1 мин"
        minutes = (number / 60).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        hours, minutes = divmod(minutes, 60)
    return (f"{int(hours)} ч " if hours else "") + f"{int(minutes)} мин"


_ACTIVITY_NAMES = {
    "cycling": "Велосипед", "running": "Бег", "walking": "Ходьба",
    "swimming": "Плавание", "strength_training": "Силовая тренировка",
    "tennis": "Теннис", "tennis_v2": "Теннис",
}


def owner_activity_type(value: object) -> str:
    """Presentation aliases only; never classify or change persisted activity types."""
    return _ACTIVITY_NAMES.get(value, "Другой вид активности") if isinstance(value, str) else (
        "Вид активности не указан")


def owner_activity_count(value: object) -> str:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return "Количество тренировок недоступно"
    last, last_two = value % 10, value % 100
    word = "тренировок" if 11 <= last_two <= 14 else (
        "тренировка" if last == 1 else "тренировки" if 2 <= last <= 4 else "тренировок")
    return f"{value} {word}"


def owner_activity_types(counts: object) -> str:
    """A compact composition; aliases share a label, exact codes remain in details."""
    if not isinstance(counts, dict):
        return "Состав тренировок недоступен"
    labels = dict.fromkeys(owner_activity_type(code).lower() for code, count in counts.items()
                           if isinstance(count, int) and not isinstance(count, bool) and count > 0)
    return ", ".join(labels) or "Нет сохранённых видов активности"


def owner_distance(value: object) -> str:
    """Native metres in, kilometres for display only (including tiny positives)."""
    number = _nonnegative(value)
    if number is None:
        return "Недоступно"
    with localcontext(_display_context(number)):
        if number >= Decimal("1e12"):
            return _compact_unit(number / 1000, "км")
        km = (number / 1000).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if number > 0 and km == 0:
            return "<0,01 км"
    return f"{_decimal_text(km)} км"


def _nonnegative(value: object) -> Decimal | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if (isinstance(value, float) and not isfinite(value)) or value < 0:
        return None
    return Decimal(value) if isinstance(value, int) else Decimal(str(value))


def _display_context(number: Decimal) -> Context:
    # Own display context: enough integer + fractional digits, no caller precision leak.
    return Context(prec=max(28, number.adjusted() + 6), rounding=ROUND_HALF_UP)


def _compact_unit(number: Decimal, unit: str) -> str:
    """Bound extreme label length; explicit approximation, exact native value in details."""
    coefficient, exponent = format(number, ".2E").split("E")
    coefficient = coefficient.rstrip("0").rstrip(".").replace(".", ",")
    return f"≈{coefficient} × 10^{int(exponent)} {unit}"


def _decimal_text(value: Decimal) -> str:
    return format(value, "f").rstrip("0").rstrip(".").replace(".", ",") or "0"


def owner_number(value: object) -> str:
    """One decimal for Owner activity numbers; zero and missing stay distinct."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
        return f"{value:.1f}"
    return "Не предоставлено"
