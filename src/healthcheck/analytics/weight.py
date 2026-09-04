"""Pure deterministic R01 weight and body-composition analytics v1.

All functions are framework-free: they consume immutable records (notably
:class:`CanonicalCandidate` from #7) and return immutable DTOs.  Framework
objects (SQLAlchemy sessions, FastAPI requests) must never enter this module.

Contracts implemented (``docs/R01_IMPLEMENTATION_SPEC.md`` §11):

- daily median reduction for multiple canonical weights on one local date;
- ``weight_trend_taewma_v1``: time-aware EWMA with a 21-day half-life;
- ``weight_rate_theil_sen_90d_v1``: trailing 90-calendar-day Theil–Sen slope
  in kg/week, available only with >= 6 observations spanning >= 42 days;
- ``body_composition_decomposition_v1``: same confirmed session estimated
  fat/lean mass from weight + body-fat percentage with exact input IDs.
  Algorithm identity belongs to each scalar independently: the weight and
  the body-fat value may carry different measurement-algorithm
  compatibility groups, and the derived group follows the BIA lineage;
- source muscle mass stays distinct from estimated lean mass;
- recomposition evidence only inside one measurement-algorithm compatibility
  group; similar-weight comparison only for observations >= 28 days apart
  with weight differing by <= 1%;
- missing/insufficient evidence returns ``unavailable`` + reason, never a
  fabricated zero.

Accepted #7 contracts consumed:

- canonical identity is ``(selection_run_id, metric_code, semantic_key)``
  (surfaced here as ``metric_code``/``semantic_key``/``evidence_id``);
- coverage is source/provider scoped (consumed as an opaque
  :class:`CoverageSummary`; this module never recomputes coverage);
- failed canonical runs are never active (only ``confirmed`` + ``current``
  candidates are eligible here);
- canonical period fields may be null: observation dates always come from
  the source session local date (``source_local_date``); no midnight UTC
  timestamp is ever invented.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

WEIGHT_TREND_ALGORITHM = "weight_trend_taewma_v1"
WEIGHT_RATE_ALGORITHM = "weight_rate_theil_sen_90d_v1"
BODY_COMPOSITION_ALGORITHM = "body_composition_decomposition_v1"
WEIGHT_ANALYTICS_VERSION = "v1"

EWMA_HALF_LIFE_DAYS = 21.0
RATE_WINDOW_DAYS = 90
RATE_MIN_OBSERVATIONS = 6
RATE_MIN_SPAN_DAYS = 42
SIMILAR_MIN_GAP_DAYS = 28
SIMILAR_MAX_WEIGHT_DIFF_RATIO = 0.01

WEIGHT_METRIC_CODES = frozenset({"weight"})
BODY_FAT_METRIC_CODES = frozenset({"body_fat_pct", "body_fat", "body_fat_percentage"})
MUSCLE_METRIC_CODES = frozenset({"muscle_mass", "muscle_mass_kg"})
WEIGHT_UNITS = frozenset({"kg"})
BODY_FAT_UNITS = frozenset({"%", "pct", "percent", "percentage", "percentage_points", "pp"})

_CONSUMER_BIA_NOTE = (
    "Consumer BIA is trend evidence, not precise tissue truth: "
    "small changes may reflect hydration, glycogen, or method noise, "
    "never an automatic claim of muscle gain or fat loss."
)


def ewma_alpha(delta_days: float, half_life_days: float = EWMA_HALF_LIFE_DAYS) -> float:
    """Return the time-aware smoothing factor for a gap of ``delta_days``.

    ``alpha = 1 - 2**(-delta_days / half_life)`` per the R01 spec.  A zero
    gap yields 0.0 (trend unchanged); a 21-day gap yields exactly 0.5.
    """

    if not math.isfinite(delta_days) or delta_days < 0:
        raise ValueError("ewma delta_days must be a finite nonnegative number")
    if not math.isfinite(half_life_days) or half_life_days <= 0:
        raise ValueError("ewma half_life_days must be a finite positive number")
    return 1.0 - 2.0 ** (-delta_days / half_life_days)


@dataclass(frozen=True, slots=True)
class WeightObservation:
    """One confirmed canonical weight projected to the analytics contract."""

    evidence_id: str
    observed_date: date
    value_kg: float
    source_timestamp_utc: datetime | None = None
    compatibility_group: str | None = None
    source_id: str | None = None
    algorithm_code: str | None = None
    algorithm_version: str | None = None
    semantic_key: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "observed_date": self.observed_date.isoformat(),
            "value_kg": self.value_kg,
            "source_timestamp_utc": (
                self.source_timestamp_utc.isoformat() if self.source_timestamp_utc else None
            ),
            "compatibility_group": self.compatibility_group,
            "source_id": self.source_id,
            "algorithm_code": self.algorithm_code,
            "algorithm_version": self.algorithm_version,
            "semantic_key": self.semantic_key,
        }


@dataclass(frozen=True, slots=True)
class WeightExclusion:
    """A candidate skipped by analytics with a stable machine-readable reason."""

    evidence_id: str | None
    metric_code: str | None
    semantic_key: str | None
    reason_code: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "metric_code": self.metric_code,
            "semantic_key": self.semantic_key,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class DailyWeightPoint:
    """Daily median of canonical weights for one local date."""

    observed_date: date
    median_kg: float
    observation_count: int
    evidence_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "observed_date": self.observed_date.isoformat(),
            "median_kg": self.median_kg,
            "observation_count": self.observation_count,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class TrendPoint:
    """One time-aware EWMA step; raw daily medians stay visible separately."""

    observed_date: date
    median_kg: float
    trend_kg: float
    alpha: float | None
    delta_days: float | None
    evidence_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "observed_date": self.observed_date.isoformat(),
            "median_kg": self.median_kg,
            "trend_kg": self.trend_kg,
            "alpha": self.alpha,
            "delta_days": self.delta_days,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class WeightTrendResult:
    algorithm: str = WEIGHT_TREND_ALGORITHM
    available: bool = True
    reason: str | None = None
    points: tuple[TrendPoint, ...] = ()
    daily_points: tuple[DailyWeightPoint, ...] = ()
    input_count: int = 0
    covered_span_days: int | None = None
    exclusions: tuple[WeightExclusion, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "available": self.available,
            "reason": self.reason,
            "points": [item.as_dict() for item in self.points],
            "daily_points": [item.as_dict() for item in self.daily_points],
            "input_count": self.input_count,
            "covered_span_days": self.covered_span_days,
            "exclusions": [item.as_dict() for item in self.exclusions],
        }


@dataclass(frozen=True, slots=True)
class WeightRateResult:
    algorithm: str = WEIGHT_RATE_ALGORITHM
    available: bool = False
    reason: str | None = None
    slope_kg_per_week: float | None = None
    observation_count: int = 0
    covered_span_days: int | None = None
    window_start_date: date | None = None
    window_end_date: date | None = None
    pair_count: int = 0
    exclusions: tuple[WeightExclusion, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "available": self.available,
            "reason": self.reason,
            "slope_kg_per_week": self.slope_kg_per_week,
            "observation_count": self.observation_count,
            "covered_span_days": self.covered_span_days,
            "window_start_date": self.window_start_date.isoformat()
            if self.window_start_date
            else None,
            "window_end_date": self.window_end_date.isoformat()
            if self.window_end_date
            else None,
            "pair_count": self.pair_count,
            "exclusions": [item.as_dict() for item in self.exclusions],
        }


@dataclass(frozen=True, slots=True)
class CompositionInput:
    """One scalar value offered for same-session fat/lean derivation."""

    measurement_id: str
    metric_code: str
    value: float
    unit: str | None = None
    session_id: str | None = None
    compatibility_group: str | None = None
    algorithm_code: str | None = None
    algorithm_version: str | None = None
    observed_date: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_code", self.metric_code.strip())


@dataclass(frozen=True, slots=True)
class BodyCompositionResult:
    algorithm: str = BODY_COMPOSITION_ALGORITHM
    available: bool = False
    reason: str | None = None
    session_id: str | None = None
    observed_date: date | None = None
    weight_kg: float | None = None
    body_fat_pct: float | None = None
    estimated_fat_mass_kg: float | None = None
    estimated_lean_mass_kg: float | None = None
    weight_measurement_id: str | None = None
    body_fat_measurement_id: str | None = None
    compatibility_group: str | None = None
    analytics_version: str = WEIGHT_ANALYTICS_VERSION
    caution: str = _CONSUMER_BIA_NOTE

    def as_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "available": self.available,
            "reason": self.reason,
            "session_id": self.session_id,
            "observed_date": self.observed_date.isoformat() if self.observed_date else None,
            "weight_kg": self.weight_kg,
            "body_fat_pct": self.body_fat_pct,
            "estimated_fat_mass_kg": self.estimated_fat_mass_kg,
            "estimated_lean_mass_kg": self.estimated_lean_mass_kg,
            "weight_measurement_id": self.weight_measurement_id,
            "body_fat_measurement_id": self.body_fat_measurement_id,
            "input_measurement_ids": (
                [self.weight_measurement_id, self.body_fat_measurement_id]
                if self.weight_measurement_id and self.body_fat_measurement_id
                else []
            ),
            "compatibility_group": self.compatibility_group,
            "analytics_version": self.analytics_version,
            "caution": self.caution,
        }


@dataclass(frozen=True, slots=True)
class CompositionPoint:
    """One session's derived composition with its source muscle kept separate.

    Exact source algorithm provenance (code/version) travels with the point;
    the compatibility group alone is never a substitute for it.
    """

    session_id: str
    observed_date: date
    compatibility_group: str | None
    weight_kg: float | None = None
    body_fat_pct: float | None = None
    estimated_fat_mass_kg: float | None = None
    estimated_lean_mass_kg: float | None = None
    source_muscle_mass_kg: float | None = None
    weight_measurement_id: str | None = None
    body_fat_measurement_id: str | None = None
    muscle_measurement_id: str | None = None
    algorithm_code: str | None = None
    algorithm_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "observed_date": self.observed_date.isoformat(),
            "compatibility_group": self.compatibility_group,
            "algorithm_code": self.algorithm_code,
            "algorithm_version": self.algorithm_version,
            "weight_kg": self.weight_kg,
            "body_fat_pct": self.body_fat_pct,
            "estimated_fat_mass_kg": self.estimated_fat_mass_kg,
            "estimated_lean_mass_kg": self.estimated_lean_mass_kg,
            "source_muscle_mass_kg": self.source_muscle_mass_kg,
            "weight_measurement_id": self.weight_measurement_id,
            "body_fat_measurement_id": self.body_fat_measurement_id,
            "muscle_measurement_id": self.muscle_measurement_id,
        }


@dataclass(frozen=True, slots=True)
class SimilarWeightComparison:
    available: bool = False
    reason: str | None = None
    earlier_date: date | None = None
    later_date: date | None = None
    days_apart: int | None = None
    earlier_weight_kg: float | None = None
    later_weight_kg: float | None = None
    weight_delta_kg: float | None = None
    weight_diff_ratio: float | None = None
    earlier_body_fat_pct: float | None = None
    later_body_fat_pct: float | None = None
    body_fat_delta_pp: float | None = None
    earlier_fat_mass_kg: float | None = None
    later_fat_mass_kg: float | None = None
    fat_mass_delta_kg: float | None = None
    compatibility_group: str | None = None
    earlier_algorithm_code: str | None = None
    earlier_algorithm_version: str | None = None
    later_algorithm_code: str | None = None
    later_algorithm_version: str | None = None
    caution: str = _CONSUMER_BIA_NOTE

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "earlier_date": self.earlier_date.isoformat() if self.earlier_date else None,
            "later_date": self.later_date.isoformat() if self.later_date else None,
            "days_apart": self.days_apart,
            "earlier_weight_kg": self.earlier_weight_kg,
            "later_weight_kg": self.later_weight_kg,
            "weight_delta_kg": self.weight_delta_kg,
            "weight_diff_ratio": self.weight_diff_ratio,
            "earlier_body_fat_pct": self.earlier_body_fat_pct,
            "later_body_fat_pct": self.later_body_fat_pct,
            "body_fat_delta_pp": self.body_fat_delta_pp,
            "earlier_fat_mass_kg": self.earlier_fat_mass_kg,
            "later_fat_mass_kg": self.later_fat_mass_kg,
            "fat_mass_delta_kg": self.fat_mass_delta_kg,
            "compatibility_group": self.compatibility_group,
            "earlier_algorithm_code": self.earlier_algorithm_code,
            "earlier_algorithm_version": self.earlier_algorithm_version,
            "later_algorithm_code": self.later_algorithm_code,
            "later_algorithm_version": self.later_algorithm_version,
            "caution": self.caution,
        }


@dataclass(frozen=True, slots=True)
class WeightSeries:
    """Raw + daily + trend points with provenance for API/UI consumers.

    ``raw_points`` preserves every canonical weight observation for
    drill-down; ``daily_points`` holds the per-date medians the trend
    actually consumes.
    """

    raw_points: tuple[WeightObservation, ...] = ()
    daily_points: tuple[DailyWeightPoint, ...] = ()
    trend_points: tuple[TrendPoint, ...] = ()
    trend_algorithm: str = WEIGHT_TREND_ALGORITHM
    trend_available: bool = False
    trend_reason: str | None = None
    input_count: int = 0
    covered_span_days: int | None = None
    exclusions: tuple[WeightExclusion, ...] = ()
    composition_by_group: Mapping[str, tuple[CompositionPoint, ...]] = field(
        default_factory=dict
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_points": [item.as_dict() for item in self.raw_points],
            "daily_points": [item.as_dict() for item in self.daily_points],
            "trend_points": [item.as_dict() for item in self.trend_points],
            "trend_algorithm": self.trend_algorithm,
            "trend_available": self.trend_available,
            "trend_reason": self.trend_reason,
            "input_count": self.input_count,
            "covered_span_days": self.covered_span_days,
            "exclusions": [item.as_dict() for item in self.exclusions],
            "composition_by_group": {
                group: [item.as_dict() for item in points]
                for group, points in self.composition_by_group.items()
            },
        }


@dataclass(frozen=True, slots=True)
class WeightSummary:
    """Everything the dashboard summary endpoint needs, with explicit gaps."""

    trend: WeightTrendResult = field(default_factory=WeightTrendResult)
    rate: WeightRateResult = field(default_factory=WeightRateResult)
    latest_composition: BodyCompositionResult = field(
        default_factory=BodyCompositionResult
    )
    similar_weight: SimilarWeightComparison = field(
        default_factory=SimilarWeightComparison
    )
    coverage: Mapping[str, Any] | None = None
    algorithm_versions: Mapping[str, str] = field(
        default_factory=lambda: {
            "trend": WEIGHT_TREND_ALGORITHM,
            "rate": WEIGHT_RATE_ALGORITHM,
            "composition": BODY_COMPOSITION_ALGORITHM,
        }
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "trend": self.trend.as_dict(),
            "rate": self.rate.as_dict(),
            "latest_composition": self.latest_composition.as_dict(),
            "similar_weight": self.similar_weight.as_dict(),
            "coverage": dict(self.coverage) if self.coverage is not None else None,
            "algorithm_versions": dict(self.algorithm_versions),
        }


def coerce_weight_observations(
    candidates: Iterable[Any],
    *,
    compatibility_group: str | None = None,
) -> tuple[tuple[WeightObservation, ...], tuple[WeightExclusion, ...]]:
    """Project canonical candidates to weight observations.

    Only ``confirmed`` + ``current`` candidates with metric ``weight``,
    a finite positive kilogram value, and a source local date survive.
    Repository-loaded canonical period fields may be null, so the source
    session local date is the only accepted observation date — a missing
    date excludes the point (``missing_observed_date``) instead of
    inventing a midnight timestamp.
    """

    normalized_group = compatibility_group.strip() if compatibility_group else None
    observations: list[WeightObservation] = []
    exclusions: list[WeightExclusion] = []
    for candidate in candidates:
        metric = str(getattr(candidate, "metric_code", "") or "").strip()
        semantic = getattr(candidate, "semantic_key", None)
        evidence = (
            getattr(candidate, "evidence_id", None)
            or getattr(candidate, "source_measurement_id", None)
            or getattr(candidate, "derived_measurement_id", None)
        )
        if metric not in WEIGHT_METRIC_CODES:
            continue
        if not bool(getattr(candidate, "confirmed", True)):
            exclusions.append(_exclusion(evidence, metric, semantic, "not_confirmed"))
            continue
        if not bool(getattr(candidate, "current", True)):
            exclusions.append(_exclusion(evidence, metric, semantic, "superseded"))
            continue
        group = getattr(candidate, "compatibility_group", None)
        group = group.strip() if isinstance(group, str) and group.strip() else None
        if normalized_group is not None and group != normalized_group:
            exclusions.append(
                _exclusion(evidence, metric, semantic, "incompatible_algorithm_group")
            )
            continue
        observed = getattr(candidate, "source_local_date", None)
        if observed is None:
            exclusions.append(
                _exclusion(evidence, metric, semantic, "missing_observed_date")
            )
            continue
        if isinstance(observed, datetime):
            observed = observed.date()
        if not isinstance(observed, date):
            exclusions.append(
                _exclusion(evidence, metric, semantic, "missing_observed_date")
            )
            continue
        value = getattr(candidate, "normalized_value", None)
        if value is None or not isinstance(value, (int, float)) or not math.isfinite(
            float(value)
        ):
            exclusions.append(_exclusion(evidence, metric, semantic, "missing_value"))
            continue
        if float(value) <= 0:
            exclusions.append(
                _exclusion(evidence, metric, semantic, "non_positive_weight")
            )
            continue
        unit = getattr(candidate, "normalized_unit", None)
        if unit is not None and str(unit).strip().casefold() != "kg":
            exclusions.append(_exclusion(evidence, metric, semantic, "invalid_unit"))
            continue
        observations.append(
            WeightObservation(
                evidence_id=str(evidence) if evidence is not None else "",
                observed_date=observed,
                value_kg=float(value),
                source_timestamp_utc=getattr(candidate, "source_timestamp_utc", None),
                compatibility_group=group,
                source_id=None,
                algorithm_code=getattr(candidate, "algorithm_code", None),
                algorithm_version=getattr(candidate, "algorithm_version", None),
                semantic_key=str(semantic) if semantic is not None else None,
            )
        )
    observations.sort(key=_observation_sort_key)
    exclusions.sort(
        key=lambda item: (item.metric_code or "", item.semantic_key or "",
                          item.evidence_id or "", item.reason_code)
    )
    return tuple(observations), tuple(exclusions)


def daily_median_weights(
    observations: Iterable[WeightObservation],
) -> tuple[DailyWeightPoint, ...]:
    """Reduce multiple canonical weights on one local date to the median."""

    by_date: dict[date, list[WeightObservation]] = {}
    for item in observations:
        by_date.setdefault(item.observed_date, []).append(item)
    points: list[DailyWeightPoint] = []
    for observed_date in sorted(by_date):
        items = sorted(by_date[observed_date], key=_observation_sort_key)
        values = [item.value_kg for item in items]
        points.append(
            DailyWeightPoint(
                observed_date=observed_date,
                median_kg=float(statistics.median(values)),
                observation_count=len(items),
                evidence_ids=tuple(item.evidence_id for item in items),
            )
        )
    return tuple(points)


def time_aware_ewma(
    daily_points: Iterable[DailyWeightPoint],
    *,
    exclusions: Iterable[WeightExclusion] = (),
) -> WeightTrendResult:
    """Apply the 21-day half-life time-aware EWMA over daily medians."""

    ordered = tuple(sorted(daily_points, key=lambda item: item.observed_date))
    normalized_exclusions = tuple(exclusions)
    if not ordered:
        return WeightTrendResult(
            available=False,
            reason="no_data",
            exclusions=normalized_exclusions,
        )
    points: list[TrendPoint] = []
    previous_trend: float | None = None
    previous_date: date | None = None
    for current in ordered:
        if previous_trend is None or previous_date is None:
            trend = current.median_kg
            alpha: float | None = None
            delta: float | None = None
        else:
            delta_days = float((current.observed_date - previous_date).days)
            alpha_value = ewma_alpha(delta_days)
            trend = alpha_value * current.median_kg + (1.0 - alpha_value) * previous_trend
            alpha = alpha_value
            delta = delta_days
        points.append(
            TrendPoint(
                observed_date=current.observed_date,
                median_kg=current.median_kg,
                trend_kg=trend,
                alpha=alpha,
                delta_days=delta,
                evidence_ids=current.evidence_ids,
            )
        )
        previous_trend = trend
        previous_date = current.observed_date
    span = (ordered[-1].observed_date - ordered[0].observed_date).days
    return WeightTrendResult(
        available=True,
        reason=None,
        points=tuple(points),
        daily_points=ordered,
        input_count=sum(item.observation_count for item in ordered),
        covered_span_days=span,
        exclusions=normalized_exclusions,
    )


def theil_sen_rate(
    daily_points: Iterable[DailyWeightPoint],
    *,
    as_of_date: date | None = None,
    exclusions: Iterable[WeightExclusion] = (),
) -> WeightRateResult:
    """Compute the trailing 90-calendar-day Theil–Sen slope in kg/week.

    The window is ``(latest - 90 days, latest]`` where ``latest`` is the
    newest daily median (or ``as_of_date`` when it precedes the data — the
    window never looks into the future).  At least six observations spanning
    at least 42 days are required; anything less returns ``unavailable``
    with a reason, never a fabricated zero.
    """

    ordered = tuple(sorted(daily_points, key=lambda item: item.observed_date))
    normalized_exclusions = tuple(exclusions)
    if not ordered:
        return WeightRateResult(
            available=False, reason="no_data", exclusions=normalized_exclusions
        )
    latest = ordered[-1].observed_date
    if as_of_date is not None and as_of_date < latest:
        latest = as_of_date
    window_start = _add_days(latest, -RATE_WINDOW_DAYS)
    window = tuple(
        item for item in ordered if item.observed_date > window_start
        and item.observed_date <= latest
    )
    if not window:
        return WeightRateResult(
            available=False,
            reason="no_data_in_window",
            window_start_date=window_start,
            window_end_date=latest,
            exclusions=normalized_exclusions,
        )
    span = (window[-1].observed_date - window[0].observed_date).days
    if len(window) < RATE_MIN_OBSERVATIONS:
        return WeightRateResult(
            available=False,
            reason="insufficient_observations",
            observation_count=len(window),
            covered_span_days=span,
            window_start_date=window_start,
            window_end_date=latest,
            exclusions=normalized_exclusions,
        )
    if span < RATE_MIN_SPAN_DAYS:
        return WeightRateResult(
            available=False,
            reason="insufficient_span",
            observation_count=len(window),
            covered_span_days=span,
            window_start_date=window_start,
            window_end_date=latest,
            exclusions=normalized_exclusions,
        )
    slopes: list[float] = []
    for left in range(len(window)):
        for right in range(left + 1, len(window)):
            days = (window[right].observed_date - window[left].observed_date).days
            if days <= 0:
                continue
            slopes.append((window[right].median_kg - window[left].median_kg) / days)
    if not slopes:
        return WeightRateResult(
            available=False,
            reason="insufficient_span",
            observation_count=len(window),
            covered_span_days=span,
            window_start_date=window_start,
            window_end_date=latest,
            exclusions=normalized_exclusions,
        )
    median_per_day = float(statistics.median(slopes))
    return WeightRateResult(
        available=True,
        reason=None,
        slope_kg_per_week=median_per_day * 7.0,
        observation_count=len(window),
        covered_span_days=span,
        window_start_date=window_start,
        window_end_date=latest,
        pair_count=len(slopes),
        exclusions=normalized_exclusions,
    )


def derive_body_composition(
    weight: CompositionInput | None,
    body_fat: CompositionInput | None,
    *,
    analytics_version: str = WEIGHT_ANALYTICS_VERSION,
) -> BodyCompositionResult:
    """Derive estimated fat/lean mass for one confirmed same-session pair.

    Algorithm identity belongs to each scalar measurement independently, so
    the raw weight and the body-fat value are NOT required to share a
    measurement-algorithm compatibility group (e.g. a scale weight group
    next to a Xiaomi-app BIA group is a valid pair).  The derived
    composition compatibility group represents the body-composition/BIA
    algorithm lineage, i.e. the body-fat input's group.
    """

    if weight is None or body_fat is None:
        missing = "weight" if weight is None else "body_fat"
        return BodyCompositionResult(available=False, reason=f"missing_{missing}")
    if weight.metric_code not in WEIGHT_METRIC_CODES:
        return BodyCompositionResult(available=False, reason="invalid_weight_metric")
    if body_fat.metric_code in MUSCLE_METRIC_CODES:
        return BodyCompositionResult(
            available=False, reason="source_muscle_not_lean"
        )
    if body_fat.metric_code not in BODY_FAT_METRIC_CODES:
        return BodyCompositionResult(available=False, reason="invalid_body_fat_metric")
    if weight.session_id is None or body_fat.session_id is None:
        return BodyCompositionResult(available=False, reason="missing_session")
    if weight.session_id != body_fat.session_id:
        return BodyCompositionResult(available=False, reason="cross_session")
    if (
        weight.observed_date is not None
        and body_fat.observed_date is not None
        and weight.observed_date != body_fat.observed_date
    ):
        return BodyCompositionResult(
            available=False, reason="conflicting_observed_date"
        )
    if not _unit_accepted(weight.unit, WEIGHT_UNITS) or not _unit_accepted(
        body_fat.unit, BODY_FAT_UNITS
    ):
        return BodyCompositionResult(available=False, reason="invalid_unit")
    fat_group = _normalize_group(body_fat.compatibility_group)
    if fat_group is None:
        return BodyCompositionResult(
            available=False, reason="missing_compatibility_group"
        )
    if not math.isfinite(weight.value) or weight.value <= 0:
        return BodyCompositionResult(available=False, reason="invalid_weight_value")
    if not math.isfinite(body_fat.value) or not 0.0 < body_fat.value < 100.0:
        return BodyCompositionResult(available=False, reason="invalid_body_fat_value")
    fat_mass = weight.value * body_fat.value / 100.0
    lean_mass = weight.value - fat_mass
    observed = weight.observed_date or body_fat.observed_date
    return BodyCompositionResult(
        available=True,
        reason=None,
        session_id=weight.session_id,
        observed_date=observed,
        weight_kg=weight.value,
        body_fat_pct=body_fat.value,
        estimated_fat_mass_kg=fat_mass,
        estimated_lean_mass_kg=lean_mass,
        weight_measurement_id=weight.measurement_id,
        body_fat_measurement_id=body_fat.measurement_id,
        compatibility_group=fat_group,
        analytics_version=analytics_version,
    )


def composition_series_by_group(
    sessions: Iterable[Mapping[str, Any]],
) -> dict[str, tuple[CompositionPoint, ...]]:
    """Group per-session composition evidence by algorithm compatibility group.

    Each session mapping carries ``session_id``, ``observed_date``,
    ``compatibility_group``, optional ``weight``/``body_fat``/``muscle``
    sub-mappings with ``measurement_id`` + ``value``, and is derived only
    inside its own group — groups are never merged or calibrated against
    each other.  Source muscle mass is preserved as its own field and never
    renamed to lean mass.
    """

    grouped: dict[str, list[CompositionPoint]] = {}
    for session in sessions:
        session_id = session.get("session_id")
        observed = session.get("observed_date")
        if session_id is None or observed is None:
            continue
        if isinstance(observed, str):
            observed = date.fromisoformat(observed[:10])
        if isinstance(observed, datetime):
            observed = observed.date()
        if not isinstance(observed, date):
            continue
        group = _normalize_group(session.get("compatibility_group"))
        if group is None:
            continue
        weight = session.get("weight") or {}
        body_fat = session.get("body_fat") or {}
        muscle = session.get("muscle") or {}
        weight_value = _finite_or_none(weight.get("value"))
        fat_value = _finite_or_none(body_fat.get("value"))
        muscle_value = _finite_or_none(muscle.get("value"))
        fat_mass: float | None = None
        lean_mass: float | None = None
        if (
            weight_value is not None
            and weight_value > 0
            and fat_value is not None
            and 0.0 < fat_value < 100.0
        ):
            fat_mass = weight_value * fat_value / 100.0
            lean_mass = weight_value - fat_mass
        # Composition lineage follows the body-fat/BIA side; an explicit
        # per-metric algorithm beats the session-level fallback.
        algorithm_code = _text_or_none(body_fat.get("algorithm_code")) or _text_or_none(
            session.get("algorithm_code")
        )
        algorithm_version = _text_or_none(
            body_fat.get("algorithm_version")
        ) or _text_or_none(session.get("algorithm_version"))
        grouped.setdefault(group, []).append(
            CompositionPoint(
                session_id=str(session_id),
                observed_date=observed,
                compatibility_group=group,
                weight_kg=weight_value,
                body_fat_pct=fat_value,
                estimated_fat_mass_kg=fat_mass,
                estimated_lean_mass_kg=lean_mass,
                source_muscle_mass_kg=muscle_value,
                weight_measurement_id=_text_or_none(weight.get("measurement_id")),
                body_fat_measurement_id=_text_or_none(body_fat.get("measurement_id")),
                muscle_measurement_id=_text_or_none(muscle.get("measurement_id")),
                algorithm_code=algorithm_code,
                algorithm_version=algorithm_version,
            )
        )
    return {
        group: tuple(sorted(points, key=lambda item: (item.observed_date, item.session_id)))
        for group, points in sorted(grouped.items())
    }


def similar_weight_comparison(
    earlier: CompositionPoint | Mapping[str, Any] | None,
    later: CompositionPoint | Mapping[str, Any] | None,
) -> SimilarWeightComparison:
    """Compare two same-algorithm sessions at a similar body weight.

    Gates: identical body-composition compatibility groups, at least 28
    days apart, ``|later - earlier| / earlier <= 1%``, and comparable
    composition evidence (body-fat/fat-mass) on BOTH sides — similar
    weights alone never yield an available comparison.  Boundaries are
    inclusive.  Anything else returns ``unavailable`` + reason — never a
    cross-group comparison and never a causal tissue claim.
    """

    if earlier is None or later is None:
        return SimilarWeightComparison(available=False, reason="missing_session")
    earlier_point = _as_composition_point(earlier)
    later_point = _as_composition_point(later)
    if earlier_point is None or later_point is None:
        return SimilarWeightComparison(available=False, reason="missing_session")
    if (
        earlier_point.compatibility_group is None
        or later_point.compatibility_group is None
        or earlier_point.compatibility_group != later_point.compatibility_group
    ):
        return SimilarWeightComparison(
            available=False, reason="incompatible_algorithm_group"
        )
    if earlier_point.weight_kg is None or later_point.weight_kg is None:
        return SimilarWeightComparison(available=False, reason="missing_weight")
    if earlier_point.weight_kg <= 0 or later_point.weight_kg <= 0:
        return SimilarWeightComparison(available=False, reason="invalid_weight_value")
    if (
        earlier_point.body_fat_pct is None
        or later_point.body_fat_pct is None
        or not math.isfinite(earlier_point.body_fat_pct)
        or not math.isfinite(later_point.body_fat_pct)
    ):
        return SimilarWeightComparison(
            available=False,
            reason="missing_composition_evidence",
            earlier_date=earlier_point.observed_date,
            later_date=later_point.observed_date,
            compatibility_group=earlier_point.compatibility_group,
        )
    first, second = (
        (earlier_point, later_point)
        if earlier_point.observed_date <= later_point.observed_date
        else (later_point, earlier_point)
    )
    days_apart = (second.observed_date - first.observed_date).days
    if days_apart < SIMILAR_MIN_GAP_DAYS:
        return SimilarWeightComparison(
            available=False,
            reason="insufficient_gap",
            earlier_date=first.observed_date,
            later_date=second.observed_date,
            days_apart=days_apart,
            compatibility_group=first.compatibility_group,
        )
    ratio = abs(second.weight_kg - first.weight_kg) / first.weight_kg
    if ratio > SIMILAR_MAX_WEIGHT_DIFF_RATIO:
        return SimilarWeightComparison(
            available=False,
            reason="weight_diff_exceeds_threshold",
            earlier_date=first.observed_date,
            later_date=second.observed_date,
            days_apart=days_apart,
            earlier_weight_kg=first.weight_kg,
            later_weight_kg=second.weight_kg,
            weight_delta_kg=second.weight_kg - first.weight_kg,
            weight_diff_ratio=ratio,
            compatibility_group=first.compatibility_group,
        )
    fat_delta: float | None = None
    if first.body_fat_pct is not None and second.body_fat_pct is not None:
        fat_delta = second.body_fat_pct - first.body_fat_pct
    mass_delta: float | None = None
    if (
        first.estimated_fat_mass_kg is not None
        and second.estimated_fat_mass_kg is not None
    ):
        mass_delta = second.estimated_fat_mass_kg - first.estimated_fat_mass_kg
    return SimilarWeightComparison(
        available=True,
        reason=None,
        earlier_date=first.observed_date,
        later_date=second.observed_date,
        days_apart=days_apart,
        earlier_weight_kg=first.weight_kg,
        later_weight_kg=second.weight_kg,
        weight_delta_kg=second.weight_kg - first.weight_kg,
        weight_diff_ratio=ratio,
        earlier_body_fat_pct=first.body_fat_pct,
        later_body_fat_pct=second.body_fat_pct,
        body_fat_delta_pp=fat_delta,
        earlier_fat_mass_kg=first.estimated_fat_mass_kg,
        later_fat_mass_kg=second.estimated_fat_mass_kg,
        fat_mass_delta_kg=mass_delta,
        compatibility_group=first.compatibility_group,
        earlier_algorithm_code=first.algorithm_code,
        earlier_algorithm_version=first.algorithm_version,
        later_algorithm_code=second.algorithm_code,
        later_algorithm_version=second.algorithm_version,
    )


def build_weight_series(
    candidates: Iterable[Any],
    *,
    compatibility_group: str | None = None,
    composition_sessions: Iterable[Mapping[str, Any]] = (),
) -> WeightSeries:
    """Build the API-facing weight series from canonical candidates."""

    observations, exclusions = coerce_weight_observations(
        candidates, compatibility_group=compatibility_group
    )
    daily = daily_median_weights(observations)
    trend = time_aware_ewma(daily, exclusions=exclusions)
    composition = composition_series_by_group(composition_sessions)
    if compatibility_group is not None:
        normalized = compatibility_group.strip()
        composition = {
            group: points for group, points in composition.items() if group == normalized
        }
    return WeightSeries(
        raw_points=observations,
        daily_points=daily,
        trend_points=trend.points,
        trend_algorithm=WEIGHT_TREND_ALGORITHM,
        trend_available=trend.available,
        trend_reason=trend.reason,
        input_count=trend.input_count,
        covered_span_days=trend.covered_span_days,
        exclusions=exclusions,
        composition_by_group=composition,
    )


def build_weight_summary(
    candidates: Iterable[Any],
    *,
    compatibility_group: str | None = None,
    composition_sessions: Iterable[Mapping[str, Any]] = (),
    latest_composition: BodyCompositionResult | None = None,
    similar_pair: tuple[Any, Any] | None = None,
    coverage: Any | None = None,
    as_of_date: date | None = None,
) -> WeightSummary:
    """Build the API-facing weight summary with explicit unavailable reasons."""

    observations, exclusions = coerce_weight_observations(
        candidates, compatibility_group=compatibility_group
    )
    daily = daily_median_weights(observations)
    trend = time_aware_ewma(daily, exclusions=exclusions)
    rate = theil_sen_rate(daily, as_of_date=as_of_date, exclusions=exclusions)
    composition = (
        latest_composition
        if latest_composition is not None
        else BodyCompositionResult(available=False, reason="no_data")
    )
    similar = (
        similar_weight_comparison(similar_pair[0], similar_pair[1])
        if similar_pair is not None
        else SimilarWeightComparison(available=False, reason="no_data")
    )
    void = composition_series_by_group(composition_sessions)
    if compatibility_group is not None:
        normalized = compatibility_group.strip()
        void = {group: points for group, points in void.items() if group == normalized}
    _ = void
    return WeightSummary(
        trend=trend,
        rate=rate,
        latest_composition=composition,
        similar_weight=similar,
        coverage=_coverage_as_dict(coverage),
    )


def _observation_sort_key(item: WeightObservation) -> tuple[Any, ...]:
    timestamp = item.source_timestamp_utc
    if timestamp is None:
        timestamp_key = ""
    else:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            timestamp_key = timestamp.isoformat()
        else:
            timestamp_key = timestamp.isoformat()
    return (item.observed_date, timestamp_key, item.evidence_id)


def _exclusion(
    evidence: Any, metric: Any, semantic: Any, reason: str
) -> WeightExclusion:
    return WeightExclusion(
        evidence_id=str(evidence) if evidence is not None else None,
        metric_code=str(metric) if metric is not None else None,
        semantic_key=str(semantic) if semantic is not None else None,
        reason_code=reason,
    )


def _normalize_group(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unit_accepted(unit: Any, accepted: frozenset[str]) -> bool:
    if unit is None:
        return False
    return str(unit).strip().casefold() in accepted


def _finite_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _add_days(value: date, days: int) -> date:
    from datetime import timedelta

    return value + timedelta(days=days)


def _as_composition_point(value: CompositionPoint | Mapping[str, Any]) -> (
    CompositionPoint | None
):
    if isinstance(value, CompositionPoint):
        return value
    if isinstance(value, Mapping):
        observed = value.get("observed_date")
        if isinstance(observed, str):
            observed = date.fromisoformat(observed[:10])
        if isinstance(observed, datetime):
            observed = observed.date()
        if not isinstance(observed, date):
            return None
        session_id = value.get("session_id")
        if session_id is None:
            return None
        return CompositionPoint(
            session_id=str(session_id),
            observed_date=observed,
            compatibility_group=_normalize_group(value.get("compatibility_group")),
            weight_kg=_finite_or_none(value.get("weight_kg", value.get("weight"))),
            body_fat_pct=_finite_or_none(
                value.get("body_fat_pct", value.get("body_fat"))
            ),
            estimated_fat_mass_kg=_finite_or_none(value.get("estimated_fat_mass_kg")),
            estimated_lean_mass_kg=_finite_or_none(value.get("estimated_lean_mass_kg")),
            algorithm_code=_text_or_none(value.get("algorithm_code")),
            algorithm_version=_text_or_none(value.get("algorithm_version")),
        )
    return None


def _coverage_as_dict(coverage: Any) -> dict[str, Any] | None:
    if coverage is None:
        return None
    if isinstance(coverage, Mapping):
        return dict(coverage)
    as_dict = getattr(coverage, "as_dict", None)
    if callable(as_dict):
        result = as_dict()
        return dict(result) if isinstance(result, Mapping) else None
    return None


__all__ = [
    "BODY_COMPOSITION_ALGORITHM",
    "BODY_FAT_METRIC_CODES",
    "EWMA_HALF_LIFE_DAYS",
    "MUSCLE_METRIC_CODES",
    "RATE_MIN_OBSERVATIONS",
    "RATE_MIN_SPAN_DAYS",
    "RATE_WINDOW_DAYS",
    "SIMILAR_MAX_WEIGHT_DIFF_RATIO",
    "SIMILAR_MIN_GAP_DAYS",
    "WEIGHT_ANALYTICS_VERSION",
    "WEIGHT_METRIC_CODES",
    "WEIGHT_RATE_ALGORITHM",
    "WEIGHT_TREND_ALGORITHM",
    "BodyCompositionResult",
    "CompositionInput",
    "CompositionPoint",
    "DailyWeightPoint",
    "SimilarWeightComparison",
    "TrendPoint",
    "WeightExclusion",
    "WeightObservation",
    "WeightRateResult",
    "WeightSeries",
    "WeightSummary",
    "WeightTrendResult",
    "build_weight_series",
    "build_weight_summary",
    "coerce_weight_observations",
    "composition_series_by_group",
    "daily_median_weights",
    "derive_body_composition",
    "ewma_alpha",
    "similar_weight_comparison",
    "theil_sen_rate",
    "time_aware_ewma",
]
