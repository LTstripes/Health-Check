"""Read only persisted, scoped facts for source-freshness-v1 diagnostics."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, case, func, or_, select
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
from healthcheck.google.contracts import FAMILY_GOOGLE_WEARABLES
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
    return _checkpoint_state(state)


def _checkpoint_state(state: SyncStreamState | None) -> tuple[
    datetime | None, datetime | None, str | None
]:
    if state is None:
        return None, None, None
    status = state.diagnostic_status
    if status is not None:
        if status in {"present", "confirmed_empty"}:
            status = "succeeded"
        elif status in {"unknown", "partial", "invalid", "not_run",
                        "request_budget_exhausted"}:
            status = "partial"
        elif status in {"unavailable", "scope_required", "unsupported_or_not_found"}:
            status = "required_stream_unavailable"
        elif status in {
            "reauth_required", "authentication_failed", "session_expired_or_unusable",
            "mfa_failed",
        }:
            status = "reauth_required"
        elif status in {
            "failed", "provider_unavailable", "provider_error", "rate_limited",
            "session_corrupt", "windows_protection_unavailable", "session_missing",
            "storage_permission", "dependency_missing", "invalid_input",
            "method_unavailable",
        }:
            status = "failed"
        else:
            status = "partial"
    return (restore_stored_utc(state.last_attempt_at),
            restore_stored_utc(state.last_success_at), status)


def _google_heart_rate_checkpoint(session: Session, provider_id: str, day: date) -> tuple[
    datetime | None, datetime | None, str | None
]:
    base = "google:refresh:heart_rate:list:any"
    states = session.scalars(select(SyncStreamState).where(
        SyncStreamState.provider_id == provider_id,
        SyncStreamState.acquisition_source_id.is_(None),
        SyncStreamState.stream_code.like(f"{base}:day:%"),
    )).all()
    dated = []
    for state in states:
        suffix = state.stream_code.removeprefix(f"{base}:day:")
        try:
            partition_day = date.fromisoformat(suffix)
        except ValueError:
            continue
        if suffix == partition_day.isoformat() and partition_day <= day:
            dated.append((partition_day, state))
    if dated:
        return _checkpoint_state(max(dated, key=lambda row: row[0])[1])
    return _checkpoint(session, provider_id, base)


def _provider_terminal(session: Session, provider_id: str, provider: str) -> tuple[
    datetime | None, str | None
]:
    streams = ("garmin_incremental",) if provider == "garmin" else (
        "google_incremental", "google_historical", "google_refresh",
    )
    row = session.execute(select(
        SyncRun.completed_at, SyncRun.error_category,
    ).where(
        SyncRun.provider_id == provider_id,
        SyncRun.stream_code.in_(streams),
        SyncRun.completed_at.is_not(None),
        SyncRun.status == "failed",
        or_(SyncRun.error_category == "reauth_required", and_(
            SyncRun.error_category == "failed", SyncRun.item_count == 0,
        )),
    ).order_by(SyncRun.completed_at.desc()).limit(1)).first()
    # A zero-attempt failed run is the persisted pre-surface auth failure.
    # A reauth abort is provider-wide even if some surfaces ran first.
    if row is None:
        return None, None
    return restore_stored_utc(row[0]), (
        "reauth_required" if row[1] == "reauth_required" else "failed"
    )


def _apply_provider_terminal(
    attempt: datetime | None, success: datetime | None, status: str | None,
    provider_terminal: tuple[datetime | None, str | None],
) -> tuple[datetime | None, datetime | None, str | None]:
    global_at, global_status = provider_terminal
    if global_at is not None and (attempt is None or global_at > attempt) and (
        success is None or global_at > success
    ):
        return global_at, success, global_status
    return attempt, success, status


def _activity_coverage(session: Session, provider_id: str, day: date) -> tuple[
    str, int | None, bool
]:
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
    accepted = [(
        max(start, restore_stored_utc(row.interval_start)),
        min(end, restore_stored_utc(row.interval_end)), row.status,
        row.acquisition_source_id,
    ) for row in rows if row.status in {"present", "confirmed_empty"}]
    accepted.sort(key=lambda row: (row[0], row[1], row[2]))
    cursor = start
    for left, right, _, _ in accepted:
        if left > cursor:
            break
        cursor = max(cursor, right)
        if cursor >= end:
            break
    if cursor < end:
        return "unknown", None, True
    # The complete inventory coverage is authoritative; a current partial
    # projection can still be an accepted activity with optional fields absent.
    record_sources = session.execute(select(
        GarminSource.id, GarminSource.acquisition_source_id,
    ).join(
        GarminSourceRecord, GarminSource.id == GarminSourceRecord.garmin_source_id
    ).where(
        GarminSource.provider_id == provider_id,
        GarminSourceRecord.stream_code == "activity",
        GarminSourceRecord.projection_status == "current",
        GarminSourceRecord.record_status.in_(("ok", "partial")),
        GarminSourceRecord.source_local_date >= day - timedelta(days=6),
        GarminSourceRecord.source_local_date <= day,
    ).distinct()).all()
    coverage_sources = {source for _, _, _, source in accepted if source is not None}
    represented_acquisitions = {acquisition for _, acquisition in record_sources}
    source_count = len(record_sources) + len(coverage_sources - represented_acquisitions)
    count = session.scalar(select(func.count(GarminSourceRecord.id)).join(
        GarminSource, GarminSource.id == GarminSourceRecord.garmin_source_id
    ).where(
        GarminSource.provider_id == provider_id,
        GarminSourceRecord.stream_code == "activity",
        GarminSourceRecord.projection_status == "current",
        GarminSourceRecord.record_status.in_(("ok", "partial")),
        GarminSourceRecord.source_local_date >= day - timedelta(days=6),
        GarminSourceRecord.source_local_date <= day,
    ))
    if count == 0 and any(status == "present" for _, _, status, _ in accepted):
        return "unknown", None, source_count <= 1
    return "complete", count, source_count <= 1


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
    provider_terminal = _provider_terminal(session, provider_id, scope.provider)
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
        attempt, success, terminal = _apply_provider_terminal(
            restore_stored_utc(latest[0]) if latest else None,
            max(successful, default=None),
            latest[1] if latest and latest[1] in {"failed", "partial"} else None,
            provider_terminal,
        )
        # Training's own reauth result is not persisted by its existing service.
        return Facts(last_attempt_at_utc=attempt, last_success_at_utc=success,
                     terminal_status=terminal,
                     evidence_at_utc=stamp, evidence_local_date=local_day,
                     observed_once=observed, attribution_resolved=not unresolved)
    if scope.provider == "garmin":
        attempt, success, terminal = _checkpoint(session, provider_id, code)
        attempt, success, terminal = _apply_provider_terminal(
            attempt, success, terminal, provider_terminal,
        )
        if scope.family == "activity":
            coverage, count, resolved = _activity_coverage(
                session, provider_id, evaluation_local_date,
            )
            return Facts(last_attempt_at_utc=attempt, last_success_at_utc=success,
                         terminal_status=terminal, coverage=coverage,
                         activity_count=count, observed_once=count is not None,
                         attribution_resolved=resolved)
        # Sync marks this exact surface successful only after its expected
        # metric (or structural daily summary) proves accepted coverage.
        # Sibling field gaps can leave the current record partial.
        stamp, local_day, unresolved, observed = _evidence_query(
            session, GarminSourceRecord,
            joins=((GarminSource, GarminSource.id == GarminSourceRecord.garmin_source_id),),
            conditions=(GarminSource.provider_id == provider_id,
                        GarminSourceRecord.stream_code == _GARMIN_STREAM[code],
                        GarminSourceRecord.surface_code == code,
                        GarminSourceRecord.projection_status == "current",
                        GarminSourceRecord.record_status.in_(("ok", "partial"))),
            source_identity=GarminSourceRecord.garmin_source_id,
        )
    else:
        # Normal/list evidence only. Reconcile/rollup and historical partitions have
        # different semantics and may not silently satisfy normal-stream freshness.
        stream = "sleep" if code == "wearables_sleep_reconcile" else code
        mode = "reconcile" if code == "wearables_sleep_reconcile" else "list"
        family = FAMILY_GOOGLE_WEARABLES if code == "wearables_sleep_reconcile" else None
        if code == "heart_rate":
            attempt, success, terminal = _google_heart_rate_checkpoint(
                session, provider_id, evaluation_local_date,
            )
        else:
            family_key = "google-wearables" if family is not None else "any"
            checkpoint = f"google:refresh:{stream}:{mode}:{family_key}"
            attempt, success, terminal = _checkpoint(session, provider_id, checkpoint)
        attempt, success, terminal = _apply_provider_terminal(
            attempt, success, terminal, provider_terminal,
        )
        stamp, local_day, unresolved, observed = _evidence_query(
            session, GoogleSourceRecord,
            joins=((GoogleSource, GoogleSource.id == GoogleSourceRecord.google_source_id),),
            conditions=(GoogleSource.provider_id == provider_id,
                        GoogleSourceRecord.stream_code == stream,
                        GoogleSourceRecord.query_mode == mode,
                        GoogleSourceRecord.data_source_family == family,
                        GoogleSourceRecord.projection_status == "current",
                        GoogleSourceRecord.record_status == "ok"),
            source_identity=GoogleSourceRecord.google_source_id,
        )
    return Facts(last_attempt_at_utc=attempt, last_success_at_utc=success,
                 terminal_status=terminal, evidence_at_utc=stamp,
                 evidence_local_date=local_day, observed_once=observed,
                 attribution_resolved=not unresolved)
