"""Pure sleep duration checks shared by current and legacy persisted readers."""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from healthcheck.db.repositories import restore_stored_utc

SLEEP_DURATION_QUALITY_VERSION = "sleep-duration-quality-v1"


def garmin_confirmed_session_bounds(
    record: Any, stages: Sequence[Any],
) -> tuple[datetime | None, datetime | None]:
    """Recover only v3's preserved paired summary end; never guess from stage span.

    V3 attaches the summary Local epoch and its explicitly paired fixed offset
    when a stage endpoint exactly matches summary End GMT. Legacy levels lack
    this evidence, even when contiguous. No raw body or host timezone is used.
    """
    if (record.normalization_contract_version != "r02-garmin-sleep-normalization-v3"
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
        offset = temporal.get("source_utc_offset_minutes")
        if (not isinstance(path, str)
                or not path.endswith("dailySleepDTO.sleepEndTimestampLocal")
                or not isinstance(stamp, str) or len(stamp) > 20
                or not stamp.lstrip("-").isdigit()
                or isinstance(offset, bool) or not isinstance(offset, int)
                or not -1439 <= offset <= 1439):
            continue
        try:
            end = (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=int(stamp))
                   - timedelta(minutes=offset))
        except (ValueError, OverflowError):
            continue
        if row.end_precision == "instant" and restore_stored_utc(row.end_at_utc) == end:
            ends.add(end)
    if start is None or len(ends) != 1:
        return None, None
    end = next(iter(ends))
    return (start, end) if end > start else (None, None)


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
