"""Display formatting only; retain source date/time precision and timezone."""

from datetime import date, datetime, timedelta
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


def owner_date(value: object) -> str:
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
        offset = parsed.utcoffset()
        if offset is not None:
            text += " UTC" if offset == timedelta(0) else f" UTC{parsed:%z}"
    return text


def owner_number(value: object) -> str:
    """One decimal for Owner activity numbers; zero and missing stay distinct."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
        return f"{value:.1f}"
    return "Не предоставлено"
