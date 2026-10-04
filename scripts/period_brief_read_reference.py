"""Frozen query oracles from main 9eb5b82221c99d96e7681f26c4f41e637186fe47.

Only for synthetic equivalence/performance checks; never imported by product code.
Bodies are copied verbatim (dedented) from the assigned baseline.
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.orm import Session

from healthcheck.analytics.garmin_baselines import PROJECTION_CURRENT, GarminSeriesQuery
from healthcheck.analytics.sleep_agreement_report import _iso
from healthcheck.db.models import (
    AgreementRun,
    AgreementRunPair,
    CoverageInterval,
    GarminRecordMetric,
    GarminSource,
    GarminSourceRecord,
    Provider,
    SyncRun,
    SyncStreamState,
)
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.garmin.capabilities import GARMIN_PROVIDER_CODE
from healthcheck.google.contracts import GOOGLE_PROVIDER_CODE
from healthcheck.source_freshness_read import _GARMIN_STREAM


def _garmin_series_evidence_query(
    session: Session, provider_id: str, surface: str,
) -> tuple[datetime | None, date | None, str | None, bool, bool]:
    """Select chronology within the latest accepted civil day of one series surface."""
    model = GarminSourceRecord
    timestamp_kind = model.temporal_precision.in_(("instant", "minute"))
    invalid = (
        model.temporal_precision.in_(("local", "unknown"))
        | model.source_local_date.is_(None)
        | (timestamp_kind & model.source_timestamp_utc.is_(None))
    )
    conditions = (
        GarminSource.provider_id == provider_id,
        model.stream_code == _GARMIN_STREAM[surface],
        model.surface_code == surface,
        model.projection_status == "current",
        model.record_status.in_(("ok", "partial")),
    )
    latest_day, count = session.execute(select(
        func.max(model.source_local_date),
        func.count(),
    ).select_from(model).join(
        GarminSource, GarminSource.id == model.garmin_source_id,
    ).where(*conditions)).one()
    if not count:
        return None, None, None, True, False
    if latest_day is None:
        return None, None, "invalid_chronology", True, True
    stamp, invalid_count, source_count = session.execute(select(
        func.max(case((timestamp_kind, model.source_timestamp_utc))),
        func.sum(case((invalid, 1), else_=0)),
        func.count(func.distinct(model.garmin_source_id)),
    ).select_from(model).join(
        GarminSource, GarminSource.id == model.garmin_source_id,
    ).where(*conditions, model.source_local_date == latest_day)).one()
    return (
        restore_stored_utc(stamp), None if stamp is not None else latest_day,
        "invalid_chronology" if invalid_count else None,
        source_count <= 1, True,
    )


def _source_data_quality(
    self,
    selected_pairs: list[tuple[AgreementRun, AgreementRunPair]],
    start_date: date | None,
    end_date: date | None,
) -> list[dict[str, Any]]:
    providers = list(
        self.session.scalars(select(Provider).order_by(Provider.code, Provider.id))
    )
    states = list(self.session.scalars(select(SyncStreamState)))
    sync_runs = list(self.session.scalars(select(SyncRun)))
    intervals = list(self.session.scalars(select(CoverageInterval)))
    latest_evidence_date = max((pair.wake_date for _run, pair in selected_pairs), default=None)
    actual_by_provider = {
        GARMIN_PROVIDER_CODE: latest_evidence_date,
        GOOGLE_PROVIDER_CODE: latest_evidence_date,
    }
    result = []
    for provider in providers:
        provider_states = [item for item in states if item.provider_id == provider.id]
        provider_runs = [item for item in sync_runs if item.provider_id == provider.id]
        provider_intervals = [
            item
            for item in intervals
            if item.provider_id == provider.id
            and (
                start_date is None
                or end_date is None
                or item.interval_end.date() >= start_date
                and item.interval_start.date() <= end_date
            )
        ]
        interval_counts = Counter(item.status for item in provider_intervals)
        latest_success = max(
            [
                item.last_success_at
                for item in provider_states
                if item.last_success_at is not None
            ]
            + [
                item.completed_at
                for item in provider_runs
                if item.status == "succeeded" and item.completed_at is not None
            ],
            default=None,
        )
        latest_attempt = max(
            [
                item.last_attempt_at
                for item in provider_states
                if item.last_attempt_at is not None
            ]
            + [item.completed_at for item in provider_runs if item.completed_at is not None],
            default=None,
        )
        latest_status = next(
            (
                item.status
                for item in sorted(
                    provider_runs,
                    key=lambda row: (row.completed_at or row.started_at, row.id),
                    reverse=True,
                )
            ),
            None,
        )
        state = "unknown"
        if latest_status == "failed":
            state = "failed"
        elif latest_status == "partial" or interval_counts.get("unavailable"):
            state = "unavailable"
        elif interval_counts.get("present") or (
            provider_runs and latest_status == "succeeded"
        ):
            state = "usable"
        elif interval_counts.get("confirmed_empty"):
            state = "confirmed_empty"
        result.append(
            {
                "provider_code": provider.code,
                "provider_display_name": provider.display_name,
                "state": state,
                "last_successful_sync": _iso(latest_success),
                "last_attempt": _iso(latest_attempt),
                "last_sync_status": latest_status,
                "last_actual_measurement_or_evidence_date": _iso(
                    actual_by_provider.get(provider.code)
                ),
                "coverage_state_counts": dict(sorted(interval_counts.items())),
                "coverage_facts": [
                    {
                        "stream_code": item.stream_code,
                        "metric_code": item.metric_code,
                        "status": item.status,
                        "observed_count": item.observed_count,
                        "expected_count": item.expected_count,
                        "diagnostic_reason": item.diagnostic_reason,
                    }
                    for item in sorted(
                        provider_intervals,
                        key=lambda row: (row.interval_start, row.metric_code, row.id),
                    )
                ],
                "window": {"start_date": _iso(start_date), "end_date": _iso(end_date)},
            }
        )
    return result


def _candidate_statement(query: GarminSeriesQuery) -> Select[Any]:
    start_utc = datetime(
        query.start_date.year, query.start_date.month, query.start_date.day, tzinfo=UTC
    )
    end_exclusive = datetime(
        query.end_date.year, query.end_date.month, query.end_date.day, tzinfo=UTC
    ) + timedelta(days=1)
    date_in_window = and_(
        GarminSourceRecord.source_local_date.is_not(None),
        GarminSourceRecord.source_local_date >= query.start_date,
        GarminSourceRecord.source_local_date <= query.end_date,
    )
    utc_in_window = and_(
        GarminSourceRecord.source_local_date.is_(None),
        GarminSourceRecord.source_timestamp_utc.is_not(None),
        GarminSourceRecord.source_timestamp_utc >= start_utc,
        GarminSourceRecord.source_timestamp_utc < end_exclusive,
    )
    return (
        select(GarminRecordMetric, GarminSourceRecord)
        .join(
            GarminSourceRecord,
            GarminRecordMetric.record_id == GarminSourceRecord.id,
        )
        .where(
            GarminSourceRecord.garmin_source_id == query.garmin_source_id.strip(),
            GarminSourceRecord.projection_status == PROJECTION_CURRENT,
            GarminRecordMetric.metric_code == query.metric_code.strip(),
            or_(date_in_window, utc_in_window),
        )
        .order_by(
            GarminSourceRecord.source_local_date,
            GarminSourceRecord.source_timestamp_utc,
            GarminSourceRecord.id,
            GarminRecordMetric.id,
        )
    )
