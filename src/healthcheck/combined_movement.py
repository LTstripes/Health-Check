"""Opt-in Steps views and accepted Weight evidence in the caller-owned snapshot."""

from dataclasses import asdict

from healthcheck import chat_evidence
from healthcheck.chat_evidence import EvidenceError, EvidenceRequest
from healthcheck.garmin import completed_steps_read as completed
from healthcheck.garmin.observed_steps_read import (
    MAX_CANDIDATES,
    MAX_PROVENANCE,
    read_observed_steps_window,
)
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.sleep_evidence import _fields, _project

STEPS_SCHEMA = {
    **_fields("source_id start_date end_date search_complete candidates_examined "
              "provenance_examined reason contract_version"),
    "source_identity": _fields("source_id provider_code source_kind source_instance_id"),
    "cells": [{
        **_fields("source_id calendar_date state value reason search_complete metric_code "
                  "unit attribution coverage device timezone finality"),
        "evidence": [{
            **_fields("record_id metric_row_id raw_payload_id raw_artifact_id content_hash "
                      "ingest_event_id normalization_version reconciliation_version "
                      "projection_status metric_state metric_reason value"),
            "observation_ids": [True],
        }],
    }],
}


def read_steps(session, source_id, start, end):
    result = read_observed_steps_window(
        session, source_id=source_id, start_date=start, end_date=end)
    # The reader can retain an earlier complete prefix. Combined exports instead
    # reject the selected slice as a whole; no apparently complete prefix escapes.
    if not result.search_complete:
        raise EvidenceError("steps_search_incomplete")
    return {
        **_project(asdict(result), STEPS_SCHEMA),
        "temporal_precision": "date", "acquisition_coverage_state": "unknown",
        "meaning": "saved_observed_account_daily_steps_not_completed_daily_total",
        "source_pooling": "not_performed", "aggregate": None,
        "limits": {"candidate_record_cap": MAX_CANDIDATES,
                   "provenance_cap": MAX_PROVENANCE},
        "warnings": ["saved_observed_values_have_unknown_finality_and_coverage",
                     "missing_is_not_zero", "sources_are_not_summed"],
    }


COMPLETED_STEPS_SCHEMA = {
    **_fields("source_id start_date end_date evaluated_at search_complete candidates_examined "
              "provenance_examined artifacts_examined bytes_examined reason contract_version "
              "display_zone"),
    "source_identity": STEPS_SCHEMA["source_identity"],
    "cells": [{
        **_fields("source_id calendar_date completion_boundary_utc state value reason "
                  "latest_received_at search_complete coverage device timezone finality"),
        "evidence": [_fields(
            "observation_id raw_payload_id raw_artifact_id content_hash sync_run_id "
            "ingest_event_id received_at state value reason acquisition_proven "
            "acquisition_proof acquisition_receipt_version")],
    }],
}


def read_completed_steps(session, source_id, start, end, clock, profile):
    """Reuse v2 selection in the caller's snapshot; export only its allowlist."""
    result = completed.read_completed_steps_window(
        session, payload_store=ContentAddressedGarminPayloadStore(profile / "artifacts"),
        source_id=source_id, start_date=start, end_date=end, evaluated_at=clock)
    if not result.search_complete:
        raise EvidenceError("steps_search_incomplete")
    return {
        **_project(asdict(result), COMPLETED_STEPS_SCHEMA),
        "temporal_precision": "date", "acquisition_coverage_state": "unknown",
        "meaning": "saved_completed_day_account_steps_moscow_display_policy",
        "source_pooling": "not_performed", "aggregate": None,
        "requested_day_count": (end - start).days + 1,
        "completed_day_count": len(result.cells),
        "excluded_uncompleted_day_count": (end - start).days + 1 - len(result.cells),
        "effective_completed_range": {
            "start_date": result.cells[0].calendar_date.isoformat() if result.cells else None,
            "end_date": result.cells[-1].calendar_date.isoformat() if result.cells else None,
        },
        "limits": {"candidate_record_cap": completed.MAX_CANDIDATES,
                   "provenance_cap": completed.MAX_PROVENANCE,
                   "original_cap": completed.MAX_ARTIFACTS,
                   "original_byte_cap": completed.MAX_ARTIFACT_BYTES,
                   "total_original_bytes_cap": completed.MAX_TOTAL_BYTES,
                   "cooperative_read_seconds": completed.MAX_READ_SECONDS},
        "warnings": ["moscow_completion_policy_is_not_provider_timezone",
                     "later_acquisitions_may_correct_completed_days",
                     "saved_search_completeness_is_not_provider_coverage",
                     "missing_is_not_zero", "sources_are_not_summed"],
    }


def read_weight(session, start, end, profile_kind, clock, local_date, profile):
    # Reuse the accepted v1 exporter projection and its 2000-input guard. This
    # calls WeightQueryService in this snapshot, without Context/config loading.
    request = EvidenceRequest(start, end, ("weight",), row_limit=chat_evidence.MAX_ROWS)
    packet = chat_evidence._assemble(session, request, profile_kind, clock, local_date, profile)
    section = packet["sections"]["weight"]
    if any(section[key]["has_more"] for key in (
            "measured_facts", "daily_series", "trend_series")):
        raise EvidenceError("weight_selected_points_exceed_max")
    return {
        **section, "contract_version": "health-chat-combined-weight-v1",
        "reader_contract": chat_evidence.ENVELOPE_VERSION,
        "source_status": packet["source_status"]["weight"],
        "limits": {"max_weight_input_rows": chat_evidence.MAX_WEIGHT_INPUT_ROWS,
                   "max_rows_per_series": chat_evidence.MAX_ROWS},
        "warnings": ["raw_overlay_points_are_not_all_canonical_selected",
                     "daily_medians_require_saved_eligible_measurements",
                     "trend_is_derived_not_a_measurement_on_missing_dates",
                     "missing_is_not_zero", "no_cross_domain_causal_join"],
    }
