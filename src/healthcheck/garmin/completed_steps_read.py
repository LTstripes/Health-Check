"""Read-only Moscow completed-day selection over bounded saved acquisitions.

Success is a conjunction, not a run-status or parse-status shortcut: the supported
incremental/historical path calls the daily-summary provider method successfully
before persisting its original response (sync._fetch/_sync_surface/_persist_payload).
Exact observation/source/provider/event/batch links and verified original JSON
pin that path. A terminal partial run additionally needs the new immutable
daily-summary receipt; historic partials remain unproven. Succeeded legacy runs
retain their accepted proof. Mutable coverage/checkpoints and v1 stay untouched.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from time import monotonic
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    GarminDailySummaryAcquisitionReceipt,
    GarminPayloadObservation,
    GarminRawPayload,
    GarminSource,
    IngestBatch,
    IngestEvent,
    Provider,
    RawArtifact,
    SyncRun,
)
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.garmin.daily_summary_acquisition import acquisition_spine_reason, receipt_reason
from healthcheck.garmin.observed_steps import _calendar_date, _decode, _metric
from healthcheck.garmin.observed_steps_read import MAX_WINDOW_DAYS, StepsSourceIdentity
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.web.read_snapshot import ensure_read_snapshot

READ_CONTRACT_VERSION = "garmin-completed-day-steps-moscow-v2"
DISPLAY_ZONE = "Europe/Moscow"
MAX_CANDIDATES = 4096
MAX_PROVENANCE = 4096
MAX_ARTIFACTS = 1000
MAX_ARTIFACT_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_READ_SECONDS = 5.0


def completion_boundary(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time(), ZoneInfo(DISPLAY_ZONE)).astimezone(UTC)


@dataclass(frozen=True)
class CompletedStepsEvidence:
    observation_id: str
    raw_payload_id: str
    raw_artifact_id: str | None
    content_hash: str | None
    sync_run_id: str | None
    ingest_event_id: str | None
    received_at: datetime
    state: str
    value: int | None
    reason: str | None
    acquisition_proven: bool
    acquisition_proof: str | None = None
    acquisition_receipt_version: str | None = None


@dataclass(frozen=True)
class CompletedStepsDay:
    source_id: str
    calendar_date: date
    completion_boundary_utc: datetime
    state: str
    value: int | None = None
    reason: str | None = None
    latest_received_at: datetime | None = None
    evidence: tuple[CompletedStepsEvidence, ...] = ()
    search_complete: bool = True
    coverage: str = "unknown"
    device: str = "unknown"
    timezone: str = "unknown"
    finality: str = "unknown"


@dataclass(frozen=True)
class CompletedStepsWindow:
    source_id: str | None
    start_date: date
    end_date: date
    evaluated_at: datetime
    source_identity: StepsSourceIdentity | None
    source_choices: tuple[StepsSourceIdentity, ...]
    cells: tuple[CompletedStepsDay, ...]
    search_complete: bool
    candidates_examined: int
    provenance_examined: int
    artifacts_examined: int
    bytes_examined: int
    reason: str | None = None
    contract_version: str = READ_CONTRACT_VERSION
    display_zone: str = DISPLAY_ZONE


def acquisition_reason(
    observation, source, raw, artifact, run, provider, event, batch,
    receipt=None, original_day=None,
):
    """Legacy success or an exact receipt; neither can hide a contradiction."""
    reason = acquisition_spine_reason(
        observation, source, raw, artifact, run, provider, event, batch
    )
    if reason:
        return reason
    if run.status not in {"succeeded", "partial"} or run.completed_at is None:
        return "acquisition_success_unproven"
    if receipt is not None:
        return receipt_reason(receipt, observation, run, original_day)
    return None if run.status == "succeeded" else "acquisition_success_unproven"


def read_completed_steps_window(
    session: Session,
    *,
    payload_store: ContentAddressedGarminPayloadStore,
    source_id: str | None,
    start_date: date,
    end_date: date,
    evaluated_at: datetime,
) -> CompletedStepsWindow:
    """Scan originals once, cap+1, in one snapshot; never project or fall back.

    Requested civil bounds are retained. Current/future Moscow days are omitted.
    Unknown original day/integrity or any exhausted bound fails the whole search
    closed because its day/latest rank cannot be proved. Exact source selection
    is preserved; automatic choice requires one sole source in the verified range.
    """
    if type(start_date) is not date or type(end_date) is not date:
        raise ValueError("completed Steps requires civil dates")
    if not 1 <= (end_date - start_date).days + 1 <= MAX_WINDOW_DAYS:
        raise ValueError("completed Steps window must contain 1 to 366 days")
    if source_id is not None and (not isinstance(source_id, str) or not source_id.strip()):
        raise ValueError("invalid exact source")
    if not isinstance(evaluated_at, datetime) or evaluated_at.utcoffset() is None:
        raise ValueError("completed Steps requires an aware evaluation instant")
    evaluated_at = evaluated_at.astimezone(UTC)
    today = evaluated_at.astimezone(ZoneInfo(DISPLAY_ZONE)).date()
    dates = tuple(
        start_date + timedelta(days=i)
        for i in range((end_date - start_date).days + 1)
        if start_date + timedelta(days=i) < today
    )
    ensure_read_snapshot(session)
    started = monotonic()
    source = session.get(GarminSource, source_id) if source_id else None
    identity = None
    choices = ()
    candidates = provenance = artifacts = byte_count = 0

    def result(cells=(), reason=None, complete=True):
        return CompletedStepsWindow(
            source_id,
            start_date,
            end_date,
            evaluated_at,
            identity,
            choices,
            tuple(cells),
            complete,
            candidates,
            provenance,
            artifacts,
            byte_count,
            reason,
        )

    def incomplete(reason):
        return result(
            (
                CompletedStepsDay(
                    source_id or "",
                    day,
                    completion_boundary(day),
                    "search_incomplete",
                    reason=reason,
                    search_complete=False,
                )
                for day in dates
            ),
            reason,
            False,
        )

    if source_id and (source is None or source.provider_code != "garmin_connect"):
        return result(reason="source_not_found")
    if source:
        identity = StepsSourceIdentity(
            source.id, source.provider_code, source.source_kind, source.source_instance_id
        )
    if not dates:
        return result(reason="no_completed_days")
    obs = GarminPayloadObservation
    query = (
        select(
            obs,
            GarminSource,
            GarminRawPayload,
            RawArtifact,
            SyncRun,
            Provider,
            IngestEvent,
            IngestBatch,
            GarminDailySummaryAcquisitionReceipt,
        )
        .outerjoin(GarminSource, GarminSource.id == obs.garmin_source_id)
        .outerjoin(GarminRawPayload, GarminRawPayload.id == obs.garmin_raw_payload_id)
        .outerjoin(RawArtifact, RawArtifact.id == GarminRawPayload.raw_artifact_id)
        .outerjoin(SyncRun, SyncRun.id == obs.sync_run_id)
        .outerjoin(Provider, Provider.id == GarminSource.provider_id)
        .outerjoin(IngestEvent, IngestEvent.id == obs.ingest_event_id)
        .outerjoin(IngestBatch, IngestBatch.id == IngestEvent.ingest_batch_id)
        .outerjoin(
            GarminDailySummaryAcquisitionReceipt,
            GarminDailySummaryAcquisitionReceipt.observation_id == obs.id,
        )
        .where(
            obs.stream_code == "daily_health",
            obs.payload_format == "json",
            obs.source_filename == "daily_summary.json",
            obs.received_at >= completion_boundary(dates[0]),
            obs.received_at <= evaluated_at,
        )
        .order_by(obs.received_at, obs.id)
        .limit(MAX_PROVENANCE + 1)
    )
    if source_id:
        query = query.where(obs.garmin_source_id == source_id)
    try:
        rows = list(session.execute(query))
    except (ValueError, TypeError, OverflowError):
        return incomplete("acquisition_receipt_unreadable")
    provenance = len(rows)
    if provenance > MAX_PROVENANCE:
        return incomplete("provenance_limit_exceeded")
    raw_ids = {row[0].garmin_raw_payload_id for row in rows}
    candidates = len(raw_ids)
    if candidates > MAX_CANDIDATES:
        return incomplete("candidate_limit_exceeded")
    if candidates > MAX_ARTIFACTS:
        return incomplete("artifact_limit_exceeded")
    decoded = {}
    by_source_day = defaultdict(list)
    identities = {}
    for observation, src, raw, artifact, run, provider, event, batch, receipt in rows:
        if monotonic() - started > MAX_READ_SECONDS:
            return incomplete("time_limit_exceeded")
        # Reprocess is positively known to be saved-byte replay, not acquisition.
        if run is not None and run.stream_code == "garmin_reprocess":
            continue
        if raw is None or artifact is None:
            return incomplete("original_not_evidenced")
        if raw.id not in decoded:
            if artifact.byte_size > MAX_ARTIFACT_BYTES:
                return incomplete("artifact_byte_limit_exceeded")
            if byte_count + artifact.byte_size > MAX_TOTAL_BYTES:
                return incomplete("total_byte_limit_exceeded")
            try:
                content = payload_store.read(
                    artifact.relative_storage_path, max_bytes=MAX_ARTIFACT_BYTES
                )
            except (OSError, ValueError):
                return incomplete("original_unreadable")
            artifacts += 1
            byte_count += len(content)
            if (
                len(content) != artifact.byte_size
                or hashlib.sha256(content).hexdigest() != raw.content_hash
                or artifact.content_hash != raw.content_hash
            ):
                return incomplete("original_integrity_mismatch")
            payload, reason = _decode(content)
            day = _calendar_date(payload) if payload is not None else None
            if day is None:
                return incomplete(reason or "original_calendar_date_unproven")
            decoded[raw.id] = (day, _metric(payload))
        day, metric = decoded[raw.id]
        received = restore_stored_utc(observation.received_at)
        if day not in dates or received < completion_boundary(day):
            continue
        reason = acquisition_reason(
            observation, src, raw, artifact, run, provider, event, batch, receipt, day
        )
        evidence = CompletedStepsEvidence(
            observation.id,
            raw.id,
            artifact.id,
            raw.content_hash,
            observation.sync_run_id,
            observation.ingest_event_id,
            received,
            metric.state.value,
            metric.value,
            reason or metric.reason,
            reason is None,
            ("daily_summary_receipt" if receipt is not None else "succeeded_run")
            if reason is None else None,
            receipt.contract_version if receipt is not None else None,
        )
        by_source_day[observation.garmin_source_id, day].append(evidence)
        if src is not None and src.provider_code == "garmin_connect":
            identities[src.id] = StepsSourceIdentity(
                src.id, src.provider_code, src.source_kind, src.source_instance_id
            )
    if monotonic() - started > MAX_READ_SECONDS:
        return incomplete("time_limit_exceeded")
    choices = tuple(identities[key] for key in sorted(identities))
    if source_id is None:
        if len(choices) != 1:
            return result(reason="source_selection_required" if choices else "source_not_evidenced")
        identity = choices[0]
        source_id = identity.source_id
    cells = []
    for day in dates:
        evidence = tuple(by_source_day.get((source_id, day), ()))
        latest = max((item.received_at for item in evidence), default=None)
        group = [item for item in evidence if item.received_at == latest]
        states = {(item.state, item.value) for item in group}
        if not group:
            state, value, reason = "unavailable", None, "no_post_boundary_acquisition"
        elif any(not item.acquisition_proven for item in group):
            state, value, reason = (
                ("ambiguous", None, "divergent_latest_acquisitions")
                if any(item.acquisition_proven for item in group)
                else ("unavailable", None, "latest_acquisition_unproven")
            )
        elif len(states) != 1:
            state, value, reason = "ambiguous", None, "divergent_latest_acquisitions"
        else:
            state, value = next(iter(states))
            reason = group[0].reason
        cells.append(
            CompletedStepsDay(
                source_id, day, completion_boundary(day), state, value, reason, latest, evidence
            )
        )
    return result(cells)
