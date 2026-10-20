"""Shared semantic identities for Google typed projections."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from healthcheck.db.repositories import canonical_json


def google_steps_interval_key(interval: Any) -> str:
    """Key exact raw civil endpoint objects; never infer UTC or a day label."""
    if (
        _value(getattr(interval, "interval_kind", None)) != "daily_roll_up"
        or _value(getattr(interval, "state", getattr(interval, "interval_state", None))) != "value"
    ):
        raise ValueError("Steps requires a valid daily civil interval")
    endpoints = {}
    order = []
    for name in ("start", "end"):
        endpoint = getattr(interval, name, None)
        raw = getattr(endpoint, "raw_civil_json", None)
        if endpoint is None:
            evidence = json.loads(getattr(interval, f"{name}_temporal_json"))
            raw = evidence.get("raw_civil_json")
        if not isinstance(raw, str) or not isinstance(json.loads(raw), dict):
            raise ValueError("Steps interval requires raw civil endpoint objects")
        if canonical_json(json.loads(raw)) != raw:
            raise ValueError("Steps raw civil JSON must be canonical and unambiguous")
        day, wall, key = parse_steps_civil_endpoint(json.loads(raw))
        order.append(key)
        if endpoint is not None:
            precision, state = _value(endpoint.precision), _value(endpoint.state)
            local_day, local_wall, at_utc = (
                endpoint.local_date,
                endpoint.local_wall_time,
                endpoint.measured_at_utc,
            )
            zone, offset = endpoint.source_timezone, endpoint.source_utc_offset_minutes
        else:
            precision, state = (
                getattr(interval, f"{name}_precision"),
                getattr(interval, f"{name}_state"),
            )
            local_day, local_wall, at_utc = (
                getattr(interval, f"{name}_local_date"),
                getattr(interval, f"{name}_local_wall_time"),
                getattr(interval, f"{name}_at_utc"),
            )
            zone, offset = (
                getattr(interval, f"{name}_source_timezone"),
                getattr(interval, f"{name}_utc_offset_minutes"),
            )
        if (
            precision != "local"
            or state != "value"
            or local_day != day
            or local_wall != wall
            or at_utc is not None
            or zone is not None
            or offset is not None
        ):
            raise ValueError("Steps civil endpoint disagrees with raw evidence")
        endpoints[name] = canonical_json(json.loads(raw))
    if order[0] >= order[1]:
        raise ValueError("Steps civil interval must be strictly ordered")
    digest = hashlib.sha256(canonical_json(endpoints).encode()).hexdigest()
    return f"google-steps-interval-v1:{digest}"


def parse_steps_civil_endpoint(raw: object) -> tuple[date, str, tuple[int, ...]]:
    """Validate one bounded CivilDateTime without inventing an instant."""
    if not isinstance(raw, Mapping) or set(raw) - {"date", "time"}:
        raise ValueError("Steps requires a CivilDateTime object")
    day, clock = raw.get("date"), raw.get("time", {})
    if not isinstance(day, Mapping) or set(day) != {"year", "month", "day"}:
        raise ValueError("Steps requires a complete civil date")
    if not isinstance(clock, Mapping) or set(clock) - {"hours", "minutes", "seconds", "nanos"}:
        raise ValueError("Steps has an invalid civil time")
    values = []
    for container, key, lower, upper in (
        (day, "year", 1, 9999),
        (day, "month", 1, 12),
        (day, "day", 1, 31),
        (clock, "hours", 0, 23),
        (clock, "minutes", 0, 59),
        (clock, "seconds", 0, 59),
        (clock, "nanos", 0, 999999999),
    ):
        value = container.get(key, 0)
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError("Steps has an invalid civil component")
        values.append(value)
    year, month, day_number, hour, minute, second, nanos = values
    civil_day = date(year, month, day_number)
    fraction = f".{nanos:09d}".rstrip("0") if nanos else ""
    wall = f"{civil_day.isoformat()}T{hour:02d}:{minute:02d}:{second:02d}{fraction}"
    return civil_day, wall, tuple(values)


def canonical_google_interval_identity(interval: Any) -> dict[str, object]:
    """Return one path-free identity for DTO or persisted HR intervals."""

    start = getattr(interval, "start", None)
    end = getattr(interval, "end", None)
    return {
        "kind": _value(getattr(interval, "interval_kind")),
        "start": _endpoint(
            precision=_value(
                getattr(start, "precision", getattr(interval, "start_precision", None))
            ),
            state=_value(getattr(start, "state", getattr(interval, "start_state", None))),
            at_utc=getattr(start, "measured_at_utc", None)
            if start is not None
            else getattr(interval, "start_at_utc", None),
            local_wall=getattr(start, "local_wall_time", None)
            if start is not None
            else getattr(interval, "start_local_wall_time", None),
        ),
        "end": _endpoint(
            precision=_value(getattr(end, "precision", getattr(interval, "end_precision", None))),
            state=_value(getattr(end, "state", getattr(interval, "end_state", None))),
            at_utc=getattr(end, "measured_at_utc", None)
            if end is not None
            else getattr(interval, "end_at_utc", None),
            local_wall=getattr(end, "local_wall_time", None)
            if end is not None
            else getattr(interval, "end_local_wall_time", None),
        ),
    }


def is_safe_google_interval_identity(interval: Any) -> bool:
    """Whether both endpoints carry enough evidence for a logical key."""

    if _value(getattr(interval, "state", getattr(interval, "interval_state", None))) != "value":
        return False
    for endpoint_name in ("start", "end"):
        endpoint = getattr(interval, endpoint_name, None)
        if endpoint is not None:
            precision = _value(getattr(endpoint, "precision", None))
            state = _value(getattr(endpoint, "state", None))
            at_utc = getattr(endpoint, "measured_at_utc", None)
            local_wall = getattr(endpoint, "local_wall_time", None)
        else:
            precision = _value(getattr(interval, f"{endpoint_name}_precision", None))
            state = _value(getattr(interval, f"{endpoint_name}_state", None))
            at_utc = getattr(interval, f"{endpoint_name}_at_utc", None)
            local_wall = getattr(interval, f"{endpoint_name}_local_wall_time", None)
        if state != "value" or not (
            precision == "instant"
            and at_utc is not None
            or precision == "local"
            and bool(local_wall)
        ):
            return False
    return True


def _endpoint(
    *,
    precision: str | None,
    state: str | None,
    at_utc: datetime | None,
    local_wall: str | None,
) -> dict[str, object]:
    if at_utc is not None:
        return {"precision": "instant", "utc": _as_utc(at_utc).isoformat()}
    if local_wall:
        return {"precision": "local", "local": local_wall}
    return {"precision": precision or "unknown", "state": state or "missing"}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _value(value: object) -> str | None:
    return getattr(value, "value", value) if value is not None else None


__all__ = [
    "canonical_google_interval_identity",
    "is_safe_google_interval_identity",
    "google_steps_interval_key",
    "parse_steps_civil_endpoint",
]
