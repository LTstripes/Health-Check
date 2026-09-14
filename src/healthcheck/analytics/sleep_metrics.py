"""R05 deterministic comparison metrics over the accepted persisted pairing.

This module is intentionally a read-only projection.  It never calls a
provider, performs canonical selection, writes a run, or changes the source
schema.  Pairing is delegated to the accepted ``sleep_pairing`` surface; every
metric then makes its own eligibility decision and freezes the exact persisted
inputs needed by the next R05 stage.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.analytics.sleep_pairing import (
    SleepPair,
    SleepPairingQuery,
    SleepPairingResult,
    SleepSourceEligibility,
    _garmin_source_eligibility,
    _google_source_eligibility,
    read_persisted_sleep_pairing,
)
from healthcheck.db.models import (
    GarminDailyRecord,
    GarminPayloadObservation,
    GarminRawPayload,
    GarminRecordMetric,
    GarminSleepRecord,
    GarminSleepStageInterval,
    GarminSource,
    GarminSourceRecord,
    GooglePayloadObservation,
    GoogleRawPayload,
    GoogleRecordMetric,
    GoogleRecordSourceEvidence,
    GoogleSleepFieldState,
    GoogleSleepInterval,
    GoogleSleepRecord,
    GoogleSource,
    GoogleSourceRecord,
)
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.garmin.analytic_contract import stable_manifest_hash

R05_SLEEP_METRIC_PROJECTION_CONTRACT_VERSION = "r05-02-sleep-metric-projection-v1"
R05_SLEEP_METRIC_PROJECTION_RULE_VERSION = "r05-02-sleep-metric-rules-v1"
R05_SLEEP_METRIC_PROJECTION_ALGORITHM = "r05-02-sleep-metric-projection-v1"

# These are the only comparable/overlay cells emitted by this surface.  The
# source metric names deliberately stay visible in each metric definition.
SLEEP_COMPARISON_METRIC_CODES: tuple[str, ...] = (
    "sleep_duration_asleep_seconds",
    "sleep_time_in_bed_seconds",
    "sleep_start_at",
    "sleep_end_at",
    "sleep_stage_light_seconds",
    "sleep_stage_deep_seconds",
    "sleep_stage_rem_seconds",
    "sleep_awake_waso_seconds",
    "resting_heart_rate_bpm",
    "spo2_daily_average_pct",
)
SLEEP_CANONICAL_METRIC_CODES: tuple[str, ...] = SLEEP_COMPARISON_METRIC_CODES[:8]
SLEEP_AUXILIARY_METRIC_CODES: tuple[str, ...] = SLEEP_COMPARISON_METRIC_CODES[8:]

# These identities remain explicitly excluded from v1.  They are reported in
# the result metadata, never silently projected as comparable sleep metrics.
EXCLUDED_SLEEP_METRIC_CODES: tuple[str, ...] = (
    "sleep_score",
    "sleep_readiness_score",
    "hrv_weekly_average_ms",
    "daily_hrv_rmssd_ms",
    "hrv",
    "respiration_bpm",
    "respiratory_rate_sleep",
    "daily_respiratory_rate",
)
R05_EXCLUDED_METRIC_CODES = EXCLUDED_SLEEP_METRIC_CODES

_CURRENT = "current"
_VALUE = "value"
_MISSING = "missing"
_NULL = "null"
_INVALID = "invalid"
_STAGES = "STAGES"
_CLASSIC = "CLASSIC"
_UTC_INSTANT = "UTC instant"
_TIMING_VARIANTS = (_CLASSIC, _STAGES)
_STAGE_VARIANTS = (_STAGES,)
_AUX_VARIANTS = ("DAILY",)
_GOOGLE_STAGE_SUCCESS = "SUCCEEDED"
_STAGE_TARGETS = frozenset({"LIGHT", "DEEP", "REM", "AWAKE"})


@dataclass(frozen=True, slots=True)
class SleepMetricDefinition:
    """Frozen meaning and source identity of one R05 comparison metric."""

    metric_code: str
    unit: str
    difference_unit: str
    canonical_candidate: bool
    comparison_kind: str
    source_metric_codes: tuple[str, ...]
    variants: tuple[str, ...]
    description: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric_code": self.metric_code,
            "unit": self.unit,
            "difference_unit": self.difference_unit,
            "canonical_candidate": self.canonical_candidate,
            "comparison_kind": self.comparison_kind,
            "source_metric_codes": list(self.source_metric_codes),
            "variants": list(self.variants),
            "description": self.description,
        }


SLEEP_METRIC_DEFINITIONS: dict[str, SleepMetricDefinition] = {
    "sleep_duration_asleep_seconds": SleepMetricDefinition(
        metric_code="sleep_duration_asleep_seconds",
        unit="seconds",
        difference_unit="seconds",
        canonical_candidate=True,
        comparison_kind="sleep_session",
        source_metric_codes=("sleep_duration_seconds", "sleep_summary_minutes_asleep"),
        variants=_TIMING_VARIANTS,
        description="Asleep duration; Google minutesAsleep is converted to seconds.",
    ),
    "sleep_time_in_bed_seconds": SleepMetricDefinition(
        metric_code="sleep_time_in_bed_seconds",
        unit="seconds",
        difference_unit="seconds",
        canonical_candidate=True,
        comparison_kind="sleep_session",
        source_metric_codes=("sleep_summary_minutes_in_sleep_period", "sleep_stages"),
        variants=_TIMING_VARIANTS,
        description="Time in bed only with an explicit boundary or complete interval evidence.",
    ),
    "sleep_start_at": SleepMetricDefinition(
        metric_code="sleep_start_at",
        unit=_UTC_INSTANT,
        difference_unit="seconds",
        canonical_candidate=True,
        comparison_kind="sleep_session",
        source_metric_codes=("sleep_session_start", "sleep_stage_start"),
        variants=_TIMING_VARIANTS,
        description="Comparable UTC sleep start instant; local/date-only evidence is excluded.",
    ),
    "sleep_end_at": SleepMetricDefinition(
        metric_code="sleep_end_at",
        unit=_UTC_INSTANT,
        difference_unit="seconds",
        canonical_candidate=True,
        comparison_kind="sleep_session",
        source_metric_codes=("sleep_session_end", "sleep_stage_end"),
        variants=_TIMING_VARIANTS,
        description="Comparable UTC sleep end instant from an explicit persisted boundary.",
    ),
    "sleep_stage_light_seconds": SleepMetricDefinition(
        metric_code="sleep_stage_light_seconds",
        unit="seconds",
        difference_unit="seconds",
        canonical_candidate=True,
        comparison_kind="stage_total",
        source_metric_codes=("sleep_stages", "sleep_summary_stages"),
        variants=_STAGE_VARIANTS,
        description="LIGHT total; typed STAGES intervals or an explicit summary-only fallback.",
    ),
    "sleep_stage_deep_seconds": SleepMetricDefinition(
        metric_code="sleep_stage_deep_seconds",
        unit="seconds",
        difference_unit="seconds",
        canonical_candidate=True,
        comparison_kind="stage_total",
        source_metric_codes=("sleep_stages", "sleep_summary_stages"),
        variants=_STAGE_VARIANTS,
        description="DEEP total; typed STAGES intervals or an explicit summary-only fallback.",
    ),
    "sleep_stage_rem_seconds": SleepMetricDefinition(
        metric_code="sleep_stage_rem_seconds",
        unit="seconds",
        difference_unit="seconds",
        canonical_candidate=True,
        comparison_kind="stage_total",
        source_metric_codes=("sleep_stages", "sleep_summary_stages"),
        variants=_STAGE_VARIANTS,
        description="REM total; typed STAGES intervals or an explicit summary-only fallback.",
    ),
    "sleep_awake_waso_seconds": SleepMetricDefinition(
        metric_code="sleep_awake_waso_seconds",
        unit="seconds",
        difference_unit="seconds",
        canonical_candidate=True,
        comparison_kind="stage_total",
        source_metric_codes=("sleep_stages", "sleep_summary_stages"),
        variants=_STAGE_VARIANTS,
        description="Awake-within-session total; out-of-bed segments are not WASO.",
    ),
    "resting_heart_rate_bpm": SleepMetricDefinition(
        metric_code="resting_heart_rate_bpm",
        unit="bpm",
        difference_unit="bpm",
        canonical_candidate=False,
        comparison_kind="auxiliary_overlay",
        source_metric_codes=("resting_heart_rate_bpm", "daily_resting_heart_rate_bpm"),
        variants=_AUX_VARIANTS,
        description="Daily RHR overlay with its own same-date source eligibility.",
    ),
    "spo2_daily_average_pct": SleepMetricDefinition(
        metric_code="spo2_daily_average_pct",
        unit="%",
        difference_unit="percentage_points",
        canonical_candidate=False,
        comparison_kind="auxiliary_overlay",
        source_metric_codes=(
            "spo2_daily_average",
            "daily_oxygen_saturation_average_percentage",
        ),
        variants=_AUX_VARIANTS,
        description="Daily SpO2 overlay; trailing-window and sample values are excluded.",
    ),
}


def get_sleep_metric_definition(metric_code: str) -> SleepMetricDefinition:
    """Return the frozen R05 definition or reject an unknown projection code."""

    try:
        return SLEEP_METRIC_DEFINITIONS[metric_code]
    except KeyError as exc:
        raise ValueError(f"unknown R05 sleep metric code: {metric_code}") from exc


@dataclass(frozen=True, slots=True)
class SleepMetricEvidenceRef:
    """Metadata-only immutable evidence locator; raw bodies are never copied."""

    provider: str
    source_id: str | None
    source_instance_id: str | None
    source_class: str | None
    source_kind: str | None
    record_id: str | None
    idempotency_key: str | None
    raw_payload_id: str | None
    content_hash: str | None
    observation_id: str | None
    observation_key: str | None
    metric_row_ids: tuple[str, ...] = ()
    field_state_row_id: str | None = None
    interval_ids: tuple[str, ...] = ()
    interval_snapshots: tuple[Mapping[str, object], ...] = ()
    observation_candidates: tuple[str, ...] = ()
    field_paths: tuple[str, ...] = ()
    attribution: Mapping[str, object] = field(default_factory=dict)
    exclusion_basis: str | None = None
    immutable: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "source_id": self.source_id,
            "source_instance_id": self.source_instance_id,
            "source_class": self.source_class,
            "source_kind": self.source_kind,
            "record_id": self.record_id,
            "idempotency_key": self.idempotency_key,
            "raw_payload_id": self.raw_payload_id,
            "content_hash": self.content_hash,
            "observation_id": self.observation_id,
            "observation_key": self.observation_key,
            "metric_row_ids": list(self.metric_row_ids),
            "field_state_row_id": self.field_state_row_id,
            "interval_ids": list(self.interval_ids),
            "interval_snapshots": [dict(item) for item in self.interval_snapshots],
            "observation_candidates": list(self.observation_candidates),
            "field_paths": list(self.field_paths),
            "attribution": dict(self.attribution),
            "exclusion_basis": self.exclusion_basis,
            "immutable": self.immutable,
        }


@dataclass(frozen=True, slots=True)
class SleepMetricInputDTO:
    """One side of one metric cell, including eligibility separate from state."""

    provider: str
    record_id: str | None
    state: str
    value: int | float | str | None
    unit: str | None
    field_path: str | None
    reason: str | None
    eligible: bool
    is_zero: bool
    variant: str | None
    comparison_basis: str | None
    evidence: SleepMetricEvidenceRef
    exclusion_basis: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "record_id": self.record_id,
            "state": self.state,
            "value": self.value,
            "unit": self.unit,
            "field_path": self.field_path,
            "reason": self.reason,
            "eligible": self.eligible,
            "is_zero": self.is_zero,
            "variant": self.variant,
            "comparison_basis": self.comparison_basis,
            "evidence": self.evidence.as_dict(),
            "exclusion_basis": self.exclusion_basis,
        }


@dataclass(frozen=True, slots=True)
class SleepMetricInputManifest:
    """Immutable per-pair/per-metric input manifest for downstream #102."""

    contract_version: str
    rule_version: str
    algorithm: str
    metric_definition: SleepMetricDefinition
    pair: Mapping[str, object]
    variant: str | None
    garmin: SleepMetricInputDTO
    google: SleepMetricInputDTO
    status: str
    difference: int | float | None
    difference_unit: str
    reason: str | None
    exclusion_basis: str | None
    manifest_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "rule_version": self.rule_version,
            "algorithm": self.algorithm,
            "metric_definition": self.metric_definition.as_dict(),
            "pair": dict(self.pair),
            "variant": self.variant,
            "garmin": self.garmin.as_dict(),
            "google": self.google.as_dict(),
            "status": self.status,
            "difference": self.difference,
            "difference_unit": self.difference_unit,
            "reason": self.reason,
            "exclusion_basis": self.exclusion_basis,
            "manifest_hash": self.manifest_hash,
        }


@dataclass(frozen=True, slots=True)
class SleepMetricProjection:
    """One deterministic Google-minus-Garmin metric cell for an accepted pair."""

    pair: SleepPair
    metric_code: str
    variant: str | None
    status: str
    reason: str | None
    garmin: SleepMetricInputDTO
    google: SleepMetricInputDTO
    difference: int | float | None
    difference_unit: str
    comparable: bool
    manifest: SleepMetricInputManifest

    @property
    def input_manifest_hash(self) -> str:
        return self.manifest.manifest_hash

    def as_dict(self) -> dict[str, Any]:
        return {
            "pair": self.pair.as_dict(),
            "metric_code": self.metric_code,
            "variant": self.variant,
            "status": self.status,
            "reason": self.reason,
            "garmin": self.garmin.as_dict(),
            "google": self.google.as_dict(),
            "difference": self.difference,
            "difference_unit": self.difference_unit,
            "comparable": self.comparable,
            "input_manifest_hash": self.input_manifest_hash,
        }


@dataclass(frozen=True, slots=True)
class SleepMetricCoverage:
    """Deterministic summary count for one catalog metric."""

    metric_code: str
    variant: str | None
    comparable_count: int
    unavailable_count: int
    excluded_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric_code": self.metric_code,
            "variant": self.variant,
            "comparable_count": self.comparable_count,
            "unavailable_count": self.unavailable_count,
            "excluded_count": self.excluded_count,
        }


@dataclass(frozen=True, slots=True)
class SleepMetricProjectionResult:
    """Read-only R05 projection plus all frozen input manifests."""

    query: SleepPairingQuery
    pairing: SleepPairingResult
    metric_definitions: tuple[SleepMetricDefinition, ...]
    projections: tuple[SleepMetricProjection, ...]
    frozen_inputs: tuple[SleepMetricInputManifest, ...]
    coverage: tuple[SleepMetricCoverage, ...]
    result_hash: str

    @property
    def pairs(self) -> tuple[SleepPair, ...]:
        return self.pairing.pairs

    @property
    def metrics(self) -> tuple[SleepMetricProjection, ...]:
        return self.projections

    @property
    def excluded_metric_codes(self) -> tuple[str, ...]:
        return EXCLUDED_SLEEP_METRIC_CODES

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": R05_SLEEP_METRIC_PROJECTION_CONTRACT_VERSION,
            "rule_version": R05_SLEEP_METRIC_PROJECTION_RULE_VERSION,
            "algorithm": R05_SLEEP_METRIC_PROJECTION_ALGORITHM,
            "query": self.query.as_dict(),
            "pairing": self.pairing.as_dict(),
            "metric_definitions": [item.as_dict() for item in self.metric_definitions],
            "projections": [item.as_dict() for item in self.projections],
            "frozen_inputs": [item.as_dict() for item in self.frozen_inputs],
            "coverage": [item.as_dict() for item in self.coverage],
            "excluded_metric_codes": list(EXCLUDED_SLEEP_METRIC_CODES),
            "result_hash": self.result_hash,
        }


@dataclass(frozen=True, slots=True)
class _StoredSleepSide:
    provider: str
    source: GarminSource | GoogleSource
    record: GarminSourceRecord | GoogleSourceRecord
    metrics: tuple[GarminRecordMetric | GoogleRecordMetric, ...]
    stages: tuple[GarminSleepStageInterval | GoogleSleepInterval, ...]
    field_state: GoogleSleepFieldState | None
    evidence: SleepMetricEvidenceRef


@dataclass(frozen=True, slots=True)
class _MetricOutcome:
    state: str
    value: int | float | str | None
    unit: str | None
    field_path: str | None
    reason: str | None
    eligible: bool
    variant: str | None
    comparison_basis: str | None
    evidence: SleepMetricEvidenceRef
    exclusion_basis: str | None = None


@dataclass(frozen=True, slots=True)
class _ValidatedIntervals:
    rows: tuple[GarminSleepStageInterval | GoogleSleepInterval, ...]
    reason: str | None


@dataclass(frozen=True, slots=True)
class _StageCollection:
    state: str
    metric_row: GarminRecordMetric | GoogleRecordMetric | None
    field_state: GoogleSleepFieldState | None
    validation: _ValidatedIntervals
    reason: str | None


def _metric_map(
    rows: Sequence[GarminRecordMetric | GoogleRecordMetric],
) -> dict[str, GarminRecordMetric | GoogleRecordMetric]:
    return {row.metric_code: row for row in rows}


def _metric_value(row: GarminRecordMetric | GoogleRecordMetric | None) -> object:
    if row is None:
        return None
    if row.value_number is not None:
        return row.value_number
    return row.value_text


def _finite_number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _iso_utc(value: datetime | None) -> str | None:
    restored = restore_stored_utc(value)
    if restored is None:
        return None
    return restored.isoformat().replace("+00:00", "Z")


def _numeric_value(value: int | float) -> int | float:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _json_object(value: str | None) -> object:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def _evidence_for(
    side: _StoredSleepSide,
    *,
    metric_rows: Sequence[GarminRecordMetric | GoogleRecordMetric] = (),
    interval_rows: Sequence[GarminSleepStageInterval | GoogleSleepInterval] = (),
    field_state: GoogleSleepFieldState | None = None,
    exclusion_basis: str | None = None,
) -> SleepMetricEvidenceRef:
    """Extend record provenance with the exact rows used by one metric."""

    field_paths = set(side.evidence.field_paths)
    field_paths.update(row.field_path for row in metric_rows if row.field_path)
    for row in interval_rows:
        for name in (
            "start_source_field",
            "end_source_field",
            "start_source_local_field",
            "end_source_local_field",
            "start_source_utc_field",
            "end_source_utc_field",
        ):
            value = getattr(row, name, None)
            if value:
                field_paths.add(value)
    return replace(
        side.evidence,
        metric_row_ids=tuple(sorted({row.id for row in metric_rows})),
        field_state_row_id=(
            field_state.sleep_record_id
            if field_state is not None
            else side.evidence.field_state_row_id
        ),
        interval_ids=tuple(row.id for row in interval_rows),
        interval_snapshots=tuple(_interval_snapshot(row) for row in interval_rows),
        field_paths=tuple(sorted(field_paths)),
        exclusion_basis=exclusion_basis or side.evidence.exclusion_basis,
    )


def _interval_snapshot(
    row: GarminSleepStageInterval | GoogleSleepInterval,
) -> dict[str, object]:
    """Freeze typed interval semantics so #102 need not reread mutable rows."""

    snapshot: dict[str, object] = {
        "id": row.id,
        "ordinal": row.ordinal,
        "start_precision": row.start_precision,
        "end_precision": row.end_precision,
        "start_at_utc": _iso_utc(row.start_at_utc),
        "end_at_utc": _iso_utc(row.end_at_utc),
        "start_source_field": getattr(row, "start_source_field", None),
        "end_source_field": getattr(row, "end_source_field", None),
        "start_source_local_field": getattr(row, "start_source_local_field", None),
        "end_source_local_field": getattr(row, "end_source_local_field", None),
        "start_source_utc_field": getattr(row, "start_source_utc_field", None),
        "end_source_utc_field": getattr(row, "end_source_utc_field", None),
        "activity_level": getattr(row, "activity_level", None),
        "stage_type": getattr(row, "stage_type", None),
        "interval_kind": getattr(row, "interval_kind", "sleep_stage"),
        "interval_state": getattr(row, "interval_state", _VALUE),
        "start_state": getattr(row, "start_state", _VALUE),
        "end_state": getattr(row, "end_state", _VALUE),
    }
    for prefix in ("start", "end"):
        temporal = _json_object(getattr(row, f"{prefix}_temporal_json", None))
        if temporal is not None:
            snapshot[f"{prefix}_temporal"] = temporal
    if isinstance(row, GoogleSleepInterval):
        snapshot["create_time"] = row.create_time
        snapshot["update_time"] = row.update_time
    return snapshot


def _source_attribution(
    source: GarminSource | GoogleSource,
    record: GarminSourceRecord | GoogleSourceRecord,
    eligibility: SleepSourceEligibility,
) -> dict[str, object]:
    values: dict[str, object] = {
        "source_eligibility": eligibility.as_dict(),
        "provider_code": source.provider_code,
        "source_kind": source.source_kind,
        "source_instance_id": source.source_instance_id,
        "device_attributed": source.device_attributed,
        "device_code": source.device_code,
        "device_model": source.device_model,
        "record_projection_status": record.projection_status,
    }
    if isinstance(record, GoogleSourceRecord):
        values.update(
            {
                "query_mode": record.query_mode,
                "data_source_family": record.data_source_family,
            }
        )
    else:
        values.update(
            {
                "surface_code": record.surface_code,
                "collection_key": record.collection_key,
            }
        )
    return values


def _record_evidence(
    session: Session,
    *,
    provider: str,
    source: GarminSource | GoogleSource,
    record: GarminSourceRecord | GoogleSourceRecord,
    eligibility: SleepSourceEligibility,
) -> SleepMetricEvidenceRef:
    """Resolve immutable payload metadata without reading the raw body."""

    raw_payload_id = record.raw_payload_id
    raw: GarminRawPayload | GoogleRawPayload | None = (
        session.get(GarminRawPayload, raw_payload_id)
        if provider == "garmin"
        else session.get(GoogleRawPayload, raw_payload_id)
    )
    content_hash = raw.content_hash if raw is not None else None
    observation_id: str | None = None
    observation_key: str | None = None
    observation_candidates: tuple[str, ...] = ()
    observation_valid = False

    if provider == "garmin":
        candidates = list(
            session.scalars(
                select(GarminPayloadObservation)
                .where(GarminPayloadObservation.garmin_raw_payload_id == raw_payload_id)
                .order_by(GarminPayloadObservation.received_at, GarminPayloadObservation.id)
            )
        )
        if record.ingest_event_id is not None:
            matched = [
                item for item in candidates if item.ingest_event_id == record.ingest_event_id
            ]
            if matched:
                candidates = matched
        observation_candidates = tuple(item.id for item in candidates)
        if len(candidates) == 1:
            observation = candidates[0]
            observation_id = observation.id
            observation_key = observation.observation_key
            observation_valid = (
                observation.garmin_raw_payload_id == raw_payload_id
                and observation.garmin_source_id == record.garmin_source_id
            )
    else:
        assert isinstance(record, GoogleSourceRecord)
        if record.observation_id is not None:
            observation = session.get(GooglePayloadObservation, record.observation_id)
            if observation is not None:
                observation_candidates = (observation.id,)
                observation_id = observation.id
                observation_key = observation.observation_key
                observation_valid = (
                    observation.google_raw_payload_id == raw_payload_id
                    and observation.google_source_id == record.google_source_id
                )
        else:
            candidates = list(
                session.scalars(
                    select(GooglePayloadObservation)
                    .where(GooglePayloadObservation.google_raw_payload_id == raw_payload_id)
                    .order_by(GooglePayloadObservation.received_at, GooglePayloadObservation.id)
                )
            )
            observation_candidates = tuple(item.id for item in candidates)
            if len(candidates) == 1:
                observation = candidates[0]
                observation_id = observation.id
                observation_key = observation.observation_key
                observation_valid = observation.google_source_id == record.google_source_id

    immutable = (
        raw is not None
        and isinstance(content_hash, str)
        and len(content_hash) >= 32
        and observation_valid
        and record.projection_status == _CURRENT
    )
    reason: str | None = None
    if raw is None:
        reason = "raw_payload_missing"
    elif not isinstance(content_hash, str) or len(content_hash) < 32:
        reason = "raw_payload_content_hash_missing"
    elif not observation_candidates:
        reason = "observation_provenance_missing"
    elif len(observation_candidates) != 1:
        reason = "observation_provenance_ambiguous"
    elif not observation_valid:
        reason = "observation_provenance_mismatch"
    elif record.projection_status != _CURRENT:
        reason = "record_projection_not_current"

    return SleepMetricEvidenceRef(
        provider=provider,
        source_id=source.id,
        source_instance_id=source.source_instance_id,
        source_class=eligibility.source_class,
        source_kind=source.source_kind,
        record_id=record.id,
        idempotency_key=record.idempotency_key,
        raw_payload_id=raw_payload_id,
        content_hash=content_hash,
        observation_id=observation_id,
        observation_key=observation_key,
        observation_candidates=observation_candidates,
        field_paths=tuple(
            item
            for item in (
                record.source_field,
                record.source_local_field,
                record.source_utc_field,
            )
            if item
        ),
        attribution=_source_attribution(source, record, eligibility),
        exclusion_basis=reason,
        immutable=immutable,
    )


def _load_garmin_sleep_side(
    session: Session, pair: SleepPair
) -> _StoredSleepSide | None:
    record = session.get(GarminSourceRecord, pair.garmin_record_id)
    if record is None:
        return None
    source = session.get(GarminSource, record.garmin_source_id)
    if source is None:
        return None
    metrics = tuple(
        session.scalars(
            select(GarminRecordMetric)
            .where(GarminRecordMetric.record_id == record.id)
            .order_by(GarminRecordMetric.metric_code, GarminRecordMetric.id)
        )
    )
    sleep_record = session.get(GarminSleepRecord, record.id)
    stages: tuple[GarminSleepStageInterval, ...] = ()
    if sleep_record is not None:
        stages = tuple(
            session.scalars(
                select(GarminSleepStageInterval)
                .where(GarminSleepStageInterval.sleep_record_id == sleep_record.record_id)
                .order_by(GarminSleepStageInterval.ordinal, GarminSleepStageInterval.id)
            )
        )
    eligibility = _garmin_source_eligibility(record, source)
    return _StoredSleepSide(
        provider="garmin",
        source=source,
        record=record,
        metrics=metrics,
        stages=stages,
        field_state=None,
        evidence=_record_evidence(
            session,
            provider="garmin",
            source=source,
            record=record,
            eligibility=eligibility,
        ),
    )


def _load_google_sleep_side(
    session: Session, pair: SleepPair
) -> _StoredSleepSide | None:
    record = session.get(GoogleSourceRecord, pair.google_record_id)
    if record is None:
        return None
    source = session.get(GoogleSource, record.google_source_id)
    if source is None:
        return None
    metrics = tuple(
        session.scalars(
            select(GoogleRecordMetric)
            .where(GoogleRecordMetric.record_id == record.id)
            .order_by(GoogleRecordMetric.metric_code, GoogleRecordMetric.id)
        )
    )
    typed = session.get(GoogleSleepRecord, record.id)
    field_state = session.get(GoogleSleepFieldState, record.id)
    intervals: tuple[GoogleSleepInterval, ...] = ()
    if typed is not None:
        intervals = tuple(
            session.scalars(
                select(GoogleSleepInterval)
                .where(GoogleSleepInterval.sleep_record_id == typed.record_id)
                .order_by(GoogleSleepInterval.interval_kind, GoogleSleepInterval.ordinal)
            )
        )
    evidence_row = session.get(GoogleRecordSourceEvidence, record.id)
    eligibility = _google_source_eligibility(record, source, evidence_row)
    return _StoredSleepSide(
        provider="google",
        source=source,
        record=record,
        metrics=metrics,
        stages=intervals,
        field_state=field_state,
        evidence=_record_evidence(
            session,
            provider="google",
            source=source,
            record=record,
            eligibility=eligibility,
        ),
    )


def _outcome_missing(
    *,
    provider: str,
    record_id: str | None,
    variant: str | None,
    reason: str,
    evidence: SleepMetricEvidenceRef | None = None,
    field_path: str | None = None,
    state: str = _MISSING,
    unit: str | None = None,
    exclusion_basis: str | None = None,
) -> _MetricOutcome:
    return _MetricOutcome(
        state=state,
        value=None,
        unit=unit,
        field_path=field_path,
        reason=reason,
        eligible=False,
        variant=variant,
        comparison_basis=None,
        evidence=evidence or _empty_evidence(provider, record_id),
        exclusion_basis=exclusion_basis,
    )


def _outcome_from_scalar(
    side: _StoredSleepSide | None,
    *,
    metric_code: str,
    expected_unit: str,
    variant: str | None,
    multiplier: int | float = 1,
    output_unit: str | None = None,
) -> _MetricOutcome:
    if side is None:
        return _outcome_missing(
            provider="unknown",
            record_id=None,
            variant=variant,
            reason="persisted_record_missing",
            unit=output_unit or expected_unit,
        )
    metrics = _metric_map(side.metrics)
    row = metrics.get(metric_code)
    normalized_unit = output_unit or expected_unit
    state, state_reason = _state_reason(row)
    evidence = _evidence_for(side, metric_rows=(row,) if row is not None else ())
    if state != _VALUE:
        return _MetricOutcome(
            state=state,
            value=None,
            unit=normalized_unit if row is None else row.unit,
            field_path=row.field_path if row is not None else None,
            reason=state_reason,
            eligible=False,
            variant=variant,
            comparison_basis=None,
            evidence=evidence,
        )
    assert row is not None
    raw_value = _finite_number(row.value_number)
    if raw_value is None:
        return _MetricOutcome(
            state=state,
            value=None,
            unit=row.unit,
            field_path=row.field_path,
            reason="metric_value_invalid",
            eligible=False,
            variant=variant,
            comparison_basis=None,
            evidence=_evidence_for(
                side, metric_rows=(row,), exclusion_basis="metric_value_invalid"
            ),
            exclusion_basis="metric_value_invalid",
        )
    if row.unit != expected_unit:
        reason = "metric_unit_mismatch"
        return _MetricOutcome(
            state=state,
            value=None,
            unit=row.unit,
            field_path=row.field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis=None,
            evidence=_evidence_for(side, metric_rows=(row,), exclusion_basis=reason),
            exclusion_basis=reason,
        )
    value = _numeric_value(raw_value * multiplier)
    if not side.evidence.immutable:
        reason = side.evidence.exclusion_basis or "immutable_input_evidence_unavailable"
        return _MetricOutcome(
            state=state,
            value=value,
            unit=normalized_unit,
            field_path=row.field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis="persisted_metric",
            evidence=_evidence_for(side, metric_rows=(row,), exclusion_basis=reason),
            exclusion_basis=reason,
        )
    return _MetricOutcome(
        state=state,
        value=value,
        unit=normalized_unit,
        field_path=row.field_path,
        reason=None,
        eligible=True,
        variant=variant,
        comparison_basis="persisted_metric",
        evidence=evidence,
    )


def _outcome_from_text(
    side: _StoredSleepSide | None,
    *,
    metric_code: str,
    variant: str | None,
) -> _MetricOutcome:
    if side is None:
        return _outcome_missing(
            provider="unknown", record_id=None, variant=variant, reason="persisted_record_missing"
        )
    row = _metric_map(side.metrics).get(metric_code)
    state, state_reason = _state_reason(row)
    evidence = _evidence_for(side, metric_rows=(row,) if row is not None else ())
    if state != _VALUE:
        return _MetricOutcome(
            state=state,
            value=None,
            unit=row.unit if row is not None else None,
            field_path=row.field_path if row is not None else None,
            reason=state_reason,
            eligible=False,
            variant=variant,
            comparison_basis=None,
            evidence=evidence,
        )
    assert row is not None
    if not isinstance(row.value_text, str) or not row.value_text.strip():
        reason = "metric_value_invalid"
        return _MetricOutcome(
            state=state,
            value=None,
            unit=row.unit,
            field_path=row.field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis=None,
            evidence=_evidence_for(side, metric_rows=(row,), exclusion_basis=reason),
            exclusion_basis=reason,
        )
    value = row.value_text.strip()
    if not side.evidence.immutable:
        reason = side.evidence.exclusion_basis or "immutable_input_evidence_unavailable"
        return _MetricOutcome(
            state=state,
            value=value,
            unit=row.unit,
            field_path=row.field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis="persisted_metric",
            evidence=_evidence_for(side, metric_rows=(row,), exclusion_basis=reason),
            exclusion_basis=reason,
        )
    return _MetricOutcome(
        state=state,
        value=value,
        unit=row.unit,
        field_path=row.field_path,
        reason=None,
        eligible=True,
        variant=variant,
        comparison_basis="persisted_metric",
        evidence=evidence,
    )


def _google_sleep_variant(side: _StoredSleepSide | None) -> str | None:
    outcome = _outcome_from_text(side, metric_code="sleep_type", variant=None)
    if not outcome.eligible:
        return None
    if outcome.value not in {_CLASSIC, _STAGES}:
        return None
    return str(outcome.value)


def _stage_state_and_row(
    side: _StoredSleepSide | None,
) -> tuple[str, GarminRecordMetric | GoogleRecordMetric | None, str | None]:
    if side is None:
        return _MISSING, None, "persisted_record_missing"
    if side.provider == "garmin":
        row = _metric_map(side.metrics).get("sleep_stages")
        state, reason = _state_reason(row)
        return state, row, reason
    if side.field_state is None:
        return _MISSING, None, "sleep_stages_state_missing"
    return side.field_state.sleep_stages_state, None, None


def _stage_status(side: _StoredSleepSide | None) -> str | None:
    if side is None or side.provider != "google":
        return None
    row = _metric_map(side.metrics).get("sleep_metadata_stages_status")
    if row is None or row.state != _VALUE or not isinstance(row.value_text, str):
        return None
    return row.value_text.strip()


def _interval_start(row: GarminSleepStageInterval | GoogleSleepInterval) -> datetime | None:
    return restore_stored_utc(row.start_at_utc)


def _interval_end(row: GarminSleepStageInterval | GoogleSleepInterval) -> datetime | None:
    return restore_stored_utc(row.end_at_utc)


def _validated_intervals(
    side: _StoredSleepSide,
    *,
    rows: Sequence[GarminSleepStageInterval | GoogleSleepInterval] | None = None,
) -> _ValidatedIntervals:
    values = tuple(side.stages if rows is None else rows)
    if not values:
        return _ValidatedIntervals(values, "stage_collection_empty")
    previous_start: datetime | None = None
    previous_end: datetime | None = None
    for expected_ordinal, row in enumerate(values):
        if row.ordinal != expected_ordinal:
            return _ValidatedIntervals(values, "stage_interval_order_invalid")
        if isinstance(row, GoogleSleepInterval):
            if row.interval_kind != "sleep_stage" or row.interval_state != _VALUE:
                return _ValidatedIntervals(values, "stage_interval_invalid")
            if row.start_state != _VALUE or row.end_state != _VALUE:
                return _ValidatedIntervals(values, "stage_interval_invalid")
        if row.start_precision != "instant" or row.end_precision != "instant":
            return _ValidatedIntervals(values, "stage_interval_temporal_precision_unavailable")
        start = _interval_start(row)
        end = _interval_end(row)
        if start is None or end is None:
            return _ValidatedIntervals(values, "stage_interval_temporal_precision_unavailable")
        if end <= start:
            return _ValidatedIntervals(values, "stage_interval_invalid")
        if previous_start is not None and start < previous_start:
            return _ValidatedIntervals(values, "stage_interval_order_invalid")
        if previous_end is not None and start < previous_end:
            return _ValidatedIntervals(values, "stage_interval_overlap")
        previous_start = start
        previous_end = end
    return _ValidatedIntervals(values, None)


def _stage_rows_evidence(
    side: _StoredSleepSide,
    *,
    row: GarminRecordMetric | GoogleRecordMetric | None,
    field_state: GoogleSleepFieldState | None = None,
    rows: Sequence[GarminSleepStageInterval | GoogleSleepInterval] = (),
    exclusion_basis: str | None = None,
) -> SleepMetricEvidenceRef:
    metric_rows = (row,) if row is not None else ()
    return _evidence_for(
        side,
        metric_rows=metric_rows,
        interval_rows=rows,
        field_state=field_state,
        exclusion_basis=exclusion_basis,
    )


def _stage_collection(
    side: _StoredSleepSide | None,
    *,
    require_google_success: bool = False,
) -> _StageCollection:
    if side is None:
        return _StageCollection(
            state=_MISSING,
            metric_row=None,
            field_state=None,
            validation=_ValidatedIntervals((), "persisted_record_missing"),
            reason="persisted_record_missing",
        )
    state, metric_row, state_reason = _stage_state_and_row(side)
    rows: tuple[GarminSleepStageInterval | GoogleSleepInterval, ...]
    if side.provider == "google":
        rows = tuple(
            row
            for row in side.stages
            if isinstance(row, GoogleSleepInterval) and row.interval_kind == "sleep_stage"
        )
    else:
        rows = tuple(
            row for row in side.stages if isinstance(row, GarminSleepStageInterval)
        )
    validation = _validated_intervals(side, rows=rows)
    reason = state_reason
    if state != _VALUE and reason is None:
        reason = {
            _MISSING: "stage_collection_missing",
            _NULL: "stage_collection_null",
            _INVALID: "stage_collection_invalid",
        }.get(state, "stage_collection_state_invalid")
    if state == _VALUE and metric_row is not None and metric_row.reason == "partial_collection":
        reason = "stage_collection_partial"
    elif state == _VALUE and validation.reason is not None:
        reason = validation.reason
    if (
        side.provider == "google"
        and require_google_success
        and state == _VALUE
        and validation.reason is None
        and _stage_status(side) != _GOOGLE_STAGE_SUCCESS
    ):
        reason = "stages_status_not_succeeded"
    return _StageCollection(
        state=state,
        metric_row=metric_row,
        field_state=side.field_state,
        validation=validation,
        reason=reason,
    )


def _stage_input_outcome(
    side: _StoredSleepSide | None,
    *,
    target: str,
    variant: str | None,
    collection: _StageCollection,
    comparison_basis: str,
) -> _MetricOutcome:
    if side is None:
        return _outcome_missing(
            provider="unknown",
            record_id=None,
            variant=variant,
            reason="persisted_record_missing",
            unit="seconds",
        )
    row = collection.metric_row
    field_state = collection.field_state
    evidence = _stage_rows_evidence(
        side,
        row=row,
        field_state=field_state,
        rows=collection.validation.rows,
        exclusion_basis=collection.reason,
    )
    field_path = row.field_path if row is not None else "sleep.stages"
    if collection.state != _VALUE:
        return _MetricOutcome(
            state=collection.state,
            value=None,
            unit="seconds",
            field_path=field_path,
            reason=collection.reason,
            eligible=False,
            variant=variant,
            comparison_basis=None,
            evidence=evidence,
        )
    if collection.reason is not None:
        return _MetricOutcome(
            state=collection.state,
            value=None,
            unit="seconds",
            field_path=field_path,
            reason=collection.reason,
            eligible=False,
            variant=variant,
            comparison_basis=comparison_basis,
            evidence=evidence,
            exclusion_basis=collection.reason,
        )
    if not side.evidence.immutable:
        reason = side.evidence.exclusion_basis or "immutable_input_evidence_unavailable"
        return _MetricOutcome(
            state=collection.state,
            value=None,
            unit="seconds",
            field_path=field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis=comparison_basis,
            evidence=replace(evidence, exclusion_basis=reason),
            exclusion_basis=reason,
        )
    target_rows: list[GarminSleepStageInterval | GoogleSleepInterval] = []
    recognized_rows = 0
    for interval in collection.validation.rows:
        stage_type = getattr(interval, "activity_level", None)
        if stage_type is None:
            stage_type = getattr(interval, "stage_type", None)
        normalized = stage_type.strip().upper() if isinstance(stage_type, str) else None
        if normalized in _STAGE_TARGETS:
            recognized_rows += 1
            if normalized == target:
                target_rows.append(interval)
    if recognized_rows == 0:
        reason = "stage_type_unmapped"
        return _MetricOutcome(
            state=collection.state,
            value=None,
            unit="seconds",
            field_path=field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis=comparison_basis,
            evidence=replace(evidence, exclusion_basis=reason),
            exclusion_basis=reason,
        )
    if target == "AWAKE" and not target_rows:
        reason = "awake_collection_empty"
        return _MetricOutcome(
            state=collection.state,
            value=None,
            unit="seconds",
            field_path=field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis=comparison_basis,
            evidence=replace(evidence, exclusion_basis=reason),
            exclusion_basis=reason,
        )
    total = _numeric_value(
        sum(
            (_interval_end(interval) - _interval_start(interval)).total_seconds()
            for interval in target_rows
            if _interval_start(interval) is not None and _interval_end(interval) is not None
        )
    )
    return _MetricOutcome(
        state=collection.state,
        value=total,
        unit="seconds",
        field_path=field_path,
        reason=None,
        eligible=True,
        variant=variant,
        comparison_basis=comparison_basis,
        evidence=evidence,
    )


def _summary_stage_input_outcome(
    side: _StoredSleepSide | None,
    *,
    target: str,
    variant: str | None,
) -> _MetricOutcome:
    if side is None or side.provider != "google":
        return _outcome_missing(
            provider="garmin",
            record_id=None,
            variant=variant,
            reason="summary_stage_evidence_unavailable",
            unit="seconds",
        )
    row = _metric_map(side.metrics).get("sleep_summary_stages")
    state, state_reason = _state_reason(row)
    evidence = _evidence_for(side, metric_rows=(row,) if row is not None else ())
    field_path = row.field_path if row is not None else "sleep.summary.stagesSummary"
    if state != _VALUE:
        return _MetricOutcome(
            state=state,
            value=None,
            unit="seconds",
            field_path=field_path,
            reason=state_reason,
            eligible=False,
            variant=variant,
            comparison_basis=None,
            evidence=evidence,
        )
    assert row is not None
    parsed = _json_object(row.collection_json)
    if not isinstance(parsed, list) or not parsed:
        reason = "stage_collection_empty" if parsed == [] else "summary_stage_collection_invalid"
        return _MetricOutcome(
            state=state,
            value=None,
            unit="seconds",
            field_path=field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis="summary_only",
            evidence=replace(evidence, exclusion_basis=reason),
            exclusion_basis=reason,
        )
    target_minutes = 0
    target_present = False
    recognized_rows = 0
    for item in parsed:
        if not isinstance(item, Mapping):
            reason = "summary_stage_collection_invalid"
            return _MetricOutcome(
                state=state,
                value=None,
                unit="seconds",
                field_path=field_path,
                reason=reason,
                eligible=False,
                variant=variant,
                comparison_basis="summary_only",
                evidence=replace(evidence, exclusion_basis=reason),
                exclusion_basis=reason,
            )
        stage_type = item.get("type")
        minutes = _finite_number(item.get("minutes"))
        count = _finite_number(item.get("count"))
        if (
            not isinstance(stage_type, str)
            or minutes is None
            or count is None
            or minutes < 0
            or count < 0
        ):
            reason = "summary_stage_collection_invalid"
            return _MetricOutcome(
                state=state,
                value=None,
                unit="seconds",
                field_path=field_path,
                reason=reason,
                eligible=False,
                variant=variant,
                comparison_basis="summary_only",
                evidence=replace(evidence, exclusion_basis=reason),
                exclusion_basis=reason,
            )
        normalized = stage_type.strip().upper()
        if normalized in _STAGE_TARGETS:
            recognized_rows += 1
            if normalized == target:
                target_present = True
                target_minutes += int(minutes)
    if recognized_rows == 0:
        reason = "stage_type_unmapped"
        return _MetricOutcome(
            state=state,
            value=None,
            unit="seconds",
            field_path=field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis="summary_only",
            evidence=replace(evidence, exclusion_basis=reason),
            exclusion_basis=reason,
        )
    if target == "AWAKE" and not target_present:
        reason = "awake_collection_empty"
        return _MetricOutcome(
            state=state,
            value=None,
            unit="seconds",
            field_path=field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis="summary_only",
            evidence=replace(evidence, exclusion_basis=reason),
            exclusion_basis=reason,
        )
    if not side.evidence.immutable:
        reason = side.evidence.exclusion_basis or "immutable_input_evidence_unavailable"
        return _MetricOutcome(
            state=state,
            value=target_minutes * 60,
            unit="seconds",
            field_path=field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis="summary_only",
            evidence=replace(evidence, exclusion_basis=reason),
            exclusion_basis=reason,
        )
    return _MetricOutcome(
        state=state,
        value=target_minutes * 60,
        unit="seconds",
        field_path=field_path,
        reason=None,
        eligible=True,
        variant=variant,
        comparison_basis="summary_only",
        evidence=evidence,
    )


def _google_session_rows(
    side: _StoredSleepSide | None,
) -> tuple[GoogleSleepInterval, ...]:
    if side is None or side.provider != "google":
        return ()
    return tuple(
        row
        for row in side.stages
        if isinstance(row, GoogleSleepInterval) and row.interval_kind == "sleep_session"
    )


def _validated_google_session(
    side: _StoredSleepSide | None,
) -> tuple[GoogleSleepInterval | None, str, str | None]:
    """Return one explicit Google session boundary, never a guessed boundary."""

    if side is None or side.provider != "google":
        return None, _MISSING, "persisted_record_missing"
    field_state = side.field_state
    state = field_state.sleep_interval_state if field_state is not None else _MISSING
    rows = _google_session_rows(side)
    if len(rows) > 1:
        return None, state, "sleep_session_ambiguous"
    if not rows:
        return None, state, "sleep_session_missing"
    row = rows[0]
    if row.interval_state != _VALUE:
        return row, row.interval_state, "sleep_session_state_invalid"
    if row.start_state != _VALUE or row.end_state != _VALUE:
        return row, state, "sleep_session_endpoint_invalid"
    if row.start_precision != "instant" or row.end_precision != "instant":
        return row, state, "timing_precision_unavailable"
    start = _interval_start(row)
    end = _interval_end(row)
    if start is None or end is None:
        return row, state, "timing_precision_unavailable"
    if end <= start:
        return row, state, "sleep_session_interval_invalid"
    return row, state, None


def _google_timing_outcome(
    side: _StoredSleepSide | None,
    *,
    endpoint: str,
    variant: str | None,
) -> _MetricOutcome:
    row, state, reason = _validated_google_session(side)
    if side is None:
        return _outcome_missing(
            provider="google", record_id=None, variant=variant, reason="persisted_record_missing"
        )
    evidence = _evidence_for(side, interval_rows=(row,) if row is not None else ())
    if row is None:
        return _MetricOutcome(
            state=state,
            value=None,
            unit=_UTC_INSTANT,
            field_path=(
                "sleep.interval.startTime"
                if endpoint == "start"
                else "sleep.interval.endTime"
            ),
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis="explicit_session_boundary",
            evidence=evidence,
            exclusion_basis=reason,
        )
    field_path = (
        row.start_source_utc_field
        if endpoint == "start"
        else row.end_source_utc_field
    ) or ("sleep.interval.startTime" if endpoint == "start" else "sleep.interval.endTime")
    value = _interval_start(row) if endpoint == "start" else _interval_end(row)
    encoded = _iso_utc(value)
    if reason is not None or encoded is None:
        reason = reason or "timing_precision_unavailable"
        return _MetricOutcome(
            state=state,
            value=encoded,
            unit=_UTC_INSTANT,
            field_path=field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis="explicit_session_boundary",
            evidence=replace(evidence, exclusion_basis=reason),
            exclusion_basis=reason,
        )
    if not side.evidence.immutable:
        reason = side.evidence.exclusion_basis or "immutable_input_evidence_unavailable"
        return _MetricOutcome(
            state=state,
            value=encoded,
            unit=_UTC_INSTANT,
            field_path=field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis="explicit_session_boundary",
            evidence=replace(evidence, exclusion_basis=reason),
            exclusion_basis=reason,
        )
    return _MetricOutcome(
        state=state,
        value=encoded,
        unit=_UTC_INSTANT,
        field_path=field_path,
        reason=None,
        eligible=True,
        variant=variant,
        comparison_basis="explicit_session_boundary",
        evidence=evidence,
    )


def _garmin_timing_outcome(
    side: _StoredSleepSide | None,
    *,
    endpoint: str,
    variant: str | None,
) -> _MetricOutcome:
    if side is None:
        return _outcome_missing(
            provider="garmin", record_id=None, variant=variant, reason="persisted_record_missing"
        )
    if endpoint == "start":
        record = side.record
        field_path = record.source_utc_field or record.source_field or "source_timestamp_utc"
        if record.temporal_precision == "instant" and record.source_timestamp_utc is not None:
            value = _iso_utc(record.source_timestamp_utc)
            reason = None if value is not None else "timing_precision_unavailable"
            basis = "explicit_record_boundary"
        elif record.temporal_precision in {"local", "date"}:
            value = _iso_utc(record.source_timestamp_utc)
            reason = "timing_precision_unavailable"
            basis = "persisted_temporal_evidence"
        elif record.temporal_precision == "unknown":
            value = None
            reason = "timing_missing"
            basis = "persisted_temporal_evidence"
        else:
            value = None
            reason = "timing_precision_invalid"
            basis = "persisted_temporal_evidence"
        evidence = _evidence_for(side)
        if reason is None and not side.evidence.immutable:
            reason = side.evidence.exclusion_basis or "immutable_input_evidence_unavailable"
        temporal_state = (
            _VALUE
            if record.temporal_precision in {"instant", "local", "date"}
            else _INVALID
            if record.temporal_precision not in {"unknown", "instant", "local", "date"}
            else _MISSING
        )
        return _MetricOutcome(
            state=temporal_state,
            value=value,
            unit=_UTC_INSTANT,
            field_path=field_path,
            reason=reason,
            eligible=reason is None,
            variant=variant,
            comparison_basis=basis,
            evidence=replace(evidence, exclusion_basis=reason),
            exclusion_basis=reason,
        )

    collection = _stage_collection(side)
    evidence = _stage_rows_evidence(
        side,
        row=collection.metric_row,
        field_state=collection.field_state,
        rows=collection.validation.rows,
        exclusion_basis=collection.reason,
    )
    if collection.state != _VALUE or collection.reason is not None:
        return _MetricOutcome(
            state=collection.state,
            value=None,
            unit=_UTC_INSTANT,
            field_path=(
                collection.metric_row.field_path
                if collection.metric_row
                else "sleep.stages"
            ),
            reason=collection.reason,
            eligible=False,
            variant=variant,
            comparison_basis="complete_stage_boundary",
            evidence=evidence,
            exclusion_basis=collection.reason,
        )
    if not side.evidence.immutable:
        reason = side.evidence.exclusion_basis or "immutable_input_evidence_unavailable"
        return _MetricOutcome(
            state=collection.state,
            value=None,
            unit=_UTC_INSTANT,
            field_path=(
                collection.metric_row.field_path
                if collection.metric_row
                else "sleep.stages"
            ),
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis="complete_stage_boundary",
            evidence=replace(evidence, exclusion_basis=reason),
            exclusion_basis=reason,
        )
    last = collection.validation.rows[-1]
    value = _iso_utc(_interval_end(last))
    reason = None if value is not None else "timing_precision_unavailable"
    return _MetricOutcome(
        state=collection.state,
        value=value,
        unit=_UTC_INSTANT,
        field_path=(
            getattr(last, "end_source_utc_field", None)
            or getattr(last, "end_source_field", None)
            or "sleep.stages[-1].end_at_utc"
        ),
        reason=reason,
        eligible=reason is None,
        variant=variant,
        comparison_basis="complete_stage_boundary",
        evidence=replace(evidence, exclusion_basis=reason),
        exclusion_basis=reason,
    )


def _tib_outcome(
    side: _StoredSleepSide | None,
    *,
    variant: str | None,
) -> _MetricOutcome:
    if side is None:
        return _outcome_missing(
            provider="unknown", record_id=None, variant=variant, reason="persisted_record_missing"
        )
    if side.provider == "garmin":
        collection = _stage_collection(side)
        evidence = _stage_rows_evidence(
            side,
            row=collection.metric_row,
            field_state=collection.field_state,
            rows=collection.validation.rows,
            exclusion_basis=collection.reason,
        )
        if collection.state != _VALUE or collection.reason is not None:
            return _MetricOutcome(
                state=collection.state,
                value=None,
                unit="seconds",
                field_path=(
                    collection.metric_row.field_path
                    if collection.metric_row
                    else "sleep.stages"
                ),
                reason=collection.reason,
                eligible=False,
                variant=variant,
                comparison_basis="complete_stage_intervals",
                evidence=evidence,
                exclusion_basis=collection.reason,
            )
        if not side.evidence.immutable:
            reason = side.evidence.exclusion_basis or "immutable_input_evidence_unavailable"
            return _MetricOutcome(
                state=collection.state,
                value=None,
                unit="seconds",
                field_path=(
                    collection.metric_row.field_path
                    if collection.metric_row
                    else "sleep.stages"
                ),
                reason=reason,
                eligible=False,
                variant=variant,
                comparison_basis="complete_stage_intervals",
                evidence=replace(evidence, exclusion_basis=reason),
                exclusion_basis=reason,
            )
        total = _numeric_value(
            sum(
                (_interval_end(row) - _interval_start(row)).total_seconds()
                for row in collection.validation.rows
                if _interval_start(row) is not None and _interval_end(row) is not None
            )
        )
        return _MetricOutcome(
            state=collection.state,
            value=total,
            unit="seconds",
            field_path=(
                collection.metric_row.field_path
                if collection.metric_row
                else "sleep.stages"
            ),
            reason=None,
            eligible=True,
            variant=variant,
            comparison_basis="complete_stage_intervals",
            evidence=evidence,
        )

    # Google TIB is the persisted summary value, but it is not eligible from
    # duration alone: an explicit session boundary or a complete successful
    # typed stage collection must prove that the summary is in-bed time.
    summary_row = _metric_map(side.metrics).get("sleep_summary_minutes_in_sleep_period")
    summary_state, summary_reason = _state_reason(summary_row)
    session_row, _session_state, session_reason = _validated_google_session(side)
    explicit_boundary_ok = session_row is not None and session_reason is None
    typed_collection = _stage_collection(side, require_google_success=True)
    typed_proof_ok = (
        typed_collection.state == _VALUE
        and typed_collection.reason is None
        and bool(typed_collection.validation.rows)
    )
    evidence = _evidence_for(
        side,
        metric_rows=(summary_row,) if summary_row is not None else (),
        interval_rows=(
            (session_row,)
            if explicit_boundary_ok and session_row is not None
            else typed_collection.validation.rows
            if typed_proof_ok
            else ()
        ),
        field_state=side.field_state,
    )
    field_path = (
        summary_row.field_path
        if summary_row is not None
        else "sleep.summary.minutesInSleepPeriod"
    )
    if summary_state != _VALUE:
        return _MetricOutcome(
            state=summary_state,
            value=None,
            unit="seconds",
            field_path=field_path,
            reason=summary_reason,
            eligible=False,
            variant=variant,
            comparison_basis=None,
            evidence=evidence,
        )
    assert summary_row is not None
    raw_value = _finite_number(summary_row.value_number)
    if raw_value is None or summary_row.unit != "min":
        reason = "metric_value_invalid" if raw_value is None else "metric_unit_mismatch"
        return _MetricOutcome(
            state=summary_state,
            value=None,
            unit=summary_row.unit,
            field_path=field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis=None,
            evidence=replace(evidence, exclusion_basis=reason),
            exclusion_basis=reason,
        )
    if explicit_boundary_ok:
        basis = "summary_with_explicit_session_boundary"
    elif typed_proof_ok:
        basis = "summary_with_complete_stage_collection"
    else:
        reason = (
            typed_collection.reason
            if typed_collection.reason in {
                "stage_collection_partial",
                "stage_interval_overlap",
                "stage_interval_invalid",
                "stage_interval_order_invalid",
                "stage_interval_temporal_precision_unavailable",
            }
            else "tib_boundary_insufficient"
        )
        return _MetricOutcome(
            state=summary_state,
            value=_numeric_value(raw_value * 60),
            unit="seconds",
            field_path=field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis="summary_without_boundary",
            evidence=replace(evidence, exclusion_basis=reason),
            exclusion_basis=reason,
        )
    if not side.evidence.immutable:
        reason = side.evidence.exclusion_basis or "immutable_input_evidence_unavailable"
        return _MetricOutcome(
            state=summary_state,
            value=_numeric_value(raw_value * 60),
            unit="seconds",
            field_path=field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis=basis,
            evidence=replace(evidence, exclusion_basis=reason),
            exclusion_basis=reason,
        )
    return _MetricOutcome(
        state=summary_state,
        value=_numeric_value(raw_value * 60),
        unit="seconds",
        field_path=field_path,
        reason=None,
        eligible=True,
        variant=variant,
        comparison_basis=basis,
        evidence=evidence,
    )


def _auxiliary_side_candidates(
    session: Session,
    *,
    pair: SleepPair,
    provider: str,
    stream_code: str,
) -> tuple[_StoredSleepSide, ...]:
    """Read same-date auxiliary rows without inheriting sleep-row attribution."""

    values: list[_StoredSleepSide] = []
    if provider == "garmin":
        rows = list(
            session.execute(
                select(GarminSourceRecord, GarminDailyRecord)
                .join(GarminDailyRecord, GarminDailyRecord.record_id == GarminSourceRecord.id)
                .where(
                    GarminSourceRecord.garmin_source_id == pair.garmin_source_id,
                    GarminSourceRecord.stream_code == stream_code,
                    GarminSourceRecord.projection_status == _CURRENT,
                    GarminDailyRecord.calendar_date == pair.wake_date,
                )
                .order_by(GarminSourceRecord.id)
            )
        )
        for record, _daily in rows:
            source = session.get(GarminSource, record.garmin_source_id)
            if source is None:
                continue
            metrics = tuple(
                session.scalars(
                    select(GarminRecordMetric)
                    .where(GarminRecordMetric.record_id == record.id)
                    .order_by(GarminRecordMetric.metric_code, GarminRecordMetric.id)
                )
            )
            eligibility = _garmin_source_eligibility(record, source)
            values.append(
                _StoredSleepSide(
                    provider="garmin",
                    source=source,
                    record=record,
                    metrics=metrics,
                    stages=(),
                    field_state=None,
                    evidence=_record_evidence(
                        session,
                        provider="garmin",
                        source=source,
                        record=record,
                        eligibility=eligibility,
                    ),
                )
            )
        return tuple(values)

    rows = list(
        session.scalars(
            select(GoogleSourceRecord)
            .where(
                GoogleSourceRecord.google_source_id == pair.google_source_id,
                GoogleSourceRecord.stream_code == stream_code,
                GoogleSourceRecord.source_local_date == pair.wake_date,
                GoogleSourceRecord.projection_status == _CURRENT,
            )
            .order_by(GoogleSourceRecord.id)
        )
    )
    for record in rows:
        source = session.get(GoogleSource, record.google_source_id)
        if source is None:
            continue
        metrics = tuple(
            session.scalars(
                select(GoogleRecordMetric)
                .where(GoogleRecordMetric.record_id == record.id)
                .order_by(GoogleRecordMetric.metric_code, GoogleRecordMetric.id)
            )
        )
        evidence_row = session.get(GoogleRecordSourceEvidence, record.id)
        eligibility = _google_source_eligibility(record, source, evidence_row)
        values.append(
            _StoredSleepSide(
                provider="google",
                source=source,
                record=record,
                metrics=metrics,
                stages=(),
                field_state=None,
                evidence=_record_evidence(
                    session,
                    provider="google",
                    source=source,
                    record=record,
                    eligibility=eligibility,
                ),
            )
        )
    return tuple(values)


def _auxiliary_outcome(
    session: Session,
    *,
    pair: SleepPair,
    provider: str,
    stream_code: str,
    source_metric_code: str,
    variant: str,
    expected_unit: str,
) -> _MetricOutcome:
    candidates = _auxiliary_side_candidates(
        session,
        pair=pair,
        provider=provider,
        stream_code=stream_code,
    )
    if not candidates:
        return _outcome_missing(
            provider=provider,
            record_id=None,
            variant=variant,
            reason="auxiliary_record_missing",
            unit=expected_unit,
            exclusion_basis="auxiliary_record_missing",
        )
    if len(candidates) != 1:
        candidate_ids = tuple(side.record.id for side in candidates)
        return _outcome_missing(
            provider=provider,
            record_id=None,
            variant=variant,
            reason="auxiliary_record_ambiguous",
            unit=expected_unit,
            evidence=SleepMetricEvidenceRef(
                provider=provider,
                source_id=(candidates[0].source.id if candidates else None),
                source_instance_id=(
                    candidates[0].source.source_instance_id if candidates else None
                ),
                source_class=None,
                source_kind=None,
                record_id=None,
                idempotency_key=None,
                raw_payload_id=None,
                content_hash=None,
                observation_id=None,
                observation_key=None,
                observation_candidates=candidate_ids,
                attribution={"candidate_record_ids": list(candidate_ids)},
                exclusion_basis="auxiliary_record_ambiguous",
                immutable=False,
            ),
            exclusion_basis="auxiliary_record_ambiguous",
        )
    side = candidates[0]
    eligibility = side.evidence.attribution.get("source_eligibility")
    eligible_source = bool(side.evidence.immutable)
    source_reason = side.evidence.exclusion_basis
    if isinstance(eligibility, Mapping):
        eligible_source = eligible_source and bool(eligibility.get("eligible"))
        if provider == "google":
            eligible_source = eligible_source and eligibility.get("cohort") == pair.cohort
        source_reason = (
            None
            if eligible_source
            else str(eligibility.get("reason") or source_reason or "auxiliary_source_ineligible")
        )
    row = _metric_map(side.metrics).get(source_metric_code)
    state, row_reason = _state_reason(row)
    evidence = _evidence_for(side, metric_rows=(row,) if row is not None else ())
    field_path = row.field_path if row is not None else None
    if not eligible_source:
        reason = source_reason or "auxiliary_source_ineligible"
        return _MetricOutcome(
            state=state,
            value=None,
            unit=row.unit if row is not None else expected_unit,
            field_path=field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis="own_daily_record",
            evidence=replace(evidence, exclusion_basis=reason),
            exclusion_basis=reason,
        )
    if state != _VALUE:
        return _MetricOutcome(
            state=state,
            value=None,
            unit=row.unit if row is not None else expected_unit,
            field_path=field_path,
            reason=row_reason,
            eligible=False,
            variant=variant,
            comparison_basis=None,
            evidence=evidence,
        )
    assert row is not None
    value = _finite_number(row.value_number)
    if value is None:
        reason = "metric_value_invalid"
    elif row.unit != expected_unit:
        reason = "metric_unit_mismatch"
    else:
        reason = None
    if reason is not None:
        return _MetricOutcome(
            state=state,
            value=None,
            unit=row.unit,
            field_path=field_path,
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis="own_daily_record",
            evidence=replace(evidence, exclusion_basis=reason),
            exclusion_basis=reason,
        )
    return _MetricOutcome(
        state=state,
        value=_numeric_value(value),
        unit=expected_unit,
        field_path=field_path,
        reason=None,
        eligible=True,
        variant=variant,
        comparison_basis="own_daily_record",
        evidence=evidence,
    )


def _stage_projection_outcome(
    side: _StoredSleepSide | None,
    *,
    target: str,
    variant: str | None,
) -> _MetricOutcome:
    if side is None:
        return _outcome_missing(
            provider="unknown", record_id=None, variant=variant, reason="persisted_record_missing"
        )
    collection = _stage_collection(side)
    if side.provider != "google":
        return _stage_input_outcome(
            side,
            target=target,
            variant=variant,
            collection=collection,
            comparison_basis="typed_intervals",
        )
    # A typed Google collection is accepted only with STAGES and an explicit
    # successful stagesStatus.  A valid summary is an intentionally caveated
    # fallback, never a mixture of typed and summary values.
    if collection.state == _INVALID:
        return _stage_input_outcome(
            side,
            target=target,
            variant=variant,
            collection=collection,
            comparison_basis="typed_intervals",
        )
    if collection.validation.reason not in {None, "stage_collection_empty"}:
        return _stage_input_outcome(
            side,
            target=target,
            variant=variant,
            collection=collection,
            comparison_basis="typed_intervals",
        )
    if (
        collection.state == _VALUE
        and collection.validation.reason is None
        and collection.validation.rows
        and _stage_status(side) == _GOOGLE_STAGE_SUCCESS
    ):
        return _stage_input_outcome(
            side,
            target=target,
            variant=variant,
            collection=collection,
            comparison_basis="typed_intervals",
        )
    return _summary_stage_input_outcome(side, target=target, variant=variant)


def _dependency_unavailable(
    side: _StoredSleepSide | None,
    *,
    variant: str | None,
    reason: str,
    unit: str,
    metric_code: str,
) -> _MetricOutcome:
    if side is None:
        return _outcome_missing(
            provider="unknown", record_id=None, variant=variant, reason=reason, unit=unit
        )
    if metric_code.startswith("sleep_stage_") or metric_code == "sleep_awake_waso_seconds":
        state, row, _ = _stage_state_and_row(side)
        evidence = _stage_rows_evidence(
            side,
            row=row,
            field_state=side.field_state,
            rows=side.stages,
            exclusion_basis=reason,
        )
        return _MetricOutcome(
            state=state,
            value=None,
            unit=unit,
            field_path=row.field_path if row is not None else "sleep.stages",
            reason=reason,
            eligible=False,
            variant=variant,
            comparison_basis=None,
            evidence=evidence,
            exclusion_basis=reason,
        )
    return _outcome_missing(
        provider=side.provider,
        record_id=side.record.id,
        variant=variant,
        reason=reason,
        evidence=side.evidence,
        unit=unit,
        state=_VALUE,
        exclusion_basis=reason,
    )


def _excluded_stage_outcome(
    side: _StoredSleepSide | None,
    *,
    variant: str | None,
) -> _MetricOutcome:
    return _dependency_unavailable(
        side,
        variant=variant,
        reason="classic_sleep_excludes_stage_metric",
        unit="seconds",
        metric_code="sleep_stage_excluded",
    )


def _with_variant_gate(
    outcome: _MetricOutcome,
    *,
    variant: str | None,
) -> _MetricOutcome:
    if variant is not None or not outcome.eligible:
        return outcome
    reason = "sleep_type_unavailable"
    return replace(
        outcome,
        reason=reason,
        eligible=False,
        exclusion_basis=reason,
        evidence=replace(outcome.evidence, exclusion_basis=reason),
    )


def _timing_difference(google: object, garmin: object) -> int | float | None:
    if not isinstance(google, str) or not isinstance(garmin, str):
        return None
    try:
        google_dt = datetime.fromisoformat(google.replace("Z", "+00:00"))
        garmin_dt = datetime.fromisoformat(garmin.replace("Z", "+00:00"))
    except ValueError:
        return None
    if google_dt.tzinfo is None or garmin_dt.tzinfo is None:
        return None
    return _numeric_value((google_dt - garmin_dt).total_seconds())


def _numeric_difference(google: object, garmin: object) -> int | float | None:
    google_value = _finite_number(google)
    garmin_value = _finite_number(garmin)
    if google_value is None or garmin_value is None:
        return None
    return _numeric_value(google_value - garmin_value)


def _projection_reason(
    garmin: _MetricOutcome,
    google: _MetricOutcome,
    *,
    fallback: str | None = None,
) -> str | None:
    reasons = [item for item in (garmin.reason, google.reason) if item]
    unique = list(dict.fromkeys(reasons))
    if not unique:
        return fallback
    if len(unique) == 1:
        return unique[0]
    return ";".join(
        f"{provider}:{reason}"
        for provider, reason in (("garmin", garmin.reason), ("google", google.reason))
        if reason
    )


def _pair_metric_outcomes(
    session: Session,
    *,
    pair: SleepPair,
    definition: SleepMetricDefinition,
    garmin: _StoredSleepSide | None,
    google: _StoredSleepSide | None,
    variant: str | None,
) -> tuple[_MetricOutcome, _MetricOutcome]:
    code = definition.metric_code
    if code == "sleep_duration_asleep_seconds":
        values = (
            _outcome_from_scalar(
                garmin,
                metric_code="sleep_duration_seconds",
                expected_unit="seconds",
                variant=variant,
            ),
            _outcome_from_scalar(
                google,
                metric_code="sleep_summary_minutes_asleep",
                expected_unit="min",
                multiplier=60,
                output_unit="seconds",
                variant=variant,
            ),
        )
    elif code == "sleep_time_in_bed_seconds":
        values = (_tib_outcome(garmin, variant=variant), _tib_outcome(google, variant=variant))
    elif code == "sleep_start_at":
        values = (
            _garmin_timing_outcome(garmin, endpoint="start", variant=variant),
            _google_timing_outcome(google, endpoint="start", variant=variant),
        )
    elif code == "sleep_end_at":
        values = (
            _garmin_timing_outcome(garmin, endpoint="end", variant=variant),
            _google_timing_outcome(google, endpoint="end", variant=variant),
        )
    elif code in {
        "sleep_stage_light_seconds",
        "sleep_stage_deep_seconds",
        "sleep_stage_rem_seconds",
        "sleep_awake_waso_seconds",
    }:
        target = {
            "sleep_stage_light_seconds": "LIGHT",
            "sleep_stage_deep_seconds": "DEEP",
            "sleep_stage_rem_seconds": "REM",
            "sleep_awake_waso_seconds": "AWAKE",
        }[code]
        values = (
            _stage_projection_outcome(garmin, target=target, variant=variant),
            _stage_projection_outcome(google, target=target, variant=variant),
        )
    elif code == "resting_heart_rate_bpm":
        values = (
            _auxiliary_outcome(
                session,
                pair=pair,
                provider="garmin",
                stream_code="daily_health",
                source_metric_code="resting_heart_rate_bpm",
                variant="DAILY",
                expected_unit="bpm",
            ),
            _auxiliary_outcome(
                session,
                pair=pair,
                provider="google",
                stream_code="daily_resting_hr",
                source_metric_code="daily_resting_heart_rate_bpm",
                variant="DAILY",
                expected_unit="bpm",
            ),
        )
    elif code == "spo2_daily_average_pct":
        values = (
            _auxiliary_outcome(
                session,
                pair=pair,
                provider="garmin",
                stream_code="daily_health",
                source_metric_code="spo2_daily_average",
                variant="DAILY",
                expected_unit="%",
            ),
            _auxiliary_outcome(
                session,
                pair=pair,
                provider="google",
                stream_code="daily_spo2",
                source_metric_code="daily_oxygen_saturation_average_percentage",
                variant="DAILY",
                expected_unit="%",
            ),
        )
    else:  # pragma: no cover - guarded by the frozen registry
        raise ValueError(f"unsupported R05 metric code: {code}")

    if definition.canonical_candidate and variant is None:
        values = (
            _with_variant_gate(values[0], variant=variant),
            _with_variant_gate(values[1], variant=variant),
        )
    return values


def _pair_projection(
    session: Session,
    *,
    pair: SleepPair,
    definition: SleepMetricDefinition,
) -> SleepMetricProjection:
    garmin = _load_garmin_sleep_side(session, pair)
    google = _load_google_sleep_side(session, pair)
    google_variant = _google_sleep_variant(google)
    variant = "DAILY" if not definition.canonical_candidate else google_variant

    if not definition.canonical_candidate:
        garmin_outcome, google_outcome = _pair_metric_outcomes(
            session,
            pair=pair,
            definition=definition,
            garmin=garmin,
            google=google,
            variant=variant,
        )
        status = (
            "comparable"
            if garmin_outcome.eligible and google_outcome.eligible
            else "unavailable"
        )
        difference = (
            _numeric_difference(google_outcome.value, garmin_outcome.value)
            if status == "comparable"
            else None
        )
        if status == "comparable" and difference is None:
            status = "unavailable"
        reason = _projection_reason(
            garmin_outcome,
            google_outcome,
            fallback=None if status == "comparable" else "metric_difference_not_computable",
        )
        return _build_projection(
            definition=definition,
            pair=pair,
            variant=variant,
            garmin_outcome=garmin_outcome,
            google_outcome=google_outcome,
            status=status,
            difference=difference,
            reason=reason,
            exclusion_basis=reason if status != "comparable" else None,
        )

    if definition.comparison_kind == "stage_total" and google_variant == _CLASSIC:
        garmin_outcome = _excluded_stage_outcome(garmin, variant=google_variant)
        google_outcome = _excluded_stage_outcome(google, variant=google_variant)
        reason = "classic_sleep_excludes_stage_metric"
        return _build_projection(
            definition=definition,
            pair=pair,
            variant=google_variant,
            garmin_outcome=garmin_outcome,
            google_outcome=google_outcome,
            status="excluded",
            difference=None,
            reason=reason,
            exclusion_basis=reason,
        )

    garmin_outcome, google_outcome = _pair_metric_outcomes(
        session,
        pair=pair,
        definition=definition,
        garmin=garmin,
        google=google,
        variant=variant,
    )
    status = "comparable" if garmin_outcome.eligible and google_outcome.eligible else "unavailable"
    if status == "comparable":
        if definition.unit == _UTC_INSTANT:
            difference = _timing_difference(google_outcome.value, garmin_outcome.value)
        else:
            difference = _numeric_difference(google_outcome.value, garmin_outcome.value)
        if difference is None:
            status = "unavailable"
            reason = "metric_difference_not_computable"
        else:
            reason = None
    else:
        difference = None
        reason = _projection_reason(garmin_outcome, google_outcome)
        if reason is None:
            reason = "metric_not_eligible"
    return _build_projection(
        definition=definition,
        pair=pair,
        variant=variant,
        garmin_outcome=garmin_outcome,
        google_outcome=google_outcome,
        status=status,
        difference=difference,
        reason=reason,
        exclusion_basis=reason if status != "comparable" else None,
    )


def _coverage(
    projections: Sequence[SleepMetricProjection],
) -> tuple[SleepMetricCoverage, ...]:
    result: list[SleepMetricCoverage] = []
    for code in SLEEP_COMPARISON_METRIC_CODES:
        rows = [item for item in projections if item.metric_code == code]
        variants = sorted(
            {item.variant for item in rows},
            key=lambda item: "" if item is None else item,
        ) or [None]
        for variant in variants:
            variant_rows = [item for item in rows if item.variant == variant]
            result.append(
                SleepMetricCoverage(
                    metric_code=code,
                    variant=variant,
                    comparable_count=sum(item.status == "comparable" for item in variant_rows),
                    unavailable_count=sum(item.status == "unavailable" for item in variant_rows),
                    excluded_count=sum(item.status == "excluded" for item in variant_rows),
                )
            )
    return tuple(result)


class PersistedSleepMetricProjectionReader:
    """Read deterministic metric projections from the accepted pairing."""

    def __init__(
        self,
        session: Session,
        pairing: SleepPairingResult | None = None,
    ) -> None:
        self.session = session
        self.pairing = pairing

    def read(self, query: SleepPairingQuery | None = None) -> SleepMetricProjectionResult:
        pairing = self.pairing
        if pairing is None:
            pairing = read_persisted_sleep_pairing(self.session, query)
        elif query is not None and pairing.query != query:
            raise ValueError("provided sleep pairing does not match the projection query")
        projections: list[SleepMetricProjection] = []
        for pair in pairing.pairs:
            for definition in SLEEP_METRIC_DEFINITIONS.values():
                projections.append(
                    _pair_projection(
                        self.session,
                        pair=pair,
                        definition=definition,
                    )
                )
        projections.sort(
            key=lambda item: (
                item.pair.wake_date,
                item.pair.cohort,
                item.pair.garmin_record_id,
                item.pair.google_record_id,
                item.metric_code,
            )
        )
        frozen_inputs = tuple(item.manifest for item in projections)
        coverage = _coverage(projections)
        body = {
            "contract_version": R05_SLEEP_METRIC_PROJECTION_CONTRACT_VERSION,
            "rule_version": R05_SLEEP_METRIC_PROJECTION_RULE_VERSION,
            "algorithm": R05_SLEEP_METRIC_PROJECTION_ALGORITHM,
            "query": pairing.query.as_dict(),
            "pairing": pairing.as_dict(),
            "metric_definitions": [item.as_dict() for item in SLEEP_METRIC_DEFINITIONS.values()],
            "projections": [item.as_dict() for item in projections],
            "frozen_inputs": [item.as_dict() for item in frozen_inputs],
            "coverage": [item.as_dict() for item in coverage],
            "excluded_metric_codes": list(EXCLUDED_SLEEP_METRIC_CODES),
        }
        return SleepMetricProjectionResult(
            query=pairing.query,
            pairing=pairing,
            metric_definitions=tuple(SLEEP_METRIC_DEFINITIONS.values()),
            projections=tuple(projections),
            frozen_inputs=frozen_inputs,
            coverage=coverage,
            result_hash=stable_manifest_hash(body),
        )


def read_persisted_sleep_metric_projection(
    session: Session,
    query: SleepPairingQuery | None = None,
    *,
    pairing: SleepPairingResult | None = None,
) -> SleepMetricProjectionResult:
    """Project R05 metrics over persisted current pairing rows only."""

    return PersistedSleepMetricProjectionReader(session, pairing=pairing).read(query)


read_persisted_sleep_metrics = read_persisted_sleep_metric_projection
project_persisted_sleep_metrics = read_persisted_sleep_metric_projection
project_sleep_metrics = read_persisted_sleep_metric_projection


def _state_reason(row: GarminRecordMetric | GoogleRecordMetric | None) -> tuple[str, str | None]:
    if row is None:
        return _MISSING, "metric_row_missing"
    state = str(row.state)
    return state, row.reason or {
        _MISSING: "metric_missing",
        _NULL: "metric_null",
        _INVALID: "metric_invalid",
    }.get(state)


def _empty_evidence(provider: str, record_id: str | None = None) -> SleepMetricEvidenceRef:
    return SleepMetricEvidenceRef(
        provider=provider,
        source_id=None,
        source_instance_id=None,
        source_class=None,
        source_kind=None,
        record_id=record_id,
        idempotency_key=None,
        raw_payload_id=None,
        content_hash=None,
        observation_id=None,
        observation_key=None,
        immutable=False,
    )


def _metric_input(
    *,
    provider: str,
    record_id: str | None,
    outcome: _MetricOutcome,
) -> SleepMetricInputDTO:
    return SleepMetricInputDTO(
        provider=provider,
        record_id=record_id,
        state=outcome.state,
        value=outcome.value,
        unit=outcome.unit,
        field_path=outcome.field_path,
        reason=outcome.reason,
        eligible=outcome.eligible,
        is_zero=outcome.eligible and outcome.value == 0,
        variant=outcome.variant,
        comparison_basis=outcome.comparison_basis,
        evidence=outcome.evidence,
        exclusion_basis=outcome.exclusion_basis,
    )


def _manifest_body(
    *,
    definition: SleepMetricDefinition,
    pair: SleepPair,
    variant: str | None,
    garmin: SleepMetricInputDTO,
    google: SleepMetricInputDTO,
    status: str,
    difference: int | float | None,
    reason: str | None,
    exclusion_basis: str | None,
) -> dict[str, Any]:
    return {
        "contract_version": R05_SLEEP_METRIC_PROJECTION_CONTRACT_VERSION,
        "rule_version": R05_SLEEP_METRIC_PROJECTION_RULE_VERSION,
        "algorithm": R05_SLEEP_METRIC_PROJECTION_ALGORITHM,
        "metric_definition": definition.as_dict(),
        "pair": pair.as_dict(),
        "variant": variant,
        "garmin": garmin.as_dict(),
        "google": google.as_dict(),
        "status": status,
        "difference": difference,
        "difference_unit": definition.difference_unit,
        "reason": reason,
        "exclusion_basis": exclusion_basis,
    }


def _build_projection(
    *,
    definition: SleepMetricDefinition,
    pair: SleepPair,
    variant: str | None,
    garmin_outcome: _MetricOutcome,
    google_outcome: _MetricOutcome,
    status: str,
    difference: int | float | None,
    reason: str | None,
    exclusion_basis: str | None,
) -> SleepMetricProjection:
    garmin = _metric_input(
        provider="garmin",
        record_id=pair.garmin_record_id,
        outcome=garmin_outcome,
    )
    google = _metric_input(
        provider="google",
        record_id=pair.google_record_id,
        outcome=google_outcome,
    )
    body = _manifest_body(
        definition=definition,
        pair=pair,
        variant=variant,
        garmin=garmin,
        google=google,
        status=status,
        difference=difference,
        reason=reason,
        exclusion_basis=exclusion_basis,
    )
    manifest = SleepMetricInputManifest(
        contract_version=R05_SLEEP_METRIC_PROJECTION_CONTRACT_VERSION,
        rule_version=R05_SLEEP_METRIC_PROJECTION_RULE_VERSION,
        algorithm=R05_SLEEP_METRIC_PROJECTION_ALGORITHM,
        metric_definition=definition,
        pair=pair.as_dict(),
        variant=variant,
        garmin=garmin,
        google=google,
        status=status,
        difference=difference,
        difference_unit=definition.difference_unit,
        reason=reason,
        exclusion_basis=exclusion_basis,
        manifest_hash=stable_manifest_hash(body),
    )
    return SleepMetricProjection(
        pair=pair,
        metric_code=definition.metric_code,
        variant=variant,
        status=status,
        reason=reason,
        garmin=garmin,
        google=google,
        difference=difference,
        difference_unit=definition.difference_unit,
        comparable=status == "comparable",
        manifest=manifest,
    )


__all__ = [
    "EXCLUDED_SLEEP_METRIC_CODES",
    "R05_EXCLUDED_METRIC_CODES",
    "R05_SLEEP_METRIC_PROJECTION_ALGORITHM",
    "R05_SLEEP_METRIC_PROJECTION_CONTRACT_VERSION",
    "R05_SLEEP_METRIC_PROJECTION_RULE_VERSION",
    "SLEEP_AUXILIARY_METRIC_CODES",
    "SLEEP_CANONICAL_METRIC_CODES",
    "SLEEP_COMPARISON_METRIC_CODES",
    "SLEEP_METRIC_DEFINITIONS",
    "SleepMetricCoverage",
    "SleepMetricDefinition",
    "SleepMetricEvidenceRef",
    "SleepMetricInputDTO",
    "SleepMetricInputManifest",
    "SleepMetricProjection",
    "SleepMetricProjectionResult",
    "get_sleep_metric_definition",
    "PersistedSleepMetricProjectionReader",
    "project_persisted_sleep_metrics",
    "project_sleep_metrics",
    "read_persisted_sleep_metric_projection",
    "read_persisted_sleep_metrics",
]
