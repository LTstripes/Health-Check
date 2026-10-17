"""Opt-in saved Garmin facts for the combined snapshot; no baseline comparison."""

from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal

from healthcheck.analytics import garmin_baselines as stress
from healthcheck.chat_evidence import EvidenceError
from healthcheck.garmin import body_battery_read as battery
from healthcheck.saved_values import _source_identity
from healthcheck.sleep_evidence import TEMPORAL, _fields, _project

CONTRACT_VERSION = "health-chat-combined-selected-metrics-v1"
SOURCE = _fields("source_id provider_code source_instance_id source_kind device_attributed "
                 "device_code device_model")
EXCLUSION = _fields("reason_code record_id metric_row_id analytic_date")
INPUT_EVIDENCE = _fields(
    "raw_payload_id content_hash observation_id observation_key record_id idempotency_key "
    "metric_row_id field_path normalization_contract_version reconciliation_contract_version "
    "projection_status")
INPUT = {
    **_fields("contract_version rule_version source_instance_id provider_code algorithm_identity "
              "manifest_hash"),
    "selected": _fields("metric_code state value unit field_path aggregate_kind window"),
    "temporal": {**TEMPORAL, "analytic_date": True, "zone_policy": True},
    "evidence": INPUT_EVIDENCE,
    "exclusions": [_fields("reason_code metric_code")],
    "coverage": {
        **_fields("metric_code capability_code availability aggregate_kind window unit "
                  "parsed_sample_count usable_value_count null_count zero_count invalid_count "
                  "missing_count operational_surface_present coverage_rule_version"),
        "exclusions": [_fields("reason_code metric_code")],
    },
}
POINT = _fields("status value analytic_date measured_at_utc local_wall_time zone_policy "
                "temporal_precision is_zero exclusion_reason input_manifest_hash record_id "
                "metric_row_id idempotency_key")
BATTERY_POINT = {
    **_fields("source_local_date value eligible_sample_count is_zero"),
    "evidence": [_fields("record_id metric_row_id raw_payload_id field_path source_path "
                         "temporal_precision source_timestamp_utc record_status "
                         "normalization_version reconciliation_version")],
}


def _days(start, end):
    return {(start + timedelta(days=index)).isoformat()
            for index in range((end - start).days + 1)}


def read_stress(session, source, start, end):
    """Accepted daily averages, with all selected points and allowlisted manifests."""
    try:
        result = stress.analyze_garmin_metric_series(session, stress.GarminSeriesQuery(
            "stress_daily_average", start, end, source.id, stress.STRESS_APPLICABILITY_VERSION,
        )).as_dict()
    except stress.GarminSeriesPointCapError as exc:
        raise EvidenceError("stress_selected_points_exceed_max") from exc
    points = _project(result["points"], [POINT])
    eligible = {p["analytic_date"] for p in points
                if p["status"] in {"usable", "zero", "partial"} and p["value"] is not None}
    excluded = {p["analytic_date"] for p in points
                if p["analytic_date"] is not None and p["analytic_date"] not in eligible}
    return {
        "contract_version": CONTRACT_VERSION,
        "metric_code": "stress_daily_average", "unit": "points",
        "meaning": "provider_daily_average_not_sample_average",
        "source_identity": _project(asdict(_source_identity(source)), SOURCE),
        **_project(result, _fields("algorithm rule_version")),
        "query": _project(result["query"], _fields(
            "metric_code start_date end_date garmin_source_id max_calendar_days "
            "max_selected_points selection_version")),
        "points": points,
        "availability": _project(result["availability"], {
            **_fields("candidate_count usable_count zero_count excluded_count missing_count "
                      "null_count invalid_count not_computable_count partial_count"),
            "exclusions": [EXCLUSION],
        }),
        "applicability": _project(result["applicability"], {
            **_fields("version fetched_row_count non_candidate_count"),
            "non_candidates": [{**_fields("reason input_manifest_hash analytic_date surface_code "
                                           "collection_key ingest_event_id ingest_batch_id"),
                                "evidence": INPUT_EVIDENCE}],
        }),
        "inputs": _project(result["frozen_inputs"], [INPUT]),
        "reader_result_hash": _project(result["result_hash"], True),
        "search_complete": True,
        "eligible_day_count": len(eligible), "excluded_day_count": len(excluded),
        "missing_day_count": len(_days(start, end) - eligible),
        "missing_dates": sorted(_days(start, end) - eligible),
        "acquisition_coverage_state": "unknown",
        "baseline_comparison": "not_requested",
    }


def read_body_battery(session, source, start, end, clock):
    result = battery.read_body_battery_period(session, battery.BodyBatteryQuery(
        start, end, source.id, clock))
    # The accepted reader converts SQL failures into unavailable. A storage failure
    # rejects the combined response rather than masquerading as ordinary missing data.
    if result["reason"] == "saved_value_read_failed":
        raise EvidenceError("evidence_read_failed")
    mean = result["mean_value"]
    if mean is not None and (type(mean) is not Decimal or not mean.is_finite()):
        raise EvidenceError("unsupported_evidence_value")
    complete = result["search"]["complete"]
    eligible = {p["source_local_date"] for p in result["daily_maxima"]}
    excluded = {p["source_local_date"] for p in result["exclusions"]
                if p["source_local_date"] is not None and p["source_local_date"] not in eligible}
    body = _project(result, {
        **_fields("contract_version state reason start_date end_date requested_day_count "
                  "eligible_day_count missing_day_count acquisition_coverage_state "
                  "legacy_eligibility"),
        "source_identity": SOURCE, "daily_maxima": [BATTERY_POINT],
        "latest_maximum": BATTERY_POINT,
        "exclusions": [_fields("source_local_date reason record_id")],
        "mean_exact": _fields("numerator denominator decimal"),
        "search": _fields("complete records_examined groups_examined candidate_record_cap "
                          "per_day_record_cap incomplete_group_date"),
    })
    return {
        **body, "metric_code": "body_battery", "unit": "points",
        "meaning": "daily_maximum_among_saved_eligible_samples_not_full_day_or_morning_maximum",
        # Decimal is losslessly represented as a string, with the exact rational
        # retained above. Never float-round an accepted reader's period mean.
        "mean_value": str(mean) if mean is not None else None,
        "excluded_day_count": len(excluded) if complete else None,
        "missing_dates": sorted(_days(start, end) - eligible) if complete else None,
    }
