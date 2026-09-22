"""Shared semantic identities for Google typed projections."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


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


__all__ = ["canonical_google_interval_identity", "is_safe_google_interval_identity"]
