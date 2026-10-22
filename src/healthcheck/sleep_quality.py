"""Pure sleep duration checks shared by current and legacy persisted readers."""

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from healthcheck.db.repositories import restore_stored_utc

SLEEP_DURATION_QUALITY_VERSION = "sleep-duration-quality-v2"
SUMMARY_BOUNDS_METRIC = "sleep_summary_session_bounds"
SUMMARY_BOUNDS_VERSION = "garmin-sleep-summary-bounds-v1"
_TEMPORAL_FIELDS = (
    "precision", "measured_at_utc", "local_wall_time", "local_date", "source_field",
    "local_date_source", "source_local_timestamp", "source_timezone",
    "source_utc_offset_minutes", "source_local_field", "source_utc_field",
)


def _stored_milliseconds(value: Any) -> int | None:
    """Decode retained numeric text exactly; leave its original spelling intact."""
    if (not isinstance(value, str) or not 1 <= len(value) <= 20
            or re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", value) is None):
        return None
    try:
        number = Decimal(value)
        # The producer's datetime range, checked before an integer conversion.
        if (not number.is_finite() or not -62135596800000 <= number <= 253402300799999
                or number != number.to_integral_value()):
            return None
        return int(number)
    except (InvalidOperation, ValueError, OverflowError):
        return None


def garmin_summary_boundary_evidence(record: Any, metrics: Sequence[Any]) -> dict | None:
    """Validate and freeze v4's independent summary upper bound, never stage coverage."""
    if (record.normalization_contract_version != "r02-garmin-sleep-normalization-v4"
            or record.temporal_precision != "instant"):
        return None
    rows = [row for row in metrics if row.metric_code == SUMMARY_BOUNDS_METRIC]
    if len(rows) != 1 or rows[0].state != "value" or rows[0].unit is not None:
        return None
    row = rows[0]
    if (row.field_path != f"{record.source_path}.dailySleepDTO"
            or not isinstance(row.value_text, str) or len(row.value_text) > 8192):
        return None
    try:
        value = json.loads(row.value_text)
        if not isinstance(value, Mapping) or value.get("schema_version") != SUMMARY_BOUNDS_VERSION:
            return None
        parsed, endpoints = [], {}
        for endpoint in ("Start", "End"):
            temporal = value[endpoint.lower()]
            path = f"{record.source_path}.dailySleepDTO.sleep{endpoint}Timestamp"
            if (not isinstance(temporal, Mapping) or temporal.get("precision") != "instant"
                    or temporal.get("source_field") != path + "GMT"
                    or temporal.get("source_utc_field") != path + "GMT"):
                return None
            if any(temporal.get(key) is not None and not isinstance(temporal[key], str)
                   for key in _TEMPORAL_FIELDS if key != "source_utc_offset_minutes"):
                return None
            stamp = datetime.fromisoformat(temporal["measured_at_utc"])
            if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
                return None
            local, offset = temporal.get("source_local_timestamp"), temporal.get(
                "source_utc_offset_minutes")
            if local is not None:
                local_milliseconds = _stored_milliseconds(local)
                if (local_milliseconds is None or isinstance(offset, bool)
                        or not isinstance(offset, int) or not -1439 <= offset <= 1439
                        or temporal.get("source_local_field") != path + "Local"):
                    return None
                paired = (datetime(1970, 1, 1, tzinfo=UTC)
                          + timedelta(milliseconds=local_milliseconds)
                          - timedelta(minutes=offset))
                if paired != stamp:
                    return None
            elif offset is not None or temporal.get("source_local_field") is not None:
                return None
            parsed.append(stamp)
            endpoints[endpoint.lower()] = {key: temporal.get(key) for key in _TEMPORAL_FIELDS}
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if parsed[0] != restore_stored_utc(record.source_timestamp_utc) or parsed[1] <= parsed[0]:
        return None
    return {"schema_version": SUMMARY_BOUNDS_VERSION, "metric_row_id": row.id,
            "field_path": row.field_path, **endpoints}


def garmin_duration_session_bounds(
    record: Any, stages: Sequence[Any], metrics: Sequence[Any],
) -> tuple[datetime | None, datetime | None]:
    """Read v4's duration upper bound, with the real v3 endpoint fallback."""
    if record.normalization_contract_version == "r02-garmin-sleep-normalization-v4":
        evidence = garmin_summary_boundary_evidence(record, metrics)
        if evidence is None:
            return None, None
        return tuple(datetime.fromisoformat(evidence[key]["measured_at_utc"])
                     for key in ("start", "end"))
    return garmin_confirmed_session_bounds(record, stages)


def garmin_confirmed_session_bounds(
    record: Any, stages: Sequence[Any],
) -> tuple[datetime | None, datetime | None]:
    """Require real paired endpoint provenance for complete-stage timing.

    V3/v4 attach the summary Local epoch and its explicitly paired fixed offset
    when a stage endpoint exactly matches summary End GMT. Independent v4
    metadata alone never proves stage coverage. No raw body or host timezone.
    """
    if (record.normalization_contract_version not in {
            "r02-garmin-sleep-normalization-v3", "r02-garmin-sleep-normalization-v4"}
            or record.temporal_precision != "instant"):
        return None, None
    start = restore_stored_utc(record.source_timestamp_utc)
    ends = set()
    for row in stages:
        try:
            temporal = json.loads(row.end_temporal_json or "null")
        except (ValueError, TypeError):
            continue
        if not isinstance(temporal, Mapping):
            continue
        path = temporal.get("source_local_field")
        stamp = temporal.get("source_local_timestamp")
        stored_milliseconds = _stored_milliseconds(stamp)
        offset = temporal.get("source_utc_offset_minutes")
        if (not isinstance(path, str)
                or not path.endswith("dailySleepDTO.sleepEndTimestampLocal")
                or stored_milliseconds is None
                or isinstance(offset, bool) or not isinstance(offset, int)
                or not -1439 <= offset <= 1439):
            continue
        try:
            end = (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=stored_milliseconds)
                   - timedelta(minutes=offset))
        except (ValueError, OverflowError):
            continue
        if row.end_precision == "instant" and restore_stored_utc(row.end_at_utc) == end:
            ends.add(end)
    if start is None or len(ends) != 1:
        return None, None
    end = next(iter(ends))
    return (start, end) if end > start else (None, None)


def garmin_duration_bound_check(
    record: Any, stages: Sequence[Any], metrics: Sequence[Any], seconds: int | float | None,
) -> dict:
    """Distinguish scalar usability from a check against an evidenced upper bound."""
    start, end = garmin_duration_session_bounds(record, stages, metrics)
    if start is None or end is None:
        return {"state": "unverified", "reason": "summary_session_boundary_unavailable",
                "upper_bound_seconds": None}
    if seconds is None:
        return {"state": "unverified", "reason": "duration_scalar_unavailable",
                "upper_bound_seconds": (end - start).total_seconds()}
    bound = (end - start).total_seconds()
    return {"state": "checked", "reason": duration_quality_reason(seconds, session_seconds=bound),
            "upper_bound_seconds": bound}


def duration_quality_reason(
    seconds: int | float, *, session_seconds: float | None = None,
    tib_seconds: int | float | None = None,
) -> str | None:
    """Compare exact compatible durations without inventing a rounding allowance."""
    if seconds < 0:
        return "duration_negative"
    if session_seconds is not None and seconds > session_seconds:
        return "duration_exceeds_confirmed_session"
    if tib_seconds is not None and seconds > tib_seconds:
        return "duration_exceeds_time_in_bed"
    return None
