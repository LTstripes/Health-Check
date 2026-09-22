"""Regressions for #119 deterministic period brief packet + thin renderer."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from healthcheck import cli
from healthcheck.analytics.garmin_baselines import (
    GarminScalarSeriesResult,
    GarminSeriesPoint,
    GarminSeriesQuery,
    PersonalBaselineStats,
    PersonalPercentileResult,
    RobustDeviationResult,
    RobustTrendResult,
    SeriesAvailabilityCounts,
)
from healthcheck.analytics.period_brief import (
    PERIOD_BRIEF_BASELINE_MAX_CALENDAR_DAYS,
    PERIOD_BRIEF_BASELINE_WINDOW_LIMIT_REASON,
    PERIOD_BRIEF_BASELINE_WINDOW_POLICY,
    PERIOD_BRIEF_CONTRACT_VERSION,
    baseline_summary_from_result,
    build_period_brief_packet,
    normalize_period,
    render_period_brief_text,
    thin_period_brief_for_display,
)
from healthcheck.analytics.sleep_agreement import PersistedSleepAgreementService
from healthcheck.analytics.sleep_agreement_report import (
    ACCOUNT_UNCERTAINTY_NOTICE,
    SleepAgreementReportService,
)
from healthcheck.analytics.sleep_metrics import read_persisted_sleep_metric_projection
from healthcheck.analytics.sleep_pairing import (
    ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS,
    SleepPairingQuery,
)
from healthcheck.analytics.weight import DailyWeightPoint, WeightSummary, WeightTrendResult
from healthcheck.config import Settings
from healthcheck.db.engine import (
    create_session_factory,
    create_sqlite_engine,
    migrate_database,
)
from healthcheck.db.models import GarminSource
from healthcheck.db.repositories import repositories_for
from healthcheck.garmin.analytic_contract import get_analytic_metric_definition
from healthcheck.garmin.normalization import normalize_garmin_payload
from healthcheck.garmin.persistence import (
    GARMIN_COVERAGE_RULE_VERSION,
    GarminPersistenceRepository,
)
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.runtime import prepare_runtime
from healthcheck.web.period_brief_query import PeriodBriefService
from healthcheck.web.ui_app import create_ui_app
from test_sleep_account_cohort import COHORT, START, _garmin, _google
from test_sleep_pairing import pairing_database as pairing_database


def _weight_summary(*, points: list[dict] | None = None, rate_available: bool = True):
    if points is None:
        points = [
            {
                "observed_date": "2099-01-01",
                "median_kg": 80.0,
                "observation_count": 1,
                "evidence_ids": ["weight-1"],
            },
            {
                "observed_date": "2099-01-08",
                "median_kg": 79.5,
                "observation_count": 1,
                "evidence_ids": ["weight-2"],
            },
            {
                "observed_date": "2099-01-15",
                "median_kg": 79.0,
                "observation_count": 1,
                "evidence_ids": ["weight-3"],
            },
        ]
    return {
        "rate": {
            "available": rate_available,
            "reason": None if rate_available else "insufficient_observations",
            "slope_kg_per_week": -0.25 if rate_available else None,
            "observation_count": len(points),
            "covered_span_days": 14,
            "algorithm": "weight_rate_theil_sen_90d_v1",
        },
        "trend": {
            "available": True,
            "reason": None,
            "input_count": len(points),
            "covered_span_days": 14,
            "algorithm": "weight_trend_taewma_v1",
            "daily_points": points,
        },
        "latest_composition": {"available": False, "reason": "insufficient_inputs"},
        "coverage": {
            "status": "present",
            "status_counts": {
                "present": 3,
                "confirmed_empty": 0,
                "unavailable": 0,
                "failed": 0,
                "unknown": 0,
            },
            "observed_dates": [p["observed_date"] for p in points],
            "expected_bin_count": 3,
            "covered_bin_count": 3,
            "freshness_days": 5,
            "latest_observation_date": points[-1]["observed_date"] if points else None,
            "oldest_observation_date": points[0]["observed_date"] if points else None,
            "longest_gap_days": 7,
        },
        "current": {
            "value_kg": points[-1]["median_kg"] if points else None,
            "observed_date": points[-1]["observed_date"] if points else None,
        },
        "canonical": {"available": True},
    }


def _sleep_report(*, uncertain: bool = False, available: bool = True):
    """Fake SleepAgreementReportService group shape (accepted contract, no legacy keys)."""

    cohort = ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS if uncertain else "device_pair"
    groups = []
    if available:
        n = 14 if not uncertain else 3
        gate = {
            "exploratory": "exploratory" if n >= 14 else "insufficient_n",
            "provisional": ("exploratory_only_cohort" if uncertain else "insufficient_n"),
            "canonical_proposal_eligible": False,
            "canonical_switch_applied": False,
            "reason_codes": (
                ["account_observations_never_canonical"]
                if uncertain
                else ["provisional_n_below_42"]
            ),
        }
        group = {
            "run_id": "run-1",
            "cohort": cohort,
            "metric_code": "sleep_duration_seconds",
            "variant": None,
            "source_attribution": {
                "cohort_label": (
                    "Uncertain Garmin account / Google source or family observations"
                    if uncertain
                    else "Fitbit device pair"
                ),
                "source_classes": (["garmin_account"] if uncertain else ["fitbit_device"]),
            },
            "n": n,
            "paired_nights": n,
            "progress": {
                "status": "exploratory" if not uncertain else "accumulating",
                "exploratory_available": not uncertain,
                "n": n,
                "required_n": 14,
                "remaining_n": 0 if not uncertain else 11,
                "gate": gate,
            },
            "accepted_statistics": (
                {"bias": 1.0, "mae": 2.0, "n": 14, "gate": gate} if not uncertain else None
            ),
        }
        if uncertain:
            group["uncertainty_notice"] = ACCOUNT_UNCERTAINTY_NOTICE
        groups.append(group)
    return {
        "contract_version": "r05-05-sleep-agreement-report-v1",
        "available": available and bool(groups),
        "mode": "exploratory"
        if groups and not uncertain
        else ("unavailable" if not available else "accumulating"),
        "reason": None if available else "no_published_agreement",
        "threshold": {
            "exploratory_n": 14,
            "available_groups": 1 if groups and not uncertain else 0,
        },
        "groups": groups,
        "source_data_quality": [
            {
                "provider_code": "garmin",
                "state": "usable",
                "last_successful_sync": "2099-01-15T00:00:00+00:00",
                "last_attempt": "2099-01-15T00:00:00+00:00",
                "last_sync_status": "succeeded",
                "last_actual_measurement_or_evidence_date": "2099-01-14",
                "coverage_state_counts": {"present": 10},
            }
        ],
        "claims": {"accuracy": "not_assessed", "canonical_switch": "not_applied"},
    }


def test_normalize_period_rejects_datetime_and_inverted_bounds():
    period = normalize_period(date(2099, 1, 1), date(2099, 1, 14))
    assert period.calendar_days == 14
    with pytest.raises(ValueError):
        normalize_period(date(2099, 1, 14), date(2099, 1, 1))
    with pytest.raises(ValueError):
        normalize_period(datetime(2099, 1, 1), date(2099, 1, 2))  # type: ignore[arg-type]


def test_real_daily_weight_points_survive_producer_serialization():
    """#146: real DailyWeightPoint keys, including explicit zero, reach the packet."""

    trend = WeightTrendResult(
        available=True,
        points=(),
        daily_points=(
            DailyWeightPoint(
                observed_date=date(2099, 1, 1),
                median_kg=0.0,
                observation_count=2,
                evidence_ids=("weight-a", "weight-b"),
            ),
            DailyWeightPoint(
                observed_date=date(2099, 1, 2),
                median_kg=79.25,
                observation_count=1,
                evidence_ids=("weight-c",),
            ),
        ),
        input_count=3,
        covered_span_days=2,
    )
    summary = WeightSummary(
        trend=trend,
        coverage={
            "status": "present",
            "status_counts": {"present": 2},
            "observed_dates": ["2099-01-01", "2099-01-02"],
        },
    ).as_dict()
    packet = build_period_brief_packet(
        period=normalize_period(date(2099, 1, 1), date(2099, 1, 2)),
        weight_summary=summary,
        sleep_report=_sleep_report(available=False),
    )
    weight = packet["sections"]["weight"]
    first = next(
        fact
        for fact in weight["summary_facts"]
        if fact["code"] == "weight_first_daily_median_kg"
    )
    last = next(
        fact
        for fact in weight["summary_facts"]
        if fact["code"] == "weight_last_daily_median_kg"
    )
    assert first == {
        "code": "weight_first_daily_median_kg",
        "value": 0.0,
        "unit": "kg",
        "availability": "present",
        "observed_date": "2099-01-01",
    }
    assert last["value"] == 79.25
    assert last["observed_date"] == "2099-01-02"
    assert weight["display_points"] == [
        {"observed_date": "2099-01-01", "median_kg": 0.0},
        {"observed_date": "2099-01-02", "median_kg": 79.25},
    ]

    drifted = WeightSummary(trend=trend).as_dict()
    drifted["trend"]["daily_points"][0]["value_kg"] = drifted["trend"]["daily_points"][
        0
    ].pop("median_kg")
    with pytest.raises(ValueError, match="not a DailyWeightPoint payload"):
        build_period_brief_packet(
            period=normalize_period(date(2099, 1, 1), date(2099, 1, 2)),
            weight_summary=drifted,
            sleep_report=_sleep_report(available=False),
        )


def _real_scalar_result(
    statuses: tuple[str, ...],
    *,
    analytics_available: bool = False,
    start_date: date = date(2099, 1, 1),
    end_date: date = date(2099, 1, 5),
) -> GarminScalarSeriesResult:
    points: list[GarminSeriesPoint] = []
    for index, status in enumerate(statuses):
        value = (
            0.0
            if status == "zero"
            else (10.0 + index if status in {"usable", "partial"} else None)
        )
        points.append(
            GarminSeriesPoint(
                status=status,
                value=value,
                analytic_date=(start_date + timedelta(days=index)).isoformat(),
                measured_at_utc=None,
                local_wall_time=None,
                zone_policy="local_date_only",
                temporal_precision="date",
                is_zero=status == "zero",
                exclusion_reason="synthetic_unusable" if status == "not_computable" else None,
                input_manifest_hash=f"manifest-{index}",
                record_id=f"record-{index}",
                metric_row_id=f"metric-{index}",
                idempotency_key=f"key-{index}",
            )
        )
    usable = sum(status in {"usable", "zero", "partial"} for status in statuses)
    latest = next(
        (point.value for point in reversed(points) if point.value is not None),
        None,
    )
    availability = SeriesAvailabilityCounts(
        candidate_count=len(points),
        usable_count=usable,
        zero_count=sum(status == "zero" for status in statuses),
        excluded_count=sum(status == "excluded" for status in statuses),
        missing_count=sum(status == "missing" for status in statuses),
        null_count=sum(status == "null" for status in statuses),
        invalid_count=sum(status == "invalid" for status in statuses),
        not_computable_count=sum(status == "not_computable" for status in statuses),
        partial_count=sum(status == "partial" for status in statuses),
        exclusions=(),
    )
    baseline = PersonalBaselineStats(
        available=usable > 0,
        reason=None if usable > 0 else "no_usable_values",
        count=usable,
        mean=latest,
        median=latest,
        p10=latest,
        p25=latest,
        p50=latest,
        p75=latest,
        p90=latest,
        minimum=latest,
        maximum=latest,
    )
    percentile = PersonalPercentileResult(
        available=analytics_available,
        reason=None if analytics_available else "insufficient_usable_values",
        value=50.0 if analytics_available else None,
        latest_value=latest,
        n=usable,
    )
    trend = RobustTrendResult(
        available=analytics_available,
        reason=None if analytics_available else "insufficient_temporal_sample",
        slope_per_day=0.25 if analytics_available else None,
        input_count=usable,
        distinct_analytic_dates=usable,
        pair_count=usable * (usable - 1) // 2,
    )
    deviation = RobustDeviationResult(
        available=analytics_available,
        reason=None if analytics_available else "insufficient_usable_values",
        robust_z=0.0 if analytics_available else None,
        mad=1.0 if analytics_available else None,
        median=latest,
        latest_value=latest,
        personal_baseline_deviation=False if analytics_available else None,
    )
    return GarminScalarSeriesResult(
        algorithm="garmin_scalar_personal_baseline_v1",
        rule_version="r03-01-garmin-baseline-v1",
        query=GarminSeriesQuery(
            metric_code="stress_daily_average",
            start_date=start_date,
            end_date=end_date,
            garmin_source_id="synthetic-source",
        ),
        metric_definition=get_analytic_metric_definition("stress_daily_average"),
        points=tuple(points),
        availability=availability,
        baseline=baseline,
        personal_percentile=percentile,
        trend=trend,
        deviation=deviation,
        frozen_inputs=(),
        result_hash=f"real-dto-{','.join(statuses) or 'empty'}-{start_date}-{end_date}",
    )


def test_real_r03_result_availability_and_windows_remain_distinct():
    usable = baseline_summary_from_result(
        _real_scalar_result(("usable",) * 5, analytics_available=True).as_dict(),
        acquisition_state="present",
    )
    assert usable["availability"] == "present"
    assert usable["availability_counts"]["usable_count"] == 5

    explicit_zero = baseline_summary_from_result(
        _real_scalar_result(("zero",)).as_dict(),
        acquisition_state="present",
    )
    assert explicit_zero["availability"] == "insufficient"
    assert explicit_zero["latest_value"] == 0.0
    assert explicit_zero["availability_counts"]["zero_count"] == 1

    partial = baseline_summary_from_result(
        _real_scalar_result(("partial",)).as_dict(),
        acquisition_state="present",
    )
    assert partial["availability"] == "insufficient"
    assert partial["availability_counts"]["partial_count"] == 1

    empty_result = _real_scalar_result(()).as_dict()
    unknown = baseline_summary_from_result(empty_result, acquisition_state="unknown")
    confirmed_empty = baseline_summary_from_result(
        empty_result, acquisition_state="confirmed_empty"
    )
    assert unknown["availability"] == "unknown"
    assert confirmed_empty["availability"] == "confirmed_empty"

    metric_unavailable = baseline_summary_from_result(
        _real_scalar_result(("missing", "null", "invalid", "not_computable")).as_dict(),
        acquisition_state="present",
    )
    assert metric_unavailable["availability"] == "unavailable"
    assert metric_unavailable["availability_counts"] == {
        "candidate_count": 4,
        "usable_count": 0,
        "zero_count": 0,
        "excluded_count": 0,
        "missing_count": 1,
        "null_count": 1,
        "invalid_count": 1,
        "not_computable_count": 1,
        "partial_count": 0,
    }

    requested = normalize_period(date(2099, 1, 1), date(2099, 12, 31))
    effective_end = requested.end_date
    effective_start = effective_end - timedelta(
        days=PERIOD_BRIEF_BASELINE_MAX_CALENDAR_DAYS - 1
    )
    limited = baseline_summary_from_result(
        _real_scalar_result((), start_date=effective_start, end_date=effective_end).as_dict(),
        requested_window=requested,
        acquisition_state="unknown",
    )
    assert limited["requested_window"] == requested.as_dict()
    assert limited["effective_window"]["calendar_days"] == 180
    assert limited["window_policy"] == {
        "code": PERIOD_BRIEF_BASELINE_WINDOW_POLICY,
        "max_calendar_days": 180,
        "limited": True,
        "reason": PERIOD_BRIEF_BASELINE_WINDOW_LIMIT_REASON,
    }

    drifted = _real_scalar_result(("usable",)).as_dict()
    drifted["availability"]["present_count"] = 1
    drifted["availability"].pop("usable_count")
    with pytest.raises(ValueError, match="availability.usable_count"):
        baseline_summary_from_result(drifted, acquisition_state="present")

    packet_unknown = build_period_brief_packet(
        period=normalize_period(date(2099, 1, 1), date(2099, 1, 5)),
        weight_summary=_weight_summary(),
        sleep_report=_sleep_report(),
        sleep_baselines=[unknown],
    )
    packet_empty = build_period_brief_packet(
        period=normalize_period(date(2099, 1, 1), date(2099, 1, 5)),
        weight_summary=_weight_summary(),
        sleep_report=_sleep_report(),
        sleep_baselines=[confirmed_empty],
    )
    assert packet_unknown["result_hash"] != packet_empty["result_hash"]


def test_packet_hash_stable_for_identical_frozen_inputs():
    period = normalize_period(date(2099, 1, 1), date(2099, 1, 14))
    kwargs = dict(
        period=period,
        weight_summary=_weight_summary(),
        sleep_report=_sleep_report(),
        activities=[
            {
                "record_id": "a1",
                "activity_type": "cycling",
                "source_local_date": "2099-01-03",
                "external_record_id": "x1",
            },
            {
                "record_id": "a2",
                "activity_type": "cycling",
                "source_local_date": "2099-01-10",
                "external_record_id": "x2",
            },
        ],
        import_queue={
            "pending_candidate_count": 0,
            "confirmed_candidate_count": 1,
            "rejected_candidate_count": 0,
            "batch_count": 1,
        },
    )
    first = build_period_brief_packet(**kwargs)
    second = build_period_brief_packet(**kwargs)
    assert first["contract_version"] == PERIOD_BRIEF_CONTRACT_VERSION
    assert first["result_hash"] == second["result_hash"]
    assert len(first["result_hash"]) == 64


def test_missing_unknown_unavailable_zero_remain_distinct():
    period = normalize_period(date(2099, 1, 1), date(2099, 1, 7))
    weight = _weight_summary(points=[], rate_available=False)
    weight["coverage"] = {
        "status": "unknown",
        "status_counts": {
            "present": 0,
            "confirmed_empty": 0,
            "unavailable": 0,
            "failed": 0,
            "unknown": 7,
        },
        "observed_dates": [],
        "expected_bin_count": 1,
        "covered_bin_count": 0,
        "freshness_days": None,
        "latest_observation_date": None,
        "oldest_observation_date": None,
        "longest_gap_days": None,
    }
    weight["current"] = {"value_kg": None, "observed_date": None}
    weight["trend"]["input_count"] = 0
    weight["trend"]["available"] = False
    weight["trend"]["reason"] = "insufficient_observations"
    weight["trend"]["daily_points"] = []

    # Empty activities without an inventory signal are unknown, not confirmed_empty.
    empty_activity = build_period_brief_packet(
        period=period,
        weight_summary=weight,
        sleep_report=_sleep_report(available=False),
        activities=[],
    )
    assert empty_activity["sections"]["activity"]["state"] == "unknown"
    assert empty_activity["sections"]["sleep"]["state"] == "unavailable"

    inventoried_empty = build_period_brief_packet(
        period=period,
        weight_summary=weight,
        sleep_report=_sleep_report(available=False),
        activities=[],
        activity_inventory_status="inventoried",
    )
    assert inventoried_empty["sections"]["activity"]["state"] == "confirmed_empty"

    zero_weight = _weight_summary(
        points=[
            {
                "observed_date": "2099-01-02",
                "median_kg": 0.0,
                "observation_count": 1,
                "evidence_ids": ["weight-zero"],
            }
        ],
        rate_available=False,
    )
    # Explicit zero remains a numeric value with present availability, not null/unknown.
    packet = build_period_brief_packet(
        period=period,
        weight_summary=zero_weight,
        sleep_report=_sleep_report(available=False),
    )
    last = next(
        f
        for f in packet["sections"]["weight"]["summary_facts"]
        if f["code"] == "weight_last_daily_median_kg"
    )
    assert last["value"] == 0.0
    assert last["availability"] == "present"

    unavailable_weight = dict(weight)
    unavailable_weight["coverage"] = {
        "status": "failed",
        "status_counts": {
            "present": 0,
            "confirmed_empty": 0,
            "unavailable": 0,
            "failed": 1,
            "unknown": 0,
        },
        "observed_dates": [],
        "expected_bin_count": 1,
        "covered_bin_count": 0,
        "freshness_days": None,
        "latest_observation_date": None,
        "oldest_observation_date": None,
        "longest_gap_days": None,
    }
    failed = build_period_brief_packet(
        period=period,
        weight_summary=unavailable_weight,
        sleep_report=_sleep_report(available=False),
    )
    assert failed["sections"]["weight"]["state"] == "unavailable"


def test_display_thinning_does_not_change_analytical_numbers():
    period = normalize_period(date(2099, 1, 1), date(2099, 1, 30))
    points = [
        {
            "observed_date": f"2099-01-{day:02d}",
            "median_kg": 80.0 - (day * 0.05),
            "observation_count": 1,
            "evidence_ids": [f"weight-{day}"],
        }
        for day in range(1, 29)
    ]
    packet = build_period_brief_packet(
        period=period,
        weight_summary=_weight_summary(points=points),
        sleep_report=_sleep_report(),
        activities=[
            {
                "record_id": f"a{i}",
                "activity_type": "cycling",
                "source_local_date": f"2099-01-{i:02d}",
            }
            for i in range(1, 16)
        ],
    )
    rate_before = next(
        f["value"]
        for f in packet["sections"]["weight"]["summary_facts"]
        if f["code"] == "weight_rate_kg_per_week"
    )
    obs_before = next(
        f["value"]
        for f in packet["sections"]["weight"]["summary_facts"]
        if f["code"] == "weight_observation_count"
    )
    activity_count_before = next(
        f["value"]
        for f in packet["sections"]["activity"]["summary_facts"]
        if f["code"] == "activity_session_count"
    )
    display = thin_period_brief_for_display(packet, max_display_points=5, max_activity_sessions=3)
    assert display["display_only"] is True
    assert display["source_result_hash"] == packet["result_hash"]
    assert "result_hash" not in display
    assert len(display["sections"]["weight"]["display_points"]) <= 5
    assert len(display["sections"]["activity"]["sessions"]) == 3
    rate_after = next(
        f["value"]
        for f in display["sections"]["weight"]["summary_facts"]
        if f["code"] == "weight_rate_kg_per_week"
    )
    obs_after = next(
        f["value"]
        for f in display["sections"]["weight"]["summary_facts"]
        if f["code"] == "weight_observation_count"
    )
    activity_count_after = next(
        f["value"]
        for f in display["sections"]["activity"]["summary_facts"]
        if f["code"] == "activity_session_count"
    )
    assert rate_after == rate_before == -0.25
    assert obs_after == obs_before == 28
    assert activity_count_after == activity_count_before == 15
    # Original packet unchanged
    assert len(packet["sections"]["weight"]["display_points"]) == 28
    assert len(packet["sections"]["activity"]["sessions"]) == 15


def test_uncertain_account_cohort_is_explicitly_labeled():
    period = normalize_period(date(2099, 1, 1), date(2099, 1, 14))
    packet = build_period_brief_packet(
        period=period,
        weight_summary=_weight_summary(),
        sleep_report=_sleep_report(uncertain=True),
    )
    sleep = packet["sections"]["sleep"]
    assert ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS in sleep["exploratory_uncertain_cohorts"]
    assert sleep["groups"][0]["exploratory_label_required"] is True
    text = render_period_brief_text(packet)
    assert "exploratory/uncertain cohort" in text
    assert packet["result_hash"]


def test_sparse_weighing_is_not_owner_action():
    period = normalize_period(date(2099, 1, 1), date(2099, 1, 30))
    weight = _weight_summary()
    weight["coverage"]["freshness_days"] = 40
    packet = build_period_brief_packet(
        period=period,
        weight_summary=weight,
        sleep_report=_sleep_report(),
        import_queue={"pending_candidate_count": 0, "batch_count": 0},
    )
    assert packet["sections"]["weight"]["coverage"]["last_measurement_vs_sync_note"]
    assert packet["owner_actions"] == []


def test_pending_imports_create_owner_action():
    period = normalize_period(date(2099, 1, 1), date(2099, 1, 7))
    packet = build_period_brief_packet(
        period=period,
        weight_summary=_weight_summary(),
        sleep_report=_sleep_report(),
        import_queue={"pending_candidate_count": 2, "batch_count": 1},
    )
    assert any(item["code"] == "confirm_pending_imports" for item in packet["owner_actions"])


def test_api_period_brief_on_empty_runtime(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ui_app(settings)
    with TestClient(app) as client:
        response = client.get(
            "/api/period-brief",
            params={"start_date": "2099-01-01", "end_date": "2099-01-14"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["packet"]["contract_version"] == PERIOD_BRIEF_CONTRACT_VERSION
        assert body["packet"]["result_hash"]
        # Empty runtime has no Garmin source — activity must not claim confirmed_empty.
        assert body["packet"]["sections"]["activity"]["state"] == "unavailable"
        assert body["packet"]["sections"]["activity"]["state"] != "confirmed_empty"
        assert "Weight-Check" not in body["rendered_text"]
        assert "period brief" in body["rendered_text"].lower()
        text = client.get(
            "/api/period-brief.txt",
            params={"start_date": "2099-01-01", "end_date": "2099-01-14"},
        )
        assert text.status_code == 200
        assert "Result hash:" in text.text


def test_cli_period_brief_writes_packet_to_external_runtime(tmp_path, capsys):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    output = tmp_path / "period-brief.json"

    assert (
        cli.main(
            [
                "period-brief",
                "--data-dir",
                str(paths.root),
                "--start",
                "2099-01-01",
                "--end",
                "2099-01-14",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    stdout = capsys.readouterr().out
    assert f"period-brief: wrote packet to {output}" in stdout
    packet = json.loads(output.read_text(encoding="utf-8"))
    assert packet["contract_version"] == PERIOD_BRIEF_CONTRACT_VERSION
    assert packet["period"] == {
        "start_date": "2099-01-01",
        "end_date": "2099-01-14",
        "calendar_days": 14,
    }
    assert packet["result_hash"]


def test_activity_availability_distinguishes_inventory_outcomes():
    """#119 breaker: missing/not-fetched activity must not be confirmed_empty."""

    period = normalize_period(date(2099, 1, 1), date(2099, 1, 7))
    weight = _weight_summary()
    sleep = _sleep_report(available=False)

    no_source = build_period_brief_packet(
        period=period,
        weight_summary=weight,
        sleep_report=sleep,
        activities=[],
        activity_inventory_status="unavailable",
    )
    assert no_source["sections"]["activity"]["state"] == "unavailable"
    assert no_source["sections"]["activity"]["state"] != "confirmed_empty"
    assert no_source["sections"]["activity"]["coverage"]["inventory_status"] == "unavailable"

    not_fetched = build_period_brief_packet(
        period=period,
        weight_summary=weight,
        sleep_report=sleep,
        activities=[],
        activity_inventory_status="unknown",
    )
    assert not_fetched["sections"]["activity"]["state"] == "unknown"
    assert not_fetched["sections"]["activity"]["state"] != "confirmed_empty"

    not_requested = build_period_brief_packet(
        period=period,
        weight_summary=weight,
        sleep_report=sleep,
        activities=[],
        activity_inventory_status="not_requested",
    )
    assert not_requested["sections"]["activity"]["state"] == "not_requested"
    assert not_requested["sections"]["activity"]["state"] != "confirmed_empty"

    # Default / omitted inventory with empty list also must not claim confirmed_empty.
    omitted = build_period_brief_packet(
        period=period,
        weight_summary=weight,
        sleep_report=sleep,
        activities=[],
    )
    assert omitted["sections"]["activity"]["state"] != "confirmed_empty"
    assert omitted["sections"]["activity"]["state"] == "unknown"

    true_empty = build_period_brief_packet(
        period=period,
        weight_summary=weight,
        sleep_report=sleep,
        activities=[],
        activity_inventory_status="inventoried",
    )
    assert true_empty["sections"]["activity"]["state"] == "confirmed_empty"
    assert true_empty["sections"]["activity"]["coverage"]["inventory_status"] == "inventoried"
    assert true_empty["sections"]["activity"]["coverage"]["sessions_in_period"] == 0

    present = build_period_brief_packet(
        period=period,
        weight_summary=weight,
        sleep_report=sleep,
        activities=[
            {
                "record_id": "a1",
                "activity_type": "running",
                "source_local_date": "2099-01-03",
            }
        ],
        activity_inventory_status="inventoried",
    )
    assert present["sections"]["activity"]["state"] == "present"


def test_sleep_section_consumes_accepted_report_contract_fields():
    """Fake fixture must use accepted keys; period brief must not need legacy aliases."""

    period = normalize_period(date(2099, 1, 1), date(2099, 1, 14))
    report = _sleep_report()
    group = report["groups"][0]
    assert "cohort_label" not in group
    assert "statistics" not in group
    assert "paired_n" not in group["progress"]
    assert "canonical_gate_available" not in group["progress"]
    assert group["source_attribution"]["cohort_label"]
    assert group["accepted_statistics"]["n"] == 14
    assert group["paired_nights"] == 14
    assert "gate" in group["progress"]

    packet = build_period_brief_packet(
        period=period,
        weight_summary=_weight_summary(),
        sleep_report=report,
    )
    sleep = packet["sections"]["sleep"]
    compact = sleep["groups"][0]
    assert compact["cohort_label"] == "Fitbit device pair"
    assert compact["n"] == 14
    assert compact["paired_nights"] == 14
    assert compact["statistics_available"] is True
    assert compact["accepted_statistics_n"] == 14
    assert compact["bias"] == 1.0
    assert compact["mae"] == 2.0
    assert compact["progress"]["exploratory_available"] is True
    assert compact["progress"]["gate"]["canonical_proposal_eligible"] is False
    assert compact["progress"]["gate"]["canonical_switch_applied"] is False


def test_period_brief_preserves_accepted_account_observations_report(pairing_database):
    """Same-path: real SleepAgreementReportService account cohort -> period brief."""

    session, paths = pairing_database
    count = 14
    for index in range(count):
        wake = START + timedelta(days=index)
        _garmin(session, paths, wake)
        _google(session, paths, wake)
    query = SleepPairingQuery(
        cohort=COHORT,
        start_date=START,
        end_date=START + timedelta(days=count - 1),
    )
    projection = read_persisted_sleep_metric_projection(session, query)
    assert len(projection.pairs) == count
    persisted = PersistedSleepAgreementService(session).persist(
        projection, scope_key="synthetic:period-brief-account"
    )
    session.commit()
    report = SleepAgreementReportService(session).report(cohort=COHORT, run_id=persisted.id)
    (duration,) = [
        item for item in report["groups"] if item["metric_code"] == "sleep_duration_asleep_seconds"
    ]
    assert duration["accepted_statistics"]["n"] >= 14
    assert duration["source_attribution"]["cohort_label"]
    assert duration["uncertainty_notice"]
    assert duration["progress"]["gate"]["canonical_proposal_eligible"] is False

    period = normalize_period(START, START + timedelta(days=count - 1))
    packet = build_period_brief_packet(
        period=period,
        weight_summary=_weight_summary(),
        sleep_report=report,
    )
    sleep = packet["sections"]["sleep"]
    assert ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS in sleep["exploratory_uncertain_cohorts"]
    compact = next(
        g for g in sleep["groups"] if g["metric_code"] == "sleep_duration_asleep_seconds"
    )
    assert compact["n"] >= 14
    assert compact["paired_nights"] == duration["paired_nights"]
    assert compact["accepted_statistics_n"] >= 14
    assert compact["statistics_available"] is True
    assert "Uncertain Garmin account" in compact["cohort_label"]
    assert compact["exploratory_label_required"] is True
    assert compact["uncertainty_notice"]
    assert "not Garmin-vs-Fitbit/device agreement" in compact["uncertainty_notice"]
    assert compact["progress"]["gate"]["canonical_proposal_eligible"] is False
    assert compact["progress"]["gate"]["provisional"] == "exploratory_only_cohort"
    assert compact["progress"]["gate"]["canonical_switch_applied"] is False
    assert any(note["code"] == "uncertain_account_cohort" for note in packet["notable_changes"])


def _activity_payload(*, activity_id: str, day: str, activity_type: str = "cycling") -> dict:
    return {
        "fixture_contract_version": "r02-garmin-capability-fixture-v1",
        "fixture_id": f"synthetic-period-brief-activity-{activity_id}",
        "source_kind": "synthetic",
        "provider_code": "garmin_connect",
        "stream_code": "activity",
        "device": {
            "attributed": True,
            "code": "garmin_vivoactive_5",
            "model": "Vivoactive 5",
        },
        "client_methods": ["get_activities_by_date"],
        "payload_fields": {"activities": "activities"},
        "payload": {
            "activities": [
                {
                    "activityId": activity_id,
                    "activityType": {"typeKey": activity_type},
                    "startTimeGMT": f"{day}T08:00:00Z",
                    "duration": 1800,
                    "distance": 5000,
                    "averageSpeed": 2.7,
                    "averageHR": 120,
                }
            ]
        },
    }


def test_activity_empty_requires_complete_acquisition_coverage(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    try:
        with create_session_factory(engine)() as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "garmin-artifacts")
            outside = _activity_payload(activity_id="outside", day="2099-01-01")
            outcome = GarminPersistenceRepository(session, payload_store=store).persist_result(
                normalize_garmin_payload(outside),
                payload=outside,
                received_at=datetime(2099, 1, 2, tzinfo=UTC),
                source_contract_version=outside["fixture_contract_version"],
            )
            session.commit()
            source_id = outcome.records[0].garmin_source_id
            start = date(2099, 2, 1)
            end = date(2099, 2, 3)
            service = PeriodBriefService(session, settings)

            incomplete = service.build(
                start_date=start,
                end_date=end,
                garmin_source_id=source_id,
            )
            activity = incomplete["sections"]["activity"]
            assert activity["state"] == "unknown"
            assert activity["coverage"]["inventory_status"] == "unknown"
            assert activity["coverage"]["acquisition"] == {
                "state": "unknown",
                "complete": False,
                "surface_code": "activities",
                "requested_start_date": "2099-02-01",
                "requested_end_date": "2099-02-03",
                "status_counts": {
                    "present": 0,
                    "confirmed_empty": 0,
                    "unavailable": 0,
                    "failed": 0,
                    "unknown": 3,
                },
                "coverage_rule_versions": [],
            }

            source = session.get(GarminSource, source_id)
            assert source is not None
            repositories_for(session).coverage.record(
                provider_id=source.provider_id,
                acquisition_source_id=source.acquisition_source_id,
                stream_code="activity",
                metric_code="activities",
                interval_start=datetime(2099, 2, 1, tzinfo=UTC),
                interval_end=datetime(2099, 2, 4, tzinfo=UTC),
                resolution="day",
                status="confirmed_empty",
                calculation_rule_version=GARMIN_COVERAGE_RULE_VERSION,
                observed_count=0,
            )
            session.commit()

            proven_empty = service.build(
                start_date=start,
                end_date=end,
                garmin_source_id=source_id,
            )
            activity = proven_empty["sections"]["activity"]
            assert activity["state"] == "confirmed_empty"
            assert activity["coverage"]["inventory_status"] == "inventoried"
            assert activity["coverage"]["acquisition"]["state"] == "confirmed_empty"
            assert activity["coverage"]["acquisition"]["complete"] is True
            assert incomplete["result_hash"] != proven_empty["result_hash"]
    finally:
        engine.dispose()


def test_activity_inventory_does_not_silently_truncate_above_100(tmp_path):
    """Analytical inventory over a bounded period must remain complete past 100 rows."""

    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    try:
        with create_session_factory(engine)() as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "garmin-artifacts")
            source_id = None
            total = 105
            start = date(2099, 1, 1)
            for index in range(total):
                day = (start + timedelta(days=index)).isoformat()
                payload = _activity_payload(activity_id=f"act-{index}", day=day)
                outcome = GarminPersistenceRepository(session, payload_store=store).persist_result(
                    normalize_garmin_payload(payload),
                    payload=payload,
                    received_at=datetime(2099, 1, 1, 12, index % 60, tzinfo=UTC),
                    source_contract_version=payload.get("fixture_contract_version"),
                )
                source_id = outcome.records[0].garmin_source_id
            session.commit()
            assert source_id is not None
            end = start + timedelta(days=total - 1)
            service = PeriodBriefService(session, settings)
            listed = service._list_activities_in_period(source_id, start, end)
            assert len(listed) == total
            packet = service.build(start_date=start, end_date=end, garmin_source_id=source_id)
            activity = packet["sections"]["activity"]
            assert activity["coverage"]["inventory_status"] == "unknown"
            assert activity["state"] == "present"
            assert activity["coverage"]["acquisition"]["complete"] is False
            assert activity["coverage"]["sessions_in_period"] == total
            count_fact = next(
                f for f in activity["summary_facts"] if f["code"] == "activity_session_count"
            )
            assert count_fact["value"] == total
            assert len(activity["sessions"]) == total
            display = thin_period_brief_for_display(packet, max_activity_sessions=10)
            assert (
                display["sections"]["activity"]["summary_facts"][
                    next(
                        i
                        for i, f in enumerate(display["sections"]["activity"]["summary_facts"])
                        if f["code"] == "activity_session_count"
                    )
                ]["value"]
                == total
            )
            assert len(display["sections"]["activity"]["sessions"]) == 10
            assert (
                display["sections"]["activity"]["display_thinning"]["original_session_count"]
                == total
            )
            assert (
                display["sections"]["activity"]["display_thinning"]["analytics_unchanged"] is True
            )

            annual_end = start + timedelta(days=364)
            annual = service.build(
                start_date=start,
                end_date=annual_end,
                garmin_source_id=source_id,
            )
            baselines = [
                *annual["sections"]["sleep"]["analytics_snapshot"]["baseline_summaries"],
                *annual["sections"]["activity"]["analytics_snapshot"]["baseline_summaries"],
            ]
            assert baselines
            for baseline in baselines:
                assert baseline["requested_window"] == {
                    "start_date": start.isoformat(),
                    "end_date": annual_end.isoformat(),
                    "calendar_days": 365,
                }
                assert baseline["effective_window"]["end_date"] == annual_end.isoformat()
                assert baseline["effective_window"]["calendar_days"] == 180
                assert baseline["window_policy"]["code"] == PERIOD_BRIEF_BASELINE_WINDOW_POLICY
                assert baseline["window_policy"]["limited"] is True
                assert (
                    baseline["window_policy"]["reason"]
                    == PERIOD_BRIEF_BASELINE_WINDOW_LIMIT_REASON
                )
    finally:
        engine.dispose()
