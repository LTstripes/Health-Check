"""#376 bounded saved RHR observations, independent of UI/period aggregates.

Only the existing Garmin/Google RHR card identities are supported in this slice.
Readers seek actual persisted date groups (not calendar days), validate the whole
group, and stop at explicit work caps. No provider, canonical or schema changes.
CollectionProof is a caller-supplied, trusted, exact-scope fact, never inferred
from an empty window. Refresh chronology has provider-stream scope, not proof of
an exact source's collection success. No observation age becomes a freshness rule.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    GarminRecordMetric,
    GarminSource,
    GarminSourceRecord,
    GoogleRecordMetric,
    GoogleSource,
    GoogleSourceRecord,
)
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.garmin.overview_values import (
    latest_overview_snapshots,
    overview_metric_is_usable,
    overview_metric_matches,
)
from healthcheck.google.daily_vitals import (
    GOOGLE_DAILY_VITALS_CONTRACT_VERSION,
    get_google_daily_vital,
    project_google_daily_vital_group,
)
from healthcheck.source_freshness_read import (
    _apply_provider_terminal,
    _checkpoint,
    _provider_terminal,
)
from healthcheck.web.read_snapshot import ensure_read_snapshot

CONTRACT_VERSION = "r376-saved-rhr-read-v1"
MAX_DATE_GROUPS = 32
MAX_CANDIDATE_RECORDS = 256
MAX_SOURCE_IDENTITIES = 32
GARMIN_RHR = "resting_heart_rate_bpm"
GOOGLE_RHR = "daily_resting_heart_rate_bpm"
State = Literal[
    "exact",
    "last_eligible",
    "no_eligible_in_search",
    "search_incomplete",
    "never_collected",
    "ambiguous",
    "unavailable",
]


@dataclass(frozen=True)
class SavedValueQuery:
    provider_code: str
    metric_code: str
    requested_start_date: date
    requested_end_date: date
    evaluated_at_utc: datetime
    evaluation_local_date: date
    mode: Literal["default_latest", "explicit_period"] = "explicit_period"
    source_id: str | None = None
    history_start_date: date | None = None
    max_date_groups: int = MAX_DATE_GROUPS
    max_candidate_records: int = MAX_CANDIDATE_RECORDS

    def validate(self) -> None:
        if (self.provider_code, self.metric_code) not in {
            ("garmin_connect", GARMIN_RHR),
            ("google_health", GOOGLE_RHR),
        }:
            raise ValueError("unsupported saved-value metric identity")
        if self.mode not in {"default_latest", "explicit_period"}:
            raise ValueError("unsupported saved-value mode")
        for value in (
            self.requested_start_date,
            self.requested_end_date,
            self.evaluation_local_date,
        ):
            if type(value) is not date:
                raise ValueError("saved-value dates must be civil dates")
        if self.requested_end_date < self.requested_start_date:
            raise ValueError("requested window is reversed")
        if self.mode == "default_latest" and self.requested_start_date != self.requested_end_date:
            raise ValueError("default_latest is an observation card, not a period aggregate")
        if self.history_start_date is not None:
            if type(self.history_start_date) is not date:
                raise ValueError("history start must be a civil date")
            if self.mode != "default_latest" or self.history_start_date > self.requested_end_date:
                raise ValueError("history bound cannot change an explicit period")
        if not isinstance(self.evaluated_at_utc, datetime) or (
            self.evaluated_at_utc.tzinfo is None or self.evaluated_at_utc.utcoffset() is None
        ):
            raise ValueError("evaluation timestamp must be timezone-aware")
        for value, maximum in (
            (self.max_date_groups, MAX_DATE_GROUPS),
            (self.max_candidate_records, MAX_CANDIDATE_RECORDS),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("invalid saved-value work cap")
        if self.source_id is not None and not self.source_id.strip():
            raise ValueError("source ID must not be blank")


@dataclass(frozen=True)
class CollectionProof:
    """Trusted external collection fact, bound to this exact source and metric."""

    provider_code: str
    source_id: str
    metric_code: str
    evidence_ref: str


@dataclass(frozen=True)
class SourceIdentity:
    source_id: str
    provider_code: str
    source_instance_id: str
    source_kind: str
    device_attributed: bool
    device_code: str | None
    device_model: str | None


@dataclass(frozen=True)
class SavedObservation:
    value: float
    unit: str
    source_local_date: date
    temporal_precision: str
    source_timestamp_utc: datetime | None
    observation_age_days: int
    is_zero: bool
    record_id: str
    metric_row_id: str
    raw_payload_id: str
    observation_id: str | None
    ingest_event_id: str | None
    field_path: str
    record_status: str
    normalization_version: str
    eligibility_rule_version: str


@dataclass(frozen=True)
class SavedExclusion:
    source_local_date: date | None
    reason: str
    candidate_count: int | None
    record_ids: tuple[str, ...] = ()
    metric_states: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchEvidence:
    start_date: date | None
    end_date: date
    date_group_cap: int
    candidate_record_cap: int
    groups_examined: int = 0
    records_examined: int = 0
    complete: bool = False
    history_exhausted: bool = False
    reason: str | None = None
    incomplete_group_date: date | None = None


@dataclass(frozen=True)
class RefreshChronology:
    scope: str
    last_attempt_utc: datetime | None = None
    last_successful_refresh_utc: datetime | None = None
    terminal_status: str | None = None
    # This reader does not evaluate the accepted freshness policy/coverage.
    freshness_state: str = "unknown"
    reason: str = "freshness_not_evaluated"


@dataclass(frozen=True)
class SavedValueResult:
    contract_version: str
    state: State
    reason: str | None
    query: SavedValueQuery
    source_identity: SourceIdentity | None
    available_sources: tuple[SourceIdentity, ...]
    observation: SavedObservation | None
    newer_exclusions: tuple[SavedExclusion, ...]
    search: SearchEvidence
    refresh: RefreshChronology
    observed_in_persisted_history: bool | None = None
    collection_evidence_ref: str | None = None
    acquisition_coverage_state: str = "unknown"
    acquisition_coverage_reason: str = "not_evaluated_by_saved_value_reader"
    origin_state: str = "unknown"
    snapshot_as_of: str | None = None
    age_policy: str = "not_configured"

    def as_dict(self) -> dict:
        """JSON DTO; preserve civil dates instead of fabricating midnight instants."""

        def encode(value):
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            if isinstance(value, dict):
                return {key: encode(item) for key, item in value.items()}
            if isinstance(value, (tuple, list)):
                return [encode(item) for item in value]
            return value

        body = encode(asdict(self))
        body["metric_identity"] = {
            "metric_code": self.query.metric_code,
            "unit": "bpm",
            "stream_code": "daily_health"
            if self.query.provider_code == "garmin_connect"
            else "daily_resting_hr",
            "meaning": "provider_resting_heart_rate_snapshot"
            if self.query.provider_code == "garmin_connect"
            else "provider_daily_resting_heart_rate",
        }
        return body


def _source_identity(source) -> SourceIdentity:
    return SourceIdentity(
        source.id,
        source.provider_code,
        source.source_instance_id,
        source.source_kind,
        bool(source.device_attributed),
        source.device_code,
        source.device_model,
    )


def _refresh(session, source, query) -> RefreshChronology:
    garmin = query.provider_code == "garmin_connect"
    provider = "garmin" if garmin else "google"
    code = "resting_heart_rate" if garmin else "google:refresh:daily_resting_hr:list:any"
    attempt, success, terminal = _apply_provider_terminal(
        *_checkpoint(session, source.provider_id, code),
        _provider_terminal(session, source.provider_id, provider),
    )
    return RefreshChronology(f"provider_stream:{provider}:{code}", attempt, success, terminal)


def _record_scope(query, source_id):
    """Leading source/stream keys use existing date indexes for bounded seeks."""
    if query.provider_code == "google_health":
        model = GoogleSourceRecord
        conditions = (
            model.google_source_id == source_id,
            model.stream_code == get_google_daily_vital(query.metric_code).stream_code,
        )
    else:
        model = GarminSourceRecord
        conditions = (
            model.garmin_source_id == source_id,
            model.stream_code == "daily_health",
            or_(
                model.surface_code.is_(None),
                model.surface_code.in_(("daily_summary", "resting_heart_rate")),
            ),
        )
    return model, conditions


def _project_group(session, query, records):
    model = GoogleRecordMetric if query.provider_code == "google_health" else GarminRecordMetric
    metrics = list(
        session.scalars(
            select(model).where(
                model.record_id.in_([record.id for record in records]),
                model.metric_code == query.metric_code,
            )
        )
    )
    if query.provider_code == "google_health":
        point = project_google_daily_vital_group(
            get_google_daily_vital(query.metric_code),
            records[0].source_local_date,
            records,
            {row.record_id: row for row in metrics},
        )
        if not point.eligible:
            return (
                None,
                None,
                point.exclusion_basis or point.state,
                tuple(row.state for row in metrics),
            )
        record = records[0]
        metric = next(row for row in metrics if row.id == point.metric_row_id)
        return record, metric, None, (point.state,)
    by_id = {record.id: record for record in records}
    candidates = [
        (by_id[row.record_id], row)
        for row in metrics
        if overview_metric_matches(
            by_id[row.record_id], row, code=GARMIN_RHR, capability="resting_heart_rate"
        )
    ]
    states = tuple(row.state for _, row in candidates)
    if not candidates:
        return None, None, "metric_row_missing", states
    selected = latest_overview_snapshots(candidates)
    if len(selected) != 1:
        return None, None, "ambiguous_same_date_records", states
    record, metric = selected[0]
    if not overview_metric_is_usable(record, metric, code=GARMIN_RHR, unit="bpm"):
        reason = (
            f"metric_{metric.state}"
            if metric.state != "value"
            else "metric_unit_mismatch"
            if metric.unit != "bpm"
            else f"record_{record.record_status}"
            if record.record_status not in {"ok", "partial"}
            else "metric_value_invalid"
        )
        return None, None, reason, states
    return record, metric, None, states


def read_saved_rhr(
    session: Session,
    query: SavedValueQuery,
    *,
    never_collected: CollectionProof | None = None,
) -> SavedValueResult:
    """Read a bounded observation, never move an explicit date/window or source.

    `exact` means the observation belongs to the unchanged requested window;
    `last_eligible` is possible only in an explicitly opted-in default card.
    Work caps stop before projecting an incomplete same-date/source group.
    A matched result proves newest eligibility for the search, not that every
    historical record was read. A limited empty search proves no global absence.
    """
    query.validate()
    lower = (
        query.requested_start_date if query.mode == "explicit_period" else query.history_start_date
    )
    search = SearchEvidence(
        lower, query.requested_end_date, query.max_date_groups, query.max_candidate_records
    )
    result = SavedValueResult(
        CONTRACT_VERSION,
        "unavailable",
        None,
        query,
        None,
        (),
        None,
        (),
        search,
        RefreshChronology("not_resolved"),
    )
    # Pending writes are a caller error, not a legitimate read/unavailable DTO.
    if session.new or session.dirty or session.deleted:
        # Reuse the established error and do not demote pending writer state.
        ensure_read_snapshot(session)
    try:
        ensure_read_snapshot(session)
        return _read_saved_rhr(session, query, result, never_collected)
    except SQLAlchemyError:
        return replace(
            result,
            reason="saved_value_read_failed",
            search=replace(search, reason="saved_value_read_failed"),
        )


def _read_saved_rhr(session, query, result, proof):
    source_model = GarminSource if query.provider_code == "garmin_connect" else GoogleSource
    if query.source_id is not None:
        source = session.get(source_model, query.source_id)
        if source is None or source.provider_code != query.provider_code:
            return replace(result, reason="source_not_found")
        sources = [source]
    else:
        sources = list(
            session.scalars(
                select(source_model)
                .where(
                    source_model.provider_code == query.provider_code,
                )
                .order_by(source_model.id)
                .limit(MAX_SOURCE_IDENTITIES + 1)
            )
        )
        if len(sources) > MAX_SOURCE_IDENTITIES:
            # No truncated source list is represented as a complete conflict group.
            return replace(
                result,
                state="search_incomplete",
                reason="source_inventory_cap",
                search=replace(result.search, reason="source_inventory_cap"),
            )
        identities = tuple(_source_identity(source) for source in sources)
        if len(sources) != 1:
            return replace(
                result,
                state="ambiguous" if sources else "unavailable",
                reason="source_selection_required" if sources else "source_not_found",
                available_sources=identities,
                search=replace(result.search, complete=True),
            )
        source = sources[0]
    if proof is not None and (
        (proof.provider_code, proof.source_id, proof.metric_code)
        != (query.provider_code, source.id, query.metric_code)
        or not proof.evidence_ref.strip()
    ):
        raise ValueError(
            "collection proof must have evidence and match the exact selected identity"
        )
    model, identity_conditions = _record_scope(query, source.id)
    # This indexed existence probe includes old, retired, future and undated
    # acquisition evidence. An empty search cannot become never_collected.
    observed = session.scalar(select(model.id).where(*identity_conditions).limit(1)) is not None
    result = replace(
        result,
        source_identity=_source_identity(source),
        available_sources=tuple(_source_identity(item) for item in sources),
        refresh=_refresh(session, source, query),
        observed_in_persisted_history=observed,
        collection_evidence_ref=proof.evidence_ref if proof else None,
    )
    conditions = (*identity_conditions, model.projection_status == "current")
    dated = conditions
    if query.provider_code == "google_health":
        dated = (*dated, model.temporal_precision == "date")
    dated = (*dated, model.source_local_date.is_not(None))
    unplaced = session.scalar(
        select(model.id)
        .where(
            *conditions,
            model.source_local_date.is_(None),
        )
        .limit(1)
    )
    exclusions = (
        ()
        if unplaced is None
        # An indexed existence probe proves presence, not a complete group/count.
        else (SavedExclusion(None, "ineligible_temporal_coordinate", None),)
    )
    before = None
    groups = records_count = 0
    while True:
        bounded = (*dated, model.source_local_date <= query.requested_end_date)
        if before is not None:
            bounded = (*bounded, model.source_local_date < before)
        if result.search.start_date is not None:
            bounded = (*bounded, model.source_local_date >= result.search.start_date)
        day = session.scalar(
            select(model.source_local_date)
            .where(*bounded)
            .order_by(model.source_local_date.desc())
            .limit(1)
        )
        if day is None:
            state: State = (
                "never_collected"
                if proof is not None and not observed
                else "ambiguous"
                if any("ambiguous" in item.reason for item in exclusions)
                else "no_eligible_in_search"
            )
            return replace(
                result,
                state=state,
                reason=state,
                newer_exclusions=exclusions,
                search=replace(
                    result.search,
                    complete=True,
                    history_exhausted=result.search.start_date is None,
                    groups_examined=groups,
                    records_examined=records_count,
                ),
            )
        if groups >= query.max_date_groups or records_count >= query.max_candidate_records:
            return replace(
                result,
                state="search_incomplete",
                reason="search_work_cap",
                newer_exclusions=exclusions,
                search=replace(
                    result.search,
                    reason="search_work_cap",
                    groups_examined=groups,
                    records_examined=records_count,
                ),
            )
        remaining = query.max_candidate_records - records_count
        records = list(
            session.scalars(
                select(model)
                .where(
                    *dated,
                    model.source_local_date == day,
                )
                .limit(remaining + 1)
            )
        )
        if len(records) > remaining:
            return replace(
                result,
                state="search_incomplete",
                reason="candidate_group_cap",
                newer_exclusions=exclusions,
                search=replace(
                    result.search,
                    reason="candidate_group_cap",
                    incomplete_group_date=day,
                    groups_examined=groups,
                    records_examined=records_count + len(records),
                ),
            )
        groups += 1
        records_count += len(records)
        record, metric, reason, states = _project_group(session, query, records)
        stamp = restore_stored_utc(record.source_timestamp_utc) if record else None
        if record is not None and (
            day > query.evaluation_local_date
            or (stamp is not None and stamp > query.evaluated_at_utc.astimezone(UTC))
        ):
            record, reason = None, "future_chronology"
        if record is not None:
            observation = SavedObservation(
                float(metric.value_number),
                metric.unit,
                day,
                record.temporal_precision,
                stamp,
                (query.evaluation_local_date - day).days,
                metric.value_number == 0,
                record.id,
                metric.id,
                record.raw_payload_id,
                getattr(record, "observation_id", None),
                record.ingest_event_id,
                metric.field_path,
                record.record_status,
                record.normalization_contract_version,
                GOOGLE_DAILY_VITALS_CONTRACT_VERSION
                if query.provider_code == "google_health"
                else "r340-garmin-overview-rhr-v1",
            )
            return replace(
                result,
                state="exact" if query.requested_start_date <= day else "last_eligible",
                reason=None,
                observation=observation,
                newer_exclusions=exclusions,
                search=replace(
                    result.search,
                    complete=True,
                    groups_examined=groups,
                    records_examined=records_count,
                ),
            )
        exclusions += (
            SavedExclusion(day, reason, len(records), tuple(row.id for row in records), states),
        )
        # Seek the preceding observed group, never enumerate missing calendar days.
        before = day
