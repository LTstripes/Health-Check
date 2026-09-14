"""Deterministic R05 sleep-agreement statistics and evidence gates.

This module is a pure, read-only consumer of the accepted R05-02 metric
projection.  It does not persist a run, select a canonical source, call a
provider, or infer an epoch from a parser/software release.  Callers must
provide an epoch when a real measurement, device, or algorithm-method break
is known.

The statistical conventions are deliberately versioned here rather than
delegated to library defaults:

* ``d = google - garmin`` after the projection has converted to one unit;
* standard deviation is the sample SD (``n - 1`` denominator);
* parametric limits of agreement are ``bias +/- 1.96 * sample_sd``;
* robust summaries use median plus Hyndman-Fan Type-7 quantiles at 2.5% and
  97.5% (the same interpolation as ``statistics.quantiles``' ``inclusive``
  method);
* Tukey 1.5-IQR outliers are reported as sensitivity metadata only; primary
  statistics and gates always use the full valid N.

The provisional gate deliberately has no automatic coverage percentage or
maximum-gap threshold.  Coverage counts and observed gaps are evidence for a
reviewed packet, not an unreviewed pass/fail rule.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

R05_SLEEP_AGREEMENT_CONTRACT_VERSION = "r05-04-sleep-agreement-v1"
R05_SLEEP_AGREEMENT_RULE_VERSION = "r05-04-sleep-agreement-rules-v1"
R05_SLEEP_AGREEMENT_ALGORITHM = "r05-04-sleep-agreement-statistics-v1"
R05_SLEEP_STABILITY_RULE_VERSION = "r05-04-stability-overlap-v1"

EXPLORATORY_MIN_N = 14
PROVISIONAL_MIN_N = 42
PROVISIONAL_MIN_SPAN_DELTA_DAYS = 41
BA_Z = 1.96
TUKEY_IQR_MULTIPLIER = 1.5
ROBUST_LOA_LOW = 0.025
ROBUST_LOA_HIGH = 0.975
DEFAULT_EPOCH = "epoch-1"
_UNSET_VARIANT = object()
_EPOCH_BREAK_KINDS = frozenset({"measurement", "device", "algorithm_method"})


def _as_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError("wake_date must be a date, datetime, or ISO date")


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _type7_quantile(values: Sequence[float], probability: float) -> float:
    if not 0.0 <= probability <= 1.0:
        raise ValueError("quantile probability must be in [0, 1]")
    ordered = sorted(float(item) for item in values)
    if not ordered:
        raise ValueError("quantile requires at least one value")
    if len(ordered) == 1:
        return ordered[0]
    position = 1.0 + (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    fraction = position - lower
    if fraction == 0.0:
        return ordered[lower - 1]
    return ordered[lower - 1] + fraction * (ordered[lower] - ordered[lower - 1])


def _calendar_span_delta(first: date | None, last: date | None) -> int | None:
    if first is None or last is None:
        return None
    return (last - first).days


def _calendar_span_inclusive(first: date | None, last: date | None) -> int | None:
    delta = _calendar_span_delta(first, last)
    return None if delta is None else delta + 1


@dataclass(frozen=True, slots=True)
class EpochBasis:
    """Reviewable evidence for a real measurement epoch boundary."""

    break_kind: str
    evidence_reference: str
    detail: str | None = None

    def __post_init__(self) -> None:
        break_kind = self.break_kind.strip().lower()
        evidence_reference = self.evidence_reference.strip()
        if break_kind not in _EPOCH_BREAK_KINDS:
            raise ValueError(
                "epoch break_kind must be measurement, device, or algorithm_method"
            )
        if not evidence_reference:
            raise ValueError("epoch evidence_reference must be non-empty")
        object.__setattr__(self, "break_kind", break_kind)
        object.__setattr__(self, "evidence_reference", evidence_reference)
        if self.detail is not None:
            detail = self.detail.strip()
            object.__setattr__(self, "detail", detail or None)

    def as_dict(self) -> dict[str, str | None]:
        return {
            "break_kind": self.break_kind,
            "evidence_reference": self.evidence_reference,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class AgreementEpoch:
    """An epoch identity plus typed evidence for non-default splits."""

    identifier: str
    basis: EpochBasis | None = None

    def __post_init__(self) -> None:
        identifier = self.identifier.strip()
        if not identifier:
            raise ValueError("epoch identifier must be non-empty")
        if identifier == DEFAULT_EPOCH and self.basis is not None:
            raise ValueError("default epoch cannot carry a break basis")
        if identifier != DEFAULT_EPOCH and self.basis is None:
            raise ValueError("non-default epoch requires a typed break basis")
        object.__setattr__(self, "identifier", identifier)

    def as_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "basis": self.basis.as_dict() if self.basis else None,
        }


def _coerce_epoch(value: str | AgreementEpoch | None) -> AgreementEpoch:
    if value is None:
        return AgreementEpoch(DEFAULT_EPOCH)
    if isinstance(value, AgreementEpoch):
        return value
    if isinstance(value, str):
        return AgreementEpoch(value)
    raise TypeError("epoch must be a string or AgreementEpoch")


def _frozen_metric_candidate(metric_code: str) -> bool | None:
    """Resolve accepted #101 metric eligibility without duplicating its table."""

    from healthcheck.analytics.sleep_metrics import get_sleep_metric_definition

    try:
        return get_sleep_metric_definition(metric_code).canonical_candidate
    except KeyError:
        return None


@dataclass(frozen=True, slots=True)
class AgreementObservation:
    """One metric-night supplied to the pure statistics engine.

    ``metric_valid`` and ``source_eligible`` are separate so unavailable or
    excluded nights can be reported without entering N.  ``method_break`` is
    an explicit upstream fact; this class never treats a parser release as a
    break by itself.
    """

    wake_date: date | datetime | str
    metric_code: str
    cohort: str
    difference: int | float | None = None
    epoch: str | AgreementEpoch = DEFAULT_EPOCH
    epoch_basis: EpochBasis | None = None
    variant: str | None = None
    source_eligible: bool = True
    metric_valid: bool = True
    exclusion_reason: str | None = None
    google_value: int | float | None = None
    garmin_value: int | float | None = None
    method_break: bool = False
    google_manually_edited: bool | None = None
    canonical_candidate: bool | None = None
    difference_verified: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "wake_date", _as_date(self.wake_date))
        metric_code = self.metric_code.strip()
        cohort = self.cohort.strip()
        epoch = _coerce_epoch(self.epoch)
        if not metric_code or not cohort:
            raise ValueError("metric_code and cohort must be non-empty")
        object.__setattr__(self, "metric_code", metric_code)
        object.__setattr__(self, "cohort", cohort)
        if self.epoch_basis is not None and epoch.basis not in (None, self.epoch_basis):
            raise ValueError("epoch and epoch_basis must describe the same break")
        epoch_basis = self.epoch_basis or epoch.basis
        if epoch.identifier != DEFAULT_EPOCH and epoch_basis is None:
            raise ValueError("non-default epoch requires a typed break basis")
        object.__setattr__(self, "epoch", epoch.identifier)
        object.__setattr__(self, "epoch_basis", epoch_basis)
        if self.variant is not None:
            variant = self.variant.strip()
            object.__setattr__(self, "variant", variant or None)

        frozen_candidate = _frozen_metric_candidate(metric_code)
        if frozen_candidate is not None:
            object.__setattr__(self, "canonical_candidate", frozen_candidate)
        elif self.canonical_candidate is None:
            object.__setattr__(self, "canonical_candidate", True)

        difference = _finite(self.difference)
        google = _finite(self.google_value)
        garmin = _finite(self.garmin_value)
        if google is not None and garmin is not None:
            expected_difference = google - garmin
            if difference is not None and not math.isclose(
                difference, expected_difference, rel_tol=0.0, abs_tol=1e-12
            ):
                raise ValueError("difference must equal google_value - garmin_value")
            difference = expected_difference
            difference_verified = True
        else:
            difference_verified = bool(self.difference_verified)
        object.__setattr__(self, "difference", difference)
        object.__setattr__(self, "google_value", google)
        object.__setattr__(self, "garmin_value", garmin)
        object.__setattr__(self, "difference_verified", difference_verified)
        if not self.metric_valid or difference is None:
            object.__setattr__(self, "metric_valid", False)

    def as_dict(self) -> dict[str, object]:
        return {
            "wake_date": self.wake_date.isoformat(),
            "metric_code": self.metric_code,
            "cohort": self.cohort,
            "difference": self.difference,
            "google_value": self.google_value,
            "garmin_value": self.garmin_value,
            "epoch": self.epoch,
            "epoch_basis": self.epoch_basis.as_dict() if self.epoch_basis else None,
            "variant": self.variant,
            "source_eligible": self.source_eligible,
            "metric_valid": self.metric_valid,
            "exclusion_reason": self.exclusion_reason,
            "method_break": self.method_break,
            "google_manually_edited": self.google_manually_edited,
            "canonical_candidate": self.canonical_candidate,
            "difference_verified": self.difference_verified,
        }

    @classmethod
    def from_projection(
        cls,
        projection: Any,
        *,
        epoch: str | AgreementEpoch | None = None,
        epoch_basis: EpochBasis | None = None,
        method_break: bool = False,
    ) -> AgreementObservation:
        """Adapt one accepted #101 projection without copying raw payloads."""

        pair = projection.pair
        status = getattr(projection, "status", None)
        comparable = bool(getattr(projection, "comparable", status == "comparable"))
        difference = projection.difference if comparable and status == "comparable" else None
        garmin = getattr(projection.garmin, "value", None)
        google = getattr(projection.google, "value", None)
        return cls(
            wake_date=pair.wake_date,
            metric_code=projection.metric_code,
            cohort=pair.cohort,
            difference=difference,
            epoch=epoch if epoch is not None else getattr(projection, "epoch", DEFAULT_EPOCH),
            epoch_basis=epoch_basis or getattr(projection, "epoch_basis", None),
            variant=getattr(projection, "variant", None),
            source_eligible=True,
            metric_valid=comparable and status == "comparable",
            exclusion_reason=getattr(projection, "reason", None),
            google_value=google,
            garmin_value=garmin,
            method_break=method_break or bool(getattr(projection, "method_break", False)),
            google_manually_edited=getattr(pair, "google_manually_edited", None),
            canonical_candidate=getattr(projection, "canonical_candidate", None),
            difference_verified=True,
        )


def observations_from_projections(
    projections: Iterable[Any],
    *,
    epoch_resolver: Callable[[Any], str | AgreementEpoch] | None = None,
    epoch_by_wake_date: Mapping[date | str, str | AgreementEpoch] | None = None,
) -> tuple[AgreementObservation, ...]:
    """Convert #101 projections while requiring explicit epoch semantics.

    An epoch resolver may use persisted measurement/device/algorithm evidence.
    A parser release is not inspected or inferred here.  Absent an explicit
    resolver, all observations stay in the stable default epoch.
    """

    normalized_epochs = {
        _as_date(key): value for key, value in (epoch_by_wake_date or {}).items()
    }
    result: list[AgreementObservation] = []
    for projection in projections:
        if epoch_resolver is not None:
            resolved_epoch = epoch_resolver(projection)
        else:
            wake_date = _as_date(projection.pair.wake_date)
            resolved_epoch = normalized_epochs.get(
                wake_date, getattr(projection, "epoch", DEFAULT_EPOCH)
            )
        result.append(
            AgreementObservation.from_projection(
                projection,
                epoch=resolved_epoch,
                epoch_basis=getattr(projection, "epoch_basis", None),
            )
        )
    return tuple(result)


@dataclass(frozen=True, slots=True)
class AgreementGap:
    start_date: date
    end_date: date
    missing_days: int

    def as_dict(self) -> dict[str, object]:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "missing_days": self.missing_days,
        }


@dataclass(frozen=True, slots=True)
class AgreementCoverage:
    """Coverage facts; none is used as an automatic numeric gate."""

    requested_calendar_nights: int | None
    source_eligible_paired_nights: int
    metric_valid_nights: int
    excluded_nights: Mapping[str, int]
    valid_wake_dates: tuple[date, ...]
    gaps: tuple[AgreementGap, ...]
    longest_gap_days: int | None

    def as_dict(self) -> dict[str, object]:
        return {
            "requested_calendar_nights": self.requested_calendar_nights,
            "source_eligible_paired_nights": self.source_eligible_paired_nights,
            "metric_valid_nights": self.metric_valid_nights,
            "excluded_nights": dict(self.excluded_nights),
            "valid_wake_dates": [item.isoformat() for item in self.valid_wake_dates],
            "gaps": [item.as_dict() for item in self.gaps],
            "longest_gap_days": self.longest_gap_days,
            "automatic_coverage_threshold": None,
            "automatic_max_gap_threshold": None,
        }


@dataclass(frozen=True, slots=True)
class OutlierSensitivity:
    """Optional Tukey sensitivity view, separate from full-N primary stats."""

    lower_fence: float | None
    upper_fence: float | None
    outlier_wake_dates: tuple[date, ...]
    sensitivity_n: int
    sensitivity_bias: float | None
    sensitivity_mae: float | None
    sensitivity_rmse: float | None

    @property
    def outlier_count(self) -> int:
        return len(self.outlier_wake_dates)

    def as_dict(self) -> dict[str, object]:
        return {
            "method": "tukey_1.5_iqr",
            "lower_fence": self.lower_fence,
            "upper_fence": self.upper_fence,
            "outlier_wake_dates": [item.isoformat() for item in self.outlier_wake_dates],
            "outlier_count": self.outlier_count,
            "sensitivity_n": self.sensitivity_n,
            "sensitivity_bias": self.sensitivity_bias,
            "sensitivity_mae": self.sensitivity_mae,
            "sensitivity_rmse": self.sensitivity_rmse,
        }


@dataclass(frozen=True, slots=True)
class AgreementHalfStatistics:
    n: int
    first_wake_date: date | None
    last_wake_date: date | None
    calendar_span_days: int | None
    calendar_span_delta_days: int | None
    bias: float | None
    mae: float | None
    rmse: float | None
    sample_sd: float | None
    loa_lower: float | None
    loa_upper: float | None
    robust_median: float | None
    robust_q025: float | None
    robust_q975: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "n": self.n,
            "first_wake_date": self.first_wake_date.isoformat() if self.first_wake_date else None,
            "last_wake_date": self.last_wake_date.isoformat() if self.last_wake_date else None,
            "calendar_span_days": self.calendar_span_days,
            "calendar_span_delta_days": self.calendar_span_delta_days,
            "bias": self.bias,
            "mae": self.mae,
            "rmse": self.rmse,
            "sample_sd": self.sample_sd,
            "loa_lower": self.loa_lower,
            "loa_upper": self.loa_upper,
            "robust_median": self.robust_median,
            "robust_q025": self.robust_q025,
            "robust_q975": self.robust_q975,
        }


@dataclass(frozen=True, slots=True)
class AgreementStability:
    """Deterministic contiguous-half evidence for the provisional gate.

    The reviewed criterion is intentionally distribution-based and has no
    coverage/max-gap threshold: both half robust intervals must overlap, and
    each half bias must lie inside the full-sample robust interval.  Missing or
    non-estimable halves fail closed.
    """

    rule_version: str
    first_half: AgreementHalfStatistics | None
    second_half: AgreementHalfStatistics | None
    passed: bool | None
    status: str
    reason: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "rule_version": self.rule_version,
            "first_half": self.first_half.as_dict() if self.first_half else None,
            "second_half": self.second_half.as_dict() if self.second_half else None,
            "passed": self.passed,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class AgreementGate:
    exploratory: str
    provisional: str
    canonical_proposal_eligible: bool
    reason_codes: tuple[str, ...]
    canonical_switch_applied: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "exploratory": self.exploratory,
            "provisional": self.provisional,
            "canonical_proposal_eligible": self.canonical_proposal_eligible,
            "reason_codes": list(self.reason_codes),
            "canonical_switch_applied": self.canonical_switch_applied,
        }


@dataclass(frozen=True, slots=True)
class AgreementStatistics:
    metric_code: str
    cohort: str
    epoch: str
    epoch_basis: EpochBasis | None
    variant: str | None
    n: int
    strong_gate_eligible_n: int
    google_manually_edited_n: int
    wake_dates: tuple[date, ...]
    differences: tuple[float, ...]
    first_wake_date: date | None
    last_wake_date: date | None
    calendar_span_days: int | None
    calendar_span_delta_days: int | None
    bias: float | None
    mae: float | None
    rmse: float | None
    sample_sd: float | None
    loa_lower: float | None
    loa_upper: float | None
    robust_median: float | None
    robust_q025: float | None
    robust_q975: float | None
    pearson_r: float | None
    spearman_rho: float | None
    outlier_sensitivity: OutlierSensitivity
    coverage: AgreementCoverage
    method_break_present: bool
    stability: AgreementStability | None
    gate: AgreementGate

    @property
    def status(self) -> str:
        return self.gate.provisional if self.n >= PROVISIONAL_MIN_N else self.gate.exploratory

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": R05_SLEEP_AGREEMENT_CONTRACT_VERSION,
            "rule_version": R05_SLEEP_AGREEMENT_RULE_VERSION,
            "algorithm": R05_SLEEP_AGREEMENT_ALGORITHM,
            "metric_code": self.metric_code,
            "cohort": self.cohort,
            "epoch": self.epoch,
            "epoch_basis": self.epoch_basis.as_dict() if self.epoch_basis else None,
            "variant": self.variant,
            "n": self.n,
            "strong_gate_eligible_n": self.strong_gate_eligible_n,
            "google_manually_edited_n": self.google_manually_edited_n,
            "wake_dates": [item.isoformat() for item in self.wake_dates],
            "differences": list(self.differences),
            "first_wake_date": self.first_wake_date.isoformat() if self.first_wake_date else None,
            "last_wake_date": self.last_wake_date.isoformat() if self.last_wake_date else None,
            "calendar_span_days": self.calendar_span_days,
            "calendar_span_delta_days": self.calendar_span_delta_days,
            "bias": self.bias,
            "mae": self.mae,
            "rmse": self.rmse,
            "sample_sd": self.sample_sd,
            "loa_lower": self.loa_lower,
            "loa_upper": self.loa_upper,
            "robust_median": self.robust_median,
            "robust_q025": self.robust_q025,
            "robust_q975": self.robust_q975,
            "pearson_r": self.pearson_r,
            "spearman_rho": self.spearman_rho,
            "outlier_sensitivity": self.outlier_sensitivity.as_dict(),
            "coverage": self.coverage.as_dict(),
            "method_break_present": self.method_break_present,
            "stability": self.stability.as_dict() if self.stability else None,
            "gate": self.gate.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class SleepAgreementPacket:
    statistics: tuple[AgreementStatistics, ...]

    @property
    def groups(self) -> tuple[AgreementStatistics, ...]:
        return self.statistics

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": R05_SLEEP_AGREEMENT_CONTRACT_VERSION,
            "rule_version": R05_SLEEP_AGREEMENT_RULE_VERSION,
            "algorithm": R05_SLEEP_AGREEMENT_ALGORITHM,
            "statistics": [item.as_dict() for item in self.statistics],
        }


def _summary(values: Sequence[float]) -> tuple[float | None, ...]:
    if not values:
        return (None,) * 9
    bias = float(statistics.fmean(values))
    mae = float(statistics.fmean(abs(item) for item in values))
    rmse = math.sqrt(float(statistics.fmean(item * item for item in values)))
    sample_sd = float(statistics.stdev(values)) if len(values) >= 2 else None
    loa_lower = None if sample_sd is None else bias - BA_Z * sample_sd
    loa_upper = None if sample_sd is None else bias + BA_Z * sample_sd
    median = float(statistics.median(values))
    return (
        bias,
        mae,
        rmse,
        sample_sd,
        loa_lower,
        loa_upper,
        median,
        _type7_quantile(values, ROBUST_LOA_LOW),
        _type7_quantile(values, ROBUST_LOA_HIGH),
    )


def _correlation(observations: Sequence[AgreementObservation]) -> tuple[float | None, float | None]:
    paired = [
        (float(item.google_value), float(item.garmin_value))
        for item in observations
        if item.google_value is not None and item.garmin_value is not None
    ]
    if len(paired) < 2:
        return None, None
    google, garmin = zip(*paired)
    if len(set(google)) < 2 or len(set(garmin)) < 2:
        return None, None
    pearson = float(statistics.correlation(google, garmin))
    google_ranks = _midranks(google)
    garmin_ranks = _midranks(garmin)
    spearman = float(statistics.correlation(google_ranks, garmin_ranks))
    return pearson, spearman


def _midranks(values: Sequence[float]) -> tuple[float, ...]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(indexed):
        end = cursor + 1
        while end < len(indexed) and indexed[end][1] == indexed[cursor][1]:
            end += 1
        rank = (cursor + 1 + end) / 2.0
        for position in range(cursor, end):
            ranks[indexed[position][0]] = rank
        cursor = end
    return tuple(ranks)


def _outlier_sensitivity(
    selected: Sequence[tuple[date, AgreementObservation]],
) -> OutlierSensitivity:
    values = [float(item.difference) for _, item in selected]
    if not values:
        return OutlierSensitivity(None, None, (), 0, None, None, None)
    q1 = _type7_quantile(values, 0.25)
    q3 = _type7_quantile(values, 0.75)
    iqr = q3 - q1
    lower = q1 - TUKEY_IQR_MULTIPLIER * iqr
    upper = q3 + TUKEY_IQR_MULTIPLIER * iqr
    outlier_dates = tuple(
        wake_date
        for wake_date, item in selected
        if item.difference < lower or item.difference > upper
    )
    retained = [
        float(item.difference)
        for wake_date, item in selected
        if wake_date not in set(outlier_dates)
    ]
    bias, mae, rmse, *_ = _summary(retained)
    return OutlierSensitivity(
        lower_fence=lower,
        upper_fence=upper,
        outlier_wake_dates=outlier_dates,
        sensitivity_n=len(retained),
        sensitivity_bias=bias,
        sensitivity_mae=mae,
        sensitivity_rmse=rmse,
    )


def _coverage(
    observations: Sequence[AgreementObservation],
    selected: Sequence[tuple[date, AgreementObservation]],
    *,
    requested_start_date: date | None,
    requested_end_date: date | None,
) -> AgreementCoverage:
    eligible_dates = {item.wake_date for item in observations if item.source_eligible}
    excluded = Counter()
    for item in observations:
        if not item.source_eligible:
            excluded[item.exclusion_reason or "source_ineligible"] += 1
        elif not item.metric_valid or item.difference is None:
            excluded[item.exclusion_reason or "metric_unavailable"] += 1
    valid_by_date: dict[date, list[AgreementObservation]] = defaultdict(list)
    for item in observations:
        if item.source_eligible and item.metric_valid and item.difference is not None:
            valid_by_date[item.wake_date].append(item)
    excluded["duplicate_wake_date"] += sum(
        1
        for candidates in valid_by_date.values()
        if len({float(item.difference) for item in candidates}) > 1
    )
    selected_dates = tuple(item[0] for item in selected)
    window_dates = selected_dates
    if requested_start_date is not None and requested_end_date is not None:
        window_dates = tuple(
            item
            for item in selected_dates
            if requested_start_date <= item <= requested_end_date
        )
    gaps: list[AgreementGap] = []
    if requested_start_date is not None and requested_end_date is not None:
        if window_dates:
            if window_dates[0] > requested_start_date:
                gap_end = window_dates[0] - timedelta(days=1)
                gaps.append(
                    AgreementGap(
                        requested_start_date,
                        gap_end,
                        (gap_end - requested_start_date).days + 1,
                    )
                )
            if window_dates[-1] < requested_end_date:
                gap_start = window_dates[-1] + timedelta(days=1)
                gaps.append(
                    AgreementGap(
                        gap_start,
                        requested_end_date,
                        (requested_end_date - gap_start).days + 1,
                    )
                )
        else:
            gaps.append(
                AgreementGap(
                    requested_start_date,
                    requested_end_date,
                    (requested_end_date - requested_start_date).days + 1,
                )
            )
    for left, right in zip(window_dates, window_dates[1:]):
        missing_days = (right - left).days - 1
        if missing_days > 0:
            gaps.append(
                AgreementGap(left + timedelta(days=1), right - timedelta(days=1), missing_days)
            )
    requested = None
    if requested_start_date is not None and requested_end_date is not None:
        requested = (requested_end_date - requested_start_date).days + 1
    return AgreementCoverage(
        requested_calendar_nights=requested,
        source_eligible_paired_nights=len(eligible_dates),
        metric_valid_nights=len(selected_dates),
        excluded_nights=dict(sorted(excluded.items())),
        valid_wake_dates=selected_dates,
        gaps=tuple(gaps),
        longest_gap_days=max((item.missing_days for item in gaps), default=None),
    )


def _half(selected: Sequence[tuple[date, AgreementObservation]]) -> AgreementHalfStatistics:
    dates = tuple(item[0] for item in selected)
    values = [float(item[1].difference) for item in selected]
    summary = _summary(values)
    return AgreementHalfStatistics(
        n=len(values),
        first_wake_date=dates[0] if dates else None,
        last_wake_date=dates[-1] if dates else None,
        calendar_span_days=_calendar_span_inclusive(dates[0], dates[-1]) if dates else None,
        calendar_span_delta_days=_calendar_span_delta(dates[0], dates[-1]) if dates else None,
        bias=summary[0],
        mae=summary[1],
        rmse=summary[2],
        sample_sd=summary[3],
        loa_lower=summary[4],
        loa_upper=summary[5],
        robust_median=summary[6],
        robust_q025=summary[7],
        robust_q975=summary[8],
    )


def _stability(
    selected: Sequence[tuple[date, AgreementObservation]],
    *,
    full_robust_low: float | None,
    full_robust_high: float | None,
) -> AgreementStability:
    if len(selected) < 2:
        return AgreementStability(
            R05_SLEEP_STABILITY_RULE_VERSION,
            None,
            None,
            None,
            "missing",
            "stability_requires_two_nights",
        )
    split = len(selected) // 2
    first = _half(selected[:split])
    second = _half(selected[split:])
    if (
        first.n < 2
        or second.n < 2
        or first.robust_q025 is None
        or first.robust_q975 is None
        or second.robust_q025 is None
        or second.robust_q975 is None
        or full_robust_low is None
        or full_robust_high is None
    ):
        return AgreementStability(
            R05_SLEEP_STABILITY_RULE_VERSION,
            first,
            second,
            None,
            "missing",
            "stability_half_statistics_unavailable",
        )
    overlap = max(first.robust_q025, second.robust_q025) <= min(
        first.robust_q975, second.robust_q975
    )
    biases_inside = (
        full_robust_low <= first.bias <= full_robust_high
        and full_robust_low <= second.bias <= full_robust_high
    )
    passed = overlap and biases_inside
    reason = None if passed else "half_robust_distributions_not_stable"
    return AgreementStability(
        R05_SLEEP_STABILITY_RULE_VERSION,
        first,
        second,
        passed,
        "pass" if passed else "fail",
        reason,
    )


def _gate(
    *,
    n: int,
    strong_gate_eligible_n: int,
    cohort: str,
    canonical_candidate: bool,
    span_delta_days: int | None,
    method_break_present: bool,
    stability: AgreementStability | None,
) -> AgreementGate:
    reasons: list[str] = []
    exploratory = "exploratory" if n >= EXPLORATORY_MIN_N else "insufficient_n"
    if exploratory == "insufficient_n":
        reasons.append("exploratory_n_below_14")

    if not canonical_candidate:
        provisional = "non_canonical_metric"
        reasons.append("metric_not_canonical_candidate")
    elif strong_gate_eligible_n < PROVISIONAL_MIN_N:
        provisional = "insufficient_n"
        if n < PROVISIONAL_MIN_N:
            reasons.append("provisional_n_below_42")
        else:
            reasons.append("strong_gate_n_below_42")
    elif cohort != "device_pair":
        provisional = "not_device_pair"
        reasons.append("provisional_requires_device_pair")
    elif span_delta_days is None or span_delta_days < PROVISIONAL_MIN_SPAN_DELTA_DAYS:
        provisional = "insufficient_span"
        reasons.append("provisional_span_delta_below_41_days")
    elif method_break_present:
        provisional = "known_method_break"
        reasons.append("known_method_break")
    elif stability is None or stability.status == "missing":
        provisional = "stability_missing"
        reasons.append("stability_packet_missing")
    elif not stability.passed:
        provisional = "stability_failed"
        reasons.append("stability_failed")
    else:
        provisional = "eligible_for_provisional_proposal"

    return AgreementGate(
        exploratory=exploratory,
        provisional=provisional,
        canonical_proposal_eligible=provisional == "eligible_for_provisional_proposal",
        reason_codes=tuple(reasons),
    )


def _coerce_observations(source: Iterable[Any] | Any) -> tuple[AgreementObservation, ...]:
    projections = getattr(source, "projections", None)
    if projections is not None:
        return observations_from_projections(projections)
    result: list[AgreementObservation] = []
    for item in source:
        result.append(
            item if isinstance(item, AgreementObservation) else AgreementObservation(**item)
        )
    return tuple(result)


def _select_group(
    observations: Sequence[AgreementObservation],
    *,
    metric_code: str | None,
    cohort: str | None,
    epoch: str | None,
    variant: str | None | object,
) -> tuple[AgreementObservation, ...]:
    selected = tuple(
        item
        for item in observations
        if (metric_code is None or item.metric_code == metric_code)
        and (cohort is None or item.cohort == cohort)
        and (epoch is None or item.epoch == epoch)
        and (variant is _UNSET_VARIANT or item.variant == variant)
    )
    if not selected:
        raise ValueError("no agreement observations match the requested group")
    return selected


def compute_agreement_statistics(
    observations: Iterable[AgreementObservation] | Any,
    *,
    metric_code: str | None = None,
    cohort: str | None = None,
    epoch: str | None = None,
    variant: str | None | object = _UNSET_VARIANT,
    requested_start_date: date | datetime | str | None = None,
    requested_end_date: date | datetime | str | None = None,
) -> AgreementStatistics:
    """Compute one metric x cohort x epoch packet with fail-closed gates."""

    all_observations = _coerce_observations(observations)
    selected_observations = _select_group(
        all_observations,
        metric_code=metric_code,
        cohort=cohort,
        epoch=epoch,
        variant=variant,
    )
    key = (
        selected_observations[0].metric_code,
        selected_observations[0].cohort,
        selected_observations[0].epoch,
        selected_observations[0].variant,
    )
    if any(
        (item.metric_code, item.cohort, item.epoch, item.variant) != key
        for item in selected_observations
    ):
        raise ValueError("compute_agreement_statistics requires one metric/cohort/epoch/variant")
    epoch_basis = selected_observations[0].epoch_basis
    canonical_candidate = bool(selected_observations[0].canonical_candidate)
    if any(item.epoch_basis != epoch_basis for item in selected_observations):
        raise ValueError("one epoch cannot have conflicting break bases")
    if any(
        bool(item.canonical_candidate) != canonical_candidate
        for item in selected_observations
    ):
        raise ValueError("one agreement group cannot mix canonical metric definitions")

    by_date: dict[date, list[AgreementObservation]] = defaultdict(list)
    for item in selected_observations:
        if item.source_eligible and item.metric_valid and item.difference is not None:
            by_date[item.wake_date].append(item)
    deduped: list[tuple[date, AgreementObservation]] = []
    for wake_date in sorted(by_date):
        candidates = by_date[wake_date]
        differences = {float(item.difference) for item in candidates}
        if len(differences) == 1:
            deduped.append((wake_date, candidates[0]))

    values = [float(item.difference) for _, item in deduped]
    dates = tuple(item[0] for item in deduped)
    strong_deduped = [
        item
        for item in deduped
        if item[1].google_manually_edited is not True and item[1].difference_verified
    ]
    strong_dates = tuple(item[0] for item in strong_deduped)
    summary = _summary(values)
    strong_summary = _summary([float(item[1].difference) for item in strong_deduped])
    requested_start = None if requested_start_date is None else _as_date(requested_start_date)
    requested_end = None if requested_end_date is None else _as_date(requested_end_date)
    if (requested_start is None) != (requested_end is None):
        raise ValueError("requested start and end dates must be supplied together")
    if (
        requested_start is not None
        and requested_end is not None
        and requested_end < requested_start
    ):
        raise ValueError("requested_end_date cannot precede requested_start_date")

    coverage = _coverage(
        selected_observations,
        deduped,
        requested_start_date=requested_start,
        requested_end_date=requested_end,
    )
    provisional_stability = _stability(
        strong_deduped,
        full_robust_low=strong_summary[7],
        full_robust_high=strong_summary[8],
    )
    method_break_present = any(item.method_break for item in selected_observations)
    gate = _gate(
        n=len(values),
        strong_gate_eligible_n=len(strong_deduped),
        cohort=key[1],
        canonical_candidate=canonical_candidate,
        span_delta_days=(
            _calendar_span_delta(strong_dates[0], strong_dates[-1])
            if strong_dates
            else None
        ),
        method_break_present=method_break_present,
        stability=provisional_stability,
    )
    pearson, spearman = _correlation([item for _, item in deduped])
    return AgreementStatistics(
        metric_code=key[0],
        cohort=key[1],
        epoch=key[2],
        epoch_basis=epoch_basis,
        variant=key[3],
        n=len(values),
        strong_gate_eligible_n=len(strong_deduped),
        google_manually_edited_n=sum(
            item.google_manually_edited is True for _, item in deduped
        ),
        wake_dates=dates,
        differences=tuple(values),
        first_wake_date=dates[0] if dates else None,
        last_wake_date=dates[-1] if dates else None,
        calendar_span_days=_calendar_span_inclusive(dates[0], dates[-1]) if dates else None,
        calendar_span_delta_days=_calendar_span_delta(dates[0], dates[-1]) if dates else None,
        bias=summary[0],
        mae=summary[1],
        rmse=summary[2],
        sample_sd=summary[3],
        loa_lower=summary[4],
        loa_upper=summary[5],
        robust_median=summary[6],
        robust_q025=summary[7],
        robust_q975=summary[8],
        pearson_r=pearson,
        spearman_rho=spearman,
        outlier_sensitivity=_outlier_sensitivity(deduped),
        coverage=coverage,
        method_break_present=method_break_present,
        stability=provisional_stability,
        gate=gate,
    )


def compute_sleep_agreement(
    observations_or_projection_result: Iterable[AgreementObservation] | Any,
    *,
    epoch_resolver: Callable[[Any], str | AgreementEpoch] | None = None,
    requested_start_date: date | datetime | str | None = None,
    requested_end_date: date | datetime | str | None = None,
) -> SleepAgreementPacket:
    """Build all deterministic metric/cohort/epoch groups for a read result."""

    if getattr(observations_or_projection_result, "projections", None) is not None:
        observations = observations_from_projections(
            observations_or_projection_result.projections,
            epoch_resolver=epoch_resolver,
        )
        query = getattr(observations_or_projection_result, "query", None)
        if query is not None:
            requested_start_date = requested_start_date or getattr(query, "start_date", None)
            requested_end_date = requested_end_date or getattr(query, "end_date", None)
    else:
        observations = _coerce_observations(observations_or_projection_result)

    keys = sorted(
        {(item.metric_code, item.cohort, item.epoch, item.variant) for item in observations},
        key=lambda item: (item[0], item[1], item[2], "" if item[3] is None else item[3]),
    )
    return SleepAgreementPacket(
        statistics=tuple(
            compute_agreement_statistics(
                observations,
                metric_code=key[0],
                cohort=key[1],
                epoch=key[2],
                variant=key[3],
                requested_start_date=requested_start_date,
                requested_end_date=requested_end_date,
            )
            for key in keys
        )
    )


calculate_agreement_statistics = compute_agreement_statistics
build_agreement_statistics = compute_agreement_statistics
evaluate_sleep_agreement = compute_sleep_agreement
build_sleep_agreement_packet = compute_sleep_agreement


__all__ = [
    "AgreementCoverage",
    "AgreementEpoch",
    "AgreementGate",
    "AgreementGap",
    "AgreementHalfStatistics",
    "AgreementObservation",
    "AgreementStability",
    "AgreementStatistics",
    "DEFAULT_EPOCH",
    "EpochBasis",
    "EXPLORATORY_MIN_N",
    "PROVISIONAL_MIN_N",
    "PROVISIONAL_MIN_SPAN_DELTA_DAYS",
    "R05_SLEEP_AGREEMENT_ALGORITHM",
    "R05_SLEEP_AGREEMENT_CONTRACT_VERSION",
    "R05_SLEEP_AGREEMENT_RULE_VERSION",
    "R05_SLEEP_STABILITY_RULE_VERSION",
    "SleepAgreementPacket",
    "OutlierSensitivity",
    "build_agreement_statistics",
    "build_sleep_agreement_packet",
    "calculate_agreement_statistics",
    "compute_agreement_statistics",
    "compute_sleep_agreement",
    "evaluate_sleep_agreement",
    "observations_from_projections",
]
