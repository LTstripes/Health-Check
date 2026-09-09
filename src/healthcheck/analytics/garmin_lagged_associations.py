"""R03-03 deterministic lagged cross-metric associations.

Bounded exploratory Spearman association between two reviewed Garmin scalar
metric identities over analytic dates and explicit non-negative lags.
Association only — no causal, medical, predictive, readiness, or training claims.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from healthcheck.analytics.garmin_activity_comparison import ACTIVITY_COMPARISON_METRIC_CODES
from healthcheck.analytics.garmin_baselines import (
    MAX_SERIES_CALENDAR_DAYS,
    MAX_SERIES_SELECTED_POINTS,
    GarminScalarAnalyticsError,
    GarminSeriesPoint,
    GarminSeriesPointCapError,
    GarminSeriesWindowError,
    calendar_day_span,
    compute_garmin_scalar_series,
)
from healthcheck.garmin.analytic_contract import (
    ANALYTIC_METRIC_REGISTRY,
    AggregateKind,
    AnalyticInputAssemblyError,
    AnalyticMetricDefinition,
    get_analytic_metric_definition,
    stable_manifest_hash,
)

R03_03_ALGORITHM = "r03-03-garmin-lagged-associations-v1"
R03_03_RULE_VERSION = "r03-03-v1"
R03_03_SPEARMAN_METHOD = "spearman_midrank_correlation_v1"
R03_03_LAG_DIRECTION = "x_at_d_pairs_y_at_d_plus_k"

MIN_PAIRED_N = 5
MIN_DISTINCT_VALUES = 2
MAX_LAG_DAYS = 14
MAX_LAG_COUNT = 15

_COLLECTION_VALUED_METRIC_CODES = frozenset({"sleep_stages"})
_ACTIVITY_SESSION_METRIC_CODES = frozenset(ACTIVITY_COMPARISON_METRIC_CODES)
_PARTICIPATING_STATUSES = frozenset({"usable", "zero"})
_EXCLUSION_STATUS_REASONS = frozenset(
    {
        "missing",
        "null",
        "invalid",
        "partial",
        "not_computable",
        "excluded",
    }
)


class GarminLaggedAssociationError(GarminScalarAnalyticsError):
    """Deterministic reject for invalid R03-03 association requests."""


def spearman_midranks(values: Sequence[float]) -> list[float]:
    """Return 1-based mid-ranks for ``values`` (average rank for ties)."""

    indexed = sorted(enumerate(float(item) for item in values), key=lambda item: item[1])
    ranks = [0.0] * len(indexed)
    index = 0
    while index < len(indexed):
        end = index
        while end + 1 < len(indexed) and indexed[end + 1][1] == indexed[index][1]:
            end += 1
        average_rank = (index + 1 + end + 1) / 2.0
        for cursor in range(index, end + 1):
            ranks[indexed[cursor][0]] = average_rank
        index = end + 1
    return ranks


def spearman_rho(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman rho via mid-ranks; ``None`` when degenerate (no NaN/Inf)."""

    if len(xs) != len(ys):
        raise ValueError("spearman_rho requires equal-length series")
    count = len(xs)
    if count == 0:
        return None
    x_values = [float(item) for item in xs]
    y_values = [float(item) for item in ys]
    if len({item for item in x_values}) < MIN_DISTINCT_VALUES:
        return None
    if len({item for item in y_values}) < MIN_DISTINCT_VALUES:
        return None
    x_ranks = spearman_midranks(x_values)
    y_ranks = spearman_midranks(y_values)
    mean_x = sum(x_ranks) / count
    mean_y = sum(y_ranks) / count
    numerator = 0.0
    sum_sq_x = 0.0
    sum_sq_y = 0.0
    for left, right in zip(x_ranks, y_ranks, strict=True):
        dx = left - mean_x
        dy = right - mean_y
        numerator += dx * dy
        sum_sq_x += dx * dx
        sum_sq_y += dy * dy
    if sum_sq_x == 0.0 or sum_sq_y == 0.0:
        return None
    denominator = math.sqrt(sum_sq_x * sum_sq_y)
    if denominator == 0.0 or not math.isfinite(denominator):
        return None
    rho = numerator / denominator
    if not math.isfinite(rho):
        return None
    return float(max(-1.0, min(1.0, rho)))


@dataclass(frozen=True, slots=True)
class GarminLaggedAssociationQuery:
    """Explicit source, two distinct scalar metrics, date window, and lags."""

    garmin_source_id: str
    x_metric_code: str
    y_metric_code: str
    start_date: date
    end_date: date
    lag_days: tuple[int, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "garmin_source_id": self.garmin_source_id,
            "x_metric_code": self.x_metric_code,
            "y_metric_code": self.y_metric_code,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "lag_days": list(self.lag_days),
            "max_lag_days": MAX_LAG_DAYS,
            "max_lag_count": MAX_LAG_COUNT,
            "max_calendar_days": MAX_SERIES_CALENDAR_DAYS,
            "max_selected_points": MAX_SERIES_SELECTED_POINTS,
            "lag_direction": R03_03_LAG_DIRECTION,
            "min_paired_n": MIN_PAIRED_N,
            "spearman_method": R03_03_SPEARMAN_METHOD,
        }


@dataclass(frozen=True, slots=True)
class PairedAnalyticObservation:
    """One exact X[d] ↔ Y[d+k] pairing used by Spearman."""

    x_analytic_date: str
    y_analytic_date: str
    x_value: float
    y_value: float
    x_is_zero: bool
    y_is_zero: bool
    x_input_manifest_hash: str
    y_input_manifest_hash: str
    x_record_id: str | None
    y_record_id: str | None
    x_metric_row_id: str | None
    y_metric_row_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "x_analytic_date": self.x_analytic_date,
            "y_analytic_date": self.y_analytic_date,
            "x_value": self.x_value,
            "y_value": self.y_value,
            "x_is_zero": self.x_is_zero,
            "y_is_zero": self.y_is_zero,
            "x_input_manifest_hash": self.x_input_manifest_hash,
            "y_input_manifest_hash": self.y_input_manifest_hash,
            "x_record_id": self.x_record_id,
            "y_record_id": self.y_record_id,
            "x_metric_row_id": self.x_metric_row_id,
            "y_metric_row_id": self.y_metric_row_id,
        }


@dataclass(frozen=True, slots=True)
class LagCoverageCounts:
    """Per-lag pairing / availability coverage (neutral, non-causal)."""

    requested_lag_days: int
    candidate_x_count: int
    candidate_y_count: int
    paired_usable_count: int
    zero_x_participation_count: int
    zero_y_participation_count: int
    exclusion_counts: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_lag_days": self.requested_lag_days,
            "candidate_x_count": self.candidate_x_count,
            "candidate_y_count": self.candidate_y_count,
            "paired_usable_count": self.paired_usable_count,
            "zero_x_participation_count": self.zero_x_participation_count,
            "zero_y_participation_count": self.zero_y_participation_count,
            "exclusion_counts": dict(self.exclusion_counts),
        }


@dataclass(frozen=True, slots=True)
class LagAssociationStatistic:
    """One requested lag's association outcome."""

    lag_days: int
    status: str
    reason: str | None
    rho: float | None
    n: int
    distinct_x_count: int
    distinct_y_count: int
    coverage: LagCoverageCounts
    pairing_map: tuple[PairedAnalyticObservation, ...]
    spearman_method: str = R03_03_SPEARMAN_METHOD

    def as_dict(self) -> dict[str, Any]:
        return {
            "lag_days": self.lag_days,
            "status": self.status,
            "reason": self.reason,
            "rho": self.rho,
            "n": self.n,
            "distinct_x_count": self.distinct_x_count,
            "distinct_y_count": self.distinct_y_count,
            "coverage": self.coverage.as_dict(),
            "pairing_map": [item.as_dict() for item in self.pairing_map],
            "spearman_method": self.spearman_method,
        }


@dataclass(frozen=True, slots=True)
class GarminLaggedAssociationResult:
    """Versioned deterministic R03-03 result with frozen #55 input manifests."""

    algorithm: str
    rule_version: str
    query: GarminLaggedAssociationQuery
    x_metric_definition: AnalyticMetricDefinition
    y_metric_definition: AnalyticMetricDefinition
    lags: tuple[LagAssociationStatistic, ...]
    frozen_inputs: tuple[dict[str, Any], ...]
    result_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "rule_version": self.rule_version,
            "query": self.query.as_dict(),
            "x_metric_definition": self.x_metric_definition.as_dict(),
            "y_metric_definition": self.y_metric_definition.as_dict(),
            "lags": [item.as_dict() for item in self.lags],
            "frozen_inputs": [dict(item) for item in self.frozen_inputs],
            "result_hash": self.result_hash,
        }


@dataclass(frozen=True, slots=True)
class _DateScalar:
    status: str
    value: float | None
    is_zero: bool
    analytic_date: str
    input_manifest_hash: str
    record_id: str | None
    metric_row_id: str | None
    exclusion_reason: str | None


def metric_eligible_for_lagged_association(metric_code: str) -> tuple[bool, str | None]:
    """Return whether a registry metric may participate in R03-03 v1."""

    code = metric_code.strip()
    if code not in ANALYTIC_METRIC_REGISTRY:
        return False, "unknown_metric_code"
    if code in _COLLECTION_VALUED_METRIC_CODES:
        return False, "collection_valued_not_scalar"
    definition = get_analytic_metric_definition(code)
    if definition.aggregate_kind is AggregateKind.SAMPLE:
        return False, "sample_metric_not_supported"
    if (
        code in _ACTIVITY_SESSION_METRIC_CODES
        or definition.window == "activity_session"
    ):
        return False, "activity_session_metric_not_supported"
    return True, None


def _validate_metric_code(metric_code: str, *, role: str) -> AnalyticMetricDefinition:
    code = metric_code.strip()
    if not code:
        raise GarminLaggedAssociationError(
            f"missing_{role}_metric_code",
            f"{role}_metric_code is required",
        )
    eligible, reason = metric_eligible_for_lagged_association(code)
    if not eligible:
        assert reason is not None
        raise GarminLaggedAssociationError(
            reason,
            f"{role}_metric_code {metric_code!r} rejected for R03-03: {reason}",
        )
    return get_analytic_metric_definition(code)


def _validate_lags(lag_days: Sequence[int]) -> tuple[int, ...]:
    if lag_days is None:
        raise GarminLaggedAssociationError("empty_lag_days", "lag_days must be non-empty")
    values = list(lag_days)
    if not values:
        raise GarminLaggedAssociationError("empty_lag_days", "lag_days must be non-empty")
    if len(values) > MAX_LAG_COUNT:
        raise GarminLaggedAssociationError(
            "too_many_lag_days",
            f"at most {MAX_LAG_COUNT} lag_days may be requested; got {len(values)}",
        )
    seen: set[int] = set()
    normalized: list[int] = []
    for item in values:
        if isinstance(item, bool) or not isinstance(item, int):
            raise GarminLaggedAssociationError(
                "invalid_lag_days",
                f"lag_days entries must be integers; got {item!r}",
            )
        if item < 0 or item > MAX_LAG_DAYS:
            raise GarminLaggedAssociationError(
                "lag_out_of_range",
                f"lag_days must be in 0..{MAX_LAG_DAYS}; got {item}",
            )
        if item in seen:
            raise GarminLaggedAssociationError(
                "duplicate_lag_days",
                f"lag_days must be unique; duplicate {item}",
            )
        seen.add(item)
        normalized.append(item)
    return tuple(normalized)


def _validate_query(
    query: GarminLaggedAssociationQuery,
) -> tuple[AnalyticMetricDefinition, AnalyticMetricDefinition, tuple[int, ...]]:
    if not query.garmin_source_id or not str(query.garmin_source_id).strip():
        raise GarminLaggedAssociationError(
            "missing_garmin_source_id",
            "garmin_source_id is required for lagged associations",
        )
    if isinstance(query.start_date, datetime) or not isinstance(query.start_date, date):
        raise GarminLaggedAssociationError("invalid_start_date", "start_date must be a date")
    if isinstance(query.end_date, datetime) or not isinstance(query.end_date, date):
        raise GarminLaggedAssociationError("invalid_end_date", "end_date must be a date")
    if query.end_date < query.start_date:
        raise GarminLaggedAssociationError(
            "invalid_date_window",
            "end_date must be on or after start_date",
        )
    x_definition = _validate_metric_code(query.x_metric_code, role="x")
    y_definition = _validate_metric_code(query.y_metric_code, role="y")
    if query.x_metric_code.strip() == query.y_metric_code.strip():
        raise GarminLaggedAssociationError(
            "metrics_must_be_distinct",
            "x_metric_code and y_metric_code must be distinct",
        )
    lags = _validate_lags(query.lag_days)
    max_lag = max(lags)
    materialization_end = query.end_date + timedelta(days=max_lag)
    span = calendar_day_span(query.start_date, materialization_end)
    if span > MAX_SERIES_CALENDAR_DAYS:
        raise GarminSeriesWindowError(
            f"requested window plus max lag spans {span} calendar days; "
            f"max allowed is {MAX_SERIES_CALENDAR_DAYS}"
        )
    return x_definition, y_definition, lags


def _date_in_inclusive_window(analytic_date: str, start: date, end: date) -> bool:
    try:
        value = date.fromisoformat(analytic_date)
    except ValueError:
        return False
    return start <= value <= end


def _build_date_index(
    points: Sequence[GarminSeriesPoint],
    *,
    start: date,
    end: date,
) -> dict[str, _DateScalar]:
    """Collapse series points to at most one scalar per analytic date.

    Multiple candidates for the same metric/date become an explicit ambiguous
    exclusion — never mean/sum/pick-first/pick-latest.
    """

    grouped: dict[str, list[GarminSeriesPoint]] = {}
    for point in points:
        if point.analytic_date is None:
            continue
        if not _date_in_inclusive_window(point.analytic_date, start, end):
            continue
        grouped.setdefault(point.analytic_date, []).append(point)

    resolved: dict[str, _DateScalar] = {}
    for analytic_date, group in grouped.items():
        if len(group) > 1:
            first = group[0]
            resolved[analytic_date] = _DateScalar(
                status="ambiguous",
                value=None,
                is_zero=False,
                analytic_date=analytic_date,
                input_manifest_hash=first.input_manifest_hash,
                record_id=first.record_id,
                metric_row_id=first.metric_row_id,
                exclusion_reason="ambiguous_metric_date",
            )
            continue
        point = group[0]
        if point.status in _PARTICIPATING_STATUSES and point.value is not None:
            value = float(point.value)
            if not math.isfinite(value):
                resolved[analytic_date] = _DateScalar(
                    status="not_computable",
                    value=None,
                    is_zero=False,
                    analytic_date=analytic_date,
                    input_manifest_hash=point.input_manifest_hash,
                    record_id=point.record_id,
                    metric_row_id=point.metric_row_id,
                    exclusion_reason="non_finite_selected_value",
                )
                continue
            resolved[analytic_date] = _DateScalar(
                status=point.status,
                value=value,
                is_zero=bool(point.is_zero or value == 0.0),
                analytic_date=analytic_date,
                input_manifest_hash=point.input_manifest_hash,
                record_id=point.record_id,
                metric_row_id=point.metric_row_id,
                exclusion_reason=None,
            )
            continue
        status = point.status if point.status in _EXCLUSION_STATUS_REASONS else "not_computable"
        resolved[analytic_date] = _DateScalar(
            status=status if status != "excluded" else "excluded",
            value=None,
            is_zero=False,
            analytic_date=analytic_date,
            input_manifest_hash=point.input_manifest_hash,
            record_id=point.record_id,
            metric_row_id=point.metric_row_id,
            exclusion_reason=point.exclusion_reason or status,
        )
    return resolved


def _candidate_count(index: Mapping[str, _DateScalar]) -> int:
    return sum(1 for item in index.values() if item.status in _PARTICIPATING_STATUSES)


def _increment(counts: dict[str, int], reason: str) -> None:
    counts[reason] = counts.get(reason, 0) + 1


def _pair_lag(
    *,
    lag_days: int,
    start: date,
    end: date,
    x_index: Mapping[str, _DateScalar],
    y_index: Mapping[str, _DateScalar],
) -> LagAssociationStatistic:
    exclusion_counts: dict[str, int] = {}
    pairs: list[PairedAnalyticObservation] = []

    # Walk every X analytic date present in the query window (plus gaps only via
    # known X keys). Also consider all dates that appear in x_index within window.
    x_dates = sorted(
        analytic_date
        for analytic_date in x_index
        if _date_in_inclusive_window(analytic_date, start, end)
    )

    for x_date_str in x_dates:
        x_item = x_index[x_date_str]
        x_date = date.fromisoformat(x_date_str)
        y_date = x_date + timedelta(days=lag_days)
        y_date_str = y_date.isoformat()

        if x_item.status == "ambiguous":
            _increment(exclusion_counts, "x_ambiguous_metric_date")
            continue
        if x_item.status not in _PARTICIPATING_STATUSES:
            _increment(exclusion_counts, f"x_{x_item.status}")
            continue

        y_item = y_index.get(y_date_str)
        if y_item is None:
            _increment(exclusion_counts, "y_absent_at_lag")
            continue
        if y_item.status == "ambiguous":
            _increment(exclusion_counts, "y_ambiguous_metric_date")
            continue
        if y_item.status not in _PARTICIPATING_STATUSES:
            _increment(exclusion_counts, f"y_{y_item.status}")
            continue

        assert x_item.value is not None and y_item.value is not None
        pairs.append(
            PairedAnalyticObservation(
                x_analytic_date=x_date_str,
                y_analytic_date=y_date_str,
                x_value=x_item.value,
                y_value=y_item.value,
                x_is_zero=x_item.is_zero,
                y_is_zero=y_item.is_zero,
                x_input_manifest_hash=x_item.input_manifest_hash,
                y_input_manifest_hash=y_item.input_manifest_hash,
                x_record_id=x_item.record_id,
                y_record_id=y_item.record_id,
                x_metric_row_id=x_item.metric_row_id,
                y_metric_row_id=y_item.metric_row_id,
            )
        )

    pairs.sort(key=lambda item: (item.x_analytic_date, item.y_analytic_date))
    x_values = [item.x_value for item in pairs]
    y_values = [item.y_value for item in pairs]
    n = len(pairs)
    distinct_x = len({item for item in x_values})
    distinct_y = len({item for item in y_values})
    coverage = LagCoverageCounts(
        requested_lag_days=lag_days,
        candidate_x_count=_candidate_count(
            {
                key: value
                for key, value in x_index.items()
                if _date_in_inclusive_window(key, start, end)
            }
        ),
        candidate_y_count=_candidate_count(y_index),
        paired_usable_count=n,
        zero_x_participation_count=sum(1 for item in pairs if item.x_is_zero),
        zero_y_participation_count=sum(1 for item in pairs if item.y_is_zero),
        exclusion_counts=dict(sorted(exclusion_counts.items())),
    )

    if n < MIN_PAIRED_N:
        return LagAssociationStatistic(
            lag_days=lag_days,
            status="not_computable",
            reason="insufficient_paired_n",
            rho=None,
            n=n,
            distinct_x_count=distinct_x,
            distinct_y_count=distinct_y,
            coverage=coverage,
            pairing_map=tuple(pairs),
        )
    if distinct_x < MIN_DISTINCT_VALUES or distinct_y < MIN_DISTINCT_VALUES:
        return LagAssociationStatistic(
            lag_days=lag_days,
            status="not_computable",
            reason="constant_or_degenerate_input",
            rho=None,
            n=n,
            distinct_x_count=distinct_x,
            distinct_y_count=distinct_y,
            coverage=coverage,
            pairing_map=tuple(pairs),
        )

    rho = spearman_rho(x_values, y_values)
    if rho is None:
        return LagAssociationStatistic(
            lag_days=lag_days,
            status="not_computable",
            reason="constant_or_degenerate_input",
            rho=None,
            n=n,
            distinct_x_count=distinct_x,
            distinct_y_count=distinct_y,
            coverage=coverage,
            pairing_map=tuple(pairs),
        )
    return LagAssociationStatistic(
        lag_days=lag_days,
        status="association_available",
        reason=None,
        rho=rho,
        n=n,
        distinct_x_count=distinct_x,
        distinct_y_count=distinct_y,
        coverage=coverage,
        pairing_map=tuple(pairs),
    )


def _merge_frozen_inputs(
    x_frozen: Sequence[Mapping[str, Any]],
    y_frozen: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    merged: list[dict[str, Any]] = []
    for role, items in (("x", x_frozen), ("y", y_frozen)):
        for item in items:
            payload = dict(item)
            payload["_association_role"] = role
            merged.append(payload)
    merged.sort(
        key=lambda item: (
            item.get("_association_role") or "",
            (item.get("temporal") or {}).get("analytic_date") or "",
            (item.get("temporal") or {}).get("measured_at_utc") or "",
            (item.get("temporal") or {}).get("local_wall_time") or "",
            (item.get("evidence") or {}).get("record_id") or "",
            (item.get("evidence") or {}).get("metric_row_id") or "",
            (item.get("evidence") or {}).get("idempotency_key") or "",
            item.get("manifest_hash") or "",
        )
    )
    return tuple(merged)


def compute_garmin_lagged_associations(
    session: Session,
    *,
    garmin_source_id: str,
    x_metric_code: str,
    y_metric_code: str,
    start_date: date,
    end_date: date,
    lag_days: Sequence[int],
) -> GarminLaggedAssociationResult:
    """Build bounded deterministic lagged Spearman associations for two scalars.

    Inputs are assembled through the accepted #55/#67 storage-backed scalar
    series path. Provenance failures fail closed. Same frozen inputs/query/rules
    => same result hash.
    """

    normalized_lags = _validate_lags(lag_days)
    query = GarminLaggedAssociationQuery(
        garmin_source_id=garmin_source_id.strip(),
        x_metric_code=x_metric_code.strip(),
        y_metric_code=y_metric_code.strip(),
        start_date=start_date,
        end_date=end_date,
        lag_days=normalized_lags,
    )
    x_definition, y_definition, normalized_lags = _validate_query(query)

    max_lag = max(normalized_lags)
    y_end = query.end_date + timedelta(days=max_lag)

    x_series = compute_garmin_scalar_series(
        session,
        metric_code=query.x_metric_code,
        start_date=query.start_date,
        end_date=query.end_date,
        garmin_source_id=query.garmin_source_id,
    )
    y_series = compute_garmin_scalar_series(
        session,
        metric_code=query.y_metric_code,
        start_date=query.start_date,
        end_date=y_end,
        garmin_source_id=query.garmin_source_id,
    )

    x_index = _build_date_index(
        x_series.points,
        start=query.start_date,
        end=query.end_date,
    )
    y_index = _build_date_index(
        y_series.points,
        start=query.start_date,
        end=y_end,
    )

    lag_results = tuple(
        _pair_lag(
            lag_days=lag,
            start=query.start_date,
            end=query.end_date,
            x_index=x_index,
            y_index=y_index,
        )
        for lag in normalized_lags
    )

    frozen_inputs = _merge_frozen_inputs(x_series.frozen_inputs, y_series.frozen_inputs)
    body = {
        "algorithm": R03_03_ALGORITHM,
        "rule_version": R03_03_RULE_VERSION,
        "query": query.as_dict(),
        "x_metric_definition": x_definition.as_dict(),
        "y_metric_definition": y_definition.as_dict(),
        "lags": [item.as_dict() for item in lag_results],
        "frozen_inputs": [dict(item) for item in frozen_inputs],
    }
    result_hash = stable_manifest_hash(body)
    return GarminLaggedAssociationResult(
        algorithm=R03_03_ALGORITHM,
        rule_version=R03_03_RULE_VERSION,
        query=query,
        x_metric_definition=x_definition,
        y_metric_definition=y_definition,
        lags=lag_results,
        frozen_inputs=frozen_inputs,
        result_hash=result_hash,
    )


def analyze_garmin_lagged_associations(
    session: Session,
    query: GarminLaggedAssociationQuery,
) -> GarminLaggedAssociationResult:
    """Public API accepting an explicit :class:`GarminLaggedAssociationQuery`."""

    return compute_garmin_lagged_associations(
        session,
        garmin_source_id=query.garmin_source_id,
        x_metric_code=query.x_metric_code,
        y_metric_code=query.y_metric_code,
        start_date=query.start_date,
        end_date=query.end_date,
        lag_days=query.lag_days,
    )


__all__ = [
    "MAX_LAG_COUNT",
    "MAX_LAG_DAYS",
    "MIN_DISTINCT_VALUES",
    "MIN_PAIRED_N",
    "R03_03_ALGORITHM",
    "R03_03_LAG_DIRECTION",
    "R03_03_RULE_VERSION",
    "R03_03_SPEARMAN_METHOD",
    "AnalyticInputAssemblyError",
    "GarminLaggedAssociationError",
    "GarminLaggedAssociationQuery",
    "GarminLaggedAssociationResult",
    "GarminSeriesPointCapError",
    "GarminSeriesWindowError",
    "LagAssociationStatistic",
    "LagCoverageCounts",
    "PairedAnalyticObservation",
    "analyze_garmin_lagged_associations",
    "compute_garmin_lagged_associations",
    "metric_eligible_for_lagged_association",
    "spearman_midranks",
    "spearman_rho",
]
