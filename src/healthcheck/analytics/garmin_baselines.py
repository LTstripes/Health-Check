"""R03-01 deterministic Garmin scalar series, personal baselines, and trends.

Bounded read/analytics over accepted #55 analytic input manifests. No UI,
reporting, AI, cycling comparison, or cross-metric correlation.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord
from healthcheck.garmin.analytic_contract import (
    ANALYTIC_METRIC_REGISTRY,
    AggregateKind,
    AnalyticInputAssemblyError,
    AnalyticInputDTO,
    AnalyticMetricDefinition,
    build_analytic_input_from_storage,
    coerce_selected_number,
    get_analytic_metric_definition,
    stable_manifest_hash,
)
from healthcheck.garmin.persistence import PROJECTION_CURRENT

R03_01_ALGORITHM = "r03-01-garmin-scalar-baselines-v1"
R03_01_RULE_VERSION = "r03-01-v1"
R03_01_QUANTILE_METHOD = "type7_linear_interpolation"
R03_01_PERCENTILE_METHOD = "personal_window_midrank_v1"
R03_01_TREND_METHOD = "theil_sen_median_pairwise_per_day_v1"
R03_01_DEVIATION_METHOD = "modified_robust_z_mad_v1"

MAX_SERIES_CALENDAR_DAYS = 400
# Hard cap on selected/candidate analytic input rows for one R03-01 query.
# Calendar-day bound alone is insufficient for sample metrics (stress_sample,
# spo2_sample): a valid <=400-day window can still select thousands of current
# rows, and Theil-Sen is O(n^2). v1 fail-closes above this deterministic
# ceiling (no silent truncate/sample). 2000 keeps pairwise work bounded
# (~2e6 slopes) while remaining comparable to the calendar bound for aggregates.
MAX_SERIES_SELECTED_POINTS = 2000
PERCENTILE_MIN_USABLE = 5
TREND_MIN_USABLE = 3
TREND_MIN_DISTINCT_DATES = 3
DEVIATION_MIN_USABLE = 5
ROBUST_Z_SCALE = 0.67448975
PERSONAL_BASELINE_DEVIATION_ABS_Z = 3.5

# Collection-valued registry identities are not scalar R03-01 inputs.
_COLLECTION_VALUED_METRIC_CODES = frozenset({"sleep_stages"})

_DAILY_AMBIGUITY_KINDS = frozenset(
    {
        AggregateKind.DAILY_AVERAGE,
        AggregateKind.DAILY_MAXIMUM,
        AggregateKind.TRAILING_AGGREGATE,
    }
)


class GarminScalarAnalyticsError(ValueError):
    """Deterministic reject for invalid R03-01 series requests."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class GarminSeriesWindowError(GarminScalarAnalyticsError):
    """Request window exceeds the hard R03-01 bound."""

    def __init__(self, message: str) -> None:
        super().__init__("window_exceeds_max_calendar_days", message)


class GarminSeriesPointCapError(GarminScalarAnalyticsError):
    """Selected/candidate analytic inputs exceed the hard R03-01 point bound."""

    def __init__(self, message: str) -> None:
        super().__init__("selected_points_exceed_max", message)


def calendar_day_span(start_date: date, end_date: date) -> int:
    """Inclusive calendar-day count for an explicit date window."""

    return (end_date - start_date).days + 1


def type7_quantile(values: Sequence[float], probability: float) -> float:
    """Hyndman-Fan Type-7 / R quantile (linear interpolation).

    ``probability`` is in ``[0, 1]``. Matches ``statistics.quantiles(..., method='inclusive')``
    cut-point semantics for the corresponding probabilities.
    """

    if not 0.0 <= probability <= 1.0:
        raise ValueError("quantile probability must be in [0, 1]")
    ordered = sorted(float(item) for item in values)
    count = len(ordered)
    if count == 0:
        raise ValueError("quantile requires at least one value")
    if count == 1:
        return ordered[0]
    index = 1.0 + (count - 1) * probability
    low = int(math.floor(index))
    frac = index - low
    if frac == 0.0:
        return ordered[low - 1]
    return ordered[low - 1] + frac * (ordered[low] - ordered[low - 1])


def personal_midrank_percentile(values: Sequence[float], latest: float) -> float:
    """Personal-window mid-rank percentile: ``100 * (less + 0.5 * equal) / n``."""

    sample = [float(item) for item in values]
    count = len(sample)
    if count == 0:
        raise ValueError("percentile requires at least one value")
    target = float(latest)
    count_less = sum(1 for item in sample if item < target)
    count_equal = sum(1 for item in sample if item == target)
    return 100.0 * (count_less + 0.5 * count_equal) / count


def theil_sen_slope_per_day(
    points: Sequence[tuple[date, float]],
) -> tuple[float, int] | None:
    """Median of finite pairwise slopes with non-zero day delta (per day)."""

    slopes: list[float] = []
    for left in range(len(points)):
        for right in range(left + 1, len(points)):
            delta_days = (points[right][0] - points[left][0]).days
            if delta_days == 0:
                continue
            slope = (points[right][1] - points[left][1]) / delta_days
            if math.isfinite(slope):
                slopes.append(float(slope))
    if not slopes:
        return None
    return float(statistics.median(slopes)), len(slopes)


def modified_robust_z(values: Sequence[float], latest: float) -> tuple[float, float, float] | None:
    """Return ``(z, median, mad)`` or ``None`` when MAD is zero/non-finite."""

    sample = [float(item) for item in values]
    if not sample:
        return None
    median = float(statistics.median(sample))
    mad = float(statistics.median([abs(item - median) for item in sample]))
    if not math.isfinite(mad) or mad == 0.0:
        return None
    z_score = ROBUST_Z_SCALE * (float(latest) - median) / mad
    if not math.isfinite(z_score):
        return None
    return float(z_score), median, mad


@dataclass(frozen=True, slots=True)
class GarminSeriesQuery:
    """Explicit registered metric + inclusive local/analytic date bounds."""

    metric_code: str
    start_date: date
    end_date: date
    garmin_source_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric_code": self.metric_code,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "garmin_source_id": self.garmin_source_id,
            "max_calendar_days": MAX_SERIES_CALENDAR_DAYS,
            "max_selected_points": MAX_SERIES_SELECTED_POINTS,
        }


@dataclass(frozen=True, slots=True)
class SeriesExclusion:
    reason_code: str
    detail: str | None = None
    record_id: str | None = None
    metric_row_id: str | None = None
    analytic_date: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "detail": self.detail,
            "record_id": self.record_id,
            "metric_row_id": self.metric_row_id,
            "analytic_date": self.analytic_date,
        }


@dataclass(frozen=True, slots=True)
class GarminSeriesPoint:
    """One ordered series member with distinct availability semantics."""

    status: str
    value: int | float | None
    analytic_date: str | None
    measured_at_utc: str | None
    local_wall_time: str | None
    zone_policy: str | None
    temporal_precision: str | None
    is_zero: bool
    exclusion_reason: str | None
    input_manifest_hash: str
    record_id: str | None
    metric_row_id: str | None
    idempotency_key: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "value": self.value,
            "analytic_date": self.analytic_date,
            "measured_at_utc": self.measured_at_utc,
            "local_wall_time": self.local_wall_time,
            "zone_policy": self.zone_policy,
            "temporal_precision": self.temporal_precision,
            "is_zero": self.is_zero,
            "exclusion_reason": self.exclusion_reason,
            "input_manifest_hash": self.input_manifest_hash,
            "record_id": self.record_id,
            "metric_row_id": self.metric_row_id,
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True, slots=True)
class SeriesAvailabilityCounts:
    candidate_count: int
    usable_count: int
    zero_count: int
    excluded_count: int
    missing_count: int
    null_count: int
    invalid_count: int
    not_computable_count: int
    partial_count: int
    exclusions: tuple[SeriesExclusion, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_count": self.candidate_count,
            "usable_count": self.usable_count,
            "zero_count": self.zero_count,
            "excluded_count": self.excluded_count,
            "missing_count": self.missing_count,
            "null_count": self.null_count,
            "invalid_count": self.invalid_count,
            "not_computable_count": self.not_computable_count,
            "partial_count": self.partial_count,
            "exclusions": [item.as_dict() for item in self.exclusions],
        }


@dataclass(frozen=True, slots=True)
class PersonalBaselineStats:
    available: bool
    reason: str | None
    count: int | None
    mean: float | None
    median: float | None
    p10: float | None
    p25: float | None
    p50: float | None
    p75: float | None
    p90: float | None
    minimum: float | None
    maximum: float | None
    quantile_method: str = R03_01_QUANTILE_METHOD
    label: str = "personal_descriptive_baseline"

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "count": self.count,
            "mean": self.mean,
            "median": self.median,
            "p10": self.p10,
            "p25": self.p25,
            "p50": self.p50,
            "p75": self.p75,
            "p90": self.p90,
            "min": self.minimum,
            "max": self.maximum,
            "quantile_method": self.quantile_method,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class PersonalPercentileResult:
    available: bool
    reason: str | None
    value: float | None
    latest_value: float | None
    n: int | None
    method: str = R03_01_PERCENTILE_METHOD
    label: str = "personal_window_percentile"

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "value": self.value,
            "latest_value": self.latest_value,
            "n": self.n,
            "method": self.method,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class RobustTrendResult:
    available: bool
    reason: str | None
    slope_per_day: float | None
    input_count: int | None
    distinct_analytic_dates: int | None
    pair_count: int | None
    method: str = R03_01_TREND_METHOD

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "slope_per_day": self.slope_per_day,
            "input_count": self.input_count,
            "distinct_analytic_dates": self.distinct_analytic_dates,
            "pair_count": self.pair_count,
            "method": self.method,
        }


@dataclass(frozen=True, slots=True)
class RobustDeviationResult:
    available: bool
    reason: str | None
    robust_z: float | None
    mad: float | None
    median: float | None
    latest_value: float | None
    personal_baseline_deviation: bool | None
    threshold_abs_z: float = PERSONAL_BASELINE_DEVIATION_ABS_Z
    method: str = R03_01_DEVIATION_METHOD
    label: str = "personal_baseline_deviation"

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "robust_z": self.robust_z,
            "mad": self.mad,
            "median": self.median,
            "latest_value": self.latest_value,
            "personal_baseline_deviation": self.personal_baseline_deviation,
            "threshold_abs_z": self.threshold_abs_z,
            "method": self.method,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class GarminScalarSeriesResult:
    """Versioned deterministic R03-01 result with frozen #55 input manifests."""

    algorithm: str
    rule_version: str
    query: GarminSeriesQuery
    metric_definition: AnalyticMetricDefinition
    points: tuple[GarminSeriesPoint, ...]
    availability: SeriesAvailabilityCounts
    baseline: PersonalBaselineStats
    personal_percentile: PersonalPercentileResult
    trend: RobustTrendResult
    deviation: RobustDeviationResult
    frozen_inputs: tuple[dict[str, Any], ...]
    result_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "rule_version": self.rule_version,
            "query": self.query.as_dict(),
            "metric_definition": self.metric_definition.as_dict(),
            "points": [item.as_dict() for item in self.points],
            "availability": self.availability.as_dict(),
            "baseline": self.baseline.as_dict(),
            "personal_percentile": self.personal_percentile.as_dict(),
            "trend": self.trend.as_dict(),
            "deviation": self.deviation.as_dict(),
            "frozen_inputs": [dict(item) for item in self.frozen_inputs],
            "result_hash": self.result_hash,
        }


def _validate_query(query: GarminSeriesQuery) -> AnalyticMetricDefinition:
    metric_code = query.metric_code.strip()
    if metric_code not in ANALYTIC_METRIC_REGISTRY:
        raise GarminScalarAnalyticsError(
            "unknown_metric_code",
            f"unknown analytic metric code: {query.metric_code}",
        )
    if isinstance(query.start_date, datetime) or not isinstance(query.start_date, date):
        raise GarminScalarAnalyticsError("invalid_start_date", "start_date must be a date")
    if isinstance(query.end_date, datetime) or not isinstance(query.end_date, date):
        raise GarminScalarAnalyticsError("invalid_end_date", "end_date must be a date")
    if query.end_date < query.start_date:
        raise GarminScalarAnalyticsError(
            "invalid_date_window",
            "end_date must be on or after start_date",
        )
    span = calendar_day_span(query.start_date, query.end_date)
    if span > MAX_SERIES_CALENDAR_DAYS:
        raise GarminSeriesWindowError(
            f"requested window spans {span} calendar days; "
            f"max allowed is {MAX_SERIES_CALENDAR_DAYS}"
        )
    if not query.garmin_source_id or not str(query.garmin_source_id).strip():
        raise GarminScalarAnalyticsError(
            "missing_garmin_source_id",
            "garmin_source_id is required for personal baseline analytics",
        )
    definition = get_analytic_metric_definition(metric_code)
    if metric_code in _COLLECTION_VALUED_METRIC_CODES:
        raise GarminScalarAnalyticsError(
            "collection_valued_not_scalar",
            f"metric {metric_code} is collection-valued and not a R03-01 scalar",
        )
    return definition


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


def _point_sort_key(point: GarminSeriesPoint) -> tuple[Any, ...]:
    return (
        point.analytic_date or "",
        point.measured_at_utc or "",
        point.local_wall_time or "",
        point.record_id or "",
        point.metric_row_id or "",
        point.idempotency_key or "",
        point.input_manifest_hash,
    )


def _analytic_date_in_window(analytic_date: str | None, query: GarminSeriesQuery) -> bool:
    if analytic_date is None:
        return False
    try:
        value = date.fromisoformat(analytic_date)
    except ValueError:
        return False
    return query.start_date <= value <= query.end_date


def _classify_input(dto: AnalyticInputDTO) -> tuple[str, int | float | None, bool, str | None]:
    """Return ``(status, value, is_zero, exclusion_reason)`` for one frozen input."""

    selected = dto.selected
    if selected.collection and selected.metric_code in _COLLECTION_VALUED_METRIC_CODES:
        return "not_computable", None, False, "collection_valued_not_scalar"
    state = selected.state
    number = coerce_selected_number(selected.value)
    if state == "value":
        if number is None:
            return "not_computable", None, False, "non_numeric_selected_value"
        is_zero = float(number) == 0.0
        if dto.coverage.availability.value == "partial":
            return "partial", number, is_zero, None
        if is_zero:
            return "zero", number, True, None
        return "usable", number, False, None
    if state == "null":
        return "null", None, False, None
    if state == "invalid":
        return "invalid", None, False, selected.state
    if state == "missing":
        return "missing", None, False, None
    return "not_computable", None, False, f"unsupported_selected_state:{state}"


def _empty_baseline(reason: str) -> PersonalBaselineStats:
    return PersonalBaselineStats(
        available=False,
        reason=reason,
        count=None,
        mean=None,
        median=None,
        p10=None,
        p25=None,
        p50=None,
        p75=None,
        p90=None,
        minimum=None,
        maximum=None,
    )


def _compute_baseline(values: Sequence[float]) -> PersonalBaselineStats:
    if not values:
        return _empty_baseline("no_usable_values")
    sample = [float(item) for item in values]
    return PersonalBaselineStats(
        available=True,
        reason=None,
        count=len(sample),
        mean=float(statistics.fmean(sample)),
        median=float(statistics.median(sample)),
        p10=type7_quantile(sample, 0.10),
        p25=type7_quantile(sample, 0.25),
        p50=type7_quantile(sample, 0.50),
        p75=type7_quantile(sample, 0.75),
        p90=type7_quantile(sample, 0.90),
        minimum=float(min(sample)),
        maximum=float(max(sample)),
    )


def _compute_percentile(values: Sequence[float]) -> PersonalPercentileResult:
    if len(values) < PERCENTILE_MIN_USABLE:
        return PersonalPercentileResult(
            available=False,
            reason="insufficient_usable_values",
            value=None,
            latest_value=None,
            n=len(values),
        )
    latest = float(values[-1])
    return PersonalPercentileResult(
        available=True,
        reason=None,
        value=personal_midrank_percentile(values, latest),
        latest_value=latest,
        n=len(values),
    )


def _compute_trend(dated_values: Sequence[tuple[date, float]]) -> RobustTrendResult:
    distinct_dates = {item[0] for item in dated_values}
    if (
        len(dated_values) < TREND_MIN_USABLE
        or len(distinct_dates) < TREND_MIN_DISTINCT_DATES
    ):
        return RobustTrendResult(
            available=False,
            reason="insufficient_temporal_sample",
            slope_per_day=None,
            input_count=len(dated_values),
            distinct_analytic_dates=len(distinct_dates),
            pair_count=None,
        )
    computed = theil_sen_slope_per_day(dated_values)
    if computed is None:
        return RobustTrendResult(
            available=False,
            reason="no_nonzero_time_delta_pairs",
            slope_per_day=None,
            input_count=len(dated_values),
            distinct_analytic_dates=len(distinct_dates),
            pair_count=0,
        )
    slope, pair_count = computed
    return RobustTrendResult(
        available=True,
        reason=None,
        slope_per_day=slope,
        input_count=len(dated_values),
        distinct_analytic_dates=len(distinct_dates),
        pair_count=pair_count,
    )


def _compute_deviation(values: Sequence[float]) -> RobustDeviationResult:
    if len(values) < DEVIATION_MIN_USABLE:
        return RobustDeviationResult(
            available=False,
            reason="insufficient_usable_values",
            robust_z=None,
            mad=None,
            median=None,
            latest_value=None,
            personal_baseline_deviation=None,
        )
    latest = float(values[-1])
    computed = modified_robust_z(values, latest)
    if computed is None:
        return RobustDeviationResult(
            available=False,
            reason="mad_zero_or_non_finite",
            robust_z=None,
            mad=0.0,
            median=float(statistics.median(values)),
            latest_value=latest,
            personal_baseline_deviation=None,
        )
    z_score, median, mad = computed
    return RobustDeviationResult(
        available=True,
        reason=None,
        robust_z=z_score,
        mad=mad,
        median=median,
        latest_value=latest,
        personal_baseline_deviation=abs(z_score) >= PERSONAL_BASELINE_DEVIATION_ABS_Z,
    )


def _hash_result_body(body: Mapping[str, Any]) -> str:
    return stable_manifest_hash(body)


def compute_garmin_scalar_series(
    session: Session,
    *,
    metric_code: str,
    start_date: date,
    end_date: date,
    garmin_source_id: str,
) -> GarminScalarSeriesResult:
    """Build a bounded deterministic scalar series + personal baseline summary.

    Each selected current projection row is assembled through
    ``build_analytic_input_from_storage`` (#55). Provenance failures fail closed.
    """

    query = GarminSeriesQuery(
        metric_code=metric_code.strip(),
        start_date=start_date,
        end_date=end_date,
        garmin_source_id=garmin_source_id.strip(),
    )
    definition = _validate_query(query)

    # Fail-closed selected-point bound before assembly / Theil-Sen / frozen result.
    # Fetch cap+1 so over-cap is detected without materializing an unbounded set
    # and without silently truncating to the cap.
    rows = list(
        session.execute(
            _candidate_statement(query).limit(MAX_SERIES_SELECTED_POINTS + 1)
        ).all()
    )
    if len(rows) > MAX_SERIES_SELECTED_POINTS:
        raise GarminSeriesPointCapError(
            f"selected at least {len(rows)} candidate analytic inputs; "
            f"max allowed is {MAX_SERIES_SELECTED_POINTS}"
        )
    assembled: list[AnalyticInputDTO] = []
    for metric_row, _record in rows:
        dto = build_analytic_input_from_storage(
            session,
            metric_row_id=metric_row.id,
            metric_code=query.metric_code,
            operational_surface_present=False,
        )
        assembled.append(dto)

    # Filter to analytic window using #55 temporal projection; never invent UTC.
    windowed: list[AnalyticInputDTO] = []
    points: list[GarminSeriesPoint] = []
    exclusions: list[SeriesExclusion] = []
    frozen_by_hash: dict[str, dict[str, Any]] = {}

    for dto in assembled:
        temporal = dto.temporal
        analytic_date = temporal.analytic_date if temporal is not None else None
        if analytic_date is None:
            reason = "missing_analytic_coordinate"
            exclusions.append(
                SeriesExclusion(
                    reason_code=reason,
                    detail="no deterministic analytic date",
                    record_id=dto.evidence.record_id,
                    metric_row_id=dto.evidence.metric_row_id,
                )
            )
            points.append(
                GarminSeriesPoint(
                    status="excluded",
                    value=None,
                    analytic_date=None,
                    measured_at_utc=temporal.measured_at_utc if temporal else None,
                    local_wall_time=temporal.local_wall_time if temporal else None,
                    zone_policy=temporal.zone_policy if temporal else None,
                    temporal_precision=temporal.precision if temporal else None,
                    is_zero=False,
                    exclusion_reason=reason,
                    input_manifest_hash=dto.manifest_hash,
                    record_id=dto.evidence.record_id,
                    metric_row_id=dto.evidence.metric_row_id,
                    idempotency_key=dto.evidence.idempotency_key,
                )
            )
            frozen_by_hash[dto.manifest_hash] = dto.as_dict()
            continue
        if not _analytic_date_in_window(analytic_date, query):
            # Outside-window dates from the broad UTC probe stay out of the series.
            continue
        windowed.append(dto)

    # Daily-aggregate ambiguity: multiple current rows for same analytic date.
    if definition.aggregate_kind in _DAILY_AMBIGUITY_KINDS:
        by_date: dict[str, list[AnalyticInputDTO]] = {}
        for dto in windowed:
            assert dto.temporal is not None and dto.temporal.analytic_date is not None
            by_date.setdefault(dto.temporal.analytic_date, []).append(dto)
        ambiguous_ids = {
            dto.evidence.metric_row_id
            for group in by_date.values()
            if len(group) > 1
            for dto in group
        }
    else:
        ambiguous_ids = set()

    for dto in windowed:
        frozen_by_hash[dto.manifest_hash] = dto.as_dict()
        temporal = dto.temporal
        assert temporal is not None
        analytic_date = temporal.analytic_date
        assert analytic_date is not None
        metric_row_id = dto.evidence.metric_row_id
        if metric_row_id in ambiguous_ids:
            exclusions.append(
                SeriesExclusion(
                    reason_code="ambiguous_daily_aggregate",
                    detail="multiple current rows for same metric/date; no silent average",
                    record_id=dto.evidence.record_id,
                    metric_row_id=metric_row_id,
                    analytic_date=analytic_date,
                )
            )
            points.append(
                GarminSeriesPoint(
                    status="excluded",
                    value=None,
                    analytic_date=analytic_date,
                    measured_at_utc=temporal.measured_at_utc,
                    local_wall_time=temporal.local_wall_time,
                    zone_policy=temporal.zone_policy,
                    temporal_precision=temporal.precision,
                    is_zero=False,
                    exclusion_reason="ambiguous_daily_aggregate",
                    input_manifest_hash=dto.manifest_hash,
                    record_id=dto.evidence.record_id,
                    metric_row_id=metric_row_id,
                    idempotency_key=dto.evidence.idempotency_key,
                )
            )
            continue

        status, value, is_zero, classify_reason = _classify_input(dto)
        if status in {"not_computable", "invalid"}:
            exclusions.append(
                SeriesExclusion(
                    reason_code=classify_reason or status,
                    detail=classify_reason,
                    record_id=dto.evidence.record_id,
                    metric_row_id=metric_row_id,
                    analytic_date=analytic_date,
                )
            )
        exclusion_reason = None
        if status in {"excluded", "not_computable"}:
            exclusion_reason = classify_reason
        points.append(
            GarminSeriesPoint(
                status=status,
                value=value,
                analytic_date=analytic_date,
                measured_at_utc=temporal.measured_at_utc,
                local_wall_time=temporal.local_wall_time,
                zone_policy=temporal.zone_policy,
                temporal_precision=temporal.precision,
                is_zero=is_zero,
                exclusion_reason=exclusion_reason,
                input_manifest_hash=dto.manifest_hash,
                record_id=dto.evidence.record_id,
                metric_row_id=metric_row_id,
                idempotency_key=dto.evidence.idempotency_key,
            )
        )

    points.sort(key=_point_sort_key)
    frozen_inputs = sorted(
        frozen_by_hash.values(),
        key=lambda item: (
            (item.get("temporal") or {}).get("analytic_date") or "",
            (item.get("temporal") or {}).get("measured_at_utc") or "",
            (item.get("temporal") or {}).get("local_wall_time") or "",
            (item.get("evidence") or {}).get("record_id") or "",
            (item.get("evidence") or {}).get("metric_row_id") or "",
            (item.get("evidence") or {}).get("idempotency_key") or "",
            item.get("manifest_hash") or "",
        ),
    )
    usable_values: list[float] = []
    dated_usable: list[tuple[date, float]] = []
    for point in points:
        if point.status in {"usable", "zero", "partial"} and point.value is not None:
            usable_values.append(float(point.value))
            if point.analytic_date is not None:
                dated_usable.append(
                    (date.fromisoformat(point.analytic_date), float(point.value))
                )

    exclusions.sort(
        key=lambda item: (
            item.reason_code,
            item.analytic_date or "",
            item.record_id or "",
            item.metric_row_id or "",
            item.detail or "",
        )
    )

    availability = SeriesAvailabilityCounts(
        candidate_count=len(points),
        usable_count=sum(1 for item in points if item.status in {"usable", "zero", "partial"}),
        zero_count=sum(1 for item in points if item.is_zero or item.status == "zero"),
        excluded_count=sum(1 for item in points if item.status == "excluded"),
        missing_count=sum(1 for item in points if item.status == "missing"),
        null_count=sum(1 for item in points if item.status == "null"),
        invalid_count=sum(1 for item in points if item.status == "invalid"),
        not_computable_count=sum(1 for item in points if item.status == "not_computable"),
        partial_count=sum(1 for item in points if item.status == "partial"),
        exclusions=tuple(exclusions),
    )

    baseline = _compute_baseline(usable_values)
    percentile = _compute_percentile(usable_values)
    trend = _compute_trend(dated_usable)
    deviation = _compute_deviation(usable_values)

    body = {
        "algorithm": R03_01_ALGORITHM,
        "rule_version": R03_01_RULE_VERSION,
        "query": query.as_dict(),
        "metric_definition": definition.as_dict(),
        "points": [item.as_dict() for item in points],
        "availability": availability.as_dict(),
        "baseline": baseline.as_dict(),
        "personal_percentile": percentile.as_dict(),
        "trend": trend.as_dict(),
        "deviation": deviation.as_dict(),
        "frozen_inputs": frozen_inputs,
    }
    result_hash = _hash_result_body(body)
    return GarminScalarSeriesResult(
        algorithm=R03_01_ALGORITHM,
        rule_version=R03_01_RULE_VERSION,
        query=query,
        metric_definition=definition,
        points=tuple(points),
        availability=availability,
        baseline=baseline,
        personal_percentile=percentile,
        trend=trend,
        deviation=deviation,
        frozen_inputs=tuple(frozen_inputs),
        result_hash=result_hash,
    )


def analyze_garmin_metric_series(
    session: Session,
    query: GarminSeriesQuery,
) -> GarminScalarSeriesResult:
    """Public API accepting an explicit :class:`GarminSeriesQuery`."""

    return compute_garmin_scalar_series(
        session,
        metric_code=query.metric_code,
        start_date=query.start_date,
        end_date=query.end_date,
        garmin_source_id=query.garmin_source_id,
    )


__all__ = [
    "DEVIATION_MIN_USABLE",
    "MAX_SERIES_CALENDAR_DAYS",
    "MAX_SERIES_SELECTED_POINTS",
    "PERCENTILE_MIN_USABLE",
    "PERSONAL_BASELINE_DEVIATION_ABS_Z",
    "R03_01_ALGORITHM",
    "R03_01_DEVIATION_METHOD",
    "R03_01_PERCENTILE_METHOD",
    "R03_01_QUANTILE_METHOD",
    "R03_01_RULE_VERSION",
    "R03_01_TREND_METHOD",
    "ROBUST_Z_SCALE",
    "TREND_MIN_DISTINCT_DATES",
    "TREND_MIN_USABLE",
    "AnalyticInputAssemblyError",
    "GarminScalarAnalyticsError",
    "GarminScalarSeriesResult",
    "GarminSeriesPoint",
    "GarminSeriesPointCapError",
    "GarminSeriesQuery",
    "GarminSeriesWindowError",
    "PersonalBaselineStats",
    "PersonalPercentileResult",
    "RobustDeviationResult",
    "RobustTrendResult",
    "SeriesAvailabilityCounts",
    "SeriesExclusion",
    "analyze_garmin_metric_series",
    "calendar_day_span",
    "compute_garmin_scalar_series",
    "modified_robust_z",
    "personal_midrank_percentile",
    "theil_sen_slope_per_day",
    "type7_quantile",
]
