"""Shared surface predicate for saved daily-summary readers."""

from sqlalchemy import and_, or_, select

from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord


def daily_summary_candidate():
    """Keep legacy/metricless candidates, excluding only NULL-surface training records.

    Inspect all metrics, independently of each reader's joined metric codes.
    Stream, source, currentness and date bounds remain the caller's responsibility.
    """
    metrics = select(GarminRecordMetric.record_id).where(
        GarminRecordMetric.record_id == GarminSourceRecord.id,
    ).correlate(GarminSourceRecord)
    return or_(
        GarminSourceRecord.surface_code == "daily_summary",
        and_(
            GarminSourceRecord.surface_code.is_(None),
            or_(
                ~metrics.exists(),
                metrics.where(GarminRecordMetric.capability_code != "garmin_training").exists(),
            ),
        ),
    )
