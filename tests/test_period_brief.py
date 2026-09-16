"""Regressions for #119 deterministic period brief packet + thin renderer."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from healthcheck.analytics.period_brief import (
    PERIOD_BRIEF_CONTRACT_VERSION,
    build_period_brief_packet,
    normalize_period,
    render_period_brief_text,
    thin_period_brief_for_display,
)
from healthcheck.analytics.sleep_pairing import ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS
from healthcheck.config import Settings
from healthcheck.db.engine import migrate_database
from healthcheck.runtime import prepare_runtime
from healthcheck.web.ui_app import create_ui_app


def _weight_summary(*, points: list[dict] | None = None, rate_available: bool = True):
    points = points or [
        {"observed_date": "2099-01-01", "value_kg": 80.0},
        {"observed_date": "2099-01-08", "value_kg": 79.5},
        {"observed_date": "2099-01-15", "value_kg": 79.0},
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
            "latest_observation_date": points[-1]["observed_date"],
            "oldest_observation_date": points[0]["observed_date"],
            "longest_gap_days": 7,
        },
        "current": {
            "value_kg": points[-1]["value_kg"],
            "observed_date": points[-1]["observed_date"],
        },
        "canonical": {"available": True},
    }


def _sleep_report(*, uncertain: bool = False, available: bool = True):
    cohort = ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS if uncertain else "device_pair"
    groups = []
    if available:
        groups.append(
            {
                "run_id": "run-1",
                "cohort": cohort,
                "cohort_label": "label",
                "metric_code": "sleep_duration_seconds",
                "variant": None,
                "progress": {
                    "paired_n": 14 if not uncertain else 3,
                    "exploratory_available": not uncertain,
                    "canonical_gate_available": False,
                },
                "statistics": {"bias": 1.0, "mae": 2.0, "n": 14} if not uncertain else {},
            }
        )
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
        points=[{"observed_date": "2099-01-02", "value_kg": 0.0}],
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
        {"observed_date": f"2099-01-{day:02d}", "value_kg": 80.0 - (day * 0.05)}
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
