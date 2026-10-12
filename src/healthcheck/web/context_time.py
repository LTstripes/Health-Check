"""Local clock input adapter; Context v0 remains the canonical validator."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from healthcheck.context import ContextValidationError

_LOCAL = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?$")
_SOURCE = re.compile(r"^([^T]+)T(.+?)(Z|[+-]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)$")
_CITY_NAMES = {
    "Europe/Moscow": "Москва",
    "Europe/London": "Лондон",
    "Europe/Berlin": "Берлин",
    "Europe/Paris": "Париж",
    "America/New_York": "Нью-Йорк",
    "Asia/Tokyo": "Токио",
    "Asia/Dubai": "Дубай",
    "UTC": "Всемирное время",
}


@lru_cache(maxsize=1)
def zone_choices() -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (
                (key, f"{_CITY_NAMES.get(key, key.rsplit('/', 1)[-1].replace('_', ' '))} — {key}")
                for key in available_timezones()
            ),
            key=lambda item: item[1].casefold(),
        )
    )


def source_parts(timestamp: str) -> tuple[str, str, str]:
    match = _SOURCE.fullmatch(timestamp)
    if match is None:
        raise ContextValidationError("unsupported source representation")
    return match.groups()


def occurrences(day: str, clock: str, zone_name: str) -> tuple[tuple[str, str], ...]:
    """Return distinct valid instants in chronological order, never round offsets."""
    local = f"{day}T{clock}"
    if not _LOCAL.fullmatch(local):
        raise ContextValidationError("invalid local clock")
    try:
        naive = datetime.fromisoformat(local)
        zone = ZoneInfo(zone_name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ContextValidationError("invalid local clock or zone") from exc
    candidates = {}
    for fold in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=fold)
        try:
            instant = aware.astimezone(UTC)
            restored = instant.astimezone(zone)
        except (ValueError, OverflowError) as exc:
            raise ContextValidationError("unsupported calendar boundary") from exc
        if restored.replace(tzinfo=None) != naive:
            continue
        seconds = int(aware.utcoffset().total_seconds())
        if seconds % 60:
            raise ContextValidationError("historical second offset is unsupported by v0")
        minutes = abs(seconds) // 60
        offset = f"{'+' if seconds >= 0 else '-'}{minutes // 60:02}:{minutes % 60:02}"
        candidates[instant] = offset
    if not candidates:
        raise ContextValidationError("nonexistent local clock")
    return tuple(zip(("first", "second"), (candidates[key] for key in sorted(candidates))))


def fold_choices(form: dict[str, str]) -> dict[str, tuple[tuple[str, str], ...]]:
    result = {}
    for prefix in ("", "end_"):
        day = form.get("event_date" if not prefix else "end_date", "")
        clock = form.get("event_time" if not prefix else "end_time", "")
        if not day or not clock or not form.get("timezone_name"):
            continue
        try:
            choices = occurrences(day, clock, form["timezone_name"])
        except ContextValidationError:
            continue
        if len(choices) == 2:
            result[prefix + "occurrence"] = choices
    return result


def resolve_timestamp(day: str, clock: str, zone: str, occurrence: str) -> str:
    choices = occurrences(day, clock, zone)
    if len(choices) == 2:
        if occurrence not in dict(choices):
            raise ContextValidationError("explicit occurrence required")
        offset = dict(choices)[occurrence]
    else:
        if occurrence:
            raise ContextValidationError("occurrence only applies to a repeated clock")
        offset = choices[0][1]
    return f"{day}T{clock}{offset}"
