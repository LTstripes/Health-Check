"""Pure coverage-v1 calculation and its repository-backed service wrapper."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy.orm import Session

from healthcheck.db.repositories import repositories_for

COVERAGE_STATUSES = (
    "present",
    "confirmed_empty",
    "unavailable",
    "failed",
    "unknown",
)
DEFAULT_WEIGHT_CADENCE_DAYS = 7
COVERAGE_RULE_VERSION = "coverage-v1"


@dataclass(frozen=True, slots=True)
class CoverageObservation:
    """A canonical observation projected to the coverage contract."""

    observed_date: date
    source_id: str | None = None
    algorithm_compatibility_group: str | None = None
    metric_code: str = "weight"

    def __post_init__(self) -> None:
        if isinstance(self.observed_date, str):
            object.__setattr__(self, "observed_date", date.fromisoformat(self.observed_date))
        if isinstance(self.observed_date, datetime):
            object.__setattr__(self, "observed_date", self.observed_date.date())
        if not isinstance(self.observed_date, date):
            raise TypeError("coverage observed_date must be a date")
        object.__setattr__(self, "metric_code", self.metric_code.strip())


@dataclass(frozen=True, slots=True)
class CoverageEvidence:
    """Read-only interval evidence used to resolve one or more cadence bins."""

    interval_start: datetime
    interval_end: datetime
    status: str
    observed_count: int | None = None
    expected_count: int | None = None
    source_id: str | None = None
    interval_id: str | None = None
    computed_at: datetime | None = None

    def __post_init__(self) -> None:
        start = _as_utc(_as_datetime(self.interval_start))
        end = _as_utc(_as_datetime(self.interval_end))
        if end <= start:
            raise ValueError("coverage interval_end must be after interval_start")
        status = getattr(self.status, "value", self.status)
        if status not in COVERAGE_STATUSES:
            raise ValueError(f"unsupported coverage status: {status}")
        if self.observed_count is not None and self.observed_count < 0:
            raise ValueError("coverage observed_count must be nonnegative")
        if self.expected_count is not None and self.expected_count < 0:
            raise ValueError("coverage expected_count must be nonnegative")
        object.__setattr__(self, "interval_start", start)
        object.__setattr__(self, "interval_end", end)
        object.__setattr__(self, "status", status)
        if self.computed_at is not None:
            object.__setattr__(
                self, "computed_at", _as_utc(_as_datetime(self.computed_at))
            )

    @classmethod
    def from_model(cls, interval: Any) -> CoverageEvidence:
        return cls(
            interval_start=interval.interval_start,
            interval_end=interval.interval_end,
            status=interval.status,
            observed_count=interval.observed_count,
            expected_count=interval.expected_count,
            source_id=interval.acquisition_source_id,
            interval_id=interval.id,
            computed_at=interval.computed_at,
        )


@dataclass(frozen=True, slots=True)
class CoverageBin:
    """One half-open expected cadence bin, represented with local dates."""

    start_date: date
    end_date: date
    status: str
    observed_dates: tuple[date, ...] = ()
    observed_count: int | None = None
    expected_count: int | None = 1
    interval_ids: tuple[str, ...] = ()
    source_breakdown: Mapping[str, int] = field(default_factory=dict)
    algorithm_breakdown: Mapping[str, int] = field(default_factory=dict)

    @property
    def covered(self) -> bool:
        return self.status == "present"

    @property
    def start(self) -> date:
        return self.start_date

    @property
    def end(self) -> date:
        return self.end_date

    def as_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "status": self.status,
            "observed_dates": [value.isoformat() for value in self.observed_dates],
            "observed_count": self.observed_count,
            "expected_count": self.expected_count,
            "interval_ids": list(self.interval_ids),
            "source_breakdown": dict(self.source_breakdown),
            "algorithm_breakdown": dict(self.algorithm_breakdown),
            "covered": self.covered,
        }


@dataclass(frozen=True, slots=True)
class CoverageSummary:
    """Coverage-v1 facts for a requested period; no missing value is zero."""

    requested_start_date: date
    requested_end_date: date
    cadence_days: int
    observed_dates: tuple[date, ...]
    expected_bins: tuple[date, ...]
    covered_bins: tuple[date, ...]
    bins: tuple[CoverageBin, ...]
    oldest_observation_date: date | None
    latest_observation_date: date | None
    freshness_days: int | None
    longest_gap_days: int | None
    source_breakdown: Mapping[str, int]
    algorithm_breakdown: Mapping[str, int]
    status_counts: Mapping[str, int]

    @property
    def expected_bin_count(self) -> int:
        return len(self.expected_bins)

    @property
    def covered_bin_count(self) -> int:
        return len(self.covered_bins)

    @property
    def observed_unique_dates(self) -> tuple[date, ...]:
        return self.observed_dates

    @property
    def expected_cadence_bins(self) -> tuple[date, ...]:
        return self.expected_bins

    @property
    def covered_cadence_bins(self) -> tuple[date, ...]:
        return self.covered_bins

    @property
    def intervals(self) -> tuple[CoverageBin, ...]:
        return self.bins

    @property
    def state_counts(self) -> Mapping[str, int]:
        return self.status_counts

    @property
    def longest_missing_span_days(self) -> int | None:
        if self.longest_gap_days is None:
            return None
        return max(0, self.longest_gap_days - 1)

    @property
    def oldest(self) -> date | None:
        return self.oldest_observation_date

    @property
    def latest(self) -> date | None:
        return self.latest_observation_date

    @property
    def status(self) -> str:
        return _summary_status(self.status_counts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_start_date": self.requested_start_date.isoformat(),
            "requested_end_date": self.requested_end_date.isoformat(),
            "cadence_days": self.cadence_days,
            "observed_dates": [value.isoformat() for value in self.observed_dates],
            "expected_bins": [value.isoformat() for value in self.expected_bins],
            "covered_bins": [value.isoformat() for value in self.covered_bins],
            "expected_bin_count": self.expected_bin_count,
            "covered_bin_count": self.covered_bin_count,
            "oldest_observation_date": self.oldest_observation_date.isoformat()
            if self.oldest_observation_date
            else None,
            "latest_observation_date": self.latest_observation_date.isoformat()
            if self.latest_observation_date
            else None,
            "freshness_days": self.freshness_days,
            "longest_gap_days": self.longest_gap_days,
            "source_breakdown": dict(self.source_breakdown),
            "algorithm_breakdown": dict(self.algorithm_breakdown),
            "status_counts": dict(self.status_counts),
            "status": self.status,
            "bins": [item.as_dict() for item in self.bins],
        }


def resolve_coverage_status(
    statuses: Iterable[str], *, evidence_present: bool = False
) -> str:
    """Resolve one bin using the R01 precedence contract.

    Actual evidence wins.  Without it, an explicit capability block wins over
    a successful empty fetch, which wins over a failed attempt, with no
    conclusive evidence remaining unknown.
    """

    values = tuple(statuses)
    normalized = {_status_value(status) for status in values}
    unsupported = normalized - set(COVERAGE_STATUSES)
    if unsupported:
        raise ValueError(f"unsupported coverage statuses: {sorted(unsupported)}")
    if evidence_present or "present" in normalized:
        return "present"
    if "unavailable" in normalized:
        return "unavailable"
    evidence_events = [
        status
        for status in values
        if _status_value(status) in {"confirmed_empty", "failed"}
    ]
    if evidence_events:
        latest = max(evidence_events, key=_coverage_event_key)
        return _status_value(latest)
    if "confirmed_empty" in normalized:
        return "confirmed_empty"
    if "failed" in normalized:
        return "failed"
    return "unknown"


def calculate_coverage(
    start_date: date,
    end_date: date,
    *,
    observations: Iterable[Any] = (),
    coverage_intervals: Iterable[Any] = (),
    intervals: Iterable[Any] | None = None,
    cadence_days: int = DEFAULT_WEIGHT_CADENCE_DAYS,
    as_of_date: date | None = None,
) -> CoverageSummary:
    """Calculate sparse weight coverage over fixed cadence bins.

    Requested dates are inclusive.  Each bin starts at ``start_date`` and is
    half-open until the next cadence boundary (or the day after the requested
    end).  A date without an observation or conclusive interval is unknown,
    never a fabricated zero measurement.
    """

    start = _as_date(start_date)
    end = _as_date(end_date)
    if end < start:
        raise ValueError("coverage end_date must not precede start_date")
    if not isinstance(cadence_days, int) or isinstance(cadence_days, bool) or cadence_days < 1:
        raise ValueError("coverage cadence_days must be a positive integer")
    if intervals is not None:
        if coverage_intervals:
            raise ValueError("coverage_intervals and intervals aliases cannot both be supplied")
        coverage_intervals = intervals
    reference_date = _as_date(as_of_date) if as_of_date is not None else end
    normalized_observations = tuple(
        _coerce_observation(value) for value in (observations or ())
    )
    in_period = tuple(
        value for value in normalized_observations if start <= value.observed_date <= end
    )
    observed_dates = tuple(sorted({value.observed_date for value in in_period}))
    normalized_intervals = tuple(
        sorted(
            (_coerce_evidence(value) for value in (coverage_intervals or ())),
            key=_coverage_evidence_sort_key,
        )
    )
    expected = _expected_bins(start, end, cadence_days)
    bins: list[CoverageBin] = []
    for bin_start, bin_end in expected:
        bin_observations = tuple(
            value
            for value in in_period
            if bin_start <= value.observed_date < bin_end
        )
        overlaps = tuple(
            value
            for value in normalized_intervals
            if _interval_overlaps_bin(value, bin_start, bin_end)
        )
        status = resolve_coverage_status(
            overlaps,
            evidence_present=bool(bin_observations),
        )
        interval_counts = [
            value.observed_count for value in overlaps if value.observed_count is not None
        ]
        if bin_observations:
            observed_count: int | None = len({value.observed_date for value in bin_observations})
        elif interval_counts:
            observed_count = max(interval_counts)
        elif status == "confirmed_empty":
            observed_count = 0
        else:
            observed_count = None
        expected_count = _expected_count(overlaps)
        bins.append(
            CoverageBin(
                start_date=bin_start,
                end_date=bin_end,
                status=status,
                observed_dates=tuple(sorted({value.observed_date for value in bin_observations})),
                observed_count=observed_count,
                expected_count=expected_count,
                interval_ids=tuple(
                    value.interval_id
                    for value in overlaps
                    if value.interval_id is not None
                ),
                source_breakdown=_breakdown(
                    bin_observations, lambda value: value.source_id
                ),
                algorithm_breakdown=_breakdown(
                    bin_observations, lambda value: value.algorithm_compatibility_group
                ),
            )
        )
    status_counts = {status: 0 for status in COVERAGE_STATUSES}
    status_counts.update(Counter(item.status for item in bins))
    return CoverageSummary(
        requested_start_date=start,
        requested_end_date=end,
        cadence_days=cadence_days,
        observed_dates=observed_dates,
        expected_bins=tuple(item[0] for item in expected),
        covered_bins=tuple(item.start_date for item in bins if item.covered),
        bins=tuple(bins),
        oldest_observation_date=min(observed_dates) if observed_dates else None,
        latest_observation_date=max(observed_dates) if observed_dates else None,
        freshness_days=(reference_date - max(observed_dates)).days if observed_dates else None,
        longest_gap_days=_longest_gap(observed_dates),
        source_breakdown=_breakdown(in_period, lambda value: value.source_id),
        algorithm_breakdown=_breakdown(
            in_period, lambda value: value.algorithm_compatibility_group
        ),
        status_counts=status_counts,
    )


class CoverageService:
    """Repository-backed adapter that projects current source heads to v1."""

    def __init__(self, session: Session):
        self.session = session
        self.repositories = repositories_for(session)

    def summarize(
        self,
        *,
        start_date: date,
        end_date: date,
        metric_code: str = "weight",
        stream_code: str = "weight",
        provider_id: str | None = None,
        acquisition_source_id: str | None = None,
        observations: Iterable[Any] | None = None,
        coverage_intervals: Iterable[Any] | None = None,
        intervals: Iterable[Any] | None = None,
        cadence_days: int = DEFAULT_WEIGHT_CADENCE_DAYS,
        as_of_date: date | None = None,
    ) -> CoverageSummary:
        if intervals is not None:
            if coverage_intervals is not None:
                raise ValueError("coverage_intervals and intervals aliases cannot both be supplied")
            coverage_intervals = intervals
        if observations is None:
            observations = self._current_observations(
                metric_code=metric_code,
                start_date=start_date,
                end_date=end_date,
                provider_id=provider_id,
                acquisition_source_id=acquisition_source_id,
            )
        if coverage_intervals is None:
            coverage_intervals = self.repositories.coverage.list(
                provider_id=provider_id,
                acquisition_source_id=acquisition_source_id,
                stream_code=stream_code,
                metric_code=metric_code,
                interval_start=datetime.combine(_as_date(start_date), time.min, tzinfo=UTC),
                interval_end=datetime.combine(
                    _as_date(end_date) + timedelta(days=1), time.min, tzinfo=UTC
                ),
            )
        return calculate_coverage(
            start_date,
            end_date,
            observations=observations,
            coverage_intervals=coverage_intervals,
            cadence_days=cadence_days,
            as_of_date=as_of_date,
        )

    def summarize_current(self, **kwargs: Any) -> CoverageSummary:
        return self.summarize(**kwargs)

    summary = summarize
    calculate = summarize
    get_summary = summarize

    def _current_observations(
        self,
        *,
        metric_code: str,
        start_date: date,
        end_date: date,
        provider_id: str | None = None,
        acquisition_source_id: str | None = None,
    ) -> tuple[CoverageObservation, ...]:
        values = []
        for measurement in self.repositories.scalar_measurements.current_heads(
            metric_code,
            acquisition_source_id=acquisition_source_id,
            provider_id=provider_id,
            start_date=_as_date(start_date),
            end_date=_as_date(end_date),
        ):
            session = self.repositories.measurement_sessions.get_by_id(
                measurement.measurement_session_id
            )
            algorithm = self.repositories.measurement_algorithms.get_by_id(
                measurement.measurement_algorithm_id
            )
            if session is None:
                continue
            values.append(
                CoverageObservation(
                    observed_date=session.source_local_date,
                    source_id=session.acquisition_source_id,
                    algorithm_compatibility_group=(
                        algorithm.compatibility_group if algorithm is not None else None
                    ),
                    metric_code=metric_code,
                )
            )
        return tuple(values)


def coverage_summary(**kwargs: Any) -> CoverageSummary:
    """Functional alias for callers that do not need the class wrapper."""

    return calculate_coverage(**kwargs)


def _coerce_observation(value: Any) -> CoverageObservation:
    if isinstance(value, CoverageObservation):
        return value
    if isinstance(value, datetime):
        return CoverageObservation(value.date())
    if isinstance(value, date):
        return CoverageObservation(value)
    if hasattr(value, "source_local_date"):
        return CoverageObservation(
            observed_date=value.source_local_date,
            source_id=getattr(value, "source_id", None),
            algorithm_compatibility_group=getattr(value, "compatibility_group", None),
            metric_code=getattr(value, "metric_code", "weight"),
        )
    if isinstance(value, Mapping):
        observed_date = value.get(
            "observed_date", value.get("source_local_date", value.get("date"))
        )
        if observed_date is None:
            raise ValueError("coverage observation needs observed_date")
        return CoverageObservation(
            observed_date=_as_date(observed_date),
            source_id=value.get("source_id", value.get("acquisition_source_id")),
            algorithm_compatibility_group=value.get(
                "algorithm_compatibility_group",
                value.get("compatibility_group", value.get("algorithm_group")),
            ),
            metric_code=str(value.get("metric_code", "weight")),
        )
    raise TypeError(f"unsupported coverage observation type: {type(value).__name__}")


def _coerce_evidence(value: Any) -> CoverageEvidence:
    if isinstance(value, CoverageEvidence):
        return value
    if all(
        hasattr(value, field_name)
        for field_name in ("interval_start", "interval_end", "status")
    ):
        return CoverageEvidence.from_model(value)
    if isinstance(value, Mapping):
        return CoverageEvidence(
            interval_start=value["interval_start"],
            interval_end=value["interval_end"],
            status=value["status"],
            observed_count=value.get("observed_count"),
            expected_count=value.get("expected_count"),
            source_id=value.get("source_id", value.get("acquisition_source_id")),
            interval_id=value.get("interval_id", value.get("id")),
            computed_at=value.get("computed_at"),
        )
    raise TypeError(f"unsupported coverage evidence type: {type(value).__name__}")


def _expected_bins(start: date, end: date, cadence_days: int) -> tuple[tuple[date, date], ...]:
    result = []
    current = start
    exclusive_end = end + timedelta(days=1)
    while current < exclusive_end:
        next_start = current + timedelta(days=cadence_days)
        result.append((current, min(next_start, exclusive_end)))
        current = next_start
    return tuple(result)


def _interval_overlaps_bin(evidence: CoverageEvidence, start: date, end: date) -> bool:
    interval_start = evidence.interval_start.astimezone(UTC).date()
    raw_end = evidence.interval_end.astimezone(UTC)
    interval_end = raw_end.date()
    if raw_end.time() != time.min:
        interval_end += timedelta(days=1)
    return interval_start < end and interval_end > start


def _expected_count(overlaps: Iterable[CoverageEvidence]) -> int | None:
    values = [value.expected_count for value in overlaps if value.expected_count is not None]
    return max(values) if values else 1


def _breakdown(
    observations: Iterable[CoverageObservation], key_fn: Any
) -> dict[str, int]:
    unique = {(value.observed_date, key_fn(value) or "unknown") for value in observations}
    counts: Counter[str] = Counter(key for _observed_date, key in unique)
    return dict(sorted(counts.items()))


def _longest_gap(observed_dates: tuple[date, ...]) -> int | None:
    if len(observed_dates) < 2:
        return None
    return max(
        (right - left).days for left, right in zip(observed_dates, observed_dates[1:])
    )


def _coverage_event_key(value: Any) -> tuple[datetime, datetime, int, str]:
    status = _status_value(value)
    if isinstance(value, Mapping):
        computed_at = value.get("computed_at")
        interval_end = value.get("interval_end", datetime.min.replace(tzinfo=UTC))
        interval_id = value.get("interval_id", value.get("id", ""))
    else:
        computed_at = getattr(value, "computed_at", None)
        interval_end = getattr(value, "interval_end", datetime.min.replace(tzinfo=UTC))
        interval_id = getattr(value, "interval_id", "")
    if computed_at is None:
        computed_at = interval_end
    return (
        _as_utc(_as_datetime(computed_at)),
        _as_utc(_as_datetime(interval_end)),
        1 if status == "confirmed_empty" else 0,
        str(interval_id or ""),
    )


def _coverage_evidence_sort_key(value: CoverageEvidence) -> tuple[Any, ...]:
    """Provide an input-order-independent order for interval evidence."""

    minimum = datetime.min.replace(tzinfo=UTC)
    return (
        value.interval_start,
        value.interval_end,
        value.computed_at or minimum,
        value.status,
        value.source_id or "",
        value.interval_id or "",
        value.observed_count if value.observed_count is not None else -1,
        value.expected_count if value.expected_count is not None else -1,
    )


def _status_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        value = value.get("status")
    else:
        value = getattr(value, "status", value)
    return getattr(value, "value", value)


def _summary_status(status_counts: Mapping[str, int]) -> str:
    if status_counts.get("present", 0) == sum(status_counts.values()) and status_counts:
        return "present"
    for status in ("unavailable", "failed", "confirmed_empty", "unknown"):
        if status_counts.get(status, 0):
            return status
    return "unknown"


def _as_date(value: date | datetime) -> date:
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, date):
        raise TypeError("coverage date must be a date")
    return value


def _as_datetime(value: datetime | str) -> datetime:
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        # SQLite returns values from DateTime(timezone=True) as naive values.
        # The repository validates aware UTC input before persistence, so a
        # reloaded naive value is unambiguous and can safely be reattached to
        # UTC at this read boundary.
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# Common names for later analytics/UI adapters.
CoverageResult = CoverageSummary
CoverageSummaryDTO = CoverageSummary
CoverageBinDTO = CoverageBin
CoverageIntervalDTO = CoverageEvidence
CoverageCalculator = calculate_coverage
resolve_status = resolve_coverage_status


__all__ = [
    "COVERAGE_STATUSES",
    "COVERAGE_RULE_VERSION",
    "DEFAULT_WEIGHT_CADENCE_DAYS",
    "CoverageBin",
    "CoverageBinDTO",
    "CoverageCalculator",
    "CoverageEvidence",
    "CoverageIntervalDTO",
    "CoverageObservation",
    "CoverageResult",
    "CoverageService",
    "CoverageSummary",
    "CoverageSummaryDTO",
    "calculate_coverage",
    "coverage_summary",
    "resolve_coverage_status",
    "resolve_status",
]
