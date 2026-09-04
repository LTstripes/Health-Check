"""Hand-checkable synthetic tests for R01-05 weight analytics v1.

Every fixture uses invented values (70–90 kg range, fixed dates); no real
health data enters this file.  Expected numbers are derived by hand from
the R01 spec formulas so a reviewer can verify them without running code:

- ``alpha = 1 - 2**(-delta_days / 21)`` → 21-day gap gives exactly 0.5;
- Theil–Sen slope is the median pairwise slope in kg/day × 7;
- fat mass = weight × body-fat % / 100, lean = weight − fat mass.
"""

from __future__ import annotations

from datetime import date

import pytest

from healthcheck.analytics.coverage import calculate_coverage
from healthcheck.analytics.weight import (
    BODY_COMPOSITION_ALGORITHM,
    WEIGHT_RATE_ALGORITHM,
    WEIGHT_TREND_ALGORITHM,
    CompositionInput,
    CompositionPoint,
    DailyWeightPoint,
    build_weight_series,
    build_weight_summary,
    coerce_weight_observations,
    composition_series_by_group,
    daily_median_weights,
    derive_body_composition,
    ewma_alpha,
    similar_weight_comparison,
    theil_sen_rate,
    time_aware_ewma,
)
from healthcheck.canonical import CanonicalCandidate

GROUP = "synthetic-scale-v1"
OTHER_GROUP = "synthetic-other-v1"


def weight_candidate(
    evidence_id: str,
    observed: date | None,
    value: float | None,
    *,
    semantic: str = "weigh-in",
    group: str | None = GROUP,
    confirmed: bool = True,
    current: bool = True,
) -> CanonicalCandidate:
    return CanonicalCandidate(
        metric_code="weight",
        semantic_key=f"{semantic}-{evidence_id}",
        source_measurement_id=evidence_id,
        normalized_value=value,
        normalized_unit="kg",
        source_local_date=observed,
        compatibility_group=group,
        algorithm_code="synthetic-scale",
        algorithm_version="1",
        confirmed=confirmed,
        current=current,
    )


def composition_input(
    measurement_id: str,
    metric: str,
    value: float,
    session_id: str | None,
    *,
    group: str | None = GROUP,
    observed: date | None = None,
    unit: str | None = None,
) -> CompositionInput:
    return CompositionInput(
        measurement_id=measurement_id,
        metric_code=metric,
        value=value,
        unit=unit if unit is not None else ("kg" if metric == "weight" else "pct"),
        session_id=session_id,
        compatibility_group=group,
        observed_date=observed or date(2026, 3, 1),
    )


def test_ewma_alpha_matches_formula() -> None:
    assert ewma_alpha(0.0) == pytest.approx(0.0)
    assert ewma_alpha(21.0) == pytest.approx(0.5)
    assert ewma_alpha(42.0) == pytest.approx(0.75)
    assert ewma_alpha(1.0) == pytest.approx(1.0 - 2.0 ** (-1.0 / 21.0))
    assert ewma_alpha(60.0) == pytest.approx(1.0 - 2.0 ** (-60.0 / 21.0))


def test_daily_median_reduces_same_local_date() -> None:
    day = date(2026, 3, 10)
    observations, exclusions = coerce_weight_observations(
        [
            weight_candidate("w-1", day, 80.0),
            weight_candidate("w-2", day, 82.0),
            weight_candidate("w-3", day, 81.0),
        ]
    )
    assert exclusions == ()
    daily = daily_median_weights(observations)
    assert len(daily) == 1
    assert daily[0].median_kg == pytest.approx(81.0)
    assert daily[0].observation_count == 3
    assert daily[0].evidence_ids == ("w-1", "w-2", "w-3")


def test_ewma_hand_checkable_values() -> None:
    # Day 0: 80.0 → trend 80.0 (initialization, alpha None).
    # Day 21: 81.0 → alpha 0.5 → trend 0.5*81 + 0.5*80 = 80.5.
    # Day 42: 82.0 → alpha 0.5 → trend 0.5*82 + 0.5*80.5 = 81.25.
    daily = (
        DailyWeightPoint(date(2026, 1, 1), 80.0, 1, ("w-1",)),
        DailyWeightPoint(date(2026, 1, 22), 81.0, 1, ("w-2",)),
        DailyWeightPoint(date(2026, 2, 12), 82.0, 1, ("w-3",)),
    )
    result = time_aware_ewma(daily)
    assert result.available is True
    assert result.algorithm == WEIGHT_TREND_ALGORITHM
    assert result.points[0].trend_kg == pytest.approx(80.0)
    assert result.points[0].alpha is None
    assert result.points[1].alpha == pytest.approx(0.5)
    assert result.points[1].trend_kg == pytest.approx(80.5)
    assert result.points[2].alpha == pytest.approx(0.5)
    assert result.points[2].trend_kg == pytest.approx(81.25)
    # Raw daily medians stay visible next to the smoothed trend.
    assert [point.median_kg for point in result.points] == [80.0, 81.0, 82.0]


def test_ewma_irregular_gaps_weight_recent_point_more() -> None:
    # A 1-day gap barely moves the trend; a 60-day gap nearly replaces it.
    daily = (
        DailyWeightPoint(date(2026, 1, 1), 80.0, 1, ("w-1",)),
        DailyWeightPoint(date(2026, 1, 2), 81.0, 1, ("w-2",)),
        DailyWeightPoint(date(2026, 3, 3), 81.0, 1, ("w-3",)),
    )
    result = time_aware_ewma(daily)
    small_alpha = result.points[1].alpha
    large_alpha = result.points[2].alpha
    assert small_alpha == pytest.approx(1.0 - 2.0 ** (-1.0 / 21.0))
    assert large_alpha == pytest.approx(1.0 - 2.0 ** (-60.0 / 21.0))
    assert small_alpha < 0.05
    assert large_alpha > 0.8
    # After a 1-day gap the trend stays near 80; after 60 days it converges.
    assert result.points[1].trend_kg == pytest.approx(80.0 + small_alpha * 1.0)
    assert abs(result.points[2].trend_kg - 81.0) < abs(result.points[1].trend_kg - 81.0)


def test_reordered_inputs_are_deterministic() -> None:
    day1, day2, day3 = date(2026, 1, 1), date(2026, 1, 15), date(2026, 2, 5)
    forward = [
        weight_candidate("w-1", day1, 80.0),
        weight_candidate("w-2", day2, 79.5),
        weight_candidate("w-3", day3, 79.0),
    ]
    reverse = list(reversed(forward))
    obs_forward, _ = coerce_weight_observations(forward)
    obs_reverse, _ = coerce_weight_observations(reverse)
    assert obs_forward == obs_reverse
    trend_forward = time_aware_ewma(daily_median_weights(obs_forward))
    trend_reverse = time_aware_ewma(daily_median_weights(obs_reverse))
    assert trend_forward.points == trend_reverse.points
    rate_forward = theil_sen_rate(daily_median_weights(obs_forward))
    rate_reverse = theil_sen_rate(daily_median_weights(obs_reverse))
    assert rate_forward.slope_kg_per_week == rate_reverse.slope_kg_per_week


def linear_weekly_points(start: date, kilos: list[float]) -> tuple[DailyWeightPoint, ...]:
    from datetime import timedelta

    return tuple(
        DailyWeightPoint(start + timedelta(weeks=week), value, 1, (f"w-{week}",))
        for week, value in enumerate(kilos)
    )


def test_theil_sen_exact_linear_slope() -> None:
    # 8 weekly points declining exactly 1 kg/week over 49 days.
    daily = linear_weekly_points(
        date(2026, 1, 1), [80.0, 79.0, 78.0, 77.0, 76.0, 75.0, 74.0, 73.0]
    )
    result = theil_sen_rate(daily)
    assert result.available is True
    assert result.algorithm == WEIGHT_RATE_ALGORITHM
    assert result.slope_kg_per_week == pytest.approx(-1.0)
    assert result.observation_count == 8
    assert result.covered_span_days == 49


def test_theil_sen_resists_single_outlier() -> None:
    # Same linear decline with one +5 kg outlier on week 4.
    daily = linear_weekly_points(
        date(2026, 1, 1), [80.0, 79.0, 78.0, 82.0, 76.0, 75.0, 74.0, 73.0]
    )
    result = theil_sen_rate(daily)
    assert result.available is True
    assert result.slope_kg_per_week == pytest.approx(-1.0, abs=0.3)


def test_theil_sen_count_gate_returns_unavailable() -> None:
    from datetime import timedelta

    start = date(2026, 1, 1)
    daily = tuple(
        DailyWeightPoint(start + timedelta(days=15 * index), 80.0 - index, 1, (f"w-{index}",))
        for index in range(5)  # 5 observations spanning 60 days: count gate fails.
    )
    result = theil_sen_rate(daily)
    assert result.available is False
    assert result.reason == "insufficient_observations"
    assert result.slope_kg_per_week is None


def test_theil_sen_span_gate_returns_unavailable() -> None:
    from datetime import timedelta

    start = date(2026, 1, 1)
    daily = tuple(
        DailyWeightPoint(start + timedelta(days=3 * index), 80.0, 1, (f"w-{index}",))
        for index in range(6)  # 6 observations spanning only 15 days.
    )
    result = theil_sen_rate(daily)
    assert result.available is False
    assert result.reason == "insufficient_span"
    assert result.slope_kg_per_week is None


def test_empty_inputs_return_unavailable_never_zero() -> None:
    trend = time_aware_ewma(())
    rate = theil_sen_rate(())
    assert trend.available is False
    assert trend.reason == "no_data"
    assert trend.points == ()
    assert rate.available is False
    assert rate.reason == "no_data"
    assert rate.slope_kg_per_week is None
    assert rate.slope_kg_per_week != 0.0

    summary = build_weight_summary([])
    assert summary.trend.available is False
    assert summary.rate.available is False
    assert summary.rate.slope_kg_per_week is None
    assert summary.latest_composition.available is False
    assert summary.latest_composition.estimated_fat_mass_kg is None
    assert summary.latest_composition.estimated_lean_mass_kg is None
    assert summary.similar_weight.available is False


def test_unavailable_results_never_become_zero() -> None:
    from datetime import timedelta

    start = date(2026, 1, 1)
    few = tuple(
        DailyWeightPoint(start + timedelta(days=20 * index), 80.0, 1, (f"w-{index}",))
        for index in range(3)
    )
    for result in (theil_sen_rate(few), theil_sen_rate(())):
        assert result.available is False
        assert result.slope_kg_per_week is None
        payload = result.as_dict()
        assert payload["slope_kg_per_week"] is None
        assert payload["slope_kg_per_week"] != 0.0


def test_same_session_derivation_keeps_input_ids() -> None:
    weight = composition_input("weight-id-1", "weight", 80.0, "session-1")
    fat = composition_input("fat-id-1", "body_fat_pct", 25.0, "session-1")
    result = derive_body_composition(weight, fat)
    assert result.available is True
    assert result.algorithm == BODY_COMPOSITION_ALGORITHM
    # Hand-check: 80 × 25 / 100 = 20.0 fat; 80 − 20 = 60.0 lean.
    assert result.estimated_fat_mass_kg == pytest.approx(20.0)
    assert result.estimated_lean_mass_kg == pytest.approx(60.0)
    assert result.weight_measurement_id == "weight-id-1"
    assert result.body_fat_measurement_id == "fat-id-1"
    assert result.as_dict()["input_measurement_ids"] == ["weight-id-1", "fat-id-1"]
    assert result.compatibility_group == GROUP


def test_cross_session_derivation_rejected() -> None:
    weight = composition_input("weight-id-1", "weight", 80.0, "session-1")
    fat = composition_input("fat-id-1", "body_fat_pct", 25.0, "session-2")
    result = derive_body_composition(weight, fat)
    assert result.available is False
    assert result.reason == "cross_session"
    assert result.estimated_fat_mass_kg is None
    assert result.estimated_lean_mass_kg is None


def test_same_session_different_algorithm_groups_is_available() -> None:
    # R01: algorithm identity belongs to each scalar independently.  A scale
    # weight group next to a Xiaomi-app BIA group is still a valid pair;
    # the derived group follows the body-composition/BIA lineage.
    weight = composition_input(
        "weight-id-1", "weight", 80.0, "session-1", group="xiaomi_s400_weight"
    )
    fat = composition_input(
        "fat-id-1",
        "body_fat_pct",
        25.0,
        "session-1",
        group="xiaomi_home_s400_unknown_version",
    )
    result = derive_body_composition(weight, fat)
    assert result.available is True
    # Hand-check: 80 × 25 / 100 = 20.0 fat; 80 − 20 = 60.0 lean.
    assert result.estimated_fat_mass_kg == pytest.approx(20.0)
    assert result.estimated_lean_mass_kg == pytest.approx(60.0)
    assert result.weight_measurement_id == "weight-id-1"
    assert result.body_fat_measurement_id == "fat-id-1"
    assert result.as_dict()["input_measurement_ids"] == ["weight-id-1", "fat-id-1"]
    assert result.compatibility_group == "xiaomi_home_s400_unknown_version"
    assert result.analytics_version == "v1"


def test_same_session_conflicting_source_dates_rejected() -> None:
    weight = composition_input(
        "weight-id-1", "weight", 80.0, "session-1", observed=date(2026, 3, 1)
    )
    fat = composition_input(
        "fat-id-1", "body_fat_pct", 25.0, "session-1", observed=date(2026, 3, 2)
    )
    result = derive_body_composition(weight, fat)
    assert result.available is False
    assert result.reason == "conflicting_observed_date"
    assert result.estimated_fat_mass_kg is None
    assert result.estimated_lean_mass_kg is None


def test_derivation_rejects_invalid_canonical_units_and_values() -> None:
    good_weight = composition_input("weight-id-1", "weight", 80.0, "session-1")
    good_fat = composition_input("fat-id-1", "body_fat_pct", 25.0, "session-1")
    bad_weight_unit = composition_input(
        "weight-id-1", "weight", 80.0, "session-1", unit="lb"
    )
    bad_fat_unit = composition_input(
        "fat-id-1", "body_fat_pct", 25.0, "session-1", unit="kg"
    )
    assert derive_body_composition(bad_weight_unit, good_fat).reason == "invalid_unit"
    assert derive_body_composition(good_weight, bad_fat_unit).reason == "invalid_unit"
    bad_weight_value = composition_input("weight-id-1", "weight", 0.0, "session-1")
    bad_fat_value = composition_input(
        "fat-id-1", "body_fat_pct", 100.0, "session-1"
    )
    assert (
        derive_body_composition(bad_weight_value, good_fat).reason
        == "invalid_weight_value"
    )
    assert (
        derive_body_composition(good_weight, bad_fat_value).reason
        == "invalid_body_fat_value"
    )
    missing_group_fat = composition_input(
        "fat-id-1", "body_fat_pct", 25.0, "session-1", group=None
    )
    assert (
        derive_body_composition(good_weight, missing_group_fat).reason
        == "missing_compatibility_group"
    )


def test_source_muscle_mass_stays_distinct_from_lean() -> None:
    weight = composition_input("weight-id-1", "weight", 80.0, "session-1")
    muscle = composition_input("muscle-id-1", "muscle_mass_kg", 60.0, "session-1")
    result = derive_body_composition(weight, muscle)
    assert result.available is False
    assert result.reason == "source_muscle_not_lean"

    grouped = composition_series_by_group(
        [
            {
                "session_id": "session-1",
                "observed_date": date(2026, 3, 1),
                "compatibility_group": GROUP,
                "weight": {"measurement_id": "weight-id-1", "value": 80.0},
                "body_fat": {"measurement_id": "fat-id-1", "value": 25.0},
                "muscle": {"measurement_id": "muscle-id-1", "value": 60.0},
            }
        ]
    )
    point = grouped[GROUP][0]
    assert point.source_muscle_mass_kg == pytest.approx(60.0)
    assert point.muscle_measurement_id == "muscle-id-1"
    # Source muscle is preserved alongside — never renamed into — lean mass.
    assert point.estimated_lean_mass_kg == pytest.approx(60.0)
    assert point.estimated_fat_mass_kg == pytest.approx(20.0)


def test_composition_never_crosses_algorithm_groups() -> None:
    grouped = composition_series_by_group(
        [
            {
                "session_id": "session-1",
                "observed_date": date(2026, 3, 1),
                "compatibility_group": GROUP,
                "weight": {"measurement_id": "w-1", "value": 80.0},
                "body_fat": {"measurement_id": "f-1", "value": 25.0},
            },
            {
                "session_id": "session-2",
                "observed_date": date(2026, 3, 2),
                "compatibility_group": OTHER_GROUP,
                "weight": {"measurement_id": "w-2", "value": 80.0},
                "body_fat": {"measurement_id": "f-2", "value": 24.0},
            },
        ]
    )
    assert set(grouped) == {GROUP, OTHER_GROUP}
    assert len(grouped[GROUP]) == 1
    assert len(grouped[OTHER_GROUP]) == 1


def similar_point(
    session: str,
    observed: date,
    weight: float,
    group: str | None = GROUP,
    *,
    body_fat_pct: float | None = 25.0,
    algorithm_code: str | None = "synthetic-bia",
    algorithm_version: str | None = "1",
) -> CompositionPoint:
    fat_mass: float | None = None
    lean_mass: float | None = None
    if body_fat_pct is not None:
        fat_mass = weight * body_fat_pct / 100.0
        lean_mass = weight - fat_mass
    return CompositionPoint(
        session_id=session,
        observed_date=observed,
        compatibility_group=group,
        weight_kg=weight,
        body_fat_pct=body_fat_pct,
        estimated_fat_mass_kg=fat_mass,
        estimated_lean_mass_kg=lean_mass,
        algorithm_code=algorithm_code,
        algorithm_version=algorithm_version,
    )


def test_composition_series_keeps_exact_algorithm_provenance() -> None:
    grouped = composition_series_by_group(
        [
            {
                "session_id": "session-1",
                "observed_date": date(2026, 3, 1),
                "compatibility_group": GROUP,
                "weight": {"measurement_id": "w-1", "value": 80.0},
                "body_fat": {
                    "measurement_id": "f-1",
                    "value": 25.0,
                    "algorithm_code": "xiaomi-home",
                    "algorithm_version": "unknown",
                },
            }
        ]
    )
    point = grouped[GROUP][0]
    assert point.algorithm_code == "xiaomi-home"
    assert point.algorithm_version == "unknown"
    assert point.as_dict()["algorithm_code"] == "xiaomi-home"
    assert point.as_dict()["algorithm_version"] == "unknown"


def test_similar_weight_28_day_boundary() -> None:
    base = date(2026, 1, 1)
    earlier = similar_point("s-1", base, 80.0)
    too_close = similar_point("s-2", date(2026, 1, 28), 80.0)  # 27 days apart.
    boundary = similar_point("s-3", date(2026, 1, 29), 80.0)  # 28 days apart.
    rejected = similar_weight_comparison(earlier, too_close)
    assert rejected.available is False
    assert rejected.reason == "insufficient_gap"
    accepted = similar_weight_comparison(earlier, boundary)
    assert accepted.available is True
    assert accepted.days_apart == 28


def test_similar_weight_1_percent_boundary() -> None:
    earlier = similar_point("s-1", date(2026, 1, 1), 100.0)
    # Exactly 1% heavier: inclusive boundary → available.
    edge = similar_point("s-2", date(2026, 2, 5), 101.0)
    accepted = similar_weight_comparison(earlier, edge)
    assert accepted.available is True
    assert accepted.weight_diff_ratio == pytest.approx(0.01)
    assert accepted.weight_delta_kg == pytest.approx(1.0)
    # 1.1% heavier → unavailable, with an explanatory reason.
    over = similar_point("s-3", date(2026, 2, 5), 101.1)
    rejected = similar_weight_comparison(earlier, over)
    assert rejected.available is False
    assert rejected.reason == "weight_diff_exceeds_threshold"
    assert rejected.weight_diff_ratio > 0.01


def test_similar_weight_cross_algorithm_rejected() -> None:
    earlier = similar_point("s-1", date(2026, 1, 1), 80.0, group=GROUP)
    later = similar_point("s-2", date(2026, 2, 5), 80.0, group=OTHER_GROUP)
    result = similar_weight_comparison(earlier, later)
    assert result.available is False
    assert result.reason == "incompatible_algorithm_group"


def test_similar_weight_requires_composition_on_both_sides() -> None:
    # Same weight and sufficient gap, but no body-fat evidence anywhere.
    neither = similar_weight_comparison(
        similar_point("s-1", date(2026, 1, 1), 80.0, body_fat_pct=None),
        similar_point("s-2", date(2026, 2, 5), 80.0, body_fat_pct=None),
    )
    assert neither.available is False
    assert neither.reason == "missing_composition_evidence"
    # Composition on one side only is still not comparable; no zeros made.
    one_sided = similar_weight_comparison(
        similar_point("s-1", date(2026, 1, 1), 80.0, body_fat_pct=25.0),
        similar_point("s-2", date(2026, 2, 5), 80.0, body_fat_pct=None),
    )
    assert one_sided.available is False
    assert one_sided.reason == "missing_composition_evidence"


def test_similar_weight_compatible_pair_keeps_algorithm_identity() -> None:
    earlier = similar_point(
        "s-1",
        date(2026, 1, 1),
        80.0,
        algorithm_code="xiaomi-home",
        algorithm_version="unknown",
    )
    later = similar_point(
        "s-2",
        date(2026, 2, 5),
        80.4,
        algorithm_code="xiaomi-home",
        algorithm_version="unknown",
    )
    result = similar_weight_comparison(earlier, later)
    assert result.available is True
    assert result.compatibility_group == GROUP
    assert result.earlier_algorithm_code == "xiaomi-home"
    assert result.earlier_algorithm_version == "unknown"
    assert result.later_algorithm_code == "xiaomi-home"
    assert result.later_algorithm_version == "unknown"
    assert result.body_fat_delta_pp == pytest.approx(0.0)
    payload = result.as_dict()
    assert payload["earlier_algorithm_code"] == "xiaomi-home"
    assert payload["later_algorithm_version"] == "unknown"


def test_weight_series_preserves_raw_observations() -> None:
    day = date(2026, 3, 10)
    candidates = [
        weight_candidate("w-1", day, 80.0),
        weight_candidate("w-2", day, 82.0),
        weight_candidate("w-3", day, 81.0),
        weight_candidate("w-4", date(2026, 3, 11), 81.5),
    ]
    series = build_weight_series(candidates)
    # All four raw canonical observations survive for drill-down.
    assert [item.evidence_id for item in series.raw_points] == ["w-1", "w-2", "w-3", "w-4"]
    assert [item.value_kg for item in series.raw_points] == [80.0, 82.0, 81.0, 81.5]
    raw = series.raw_points[0]
    assert raw.observed_date == day
    assert raw.algorithm_code == "synthetic-scale"
    assert raw.algorithm_version == "1"
    assert raw.compatibility_group == GROUP
    # Daily reduction still collapses the shared date to one median…
    assert len(series.daily_points) == 2
    assert series.daily_points[0].median_kg == pytest.approx(81.0)
    assert series.daily_points[0].evidence_ids == ("w-1", "w-2", "w-3")
    # …and the trend consumes the median, while raw stays visible.
    assert series.trend_points[0].median_kg == pytest.approx(81.0)
    assert series.trend_points[0].evidence_ids == ("w-1", "w-2", "w-3")
    payload = series.as_dict()
    assert [item["evidence_id"] for item in payload["raw_points"]] == [
        "w-1",
        "w-2",
        "w-3",
        "w-4",
    ]


def test_missing_observed_date_excluded_without_midnight_invention() -> None:
    observations, exclusions = coerce_weight_observations(
        [weight_candidate("w-1", None, 80.0)]
    )
    assert observations == ()
    assert [item.reason_code for item in exclusions] == ["missing_observed_date"]
    trend = time_aware_ewma((), exclusions=exclusions)
    assert trend.available is False
    assert trend.reason == "no_data"


def test_superseded_and_unconfirmed_candidates_excluded() -> None:
    day = date(2026, 3, 1)
    observations, exclusions = coerce_weight_observations(
        [
            weight_candidate("w-old", day, 80.0, current=False),
            weight_candidate("w-pending", day, 80.0, confirmed=False),
            weight_candidate("w-ok", day, 81.0),
        ]
    )
    assert [item.value_kg for item in observations] == [81.0]
    assert sorted(item.reason_code for item in exclusions) == [
        "not_confirmed",
        "superseded",
    ]


def test_series_and_summary_consume_coverage_metadata() -> None:
    from datetime import timedelta

    start = date(2026, 1, 1)
    candidates = [
        weight_candidate(f"w-{index}", start + timedelta(weeks=index), 80.0 - index * 0.2)
        for index in range(8)
    ]
    observations, _ = coerce_weight_observations(candidates)
    coverage = calculate_coverage(
        start,
        date(2026, 3, 1),
        observations=[
            {"observed_date": item.observed_date} for item in observations
        ],
    )
    series = build_weight_series(candidates)
    assert series.trend_available is True
    assert series.input_count == 8
    assert series.covered_span_days == 49

    similar = (
        similar_point("s-1", date(2026, 1, 1), 80.0),
        similar_point("s-2", date(2026, 2, 5), 80.4),
    )
    summary = build_weight_summary(
        candidates,
        latest_composition=derive_body_composition(
            composition_input("weight-id-1", "weight", 80.0, "session-1"),
            composition_input("fat-id-1", "body_fat_pct", 25.0, "session-1"),
        ),
        similar_pair=similar,
        coverage=coverage,
    )
    assert summary.trend.available is True
    assert summary.rate.available is True
    assert summary.rate.slope_kg_per_week is not None
    assert summary.latest_composition.available is True
    assert summary.similar_weight.available is True
    assert summary.coverage is not None
    assert summary.coverage["observed_dates"][0] == "2026-01-01"
    assert summary.algorithm_versions == {
        "trend": WEIGHT_TREND_ALGORITHM,
        "rate": WEIGHT_RATE_ALGORITHM,
        "composition": BODY_COMPOSITION_ALGORITHM,
    }
    payload = summary.as_dict()
    assert payload["trend"]["algorithm"] == WEIGHT_TREND_ALGORITHM
    assert payload["rate"]["algorithm"] == WEIGHT_RATE_ALGORITHM
