"""Read only persisted, scoped facts for source-freshness-v1 diagnostics."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    CoverageInterval,
    GarminSource,
    GarminSourceRecord,
    GarminTrainingAcquisition,
    GarminTrainingObservationRecord,
    GoogleSource,
    GoogleSourceRecord,
    MeasurementSession,
    Provider,
    ScalarMeasurement,
    SyncRun,
    SyncStreamState,
)
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.source_freshness import Facts, Scope

_GARMIN_STREAM = {
    "daily_summary": "daily_health", "sleep": "sleep", "heart_rate": "intraday",
    "resting_heart_rate": "daily_health", "hrv_status": "daily_health",
    "stress": "intraday", "body_battery": "intraday", "spo2": "intraday",
    "respiration": "intraday", "activities": "activity",
}


def _evidence_query(session: Session, model, *, joins: tuple, conditions: tuple,
                    source_identity=None) -> tuple[
    datetime | None, date | None, bool, bool
]:
    """Aggregate chronology in SQLite; never load raw records or all historical rows."""
    timestamp_kind = model.temporal_precision.in_(("instant", "minute"))
    date_kind = model.temporal_precision == "date"
    invalid = (
        model.temporal_precision.in_(("local", "unknown"))
        | (timestamp_kind & model.source_timestamp_utc.is_(None))
        | (date_kind & model.source_local_date.is_(None))
    )
    statement = select(
        func.max(case((timestamp_kind, model.source_timestamp_utc))),
        func.max(case((date_kind, model.source_local_date))),
        func.sum(case((invalid, 1), else_=0)),
        func.count(),
        func.count(func.distinct(source_identity)) if source_identity is not None else func.count(),
    ).select_from(model)
    for target, condition in joins:
        statement = statement.join(target, condition)
    stamp, local_day, invalid_count, count, source_count = session.execute(
        statement.where(*conditions)
    ).one()
    unresolved = bool(invalid_count) or (stamp is not None and local_day is not None)
    unresolved = unresolved or source_identity is not None and source_count > 1
    return restore_stored_utc(stamp), local_day, unresolved, count > 0


def _checkpoint(session: Session, provider_id: str, code: str) -> tuple[
    datetime | None, datetime | None, str | None
]:
    state = session.scalar(select(SyncStreamState).where(
        SyncStreamState.provider_id == provider_id,
        SyncStreamState.acquisition_source_id.is_(None),
        SyncStreamState.stream_code == code,
    ))
    if state is None:
        return None, None, None
    status = state.diagnostic_status
    if status is not None:
        if status in {"present", "confirmed_empty"}:
            status = "succeeded"
        elif status in {"unknown", "partial", "invalid", "not_run",
                        "request_budget_exhausted"}:
            status = "partial"
        elif status in {"unavailable", "scope_required"}:
            status = "required_stream_unavailable"
        elif "auth" in status or "reauth" in status or status in {
            "session_expired_or_unusable", "mfa_failed",
        }:
            status = "reauth_required"
        elif status in {
            "failed", "provider_unavailable", "provider_error", "rate_limited",
            "session_corrupt", "windows_protection_unavailable", "session_missing",
            "storage_permission", "dependency_missing", "invalid_input",
        }:
            status = "failed"
        else:
            status = "partial"
    return (restore_stored_utc(state.last_attempt_at),
            restore_stored_utc(state.last_success_at), status)


def _activity_coverage(session: Session, provider_id: str, day: date) -> tuple[str, int | None]:
    start = datetime.combine(day - timedelta(days=6), datetime.min.time(), UTC)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC)
    rows = session.scalars(select(CoverageInterval).where(
        CoverageInterval.provider_id == provider_id,
        CoverageInterval.stream_code == "activity",
        CoverageInterval.metric_code == "activities",
        CoverageInterval.resolution == "day",
        CoverageInterval.interval_start < end,
        CoverageInterval.interval_end > start,
    )).all()
    # Coverage can be replayed/deduplicated. It is a disposition, never an attempt clock.
    accepted = sorted((
        max(start, restore_stored_utc(row.interval_start)),
        min(end, restore_stored_utc(row.interval_end)), row.status,
    ) for row in rows if row.status in {"present", "confirmed_empty"})
    cursor = start
    for left, right, _ in accepted:
        if left > cursor:
            break
        cursor = max(cursor, right)
        if cursor >= end:
            break
    if cursor < end:
        return "unknown", None
    count = session.scalar(select(func.count(GarminSourceRecord.id)).join(
        GarminSource, GarminSource.id == GarminSourceRecord.garmin_source_id
    ).where(
        GarminSource.provider_id == provider_id,
        GarminSourceRecord.stream_code == "activity",
        GarminSourceRecord.projection_status == "current",
        GarminSourceRecord.record_status == "ok",
        GarminSourceRecord.source_local_date >= day - timedelta(days=6),
        GarminSourceRecord.source_local_date <= day,
    ))
    if count == 0 and any(status == "present" for _, _, status in accepted):
        return "unknown", None
    return "complete", count


def read_facts(
    session: Session, scope: Scope, *, evaluation_local_date: date, requested: bool = True,
    disabled: bool = False,
    weight_cadence_days: int | None = None,
) -> Facts:
    if disabled or not requested:
        return Facts(requested=requested, disabled=disabled)
    if scope.family == "weight":
        successor_ids = select(MeasurementSession.supersedes_session_id).where(
            MeasurementSession.supersedes_session_id.is_not(None)
        )
        stamp, local_day, _, observed = _evidence_query(
            session, MeasurementSession,
            joins=((ScalarMeasurement,
                    ScalarMeasurement.measurement_session_id == MeasurementSession.id),),
            conditions=(ScalarMeasurement.metric_code == "weight",
                        MeasurementSession.confirmation_status == "confirmed",
                        ~MeasurementSession.id.in_(successor_ids)),
        )
        return Facts(evidence_at_utc=stamp, evidence_local_date=local_day,
                     confirmed_weight=observed, observed_once=observed,
                     weight_cadence_days=weight_cadence_days)
    provider_code = "garmin_connect" if scope.provider == "garmin" else "google_health"
    provider_id = session.scalar(select(Provider.id).where(Provider.code == provider_code))
    if provider_id is None:
        return Facts()
    code = scope.key.split(":", 1)[1]
    if scope.provider == "garmin" and code.startswith("training_"):
        # Training retains requested-day chronology separately from the normal daily surface.
        runs = session.execute(select(SyncRun.completed_at, SyncRun.status).where(
            SyncRun.provider_id == provider_id, SyncRun.stream_code == "garmin_training",
            SyncRun.completed_at.is_not(None),
        )).all()
        stamp, local_day, unresolved, observed = _evidence_query(
            session, GarminSourceRecord,
            joins=((GarminTrainingObservationRecord,
                    GarminTrainingObservationRecord.record_id == GarminSourceRecord.id),
                   (GarminTrainingAcquisition,
                    GarminTrainingAcquisition.observation_id ==
                    GarminTrainingObservationRecord.observation_id),
                   (GarminSource, GarminSource.id == GarminSourceRecord.garmin_source_id)),
            conditions=(GarminSource.provider_id == provider_id,
                        GarminTrainingAcquisition.surface == code,
                        GarminTrainingAcquisition.response_state == "value",
                        GarminSourceRecord.projection_status == "current",
                        GarminSourceRecord.record_status == "ok"),
            source_identity=GarminSourceRecord.garmin_source_id,
        )
        latest = max(runs, key=lambda row: restore_stored_utc(row[0]), default=None)
        successful = [restore_stored_utc(at) for at, status in runs if status == "succeeded"]
        return Facts(last_attempt_at_utc=restore_stored_utc(latest[0]) if latest else None,
                     last_success_at_utc=max(successful, default=None),
                     terminal_status="partial" if latest and latest[1] != "succeeded" else None,
                     evidence_at_utc=stamp, evidence_local_date=local_day,
                     observed_once=observed, attribution_resolved=not unresolved)
    if scope.provider == "garmin":
        attempt, success, terminal = _checkpoint(session, provider_id, code)
        if scope.family == "activity":
            coverage, count = _activity_coverage(session, provider_id, evaluation_local_date)
            source_count = session.scalar(select(func.count(GarminSource.id)).where(
                GarminSource.provider_id == provider_id
            ))
            return Facts(last_attempt_at_utc=attempt, last_success_at_utc=success,
                         terminal_status=terminal, coverage=coverage,
                         activity_count=count, observed_once=count is not None,
                         attribution_resolved=source_count <= 1)
        stamp, local_day, unresolved, observed = _evidence_query(
            session, GarminSourceRecord,
            joins=((GarminSource, GarminSource.id == GarminSourceRecord.garmin_source_id),),
            conditions=(GarminSource.provider_id == provider_id,
                        GarminSourceRecord.stream_code == _GARMIN_STREAM[code],
                        GarminSourceRecord.surface_code == code,
                        GarminSourceRecord.projection_status == "current",
                        GarminSourceRecord.record_status == "ok"),
            source_identity=GarminSourceRecord.garmin_source_id,
        )
    else:
        # Normal/list evidence only. Reconcile/rollup and historical partitions have
        # different semantics and may not silently satisfy normal-stream freshness.
        stream = "sleep" if code == "wearables_sleep_reconcile" else code
        mode = "reconcile" if code == "wearables_sleep_reconcile" else "list"
        checkpoint = f"google:incremental:{stream}:{mode}:any"
        attempt, success, terminal = _checkpoint(session, provider_id, checkpoint)
        stamp, local_day, unresolved, observed = _evidence_query(
            session, GoogleSourceRecord,
            joins=((GoogleSource, GoogleSource.id == GoogleSourceRecord.google_source_id),),
            conditions=(GoogleSource.provider_id == provider_id,
                        GoogleSourceRecord.stream_code == stream,
                        GoogleSourceRecord.query_mode == mode,
                        GoogleSourceRecord.projection_status == "current",
                        GoogleSourceRecord.record_status == "ok"),
            source_identity=GoogleSourceRecord.google_source_id,
        )
    return Facts(last_attempt_at_utc=attempt, last_success_at_utc=success,
                 terminal_status=terminal, evidence_at_utc=stamp,
                 evidence_local_date=local_day, observed_once=observed,
                 attribution_resolved=not unresolved)
