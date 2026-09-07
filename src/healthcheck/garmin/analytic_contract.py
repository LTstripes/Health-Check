"""Pre-R03 Garmin analytic input, metric identity, and coverage contract v1.

Bounded read/semantic helpers over existing Garmin projections. This module does
not calculate LLM math, schedule sync, ingest Fitbit/Google, parse FIT/GPS, or
build a generic provider framework.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from numbers import Real
from typing import Any

from healthcheck.garmin.normalization import (
    GarminFieldState,
    GarminMetricDTO,
    GarminRecordDTO,
    GarminTemporalDTO,
    GarminTemporalPrecision,
)

ANALYTIC_INPUT_CONTRACT_VERSION = "r03-garmin-analytic-input-v1"
ANALYTIC_RULE_VERSION = "r03-garmin-analytic-rules-v1"
ANALYTIC_COVERAGE_RULE_VERSION = "r03-garmin-analytic-coverage-v1"


class AggregateKind(StrEnum):
    """Statistically distinct aggregation shapes for analytic metric identity."""

    DAILY_AVERAGE = "daily_average"
    DAILY_MAXIMUM = "daily_maximum"
    TRAILING_AGGREGATE = "trailing_aggregate"
    SAMPLE = "sample"
    SESSION_TOTAL = "session_total"
    UNKNOWN = "unknown"


class AnalyticAvailability(StrEnum):
    """Metric-level analytic availability; distinct from operational surface present."""

    AVAILABLE = "available"
    MISSING = "missing"
    NULL = "null"
    ZERO = "zero"
    INVALID = "invalid"
    NOT_COMPUTABLE = "not_computable"
    PARTIAL = "partial"


@dataclass(frozen=True, slots=True)
class AnalyticMetricDefinition:
    """Reviewed analytic metric meaning, unit, and aggregation/window semantics."""

    metric_code: str
    capability_code: str
    unit: str | None
    aggregate_kind: AggregateKind
    window: str
    source_field_paths: tuple[str, ...]
    description: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric_code": self.metric_code,
            "capability_code": self.capability_code,
            "unit": self.unit,
            "aggregate_kind": self.aggregate_kind.value,
            "window": self.window,
            "source_field_paths": list(self.source_field_paths),
            "description": self.description,
        }


# Stress / SpO2 aggregate identity is mandatory for R03. Other codes are registered
# so sleep duration cannot silently imply score/stages/naps completeness.
ANALYTIC_METRIC_REGISTRY: dict[str, AnalyticMetricDefinition] = {
    "stress_daily_average": AnalyticMetricDefinition(
        metric_code="stress_daily_average",
        capability_code="stress",
        unit="points",
        aggregate_kind=AggregateKind.DAILY_AVERAGE,
        window="calendar_day",
        source_field_paths=("avgStressLevel",),
        description="Garmin daily average stress for one local calendar day.",
    ),
    "stress_daily_maximum": AnalyticMetricDefinition(
        metric_code="stress_daily_maximum",
        capability_code="stress",
        unit="points",
        aggregate_kind=AggregateKind.DAILY_MAXIMUM,
        window="calendar_day",
        source_field_paths=("maxStressLevel",),
        description="Garmin daily maximum stress for one local calendar day.",
    ),
    "stress_sample": AnalyticMetricDefinition(
        metric_code="stress_sample",
        capability_code="stress",
        unit="points",
        aggregate_kind=AggregateKind.SAMPLE,
        window="point",
        source_field_paths=("stress", "stressLevel", "stressValuesArray", "stressValues"),
        description="Point/sample stress observation; not a daily average or maximum.",
    ),
    "spo2_daily_average": AnalyticMetricDefinition(
        metric_code="spo2_daily_average",
        capability_code="spo2",
        unit="%",
        aggregate_kind=AggregateKind.DAILY_AVERAGE,
        window="calendar_day",
        source_field_paths=("averageSpO2",),
        description="Garmin daily average SpO2 for one local calendar day.",
    ),
    "spo2_trailing_7d_average": AnalyticMetricDefinition(
        metric_code="spo2_trailing_7d_average",
        capability_code="spo2",
        unit="%",
        aggregate_kind=AggregateKind.TRAILING_AGGREGATE,
        window="trailing_7d",
        source_field_paths=("lastSevenDaysAvgSpO2",),
        description="Garmin trailing seven-day average SpO2; not a daily value.",
    ),
    "spo2_sample": AnalyticMetricDefinition(
        metric_code="spo2_sample",
        capability_code="spo2",
        unit="%",
        aggregate_kind=AggregateKind.SAMPLE,
        window="point",
        source_field_paths=("spo2", "spo2Percent", "spo2Values"),
        description="Point/sample SpO2 observation; not a daily or trailing average.",
    ),
    "sleep_duration_seconds": AnalyticMetricDefinition(
        metric_code="sleep_duration_seconds",
        capability_code="sleep",
        unit="seconds",
        aggregate_kind=AggregateKind.SESSION_TOTAL,
        window="sleep_session",
        source_field_paths=("dailySleepDTO.sleepTimeSeconds",),
        description="Sleep duration for one sleep session; does not imply score/stages/naps.",
    ),
    "sleep_score": AnalyticMetricDefinition(
        metric_code="sleep_score",
        capability_code="sleep_score",
        unit="points",
        aggregate_kind=AggregateKind.SESSION_TOTAL,
        window="sleep_session",
        source_field_paths=("dailySleepDTO.sleepScores.overall.value",),
        description="Provider sleep score for one sleep session.",
    ),
    "sleep_stages": AnalyticMetricDefinition(
        metric_code="sleep_stages",
        capability_code="sleep_stages",
        unit=None,
        aggregate_kind=AggregateKind.SESSION_TOTAL,
        window="sleep_session",
        source_field_paths=("levels",),
        description="Sleep stage intervals; independent of duration presence.",
    ),
    "nap_duration_seconds": AnalyticMetricDefinition(
        metric_code="nap_duration_seconds",
        capability_code="naps",
        unit="seconds",
        aggregate_kind=AggregateKind.SESSION_TOTAL,
        window="calendar_day",
        source_field_paths=("dailySleepDTO.napTimeSeconds",),
        description="Nap duration; independent of overnight sleep duration presence.",
    ),
}

# Operational surface acquisition may succeed when any related metric is usable.
SURFACE_ANALYTIC_METRIC_CODES: dict[str, tuple[str, ...]] = {
    "stress": ("stress_daily_average", "stress_daily_maximum", "stress_sample"),
    "spo2": ("spo2_daily_average", "spo2_trailing_7d_average", "spo2_sample"),
    "sleep": (
        "sleep_duration_seconds",
        "sleep_score",
        "sleep_stages",
        "nap_duration_seconds",
    ),
}


def get_analytic_metric_definition(metric_code: str) -> AnalyticMetricDefinition:
    """Return the reviewed analytic definition for ``metric_code``."""

    key = metric_code.strip()
    try:
        return ANALYTIC_METRIC_REGISTRY[key]
    except KeyError as exc:
        raise KeyError(f"unknown analytic metric code: {metric_code}") from exc


def resolve_aggregate_kind(metric_code: str, field_path: str | None = None) -> AggregateKind:
    """Resolve aggregate kind from metric code, with field-path fallback."""

    code = metric_code.strip()
    if code in ANALYTIC_METRIC_REGISTRY:
        return ANALYTIC_METRIC_REGISTRY[code].aggregate_kind
    leaf = (field_path or "").rsplit(".", 1)[-1]
    if leaf == "avgStressLevel" or leaf == "averageSpO2":
        return AggregateKind.DAILY_AVERAGE
    if leaf == "maxStressLevel":
        return AggregateKind.DAILY_MAXIMUM
    if leaf == "lastSevenDaysAvgSpO2":
        return AggregateKind.TRAILING_AGGREGATE
    if leaf in {"stress", "stressLevel", "spo2", "spo2Percent"} or "Values" in leaf:
        return AggregateKind.SAMPLE
    return AggregateKind.UNKNOWN


@dataclass(frozen=True, slots=True)
class AnalyticTemporalSemantics:
    """Bounded analytic time projection without inventing UTC for local-only values."""

    precision: str
    analytic_date: str | None
    measured_at_utc: str | None
    local_wall_time: str | None
    source_local_timestamp: str | None
    source_utc_offset_minutes: int | None
    source_timezone: str | None
    source_field: str | None
    source_local_field: str | None
    source_utc_field: str | None
    zone_policy: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "precision": self.precision,
            "analytic_date": self.analytic_date,
            "measured_at_utc": self.measured_at_utc,
            "local_wall_time": self.local_wall_time,
            "source_local_timestamp": self.source_local_timestamp,
            "source_utc_offset_minutes": self.source_utc_offset_minutes,
            "source_timezone": self.source_timezone,
            "source_field": self.source_field,
            "source_local_field": self.source_local_field,
            "source_utc_field": self.source_utc_field,
            "zone_policy": self.zone_policy,
        }


def project_analytic_temporal(temporal: GarminTemporalDTO) -> AnalyticTemporalSemantics:
    """Project a normalization temporal DTO into analytic time semantics."""

    precision = temporal.precision.value
    if temporal.precision is GarminTemporalPrecision.UTC_INSTANT:
        zone_policy = "utc"
        if temporal.source_local_field or temporal.local_wall_time:
            zone_policy = "utc_with_source_local"
    elif temporal.precision is GarminTemporalPrecision.LOCAL_WALL_TIME:
        zone_policy = "local_unknown_zone"
    elif temporal.precision is GarminTemporalPrecision.DATE_ONLY:
        zone_policy = "local_date_only"
    else:
        zone_policy = "unknown"
    return AnalyticTemporalSemantics(
        precision=precision,
        analytic_date=temporal.local_date.isoformat() if temporal.local_date else None,
        measured_at_utc=(
            temporal.measured_at_utc.isoformat() if temporal.measured_at_utc is not None else None
        ),
        local_wall_time=temporal.local_wall_time,
        source_local_timestamp=temporal.source_local_timestamp,
        source_utc_offset_minutes=temporal.source_utc_offset_minutes,
        source_timezone=temporal.source_timezone,
        source_field=temporal.source_field,
        source_local_field=temporal.source_local_field,
        source_utc_field=temporal.source_utc_field,
        zone_policy=zone_policy,
    )


@dataclass(frozen=True, slots=True)
class AnalyticExclusion:
    """One deterministic exclusion/shape-loss reason for analytic coverage."""

    reason_code: str
    metric_code: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "metric_code": self.metric_code,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class MetricAnalyticCoverage:
    """Metric-level analytic availability; operational present is not completeness."""

    metric_code: str
    capability_code: str
    availability: AnalyticAvailability
    aggregate_kind: AggregateKind
    window: str
    unit: str | None
    parsed_sample_count: int
    usable_value_count: int
    null_count: int
    zero_count: int
    invalid_count: int
    missing_count: int
    operational_surface_present: bool
    exclusions: tuple[AnalyticExclusion, ...] = ()
    coverage_rule_version: str = ANALYTIC_COVERAGE_RULE_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric_code": self.metric_code,
            "capability_code": self.capability_code,
            "availability": self.availability.value,
            "aggregate_kind": self.aggregate_kind.value,
            "window": self.window,
            "unit": self.unit,
            "parsed_sample_count": self.parsed_sample_count,
            "usable_value_count": self.usable_value_count,
            "null_count": self.null_count,
            "zero_count": self.zero_count,
            "invalid_count": self.invalid_count,
            "missing_count": self.missing_count,
            "operational_surface_present": self.operational_surface_present,
            "exclusions": [item.as_dict() for item in self.exclusions],
            "coverage_rule_version": self.coverage_rule_version,
        }


def _metric_rows_for_code(
    records: Sequence[GarminRecordDTO], metric_code: str
) -> tuple[GarminMetricDTO, ...]:
    rows: list[GarminMetricDTO] = []
    for record in records:
        metric = record.metric(metric_code)
        if metric is not None:
            rows.append(metric)
        for item in record.metrics:
            if item.metric_code == metric_code and item is not metric:
                rows.append(item)
    return tuple(rows)


def evaluate_metric_analytic_coverage(
    metric_code: str,
    records: Sequence[GarminRecordDTO],
    *,
    operational_surface_present: bool = False,
) -> MetricAnalyticCoverage:
    """Compute bounded analytic coverage for one metric across current records."""

    definition = get_analytic_metric_definition(metric_code)
    rows = _metric_rows_for_code(records, metric_code)
    usable = 0
    null_count = 0
    zero_count = 0
    invalid_count = 0
    missing_count = 0
    exclusions: list[AnalyticExclusion] = []
    for row in rows:
        if row.state is GarminFieldState.VALUE:
            if row.is_zero:
                zero_count += 1
            usable += 1
            if row.metric_code == "sleep_stages" and not row.collection:
                exclusions.append(
                    AnalyticExclusion(
                        reason_code="empty_stage_collection",
                        metric_code=metric_code,
                    )
                )
        elif row.state is GarminFieldState.NULL:
            null_count += 1
        elif row.state is GarminFieldState.INVALID:
            invalid_count += 1
            exclusions.append(
                AnalyticExclusion(
                    reason_code=row.reason or "invalid_metric",
                    metric_code=metric_code,
                    detail=row.field_path,
                )
            )
        else:
            missing_count += 1
    parsed = len(rows)
    if usable > 0 and (invalid_count > 0 or (metric_code == "sleep_stages" and exclusions)):
        availability = AnalyticAvailability.PARTIAL
    elif usable > 0 and zero_count == usable:
        availability = AnalyticAvailability.ZERO
    elif usable > 0:
        availability = AnalyticAvailability.AVAILABLE
    elif null_count > 0 and missing_count == 0 and invalid_count == 0:
        availability = AnalyticAvailability.NULL
    elif invalid_count > 0 and usable == 0:
        availability = AnalyticAvailability.INVALID
    elif parsed == 0:
        availability = AnalyticAvailability.NOT_COMPUTABLE
        exclusions.append(
            AnalyticExclusion(
                reason_code="metric_absent_from_projection",
                metric_code=metric_code,
                detail=(
                    "operational_present_without_metric"
                    if operational_surface_present
                    else "no_metric_rows"
                ),
            )
        )
    else:
        availability = AnalyticAvailability.MISSING
    return MetricAnalyticCoverage(
        metric_code=definition.metric_code,
        capability_code=definition.capability_code,
        availability=availability,
        aggregate_kind=definition.aggregate_kind,
        window=definition.window,
        unit=definition.unit,
        parsed_sample_count=parsed,
        usable_value_count=usable,
        null_count=null_count,
        zero_count=zero_count,
        invalid_count=invalid_count,
        missing_count=missing_count,
        operational_surface_present=operational_surface_present,
        exclusions=tuple(exclusions),
    )


def evaluate_sleep_metric_family_coverage(
    records: Sequence[GarminRecordDTO],
    *,
    operational_surface_present: bool = False,
) -> dict[str, MetricAnalyticCoverage]:
    """Sleep duration presence must not imply score/stages/naps availability."""

    return {
        code: evaluate_metric_analytic_coverage(
            code, records, operational_surface_present=operational_surface_present
        )
        for code in SURFACE_ANALYTIC_METRIC_CODES["sleep"]
    }


@dataclass(frozen=True, slots=True)
class AnalyticEvidenceRef:
    """Immutable evidence locator sufficient to re-verify an analysis input."""

    raw_payload_id: str | None
    content_hash: str | None
    observation_id: str | None
    observation_key: str | None
    record_id: str | None
    idempotency_key: str | None
    metric_row_id: str | None
    field_path: str | None
    normalization_contract_version: str | None
    reconciliation_contract_version: str | None
    projection_status: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_payload_id": self.raw_payload_id,
            "content_hash": self.content_hash,
            "observation_id": self.observation_id,
            "observation_key": self.observation_key,
            "record_id": self.record_id,
            "idempotency_key": self.idempotency_key,
            "metric_row_id": self.metric_row_id,
            "field_path": self.field_path,
            "normalization_contract_version": self.normalization_contract_version,
            "reconciliation_contract_version": self.reconciliation_contract_version,
            "projection_status": self.projection_status,
        }


@dataclass(frozen=True, slots=True)
class AnalyticSelectedValue:
    """One selected value frozen into an analysis input manifest."""

    metric_code: str
    state: str
    value: int | float | str | None
    unit: str | None
    field_path: str | None
    aggregate_kind: str
    window: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric_code": self.metric_code,
            "state": self.state,
            "value": self.value,
            "unit": self.unit,
            "field_path": self.field_path,
            "aggregate_kind": self.aggregate_kind,
            "window": self.window,
        }


@dataclass(frozen=True, slots=True)
class AnalyticInputDTO:
    """Bounded R03 analytic input DTO / evidence manifest v1."""

    contract_version: str
    rule_version: str
    metric_definition: AnalyticMetricDefinition
    selected: AnalyticSelectedValue
    temporal: AnalyticTemporalSemantics | None
    coverage: MetricAnalyticCoverage
    evidence: AnalyticEvidenceRef
    source_instance_id: str | None
    provider_code: str | None
    algorithm_identity: str | None
    exclusions: tuple[AnalyticExclusion, ...]
    manifest_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "rule_version": self.rule_version,
            "metric_definition": self.metric_definition.as_dict(),
            "selected": self.selected.as_dict(),
            "temporal": self.temporal.as_dict() if self.temporal is not None else None,
            "coverage": self.coverage.as_dict(),
            "evidence": self.evidence.as_dict(),
            "source_instance_id": self.source_instance_id,
            "provider_code": self.provider_code,
            "algorithm_identity": self.algorithm_identity,
            "exclusions": [item.as_dict() for item in self.exclusions],
            "manifest_hash": self.manifest_hash,
        }


def _stable_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def stable_manifest_hash(payload: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 hex digest over canonical JSON of the manifest body."""

    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def build_analytic_input_dto(
    *,
    metric_code: str,
    selected_state: str,
    selected_value: int | float | str | None,
    field_path: str | None,
    temporal: GarminTemporalDTO | None = None,
    records: Sequence[GarminRecordDTO] = (),
    operational_surface_present: bool = False,
    evidence: AnalyticEvidenceRef,
    source_instance_id: str | None = None,
    provider_code: str | None = "garmin_connect",
    algorithm_identity: str | None = None,
    rule_version: str = ANALYTIC_RULE_VERSION,
    extra_exclusions: Sequence[AnalyticExclusion] = (),
) -> AnalyticInputDTO:
    """Build a frozen analytic input DTO; same evidence+rule => same manifest hash."""

    definition = get_analytic_metric_definition(metric_code)
    coverage = evaluate_metric_analytic_coverage(
        metric_code,
        records,
        operational_surface_present=operational_surface_present,
    )
    selected = AnalyticSelectedValue(
        metric_code=definition.metric_code,
        state=selected_state,
        value=selected_value,
        unit=definition.unit,
        field_path=field_path,
        aggregate_kind=definition.aggregate_kind.value,
        window=definition.window,
    )
    temporal_semantics = project_analytic_temporal(temporal) if temporal is not None else None
    exclusions = tuple(coverage.exclusions) + tuple(extra_exclusions)
    not_computable = selected_state in {"missing", "null", "invalid"} or (
        coverage.availability is AnalyticAvailability.NOT_COMPUTABLE
    )
    already = any(item.reason_code == "not_computable_input" for item in exclusions)
    if not_computable and not already:
        exclusions = exclusions + (
            AnalyticExclusion(
                reason_code="not_computable_input",
                metric_code=metric_code,
                detail=selected_state,
            ),
        )
    body = {
        "contract_version": ANALYTIC_INPUT_CONTRACT_VERSION,
        "rule_version": rule_version,
        "metric_definition": definition.as_dict(),
        "selected": selected.as_dict(),
        "temporal": temporal_semantics.as_dict() if temporal_semantics is not None else None,
        "coverage": coverage.as_dict(),
        "evidence": evidence.as_dict(),
        "source_instance_id": source_instance_id,
        "provider_code": provider_code,
        "algorithm_identity": algorithm_identity,
        "exclusions": [item.as_dict() for item in exclusions],
    }
    return AnalyticInputDTO(
        contract_version=ANALYTIC_INPUT_CONTRACT_VERSION,
        rule_version=rule_version,
        metric_definition=definition,
        selected=selected,
        temporal=temporal_semantics,
        coverage=coverage,
        evidence=evidence,
        source_instance_id=source_instance_id,
        provider_code=provider_code,
        algorithm_identity=algorithm_identity,
        exclusions=exclusions,
        manifest_hash=stable_manifest_hash(body),
    )


def build_analytic_input_from_metric(
    record: GarminRecordDTO,
    metric: GarminMetricDTO,
    *,
    evidence: AnalyticEvidenceRef,
    operational_surface_present: bool = False,
    rule_version: str = ANALYTIC_RULE_VERSION,
) -> AnalyticInputDTO:
    """Build an input DTO from one normalized metric row and its parent record."""

    return build_analytic_input_dto(
        metric_code=metric.metric_code,
        selected_state=metric.state.value,
        selected_value=(
            metric.value
            if isinstance(metric.value, (int, float, str)) or metric.value is None
            else str(metric.value)
        ),
        field_path=metric.field_path,
        temporal=record.temporal,
        records=(record,),
        operational_surface_present=operational_surface_present,
        evidence=evidence,
        source_instance_id=record.source.source_instance_id,
        provider_code=record.source.provider_code,
        algorithm_identity=metric.capability_code,
        rule_version=rule_version,
    )


def substitute_aggregate_is_forbidden(
    requested_metric_code: str, available_metric_codes: Iterable[str]
) -> bool:
    """Return True when a statistically different aggregate must not stand in."""

    requested = get_analytic_metric_definition(requested_metric_code)
    available = {code for code in available_metric_codes}
    if requested.metric_code in available:
        return False
    siblings = [
        get_analytic_metric_definition(code)
        for code in available
        if code in ANALYTIC_METRIC_REGISTRY
        and ANALYTIC_METRIC_REGISTRY[code].capability_code == requested.capability_code
    ]
    return any(item.aggregate_kind != requested.aggregate_kind for item in siblings)


def coerce_selected_number(value: Any) -> int | float | None:
    """Coerce a finite numeric selected value; booleans are rejected."""

    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    if isinstance(value, float) and (value != value or value in {float("inf"), float("-inf")}):
        return None
    return float(value) if isinstance(value, float) else int(value)


__all__ = [
    "ANALYTIC_COVERAGE_RULE_VERSION",
    "ANALYTIC_INPUT_CONTRACT_VERSION",
    "ANALYTIC_METRIC_REGISTRY",
    "ANALYTIC_RULE_VERSION",
    "AggregateKind",
    "AnalyticAvailability",
    "AnalyticEvidenceRef",
    "AnalyticExclusion",
    "AnalyticInputDTO",
    "AnalyticMetricDefinition",
    "AnalyticSelectedValue",
    "AnalyticTemporalSemantics",
    "MetricAnalyticCoverage",
    "SURFACE_ANALYTIC_METRIC_CODES",
    "build_analytic_input_dto",
    "build_analytic_input_from_metric",
    "coerce_selected_number",
    "evaluate_metric_analytic_coverage",
    "evaluate_sleep_metric_family_coverage",
    "get_analytic_metric_definition",
    "project_analytic_temporal",
    "resolve_aggregate_kind",
    "stable_manifest_hash",
    "substitute_aggregate_is_forbidden",
]
