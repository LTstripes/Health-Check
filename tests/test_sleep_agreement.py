"""Synthetic regressions for the R05-04 agreement statistics contract."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from healthcheck.analytics.sleep_agreement import (
    AgreementObservation,
    compute_agreement_statistics,
    compute_sleep_agreement,
    observations_from_projections,
)


def _observations(
    differences: list[float],
    *,
    start: date = date(2099, 1, 1),
    cohort: str = "device_pair",
    epoch: str = "epoch-1",
    metric_code: str = "sleep_duration_asleep_seconds",
    **kwargs,
) -> list[AgreementObservation]:
    return [
        AgreementObservation(
            wake_date=start + timedelta(days=index),
            metric_code=metric_code,
            cohort=cohort,
            epoch=epoch,
            difference=difference,
            **kwargs,
        )
        for index, difference in enumerate(differences)
    ]


def test_statistics_pin_difference_sd_loa_and_robust_quantiles():
    result = compute_agreement_statistics(
        _observations([1, -2, 3, 0]),
        requested_start_date="2099-01-01",
        requested_end_date="2099-01-04",
    )

    assert result.n == 4
    assert result.differences == (1.0, -2.0, 3.0, 0.0)
    assert result.bias == pytest.approx(0.5)
    assert result.mae == pytest.approx(1.5)
    assert result.rmse == pytest.approx((14 / 4) ** 0.5)
    assert result.sample_sd == pytest.approx(2.081665999)
    assert result.loa_lower == pytest.approx(0.5 - 1.96 * result.sample_sd)
    assert result.loa_upper == pytest.approx(0.5 + 1.96 * result.sample_sd)
    assert result.robust_median == pytest.approx(0.5)
    assert result.robust_q025 == pytest.approx(-1.85)
    assert result.robust_q975 == pytest.approx(2.85)
    assert result.coverage.requested_calendar_nights == 4


def test_n_is_unique_by_wake_date_and_conflicting_duplicates_fail_closed():
    observations = _observations([1, 2, 3])
    observations.append(
        AgreementObservation(
            wake_date=date(2099, 1, 2),
            metric_code=observations[0].metric_code,
            cohort=observations[0].cohort,
            difference=99,
        )
    )

    result = compute_agreement_statistics(observations)

    assert result.n == 2
    assert result.wake_dates == (date(2099, 1, 1), date(2099, 1, 3))
    assert result.coverage.source_eligible_paired_nights == 3
    assert result.coverage.metric_valid_nights == 2
    assert result.coverage.excluded_nights["duplicate_wake_date"] == 1
    assert result.gate.exploratory == "insufficient_n"


def test_fourteen_nights_are_exploratory_without_a_span_gate():
    result = compute_agreement_statistics(_observations([0] * 14))

    assert result.n == 14
    assert result.gate.exploratory == "exploratory"
    assert result.gate.provisional == "insufficient_n"


def test_exact_42_device_pair_nights_and_41_day_delta_can_propose_only_after_stability():
    result = compute_agreement_statistics(_observations([0] * 42))

    assert result.calendar_span_delta_days == 41
    assert result.calendar_span_days == 42
    assert result.stability is not None
    assert result.stability.status == "pass"
    assert result.gate.provisional == "eligible_for_provisional_proposal"
    assert result.gate.canonical_proposal_eligible is True
    assert result.gate.canonical_switch_applied is False
    assert result.as_dict()["coverage"]["automatic_coverage_threshold"] is None
    assert result.as_dict()["coverage"]["automatic_max_gap_threshold"] is None


def test_family_pair_42_nights_never_qualify_for_provisional_canonical_evidence():
    result = compute_agreement_statistics(_observations([0] * 42, cohort="family_pair"))

    assert result.gate.exploratory == "exploratory"
    assert result.gate.provisional == "not_device_pair"
    assert result.gate.canonical_proposal_eligible is False


def test_known_method_break_blocks_provisional_gate_but_is_not_inferred_from_parser_release():
    observations = _observations([0] * 42)
    observations[21] = AgreementObservation(
        wake_date=observations[21].wake_date,
        metric_code=observations[21].metric_code,
        cohort=observations[21].cohort,
        difference=0,
        epoch="epoch-1",
        method_break=True,
    )

    result = compute_agreement_statistics(observations)

    assert result.method_break_present is True
    assert result.gate.provisional == "known_method_break"


def test_stability_uses_ordered_floor_half_and_fails_on_nonoverlapping_distributions():
    result = compute_agreement_statistics(_observations([-100] * 21 + [100] * 21))

    assert result.stability is not None
    assert result.stability.first_half is not None
    assert result.stability.second_half is not None
    assert result.stability.first_half.n == 21
    assert result.stability.second_half.n == 21
    assert result.stability.first_half.bias == -100
    assert result.stability.second_half.bias == 100
    assert result.stability.status == "fail"
    assert result.gate.provisional == "stability_failed"
    assert "max_gap" not in " ".join(result.gate.reason_codes)


def test_outliers_are_visible_and_full_n_remains_primary():
    result = compute_agreement_statistics(_observations([0] * 13 + [100]))

    assert result.n == 14
    assert result.bias == pytest.approx(100 / 14)
    assert result.outlier_sensitivity.outlier_count == 1
    assert result.outlier_sensitivity.sensitivity_n == 13
    assert result.outlier_sensitivity.sensitivity_bias == 0


def test_low_and_degenerate_n_fail_closed_without_fabricated_sd_or_loa():
    result = compute_agreement_statistics(_observations([0]))

    assert result.n == 1
    assert result.sample_sd is None
    assert result.loa_lower is None
    assert result.loa_upper is None
    assert result.stability is not None
    assert result.stability.status == "missing"
    assert result.gate.exploratory == "insufficient_n"


def test_coverage_reports_internal_gaps_without_automatic_gap_decision():
    observations = _observations([0], start=date(2099, 1, 1)) + _observations(
        [0], start=date(2099, 1, 5)
    )
    result = compute_agreement_statistics(
        observations,
        requested_start_date=date(2099, 1, 1),
        requested_end_date=date(2099, 1, 5),
    )

    assert result.coverage.requested_calendar_nights == 5
    assert result.coverage.longest_gap_days == 3
    assert result.coverage.gaps[0].missing_days == 3
    assert result.gate.provisional == "insufficient_n"
    assert result.as_dict()["coverage"]["automatic_max_gap_threshold"] is None


def test_projection_adapter_keeps_real_epoch_explicit_and_builds_per_group_packet():
    def projection(wake_date: date, difference: int, metric_code: str):
        return SimpleNamespace(
            pair=SimpleNamespace(wake_date=wake_date, cohort="device_pair"),
            metric_code=metric_code,
            variant=None,
            status="comparable",
            comparable=True,
            difference=difference,
            reason=None,
            garmin=SimpleNamespace(value=100),
            google=SimpleNamespace(value=100 + difference),
        )

    projections = [
        projection(date(2099, 1, 1), 2, "sleep_duration_asleep_seconds"),
        projection(date(2099, 1, 1), 4, "sleep_stage_light_seconds"),
    ]
    observations = observations_from_projections(
        projections,
        epoch_resolver=lambda item: "device-method-epoch-a",
    )
    packet = compute_sleep_agreement(observations)

    assert {item.metric_code for item in packet.groups} == {
        "sleep_duration_asleep_seconds",
        "sleep_stage_light_seconds",
    }
    assert all(item.epoch == "device-method-epoch-a" for item in packet.groups)


def test_classic_and_stages_variants_are_separate_groups():
    observations = _observations([1], metric_code="sleep_duration_asleep_seconds")
    observations.append(
        AgreementObservation(
            wake_date=date(2099, 1, 2),
            metric_code="sleep_duration_asleep_seconds",
            cohort="device_pair",
            variant="STAGES",
            difference=2,
        )
    )

    packet = compute_sleep_agreement(observations)

    assert {(item.variant, item.n) for item in packet.groups} == {(None, 1), ("STAGES", 1)}
