"""R03-02 deterministic Garmin activity / cycling session comparison.

Bounded storage-backed comparison of explicitly selected persisted activity
sessions. No GPS/FIT/routes, UI, AI, correlations, readiness, or training advice.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord
from healthcheck.garmin.analytic_contract import (
    ANALYTIC_METRIC_REGISTRY,
    AnalyticAvailability,
    AnalyticInputAssemblyError,
    AnalyticInputDTO,
    AnalyticMetricDefinition,
    build_analytic_input_from_storage,
    coerce_selected_number,
    get_analytic_metric_definition,
    stable_manifest_hash,
)
from healthcheck.garmin.capabilities import GarminStream
from healthcheck.garmin.persistence import PROJECTION_CURRENT

R03_02_ALGORITHM = "r03-02-garmin-activity-comparison-v1"
R03_02_RULE_VERSION = "r03-02-v1"

MIN_SELECTED_ACTIVITIES = 2
MAX_SELECTED_ACTIVITIES = 20

ACTIVITY_COMPARISON_METRIC_CODES: tuple[str, ...] = (
    "duration_seconds",
    "distance_meters",
    "speed_mps",
    "heart_rate_bpm",
    "power_watts",
    "cadence_rpm",
    "training_effect",
    "acute_training_load",
)

# Cadence is only comparable when the persisted source leaf is unambiguous RPM.
_CADENCE_UNAMBIGUOUS_LEAVES = frozenset(
    {
        "cadenceRpm",
        "averageBikeCadence",
        "avgBikeCadence",
        "bikeCadence",
    }
)
_CADENCE_AMBIGUOUS_MARKERS = ("RunningCadence", "StepsPerMinute", "stepsPerMinute")

_USABLE_COMPARISON_STATUSES = frozenset({"usable", "zero"})


class GarminActivityComparisonError(ValueError):
    """Deterministic reject for invalid R03-02 comparison requests."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class GarminActivityComparisonQuery:
    """Explicit source + ordered activity record IDs + reference from that set."""

    garmin_source_id: str
    activity_record_ids: tuple[str, ...]
    reference_activity_id: str
    metric_codes: tuple[str, ...] = ACTIVITY_COMPARISON_METRIC_CODES

    def as_dict(self) -> dict[str, Any]:
        return {
            "garmin_source_id": self.garmin_source_id,
            "activity_record_ids": list(self.activity_record_ids),
            "reference_activity_id": self.reference_activity_id,
            "metric_codes": list(self.metric_codes),
            "min_selected_activities": MIN_SELECTED_ACTIVITIES,
            "max_selected_activities": MAX_SELECTED_ACTIVITIES,
        }


@dataclass(frozen=True, slots=True)
class SessionMetricCoverage:
    """Per-session, per-metric coverage with distinct availability states."""

    metric_code: str
    status: str
    value: int | float | None
    is_zero: bool
    unit: str | None
    aggregate_kind: str | None
    window: str | None
    field_path: str | None
    reason: str | None
    input_manifest_hash: str | None
    metric_row_id: str | None
    comparable: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric_code": self.metric_code,
            "status": self.status,
            "value": self.value,
            "is_zero": self.is_zero,
            "unit": self.unit,
            "aggregate_kind": self.aggregate_kind,
            "window": self.window,
            "field_path": self.field_path,
            "reason": self.reason,
            "input_manifest_hash": self.input_manifest_hash,
            "metric_row_id": self.metric_row_id,
            "comparable": self.comparable,
        }


@dataclass(frozen=True, slots=True)
class ComparedActivitySession:
    """One selected activity session with identity, type, and metric coverage."""

    record_id: str
    external_record_id: str | None
    activity_type: str | None
    idempotency_key: str | None
    stream_code: str
    projection_status: str
    is_reference: bool
    temporal: dict[str, Any] | None
    metric_coverage: tuple[SessionMetricCoverage, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "external_record_id": self.external_record_id,
            "activity_type": self.activity_type,
            "idempotency_key": self.idempotency_key,
            "stream_code": self.stream_code,
            "projection_status": self.projection_status,
            "is_reference": self.is_reference,
            "temporal": dict(self.temporal) if self.temporal is not None else None,
            "metric_coverage": [item.as_dict() for item in self.metric_coverage],
        }


@dataclass(frozen=True, slots=True)
class MetricComparisonDelta:
    """Reference vs non-reference metric delta when identities are comparable."""

    metric_code: str
    status: str
    reason: str | None
    reference_value: int | float | None
    compared_value: int | float | None
    absolute_delta: int | float | None
    percent_delta: float | None
    percent_status: str | None
    percent_reason: str | None
    unit: str | None
    aggregate_kind: str | None
    window: str | None
    reference_field_path: str | None
    compared_field_path: str | None
    same_activity_type: bool
    reference_activity_type: str | None
    compared_activity_type: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric_code": self.metric_code,
            "status": self.status,
            "reason": self.reason,
            "reference_value": self.reference_value,
            "compared_value": self.compared_value,
            "absolute_delta": self.absolute_delta,
            "percent_delta": self.percent_delta,
            "percent_status": self.percent_status,
            "percent_reason": self.percent_reason,
            "unit": self.unit,
            "aggregate_kind": self.aggregate_kind,
            "window": self.window,
            "reference_field_path": self.reference_field_path,
            "compared_field_path": self.compared_field_path,
            "same_activity_type": self.same_activity_type,
            "reference_activity_type": self.reference_activity_type,
            "compared_activity_type": self.compared_activity_type,
        }


@dataclass(frozen=True, slots=True)
class SessionComparisonBlock:
    """All metric deltas for one non-reference session vs the reference."""

    compared_record_id: str
    reference_record_id: str
    same_activity_type: bool
    compared_activity_type: str | None
    reference_activity_type: str | None
    metrics: tuple[MetricComparisonDelta, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "compared_record_id": self.compared_record_id,
            "reference_record_id": self.reference_record_id,
            "same_activity_type": self.same_activity_type,
            "compared_activity_type": self.compared_activity_type,
            "reference_activity_type": self.reference_activity_type,
            "metrics": [item.as_dict() for item in self.metrics],
        }


@dataclass(frozen=True, slots=True)
class ComparisonCoverageSummary:
    """Comparison-level coverage counts and deterministic reasons."""

    selected_session_count: int
    metric_code_count: int
    session_metric_cells: int
    usable_count: int
    zero_count: int
    missing_count: int
    null_count: int
    invalid_count: int
    partial_count: int
    not_computable_count: int
    unsupported_count: int
    comparable_pair_count: int
    not_comparable_pair_count: int
    reasons: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "selected_session_count": self.selected_session_count,
            "metric_code_count": self.metric_code_count,
            "session_metric_cells": self.session_metric_cells,
            "usable_count": self.usable_count,
            "zero_count": self.zero_count,
            "missing_count": self.missing_count,
            "null_count": self.null_count,
            "invalid_count": self.invalid_count,
            "partial_count": self.partial_count,
            "not_computable_count": self.not_computable_count,
            "unsupported_count": self.unsupported_count,
            "comparable_pair_count": self.comparable_pair_count,
            "not_comparable_pair_count": self.not_comparable_pair_count,
            "reasons": [dict(item) for item in self.reasons],
        }


@dataclass(frozen=True, slots=True)
class GarminActivityComparisonResult:
    """Versioned deterministic R03-02 result with frozen #55 input manifests."""

    algorithm: str
    rule_version: str
    query: GarminActivityComparisonQuery
    metric_definitions: tuple[AnalyticMetricDefinition, ...]
    sessions: tuple[ComparedActivitySession, ...]
    comparisons: tuple[SessionComparisonBlock, ...]
    coverage: ComparisonCoverageSummary
    frozen_inputs: tuple[dict[str, Any], ...]
    result_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "rule_version": self.rule_version,
            "query": self.query.as_dict(),
            "metric_definitions": [item.as_dict() for item in self.metric_definitions],
            "sessions": [item.as_dict() for item in self.sessions],
            "comparisons": [item.as_dict() for item in self.comparisons],
            "coverage": self.coverage.as_dict(),
            "frozen_inputs": [dict(item) for item in self.frozen_inputs],
            "result_hash": self.result_hash,
        }


def _hash_result_body(body: Mapping[str, Any]) -> str:
    return stable_manifest_hash(body)


def _field_leaf(field_path: str | None) -> str:
    if not field_path:
        return ""
    return field_path.rsplit(".", 1)[-1]


def cadence_source_field_is_unambiguous(field_path: str | None) -> bool:
    """Return True only for reviewed unambiguous cadence RPM source leaves."""

    leaf = _field_leaf(field_path)
    if not leaf:
        return False
    if any(marker in leaf for marker in _CADENCE_AMBIGUOUS_MARKERS):
        return False
    return leaf in _CADENCE_UNAMBIGUOUS_LEAVES


def _validate_query(
    *,
    garmin_source_id: str,
    activity_record_ids: Sequence[str],
    reference_activity_id: str,
    metric_codes: Sequence[str] | None,
) -> GarminActivityComparisonQuery:
    source_id = (garmin_source_id or "").strip()
    if not source_id:
        raise GarminActivityComparisonError(
            "missing_garmin_source_id",
            "garmin_source_id is required for activity comparison",
        )
    if not activity_record_ids:
        raise GarminActivityComparisonError(
            "selection_below_minimum",
            f"activity selection requires {MIN_SELECTED_ACTIVITIES}..{MAX_SELECTED_ACTIVITIES} "
            "distinct record IDs",
        )
    ordered_ids = [str(item).strip() for item in activity_record_ids]
    if any(not item for item in ordered_ids):
        raise GarminActivityComparisonError(
            "blank_activity_record_id",
            "activity_record_ids must not contain blank IDs",
        )
    if len(ordered_ids) != len(set(ordered_ids)):
        raise GarminActivityComparisonError(
            "duplicate_activity_record_ids",
            "activity_record_ids must be distinct",
        )
    if not (MIN_SELECTED_ACTIVITIES <= len(ordered_ids) <= MAX_SELECTED_ACTIVITIES):
        raise GarminActivityComparisonError(
            "selection_bounds_violated",
            f"activity selection requires {MIN_SELECTED_ACTIVITIES}..{MAX_SELECTED_ACTIVITIES} "
            f"distinct record IDs; got {len(ordered_ids)}",
        )
    reference_id = (reference_activity_id or "").strip()
    if not reference_id:
        raise GarminActivityComparisonError(
            "missing_reference_activity_id",
            "reference_activity_id is required",
        )
    if reference_id not in ordered_ids:
        raise GarminActivityComparisonError(
            "reference_not_in_selection",
            "reference_activity_id must be one of the selected activity_record_ids",
        )
    codes = (
        tuple(ACTIVITY_COMPARISON_METRIC_CODES)
        if metric_codes is None
        else tuple(code.strip() for code in metric_codes)
    )
    if not codes:
        raise GarminActivityComparisonError(
            "empty_metric_codes",
            "at least one metric code is required",
        )
    if len(codes) != len(set(codes)):
        raise GarminActivityComparisonError(
            "duplicate_metric_codes",
            "metric_codes must be distinct",
        )
    for code in codes:
        if code not in ACTIVITY_COMPARISON_METRIC_CODES:
            raise GarminActivityComparisonError(
                "unsupported_metric_code",
                f"metric code is not part of R03-02 activity comparison: {code}",
            )
        if code not in ANALYTIC_METRIC_REGISTRY:
            raise GarminActivityComparisonError(
                "unknown_metric_code",
                f"unknown analytic metric code: {code}",
            )
    return GarminActivityComparisonQuery(
        garmin_source_id=source_id,
        activity_record_ids=tuple(ordered_ids),
        reference_activity_id=reference_id,
        metric_codes=codes,
    )


def _load_selected_records(
    session: Session, query: GarminActivityComparisonQuery
) -> tuple[GarminSourceRecord, ...]:
    rows = list(
        session.scalars(
            select(GarminSourceRecord).where(
                GarminSourceRecord.id.in_(query.activity_record_ids)
            )
        )
    )
    by_id = {row.id: row for row in rows}
    ordered: list[GarminSourceRecord] = []
    for record_id in query.activity_record_ids:
        record = by_id.get(record_id)
        if record is None:
            raise GarminActivityComparisonError(
                "unknown_activity_record_id",
                f"activity record not found: {record_id}",
            )
        if record.garmin_source_id != query.garmin_source_id:
            raise GarminActivityComparisonError(
                "wrong_source_activity_record",
                f"activity record {record_id} does not belong to garmin_source_id "
                f"{query.garmin_source_id}",
            )
        if record.projection_status != PROJECTION_CURRENT:
            raise GarminActivityComparisonError(
                "non_current_activity_record",
                f"activity record {record_id} is not a current projection "
                f"(status={record.projection_status})",
            )
        if record.stream_code != GarminStream.ACTIVITY.value:
            raise GarminActivityComparisonError(
                "non_activity_record",
                f"record {record_id} stream_code={record.stream_code!r} is not activity",
            )
        ordered.append(record)
    return tuple(ordered)


def _classify_selected(
    dto: AnalyticInputDTO,
) -> tuple[str, int | float | None, bool, str | None]:
    selected = dto.selected
    state = selected.state
    number = coerce_selected_number(selected.value)
    if state == "value":
        if number is None:
            return "not_computable", None, False, "non_numeric_selected_value"
        is_zero = float(number) == 0.0
        if dto.coverage.availability is AnalyticAvailability.PARTIAL:
            return "partial", number, is_zero, None
        if is_zero:
            return "zero", number, True, None
        return "usable", number, False, None
    if state == "null":
        return "null", None, False, None
    if state == "invalid":
        return "invalid", None, False, "invalid_metric"
    if state == "missing":
        return "missing", None, False, None
    return "not_computable", None, False, f"unsupported_selected_state:{state}"


def _metric_supported_for_dto(
    metric_code: str, dto: AnalyticInputDTO
) -> tuple[bool, str | None]:
    definition = get_analytic_metric_definition(metric_code)
    selected = dto.selected
    if selected.aggregate_kind != definition.aggregate_kind.value:
        return False, "aggregation_mismatch"
    if selected.window != definition.window:
        return False, "window_mismatch"
    if selected.unit != definition.unit:
        return False, "unit_mismatch"
    if metric_code == "cadence_rpm" and not cadence_source_field_is_unambiguous(
        selected.field_path
    ):
        return False, "ambiguous_cadence_source_field"
    # Never invent speed from distance/duration — only provider average speed path.
    if metric_code == "speed_mps":
        leaf = _field_leaf(selected.field_path)
        if leaf not in {"averageSpeed", "speedMps"}:
            return False, "unsupported_speed_source_field"
    return True, None


def _assemble_session_metric(
    session: Session,
    *,
    record: GarminSourceRecord,
    metric_code: str,
) -> tuple[SessionMetricCoverage, AnalyticInputDTO | None]:
    definition = get_analytic_metric_definition(metric_code)
    metric_row = session.scalar(
        select(GarminRecordMetric).where(
            GarminRecordMetric.record_id == record.id,
            GarminRecordMetric.metric_code == metric_code,
        )
    )
    if metric_row is None:
        return (
            SessionMetricCoverage(
                metric_code=metric_code,
                status="not_computable",
                value=None,
                is_zero=False,
                unit=definition.unit,
                aggregate_kind=definition.aggregate_kind.value,
                window=definition.window,
                field_path=None,
                reason="metric_absent_from_projection",
                input_manifest_hash=None,
                metric_row_id=None,
                comparable=False,
            ),
            None,
        )
    try:
        dto = build_analytic_input_from_storage(
            session,
            metric_row_id=metric_row.id,
            metric_code=metric_code,
            operational_surface_present=True,
        )
    except AnalyticInputAssemblyError as exc:
        raise GarminActivityComparisonError(
            "analytic_provenance_fail_closed",
            f"fail-closed analytic input assembly for record={record.id} "
            f"metric={metric_code}: {exc}",
        ) from exc

    status, value, is_zero, classify_reason = _classify_selected(dto)
    supported, support_reason = _metric_supported_for_dto(metric_code, dto)
    if not supported:
        # Preserve distinct missing/null/invalid/partial/not_computable states.
        # Only otherwise-usable values become unsupported/not-comparable.
        if status in _USABLE_COMPARISON_STATUSES:
            status = "unsupported"
        reason = support_reason
        comparable = False
    else:
        reason = classify_reason
        comparable = status in _USABLE_COMPARISON_STATUSES
    return (
        SessionMetricCoverage(
            metric_code=metric_code,
            status=status,
            value=value,
            is_zero=is_zero,
            unit=dto.selected.unit,
            aggregate_kind=dto.selected.aggregate_kind,
            window=dto.selected.window,
            field_path=dto.selected.field_path,
            reason=reason,
            input_manifest_hash=dto.manifest_hash,
            metric_row_id=dto.evidence.metric_row_id,
            comparable=comparable,
        ),
        dto,
    )


def _coverage_lookup(
    session_block: ComparedActivitySession, metric_code: str
) -> SessionMetricCoverage:
    for item in session_block.metric_coverage:
        if item.metric_code == metric_code:
            return item
    raise KeyError(metric_code)


def _percent_delta(
    reference: float, compared: float
) -> tuple[float | None, str, str | None]:
    if not math.isfinite(reference) or not math.isfinite(compared):
        return None, "not_computable", "non_finite_value"
    if reference == 0.0:
        return None, "not_computable", "zero_reference_percent"
    percent = ((compared - reference) / reference) * 100.0
    if not math.isfinite(percent):
        return None, "not_computable", "non_finite_percent"
    return float(percent), "computed", None


def _compare_metric(
    *,
    metric_code: str,
    reference: SessionMetricCoverage,
    compared: SessionMetricCoverage,
    reference_activity_type: str | None,
    compared_activity_type: str | None,
) -> MetricComparisonDelta:
    same_type = reference_activity_type == compared_activity_type
    definition = get_analytic_metric_definition(metric_code)

    if not reference.comparable or not compared.comparable:
        reasons: list[str] = []
        if not reference.comparable:
            reasons.append(
                f"reference:{reference.reason or reference.status}"
            )
        if not compared.comparable:
            reasons.append(
                f"compared:{compared.reason or compared.status}"
            )
        # Aggregation / identity mismatch when both present but disagree.
        if (
            reference.aggregate_kind is not None
            and compared.aggregate_kind is not None
            and reference.aggregate_kind != compared.aggregate_kind
        ):
            reasons.append("aggregation_mismatch")
        if (
            reference.window is not None
            and compared.window is not None
            and reference.window != compared.window
        ):
            reasons.append("window_mismatch")
        if (
            reference.unit is not None
            and compared.unit is not None
            and reference.unit != compared.unit
        ):
            reasons.append("unit_mismatch")
        return MetricComparisonDelta(
            metric_code=metric_code,
            status="not_computable",
            reason=";".join(reasons) if reasons else "not_comparable",
            reference_value=reference.value,
            compared_value=compared.value,
            absolute_delta=None,
            percent_delta=None,
            percent_status="not_computable",
            percent_reason="sides_not_comparable",
            unit=definition.unit,
            aggregate_kind=definition.aggregate_kind.value,
            window=definition.window,
            reference_field_path=reference.field_path,
            compared_field_path=compared.field_path,
            same_activity_type=same_type,
            reference_activity_type=reference_activity_type,
            compared_activity_type=compared_activity_type,
        )

    assert reference.value is not None and compared.value is not None
    ref_num = float(reference.value)
    cmp_num = float(compared.value)
    absolute = cmp_num - ref_num
    # Preserve ints when both sides were integral and delta is integral.
    if isinstance(reference.value, int) and isinstance(compared.value, int):
        absolute_out: int | float = int(absolute)
    elif float(absolute).is_integer():
        absolute_out = int(absolute)
    else:
        absolute_out = float(absolute)
    percent, percent_status, percent_reason = _percent_delta(ref_num, cmp_num)
    return MetricComparisonDelta(
        metric_code=metric_code,
        status="compared",
        reason=None,
        reference_value=reference.value,
        compared_value=compared.value,
        absolute_delta=absolute_out,
        percent_delta=percent,
        percent_status=percent_status,
        percent_reason=percent_reason,
        unit=definition.unit,
        aggregate_kind=definition.aggregate_kind.value,
        window=definition.window,
        reference_field_path=reference.field_path,
        compared_field_path=compared.field_path,
        same_activity_type=same_type,
        reference_activity_type=reference_activity_type,
        compared_activity_type=compared_activity_type,
    )


def _summarize_coverage(
    sessions: Sequence[ComparedActivitySession],
    comparisons: Sequence[SessionComparisonBlock],
    metric_codes: Sequence[str],
) -> ComparisonCoverageSummary:
    statuses = [item.status for session in sessions for item in session.metric_coverage]
    reasons: list[dict[str, Any]] = []
    for session in sessions:
        for item in session.metric_coverage:
            if item.reason:
                reasons.append(
                    {
                        "record_id": session.record_id,
                        "metric_code": item.metric_code,
                        "status": item.status,
                        "reason": item.reason,
                    }
                )
    for block in comparisons:
        for metric in block.metrics:
            if metric.status != "compared" and metric.reason:
                reasons.append(
                    {
                        "compared_record_id": block.compared_record_id,
                        "reference_record_id": block.reference_record_id,
                        "metric_code": metric.metric_code,
                        "status": metric.status,
                        "reason": metric.reason,
                    }
                )
    reasons.sort(
        key=lambda item: (
            item.get("record_id") or item.get("compared_record_id") or "",
            item.get("metric_code") or "",
            item.get("reason") or "",
            item.get("status") or "",
        )
    )
    comparable_pairs = sum(
        1 for block in comparisons for metric in block.metrics if metric.status == "compared"
    )
    not_comparable_pairs = sum(
        1 for block in comparisons for metric in block.metrics if metric.status != "compared"
    )
    return ComparisonCoverageSummary(
        selected_session_count=len(sessions),
        metric_code_count=len(metric_codes),
        session_metric_cells=len(statuses),
        usable_count=sum(1 for status in statuses if status == "usable"),
        zero_count=sum(1 for status in statuses if status == "zero"),
        missing_count=sum(1 for status in statuses if status == "missing"),
        null_count=sum(1 for status in statuses if status == "null"),
        invalid_count=sum(1 for status in statuses if status == "invalid"),
        partial_count=sum(1 for status in statuses if status == "partial"),
        not_computable_count=sum(1 for status in statuses if status == "not_computable"),
        unsupported_count=sum(1 for status in statuses if status == "unsupported"),
        comparable_pair_count=comparable_pairs,
        not_comparable_pair_count=not_comparable_pairs,
        reasons=tuple(reasons),
    )


def compute_garmin_activity_comparison(
    session: Session,
    *,
    garmin_source_id: str,
    activity_record_ids: Sequence[str],
    reference_activity_id: str,
    metric_codes: Sequence[str] | None = None,
) -> GarminActivityComparisonResult:
    """Compare explicitly selected current Garmin activity sessions deterministically.

    Each selected metric input is assembled through ``build_analytic_input_from_storage``
    (#55). Provenance failures fail closed. Provider average speed is never replaced
    by distance/duration. Cadence requires an unambiguous RPM source field.
    """

    query = _validate_query(
        garmin_source_id=garmin_source_id,
        activity_record_ids=activity_record_ids,
        reference_activity_id=reference_activity_id,
        metric_codes=metric_codes,
    )
    records = _load_selected_records(session, query)
    definitions = tuple(get_analytic_metric_definition(code) for code in query.metric_codes)

    sessions: list[ComparedActivitySession] = []
    frozen_by_hash: dict[str, dict[str, Any]] = {}
    coverage_by_record: dict[str, dict[str, SessionMetricCoverage]] = {}

    for record in records:
        metric_rows: list[SessionMetricCoverage] = []
        per_metric: dict[str, SessionMetricCoverage] = {}
        temporal_dict: dict[str, Any] | None = None
        for metric_code in query.metric_codes:
            coverage, dto = _assemble_session_metric(
                session, record=record, metric_code=metric_code
            )
            metric_rows.append(coverage)
            per_metric[metric_code] = coverage
            if dto is not None:
                frozen_by_hash[dto.manifest_hash] = dto.as_dict()
                if temporal_dict is None and dto.temporal is not None:
                    temporal_dict = dto.temporal.as_dict()
        sessions.append(
            ComparedActivitySession(
                record_id=record.id,
                external_record_id=record.external_record_id,
                activity_type=record.activity_type,
                idempotency_key=record.idempotency_key,
                stream_code=record.stream_code,
                projection_status=record.projection_status,
                is_reference=record.id == query.reference_activity_id,
                temporal=temporal_dict,
                metric_coverage=tuple(metric_rows),
            )
        )
        coverage_by_record[record.id] = per_metric

    reference_session = next(
        item for item in sessions if item.record_id == query.reference_activity_id
    )
    comparisons: list[SessionComparisonBlock] = []
    for session_block in sessions:
        if session_block.record_id == query.reference_activity_id:
            continue
        same_type = session_block.activity_type == reference_session.activity_type
        metric_deltas: list[MetricComparisonDelta] = []
        for metric_code in query.metric_codes:
            metric_deltas.append(
                _compare_metric(
                    metric_code=metric_code,
                    reference=coverage_by_record[query.reference_activity_id][metric_code],
                    compared=coverage_by_record[session_block.record_id][metric_code],
                    reference_activity_type=reference_session.activity_type,
                    compared_activity_type=session_block.activity_type,
                )
            )
        comparisons.append(
            SessionComparisonBlock(
                compared_record_id=session_block.record_id,
                reference_record_id=reference_session.record_id,
                same_activity_type=same_type,
                compared_activity_type=session_block.activity_type,
                reference_activity_type=reference_session.activity_type,
                metrics=tuple(metric_deltas),
            )
        )

    coverage = _summarize_coverage(sessions, comparisons, query.metric_codes)
    frozen_inputs = sorted(
        frozen_by_hash.values(),
        key=lambda item: (
            (item.get("evidence") or {}).get("record_id") or "",
            (item.get("selected") or {}).get("metric_code") or "",
            item.get("manifest_hash") or "",
        ),
    )
    body = {
        "algorithm": R03_02_ALGORITHM,
        "rule_version": R03_02_RULE_VERSION,
        "query": query.as_dict(),
        "metric_definitions": [item.as_dict() for item in definitions],
        "sessions": [item.as_dict() for item in sessions],
        "comparisons": [item.as_dict() for item in comparisons],
        "coverage": coverage.as_dict(),
        "frozen_inputs": frozen_inputs,
    }
    result_hash = _hash_result_body(body)
    return GarminActivityComparisonResult(
        algorithm=R03_02_ALGORITHM,
        rule_version=R03_02_RULE_VERSION,
        query=query,
        metric_definitions=definitions,
        sessions=tuple(sessions),
        comparisons=tuple(comparisons),
        coverage=coverage,
        frozen_inputs=tuple(frozen_inputs),
        result_hash=result_hash,
    )


def analyze_garmin_activity_comparison(
    session: Session,
    query: GarminActivityComparisonQuery,
) -> GarminActivityComparisonResult:
    """Public API accepting an explicit :class:`GarminActivityComparisonQuery`."""

    return compute_garmin_activity_comparison(
        session,
        garmin_source_id=query.garmin_source_id,
        activity_record_ids=query.activity_record_ids,
        reference_activity_id=query.reference_activity_id,
        metric_codes=query.metric_codes,
    )


__all__ = [
    "ACTIVITY_COMPARISON_METRIC_CODES",
    "MAX_SELECTED_ACTIVITIES",
    "MIN_SELECTED_ACTIVITIES",
    "R03_02_ALGORITHM",
    "R03_02_RULE_VERSION",
    "ComparedActivitySession",
    "ComparisonCoverageSummary",
    "GarminActivityComparisonError",
    "GarminActivityComparisonQuery",
    "GarminActivityComparisonResult",
    "MetricComparisonDelta",
    "SessionComparisonBlock",
    "SessionMetricCoverage",
    "analyze_garmin_activity_comparison",
    "cadence_source_field_is_unambiguous",
    "compute_garmin_activity_comparison",
]
