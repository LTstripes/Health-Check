"""Frozen pre-#295 selector/assembly oracle, never imported by product code.

Function body from main 4d01fe93a49b2204bad83ea34d2685e98b3c6e13.
Shared projection helpers are unchanged by this query-only candidate.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.db.models import GoogleSourceRecord
from healthcheck.google.daily_vitals import (
    _CURRENT,
    _DATE_PRECISION,
    GOOGLE_DAILY_VITALS_CONTRACT_VERSION,
    GoogleDailyVitalPoint,
    GoogleDailyVitalsResult,
    _empty_result,
    _load_metric_rows,
    _load_sources,
    _source_result,
    get_google_daily_vital,
    project_google_daily_vital_group,
    validate_google_daily_vitals_window,
)


def read_google_daily_vitals_reference(
    session: Session,
    *,
    metric_code: str,
    start_date: date,
    end_date: date,
) -> GoogleDailyVitalsResult:
    """Read one frozen metric from persisted current Google evidence only."""

    definition = get_google_daily_vital(metric_code)
    validate_google_daily_vitals_window(start_date, end_date)
    records = list(
        session.scalars(
            select(GoogleSourceRecord)
            .where(
                GoogleSourceRecord.stream_code == definition.stream_code,
                GoogleSourceRecord.projection_status == _CURRENT,
                GoogleSourceRecord.temporal_precision == _DATE_PRECISION,
                GoogleSourceRecord.source_local_date.is_not(None),
                GoogleSourceRecord.source_local_date >= start_date,
                GoogleSourceRecord.source_local_date <= end_date,
            )
            .order_by(
                GoogleSourceRecord.source_local_date,
                GoogleSourceRecord.google_source_id,
                GoogleSourceRecord.id,
            )
        )
    )
    if not records:
        return _empty_result(definition, start_date, end_date)

    sources = _load_sources(session, records)
    metrics = _load_metric_rows(session, records, definition.metric_code)
    groups: dict[tuple[str, date], list[GoogleSourceRecord]] = {}
    for record in records:
        assert record.source_local_date is not None
        groups.setdefault((record.google_source_id, record.source_local_date), []).append(record)

    by_source: dict[str, list[GoogleDailyVitalPoint]] = {}
    for (source_id, local_date), group in groups.items():
        point = project_google_daily_vital_group(definition, local_date, group, metrics)
        by_source.setdefault(source_id, []).append(point)

    source_rows = tuple(
        _source_result(sources[source_id], by_source[source_id])
        for source_id in sorted(by_source)
        if source_id in sources
    )
    return GoogleDailyVitalsResult(
        contract_version=GOOGLE_DAILY_VITALS_CONTRACT_VERSION,
        metric_code=definition.metric_code,
        stream_code=definition.stream_code,
        unit=definition.unit,
        start_date=start_date,
        end_date=end_date,
        window_state="records_in_window",
        sources=source_rows,
    )
