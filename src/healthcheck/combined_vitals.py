"""Selected saved HRV/RHR facts; provider meanings and source conflicts stay separate."""

from collections import defaultdict
from dataclasses import asdict

from sqlalchemy import select

from healthcheck.chat_evidence import EvidenceError
from healthcheck.combined_metrics import SOURCE, _days
from healthcheck.db.models import GarminRecordMetric, GarminSource, GarminSourceRecord, GoogleSource
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.garmin.overview_values import (
    latest_overview_snapshots,
    overview_metric_is_usable,
    overview_metric_matches,
)
from healthcheck.google.daily_vitals import DailyVitalsReadCapError, read_google_daily_vitals
from healthcheck.saved_rhr_period import (
    MAX_PERIOD_RECORDS,
    MAX_RECORDS_PER_DAY,
    SavedRhrPeriodQuery,
    read_saved_rhr_period,
)
from healthcheck.saved_values import GARMIN_RHR, GOOGLE_RHR, MAX_SOURCE_IDENTITIES, _source_identity
from healthcheck.sleep_evidence import _fields, _project

CONTRACT = "health-chat-combined-vitals-v1"
OBSERVATION = _fields(
    "value unit source_local_date temporal_precision source_timestamp_utc observation_age_days "
    "is_zero record_id metric_row_id raw_payload_id observation_id ingest_event_id field_path "
    "record_status normalization_version eligibility_rule_version")
EXCLUSION = {
    **_fields("source_local_date reason candidate_count"),
    "record_ids": [True], "metric_states": [True],
}
RHR_SCHEMA = {
    **_fields("contract_version state reason requested_day_count eligible_day_count "
              "excluded_day_count mean_display acquisition_coverage_state "
              "origin_state snapshot_as_of"),
    "query": _fields("provider_code metric_code requested_start_date requested_end_date "
                     "evaluated_at_utc evaluation_local_date source_id max_candidate_records "
                     "max_records_per_day"),
    "source_identity": SOURCE, "available_sources": [SOURCE],
    "observations": [OBSERVATION], "last_observation": OBSERVATION,
    "exclusions": [EXCLUSION], "mean_exact": _fields("numerator denominator decimal"),
    "search": _fields("complete candidate_record_cap per_day_record_cap groups_examined "
                      "records_examined incomplete_group_date"),
    "refresh": _fields("scope last_attempt_utc last_successful_refresh_utc terminal_status "
                       "freshness_state reason"),
    "source_selection": _fields("state mode selected_source_id search_complete"),
}
GOOGLE_POINT = {
    **_fields("source_local_date state value unit is_zero eligible exclusion_basis record_id "
              "metric_row_id record_status query_mode data_source_family field_path"),
    "candidates": [_fields("record_id metric_row_id state reason unit record_status query_mode "
                           "data_source_family raw_payload_id observation_id")],
}


def read_vitals(session, domain, start, end, clock, local_date, garmin_id, google_id, auto):
    providers = {}
    if domain == "hrv":
        if garmin_id is not None:
            providers["garmin"] = _garmin_hrv(session, garmin_id, start, end)
        if google_id is not None:
            providers["google"] = _google_hrv(session, google_id, start, end)
    else:
        for provider, identity, code, metric in (
            ("garmin", garmin_id, "garmin_connect", GARMIN_RHR),
            ("google", google_id, "google_health", GOOGLE_RHR),
        ):
            if identity is None and not (provider == "google" and auto):
                continue
            result = read_saved_rhr_period(session, SavedRhrPeriodQuery(
                code, metric, start, end, clock, local_date, source_id=identity))
            if result["reason"] == "saved_value_read_failed":
                raise EvidenceError("evidence_read_failed")
            body = _project(result, RHR_SCHEMA)
            complete = result["search"]["complete"] and result["eligible_day_count"] is not None
            eligible = {p["source_local_date"] for p in result["observations"]}
            providers[provider] = {
                **body, "metric_code": metric, "unit": "bpm",
                "meaning": ("provider_resting_heart_rate_snapshot" if provider == "garmin"
                            else "provider_daily_resting_heart_rate"),
                "missing_dates": sorted(_days(start, end) - eligible) if complete else None,
                "missing_day_count": len(_days(start, end) - eligible) if complete else None,
            }
    return {
        "contract_version": CONTRACT, "providers": providers,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "limits": {"providers": {provider: {
            "candidate_record_cap": MAX_PERIOD_RECORDS,
            "per_day_record_cap": (MAX_RECORDS_PER_DAY
                                   if domain == "rhr" or provider == "garmin" else None),
            "source_inventory_cap": (MAX_SOURCE_IDENTITIES
                                     if domain == "rhr" and provider == "google" and auto
                                     and google_id is None else 1),
        } for provider in providers}},
        "source_pooling": "not_performed", "acquisition_coverage_state": "unknown",
        "warnings": (["garmin_weekly_and_google_daily_hrv_are_distinct",
                      "weekly_snapshots_are_not_daily_hrv_observations",
                      "hrv_period_mean_not_computed"] if domain == "hrv" else
                     ["mean_weights_eligible_saved_days_equally_not_missing_days",
                      "source_conflict_or_incomplete_search_has_no_mean"]),
    }


def _google_hrv(session, source_id, start, end):
    try:
        result = read_google_daily_vitals(
            session, metric_code="daily_hrv_average_ms", start_date=start, end_date=end,
            source_id=source_id, max_records=MAX_PERIOD_RECORDS).as_dict()
    except DailyVitalsReadCapError as exc:
        raise EvidenceError("hrv_selected_points_exceed_max") from exc
    sources = result["sources"]
    points = _project(sources[0]["points"], [GOOGLE_POINT]) if sources else []
    for point in points:
        point["temporal_precision"] = "date"
    eligible = {p["source_local_date"] for p in points if p["eligible"]}
    # An existing empty explicit source is still a valid empty saved series.
    return {
        **_project(result, _fields("contract_version metric_code stream_code unit start_date "
                                  "end_date window_state")),
        "source_identity": _project(asdict(_source_identity(
            session.get(GoogleSource, source_id))), SOURCE),
        "meaning": "provider_daily_hrv_average_not_garmin_weekly_average",
        "points": points, "mean": None, "mean_reason": "not_requested",
        "eligible_day_count": len(eligible),
        "excluded_day_count": len({p["source_local_date"] for p in points if not p["eligible"]}),
        "missing_dates": sorted(_days(start, end) - eligible),
        "missing_day_count": len(_days(start, end) - eligible),
        "search_complete": True, "acquisition_coverage_state": "unknown",
    }


def _garmin_hrv(session, source_id, start, end):
    """Bounded projection using accepted Overview snapshot eligibility and ordering.

    HRV is not registered as a scalar baseline metric. Never register or feed
    its weekly snapshots into daily arithmetic to implement this composition.
    """
    code = "hrv_weekly_average_ms"
    rows = session.execute(select(GarminSourceRecord, GarminRecordMetric).join(
        GarminRecordMetric, GarminRecordMetric.record_id == GarminSourceRecord.id,
    ).where(
        GarminSourceRecord.garmin_source_id == source_id,
        GarminSourceRecord.projection_status == "current",
        GarminSourceRecord.source_local_date >= start,
        GarminSourceRecord.source_local_date <= end,
        GarminRecordMetric.metric_code == code,
    ).order_by(GarminSourceRecord.source_local_date, GarminSourceRecord.id).limit(
        MAX_PERIOD_RECORDS + 1)).all()
    if len(rows) > MAX_PERIOD_RECORDS:
        raise EvidenceError("hrv_selected_points_exceed_max")
    groups = defaultdict(list)
    for record, metric in rows:
        groups[record.source_local_date].append((record, metric))
    points = []
    for day, group in groups.items():
        if len(group) > MAX_RECORDS_PER_DAY:
            raise EvidenceError("hrv_selected_points_exceed_max")
        candidates = [(r, m) for r, m in group if overview_metric_matches(
            r, m, code=code, capability="hrv_status")]
        latest = latest_overview_snapshots(candidates) if candidates else []
        eligible = len(latest) == 1 and overview_metric_is_usable(
            *latest[0], code=code, unit="ms")
        record, metric = latest[0] if len(latest) == 1 else (None, None)
        points.append({
            "source_local_date": day.isoformat(), "eligible": eligible,
            "state": ("partial" if record.record_status == "partial" else "value")
            if eligible else ("ambiguous" if len(latest) > 1 else
                              metric.state if metric is not None else "excluded"),
            "reason": None if eligible else ("ambiguous_saved_snapshots" if len(latest) > 1
                                             else "snapshot_ineligible"),
            "value": metric.value_number if eligible else None, "unit": "ms",
            "is_zero": bool(eligible and metric.value_number == 0),
            "evidence": [{
                "record_id": r.id, "metric_row_id": m.id, "raw_payload_id": r.raw_payload_id,
                "observation_id": getattr(r, "observation_id", None), "field_path": m.field_path,
                "state": m.state, "stored_unit": m.unit, "record_status": r.record_status,
                "temporal_precision": r.temporal_precision,
                "source_timestamp_utc": restore_stored_utc(r.source_timestamp_utc),
                "normalization_version": r.normalization_contract_version,
                "surface_code": r.surface_code, "capability_code": m.capability_code,
                "reconciliation_version": r.reconciliation_contract_version,
            } for r, m in group],
        })
    eligible = {p["source_local_date"] for p in points if p["eligible"]}
    return {
        "contract_version": CONTRACT,
        "eligibility_reader": "healthcheck.garmin.overview_values",
        "source_identity": _project(asdict(_source_identity(
            session.get(GarminSource, source_id))), SOURCE),
        "metric_code": code, "unit": "ms", "aggregate_kind": "trailing_aggregate",
        "meaning": "provider_weekly_hrv_average_snapshot_on_saved_source_local_date",
        "points": points, "mean": None,
        "mean_reason": "weekly_snapshots_must_not_be_averaged_as_daily_hrv",
        "eligible_snapshot_date_count": len(eligible),
        "excluded_snapshot_date_count": len(points) - len(eligible),
        "dates_without_eligible_snapshot": sorted(_days(start, end) - eligible),
        "search_complete": True, "acquisition_coverage_state": "unknown",
        "unknown_date_records": "not_assigned_to_requested_window",
    }
