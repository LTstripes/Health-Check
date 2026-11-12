"""Display formatting only; retain source date/time precision and timezone."""

import re
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
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
_SHORT_MONTHS = ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")


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
        if offset is not None and (
            offset != timedelta(hours=3) or precision in {"second", "microsecond", "source"}
        ):
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
    return (f"{int(hours)} ч {int(minutes):02d} мин" if hours else f"{int(minutes)} мин")


ACTIVITY_NAMES = {
    "cycling": "Велосипед", "running": "Бег", "walking": "Ходьба",
    "swimming": "Плавание", "strength_training": "Силовая тренировка",
    "tennis": "Теннис", "tennis_v2": "Теннис",
    "soccer": "Футбол", "football": "Футбол",
}


def owner_activity_type(value: object) -> str:
    """Presentation aliases only; never classify or change persisted activity types."""
    return ACTIVITY_NAMES.get(value, "Другой вид активности") if isinstance(value, str) else (
        "Вид активности не указан")


def owner_activity_count(value: object) -> str:
    if (not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0
            or isinstance(value, float) and (not isfinite(value) or not value.is_integer())):
        return "Количество тренировок недоступно"
    value = int(value)
    word = owner_plural(value, 'тренировка', 'тренировки', 'тренировок')
    return f"{owner_number(value, 0)} {word}"


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


def owner_number(value: object, digits: int = 1) -> str:
    """Localize the displayed number only, retaining the existing formatting rounding."""
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        if (isinstance(value, float) and not isfinite(value)
                or isinstance(value, Decimal) and not value.is_finite()):
            return "Не предоставлено"
        text = format(value, f",.{digits}f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        if text == "-0":
            text = "0"
        return text.replace(",", "\u202f").replace(".", ",").replace("-", "−")
    return "Не предоставлено"


def owner_signed_number(value: object, digits: int = 1) -> str:
    text = owner_number(value, digits)
    positive = text not in {"0", "Не предоставлено"} and not text.startswith("−")
    return "+" + text if positive else text


def owner_plural(n: object, one: str, few: str, many: str) -> str:
    """Russian word form, including negatives, teens and fractional counts."""
    if not isinstance(n, (int, float, Decimal)) or isinstance(n, bool):
        return many
    number = Decimal(str(n)).copy_abs()
    if not number.is_finite():
        return many
    if number != number.to_integral_value():
        return few
    last, last_two = int(number % 10), int(number % 100)
    return many if 11 <= last_two <= 14 else one if last == 1 else few if 2 <= last <= 4 else many


def owner_short_date(value: object, year: bool = False) -> str:
    try:
        if isinstance(value, date):
            parsed = value
        else:
            text = str(value)
            parsed = date.fromisoformat(text) if len(text) == 10 else datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return "Дата не указана"
    return f"{parsed.day} {_SHORT_MONTHS[parsed.month - 1]}" + (f" {parsed.year}" if year else "")


def owner_date_range(start: object, end: object, year: bool = False) -> str:
    different_years = str(start)[:4] != str(end)[:4]
    first = owner_short_date(start, different_years)
    return f"{first} — {owner_short_date(end, year or different_years)}"


def owner_time(value: object) -> str:
    """Retain source wall time; show an offset only outside Moscow."""
    try:
        if isinstance(value, (datetime, time)):
            parsed = value
        else:
            parsed = (datetime.fromisoformat(str(value)) if "T" in str(value)
                      or " " in str(value) else time.fromisoformat(str(value)))
    except (TypeError, ValueError):
        return "Время не указано"
    text = f"{parsed:%H:%M}"
    if parsed.utcoffset() not in {None, timedelta(hours=3)}:
        text += " UTC" if parsed.utcoffset() == timedelta(0) else f" UTC{parsed:%z}"
    return text


def owner_datetime_text(value: str) -> str:
    """Display an already-read event interval; never modify the source packet."""
    return " → ".join(owner_date(part.strip()) for part in value.split("→"))


def owner_decimal(value: object, digits: int = 2) -> str:
    """Localize an existing typed decimal string without parsing a raw lab result."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "Не предоставлено"
    return owner_number(number, digits)


def owner_lab_result(row: dict) -> str:
    """Format typed lab decimals; qualitative/unparsed source text stays literal."""
    if row.get("decimal") is not None and row.get("value_kind") == "numeric":
        text = str(row["decimal"])
        digits = len(text.partition(".")[2])
        return (row.get("comparator") or "") + owner_decimal(text, digits)
    return row.get("result_raw") or "—"


def owner_distance_cell(value: object) -> str:
    """Same native-metre rounding as the card; unit belongs to the table header."""
    return owner_distance(value).removesuffix(" км")


def register_owner_filters(env: object) -> None:
    env.filters.update({name: value for name, value in globals().items()
                        if name.startswith("owner_") and callable(value)})
