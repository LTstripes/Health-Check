"""Shared persisted Overview snapshot rules; no provider or selection policy."""

from math import isfinite

from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord


def overview_metric_matches(record, metric, *, code: str, capability: str) -> bool:
    if metric.metric_code != code:
        return False
    if code == "resting_heart_rate_bpm":
        return (
            record.stream_code == "daily_health"
            and record.surface_code in (None, "daily_summary", "resting_heart_rate")
            and metric.capability_code == "resting_heart_rate"
        )
    return record.surface_code in (None, capability)


def latest_overview_snapshots(
    candidates: list[tuple[GarminSourceRecord, GarminRecordMetric]],
) -> list[tuple[GarminSourceRecord, GarminRecordMetric]]:
    """A date/instant can order snapshots; UUID/ingestion order cannot."""
    day = max(record.source_local_date for record, _ in candidates)
    latest = [(record, metric) for record, metric in candidates if record.source_local_date == day]
    if all(record.source_timestamp_utc is not None for record, _ in latest):
        stamp = max(record.source_timestamp_utc for record, _ in latest)
        latest = [
            (record, metric) for record, metric in latest if record.source_timestamp_utc == stamp
        ]
    return latest


def overview_metric_is_usable(record, metric, *, code: str, unit: str) -> bool:
    number = metric.value_number
    return (
        metric.state == "value"
        and metric.unit == unit
        and (code != "resting_heart_rate_bpm" or isinstance(number, (int, float)))
        and number is not None
        and isfinite(number)
        and record.record_status in ("ok", "partial")
    )
