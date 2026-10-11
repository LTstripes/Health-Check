"""Bounded read-only access to materialized observed Steps; no replay or latest selection."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    GarminPayloadObservation,
    GarminRawPayload,
    GarminRecordMetric,
    GarminSource,
    GarminSourceRecord,
    RawArtifact,
)
from healthcheck.garmin.observed_steps import CONTRACT_VERSION, METRIC_CODE
from healthcheck.web.read_snapshot import ensure_read_snapshot

READ_CONTRACT_VERSION = "garmin-observed-daily-steps-window-v1"
MAX_WINDOW_DAYS = 366
MAX_CANDIDATES = 4096
MAX_PROVENANCE = 4096
_INTEGER = re.compile(r"(?:0|[1-9][0-9]*)\Z")


@dataclass(frozen=True)
class StepsSourceIdentity:
    source_id: str
    provider_code: str
    source_kind: str
    source_instance_id: str


@dataclass(frozen=True)
class StepsRecordEvidence:
    record_id: str
    metric_row_id: str | None
    raw_payload_id: str
    raw_artifact_id: str | None
    content_hash: str | None
    observation_ids: tuple[str, ...]
    ingest_event_id: str | None
    normalization_version: str
    reconciliation_version: str
    projection_status: str
    metric_state: str | None
    metric_reason: str | None
    value: int | None


@dataclass(frozen=True)
class StepsDayCell:
    source_id: str
    calendar_date: date
    state: str
    value: int | None = None
    reason: str | None = None
    evidence: tuple[StepsRecordEvidence, ...] = ()
    search_complete: bool = True
    metric_code: str = METRIC_CODE
    unit: str = "steps"
    attribution: str = "account"
    coverage: str = "unknown"
    device: str = "unknown"
    timezone: str = "unknown"
    finality: str = "unknown"


@dataclass(frozen=True)
class StepsWindowResult:
    source_id: str
    start_date: date
    end_date: date
    source_identity: StepsSourceIdentity | None
    cells: tuple[StepsDayCell, ...]
    search_complete: bool
    candidates_examined: int
    provenance_examined: int
    reason: str | None = None
    contract_version: str = READ_CONTRACT_VERSION


def _exact_value(metric: GarminRecordMetric | None) -> int | None:
    if (
        metric is None
        or metric.state != "value"
        or metric.value_number is not None
        or metric.collection_json is not None
        or not isinstance(metric.value_text, str)
        or not _INTEGER.fullmatch(metric.value_text)
    ):
        return None
    try:
        return int(metric.value_text)
    except ValueError:
        return None


def _record_reason(record, metric, raw, artifact, observation_ids, artifact_ids) -> str | None:
    """Verify persisted links and contract identity, without opening artifact bytes."""
    if (
        record.normalization_contract_version != CONTRACT_VERSION
        or record.reconciliation_contract_version != CONTRACT_VERSION
        or record.temporal_precision != "date"
        or record.source_field != "calendarDate"
        or record.projection_status != "current"
    ):
        return "unsupported_materialized_record"
    if metric is None:
        return "metric_row_not_evidenced"
    if (
        metric.capability_code != METRIC_CODE
        or metric.field_path != "totalSteps"
        or metric.unit != "steps"
        or metric.source_device_attributed
    ):
        return "unsupported_materialized_metric"
    if metric.state == "missing" and metric.reason != "field_absent_in_payload":
        return "leaf_absence_not_evidenced"
    if (
        raw is None
        or artifact is None
        or raw.garmin_source_id != record.garmin_source_id
        or raw.stream_code != "daily_health"
        or raw.payload_format != "json"
        or artifact.content_hash != raw.content_hash
        or (artifact_ids and artifact_ids != {artifact.id})
    ):
        return "provenance_mismatch"
    if not observation_ids:
        return "acquisition_not_evidenced"
    return None


def read_observed_steps_window(
    session: Session, *, source_id: str, start_date: date, end_date: date
) -> StepsWindowResult:
    """Read exact-source daily cells from existing projections in one caller-owned snapshot.

    Candidate/history rows include retired and unsupported Steps records, so these
    cannot silently disappear. Two independent cap+1 reads cover candidate records
    (with their singleton metric/raw/artifact links) and acquisition observations.
    Ascending date order proves earlier complete groups even if a later group exceeds
    either cap. An unexamined or truncated group never yields a numeric answer.
    """
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("an explicit exact Garmin source ID is required")
    if type(start_date) is not date or type(end_date) is not date:
        raise ValueError("Steps window requires civil dates")
    days = (end_date - start_date).days + 1
    if not 1 <= days <= MAX_WINDOW_DAYS:
        raise ValueError("Steps window must contain 1 to 366 inclusive days")
    ensure_read_snapshot(session)
    source = session.get(GarminSource, source_id)
    dates = tuple(start_date + timedelta(days=index) for index in range(days))
    if source is None or source.provider_code != "garmin_connect":
        return StepsWindowResult(
            source_id,
            start_date,
            end_date,
            None,
            tuple(
                StepsDayCell(source_id, day, "projection_unavailable", reason="source_not_found")
                for day in dates
            ),
            True,
            0,
            0,
            "source_not_found",
        )
    identity = StepsSourceIdentity(
        source.id, source.provider_code, source.source_kind, source.source_instance_id
    )
    record = GarminSourceRecord
    rows = list(
        session.execute(
            select(record, GarminRecordMetric, GarminRawPayload, RawArtifact)
            .outerjoin(
                GarminRecordMetric,
                and_(
                    GarminRecordMetric.record_id == record.id,
                    GarminRecordMetric.metric_code == METRIC_CODE,
                ),
            )
            .outerjoin(GarminRawPayload, GarminRawPayload.id == record.raw_payload_id)
            .outerjoin(RawArtifact, RawArtifact.id == GarminRawPayload.raw_artifact_id)
            .where(
                record.garmin_source_id == source_id,
                record.stream_code == "daily_health",
                record.surface_code == METRIC_CODE,
                record.source_local_date.between(start_date, end_date),
            )
            .order_by(record.source_local_date, record.id)
            .limit(MAX_CANDIDATES + 1)
        )
    )
    candidate_cutoff = rows[-1][0].source_local_date if len(rows) > MAX_CANDIDATES else None
    retained = rows[:MAX_CANDIDATES]
    complete_candidates = [
        row
        for row in retained
        if candidate_cutoff is None or row[0].source_local_date < candidate_cutoff
    ]
    # Group raw identities before joining acquisitions: repeated references must
    # not multiply observation rows or spend the independent provenance budget.
    observations = []
    if complete_candidates:
        raw_dates = (
            select(
                record.raw_payload_id.label("raw_id"),
                func.min(record.source_local_date).label("day"),
            )
            .where(record.id.in_([row[0].id for row in complete_candidates]))
            .group_by(record.raw_payload_id)
            .subquery()
        )
        observations = list(
            session.execute(
                select(GarminPayloadObservation, raw_dates.c.day)
                .join(
                    raw_dates, raw_dates.c.raw_id == GarminPayloadObservation.garmin_raw_payload_id
                )
                .where(
                    GarminPayloadObservation.garmin_source_id == source_id,
                    GarminPayloadObservation.stream_code == "daily_health",
                    GarminPayloadObservation.payload_format == "json",
                    GarminPayloadObservation.source_filename == "daily_summary.json",
                )
                .order_by(raw_dates.c.day, GarminPayloadObservation.id)
                .limit(MAX_PROVENANCE + 1)
            )
        )
    provenance_cutoff = observations[-1][1] if len(observations) > MAX_PROVENANCE else None
    by_raw = defaultdict(list)
    for observation, _day in observations[:MAX_PROVENANCE]:
        by_raw[observation.garmin_raw_payload_id].append(observation)
    observation_ids = {raw_id: tuple(item.id for item in items) for raw_id, items in by_raw.items()}
    artifact_ids = {
        raw_id: {item.raw_artifact_id for item in items} for raw_id, items in by_raw.items()
    }
    by_day = defaultdict(list)
    for row in retained:
        by_day[row[0].source_local_date].append(row)
    cells = []
    for day in dates:
        reason = (
            "candidate_limit_exceeded"
            if candidate_cutoff is not None and day >= candidate_cutoff
            else "provenance_limit_exceeded"
            if provenance_cutoff is not None and day >= provenance_cutoff and by_day[day]
            else None
        )
        evidence = []
        states = set()
        values = set()
        for record, metric, raw, artifact in by_day[day]:
            acquisitions = observation_ids.get(record.raw_payload_id, ())
            value = _exact_value(metric)
            evidence.append(
                StepsRecordEvidence(
                    record.id,
                    metric.id if metric else None,
                    record.raw_payload_id,
                    artifact.id if artifact else None,
                    raw.content_hash if raw else None,
                    acquisitions,
                    record.ingest_event_id,
                    record.normalization_contract_version,
                    record.reconciliation_contract_version,
                    record.projection_status,
                    metric.state if metric else None,
                    metric.reason if metric else None,
                    value,
                )
            )
            reason = reason or _record_reason(
                record,
                metric,
                raw,
                artifact,
                acquisitions,
                artifact_ids.get(record.raw_payload_id, set()),
            )
            if metric is not None:
                states.add("invalid" if metric.state == "value" and value is None else metric.state)
                if value is not None:
                    values.add(value)
        if reason:
            state, value = "search_incomplete", None
        elif len(values) > 1:
            state, value, reason = "ambiguous", None, "divergent_saved_observations"
        elif values:
            state, value = "value", next(iter(values))
        elif len(states) == 1:
            state, value, reason = next(iter(states)), None, "no_valid_saved_count"
        elif evidence:
            state, value, reason = "unavailable", None, "no_valid_saved_count"
        else:
            state, value, reason = "projection_unavailable", None, "not_evidenced"
        cells.append(
            StepsDayCell(
                source_id, day, state, value, reason, tuple(evidence), state != "search_incomplete"
            )
        )
    complete = all(cell.search_complete for cell in cells)
    return StepsWindowResult(
        source_id,
        start_date,
        end_date,
        identity,
        tuple(cells),
        complete,
        len(rows),
        len(observations),
        None if complete else "search_incomplete",
    )
