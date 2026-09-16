"""Deterministic period brief v1 — evidence packet + thin rendering (#119).

Assembles one versioned evidence packet over existing analytics contracts.
Does not reimplement weight/sleep/activity/coverage formulas. Renderers must
derive only from the packet (no formula recompute in UI/export).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from typing import Any

from healthcheck.analytics.coverage import COVERAGE_RULE_VERSION
from healthcheck.analytics.garmin_activity_comparison import (
    MIN_SELECTED_ACTIVITIES,
    R03_02_ALGORITHM,
    R03_02_RULE_VERSION,
)
from healthcheck.analytics.garmin_baselines import (
    R03_01_ALGORITHM,
    R03_01_RULE_VERSION,
)
from healthcheck.analytics.sleep_agreement_report import (
    ACCOUNT_UNCERTAINTY_NOTICE,
    REPORT_CONTRACT_VERSION,
)
from healthcheck.analytics.sleep_pairing import ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS
from healthcheck.analytics.weight import (
    BODY_COMPOSITION_ALGORITHM,
    WEIGHT_ANALYTICS_VERSION,
    WEIGHT_RATE_ALGORITHM,
    WEIGHT_TREND_ALGORITHM,
)
from healthcheck.garmin.analytic_contract import stable_manifest_hash

PERIOD_BRIEF_CONTRACT_VERSION = "period-brief-v1"
PERIOD_BRIEF_ALGORITHM = "period_brief_assemble_v1"
PERIOD_BRIEF_ACTIVITY_SELECTION_POLICY = "same_type_period_window_v1"

SECTION_STATES = (
    "present",
    "confirmed_empty",
    "unknown",
    "unavailable",
    "insufficient",
    "not_requested",
)


@dataclass(frozen=True, slots=True)
class PeriodWindow:
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot precede start_date")

    @property
    def calendar_days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "calendar_days": self.calendar_days,
        }


def normalize_period(start_date: date, end_date: date) -> PeriodWindow:
    """Normalize a requested inclusive calendar period."""

    if type(start_date) is not date or type(end_date) is not date:
        raise ValueError("period bounds must be calendar dates")
    return PeriodWindow(start_date=start_date, end_date=end_date)


def _coverage_state_from_summary(coverage: Mapping[str, Any] | None) -> str:
    if coverage is None:
        return "unknown"
    status = coverage.get("status")
    if status in {"present", "confirmed_empty", "unavailable", "failed", "unknown"}:
        return "unavailable" if status == "failed" else str(status)
    counts = coverage.get("status_counts") or coverage.get("state_counts") or {}
    if not isinstance(counts, Mapping):
        return "unknown"
    if counts.get("present"):
        return "present"
    if counts.get("confirmed_empty") and not counts.get("unavailable") and not counts.get("failed"):
        return "confirmed_empty"
    if counts.get("unavailable") or counts.get("failed"):
        return "unavailable"
    if counts.get("unknown"):
        return "unknown"
    observed = coverage.get("observed_dates") or []
    if observed:
        return "present"
    return "confirmed_empty"


def _weight_section_from_summary(
    *,
    period: PeriodWindow,
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    rate = summary.get("rate") if isinstance(summary.get("rate"), Mapping) else {}
    trend = summary.get("trend") if isinstance(summary.get("trend"), Mapping) else {}
    coverage = summary.get("coverage") if isinstance(summary.get("coverage"), Mapping) else None
    current = summary.get("current") if isinstance(summary.get("current"), Mapping) else None
    composition = (
        summary.get("latest_composition")
        if isinstance(summary.get("latest_composition"), Mapping)
        else {}
    )
    daily_points = trend.get("daily_points") if isinstance(trend.get("daily_points"), list) else []
    first_point = daily_points[0] if daily_points else None
    last_point = daily_points[-1] if daily_points else None
    state = _coverage_state_from_summary(coverage)
    if not daily_points and not (current and current.get("value_kg") is not None):
        if state == "present":
            state = "insufficient"
        elif state == "unknown" and not (summary.get("canonical") or {}).get("available", True):
            state = "unavailable"
    facts = [
        {
            "code": "weight_observation_count",
            "value": trend.get("input_count"),
            "unit": "count",
            "availability": "present" if trend.get("input_count") else "absent",
        },
        {
            "code": "weight_rate_kg_per_week",
            "value": rate.get("slope_kg_per_week"),
            "unit": "kg/week",
            "availability": (
                "present"
                if rate.get("available")
                else ("insufficient" if rate.get("reason") else "unavailable")
            ),
            "reason": rate.get("reason"),
        },
        {
            "code": "weight_trend_available",
            "value": bool(trend.get("available")),
            "unit": None,
            "availability": "present" if trend.get("available") else "insufficient",
            "reason": trend.get("reason"),
        },
        {
            "code": "weight_first_daily_median_kg",
            "value": (first_point or {}).get("value_kg")
            if isinstance(first_point, Mapping)
            else None,
            "unit": "kg",
            "availability": (
                "present"
                if isinstance(first_point, Mapping) and first_point.get("value_kg") is not None
                else "absent"
            ),
            "observed_date": (first_point or {}).get("observed_date")
            if isinstance(first_point, Mapping)
            else None,
        },
        {
            "code": "weight_last_daily_median_kg",
            "value": (last_point or {}).get("value_kg")
            if isinstance(last_point, Mapping)
            else None,
            "unit": "kg",
            "availability": (
                "present"
                if isinstance(last_point, Mapping) and last_point.get("value_kg") is not None
                else "absent"
            ),
            "observed_date": (last_point or {}).get("observed_date")
            if isinstance(last_point, Mapping)
            else None,
        },
        {
            "code": "weight_current_kg",
            "value": current.get("value_kg") if current else None,
            "unit": "kg",
            "availability": (
                "present" if current and current.get("value_kg") is not None else "absent"
            ),
            "observed_date": current.get("observed_date") if current else None,
        },
        {
            "code": "body_composition_available",
            "value": bool(composition.get("available")),
            "unit": None,
            "availability": "present" if composition.get("available") else "insufficient",
            "reason": composition.get("reason"),
        },
    ]
    freshness_days = coverage.get("freshness_days") if coverage else None
    sparse_note = None
    if isinstance(freshness_days, int):
        sparse_note = (
            "Sparse voluntary weighing is not classified as a broken source; "
            "freshness_days reflects last measurement age, not sync failure."
        )
    return {
        "section": "weight",
        "state": state,
        "contracts": {
            "weight_analytics_version": WEIGHT_ANALYTICS_VERSION,
            "trend_algorithm": WEIGHT_TREND_ALGORITHM,
            "rate_algorithm": WEIGHT_RATE_ALGORITHM,
            "composition_algorithm": BODY_COMPOSITION_ALGORITHM,
            "coverage_rule_version": COVERAGE_RULE_VERSION,
        },
        "coverage": {
            "status": coverage.get("status") if coverage else None,
            "status_counts": dict(coverage.get("status_counts") or {}) if coverage else {},
            "observed_count": len(coverage.get("observed_dates") or []) if coverage else 0,
            "expected_bin_count": coverage.get("expected_bin_count") if coverage else None,
            "covered_bin_count": coverage.get("covered_bin_count") if coverage else None,
            "freshness_days": freshness_days,
            "latest_observation_date": coverage.get("latest_observation_date")
            if coverage
            else None,
            "oldest_observation_date": coverage.get("oldest_observation_date")
            if coverage
            else None,
            "longest_gap_days": coverage.get("longest_gap_days") if coverage else None,
            "last_measurement_vs_sync_note": sparse_note,
            "period": period.as_dict(),
        },
        "summary_facts": facts,
        "display_points": [
            {"observed_date": item.get("observed_date"), "value_kg": item.get("value_kg")}
            for item in daily_points
            if isinstance(item, Mapping)
        ],
        "analytics_snapshot": {
            "rate": {
                "available": rate.get("available"),
                "reason": rate.get("reason"),
                "slope_kg_per_week": rate.get("slope_kg_per_week"),
                "observation_count": rate.get("observation_count"),
                "covered_span_days": rate.get("covered_span_days"),
                "algorithm": rate.get("algorithm"),
            },
            "trend": {
                "available": trend.get("available"),
                "reason": trend.get("reason"),
                "input_count": trend.get("input_count"),
                "covered_span_days": trend.get("covered_span_days"),
                "algorithm": trend.get("algorithm"),
            },
            "canonical_available": bool((summary.get("canonical") or {}).get("available", False)),
        },
    }


def _sleep_section_from_report(
    *,
    period: PeriodWindow,
    report: Mapping[str, Any],
    baseline_summaries: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    groups = report.get("groups") if isinstance(report.get("groups"), list) else []
    source_dq = (
        report.get("source_data_quality")
        if isinstance(report.get("source_data_quality"), list)
        else []
    )
    exploratory_cohorts: list[str] = []
    compact_groups: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        cohort = group.get("cohort")
        source_attr = (
            group.get("source_attribution")
            if isinstance(group.get("source_attribution"), Mapping)
            else {}
        )
        label = source_attr.get("cohort_label") or cohort
        uncertainty_notice = group.get("uncertainty_notice")
        if cohort == ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS:
            exploratory_cohorts.append(str(cohort))
            label = f"{label} (exploratory-only / uncertain attribution)"
            if not uncertainty_notice:
                uncertainty_notice = ACCOUNT_UNCERTAINTY_NOTICE
        progress = group.get("progress") if isinstance(group.get("progress"), Mapping) else {}
        gate = progress.get("gate") if isinstance(progress.get("gate"), Mapping) else {}
        stats = (
            group.get("accepted_statistics")
            if isinstance(group.get("accepted_statistics"), Mapping)
            else None
        )
        n = group.get("n")
        if n is None:
            n = progress.get("n")
        paired_nights = group.get("paired_nights")
        compact_groups.append(
            {
                "run_id": group.get("run_id"),
                "cohort": cohort,
                "cohort_label": label,
                "metric_code": group.get("metric_code"),
                "variant": group.get("variant"),
                "exploratory_label_required": cohort == ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS,
                "uncertainty_notice": uncertainty_notice,
                "n": n,
                "paired_nights": paired_nights,
                "progress": {
                    "n": progress.get("n", n),
                    "required_n": progress.get("required_n"),
                    "remaining_n": progress.get("remaining_n"),
                    "status": progress.get("status"),
                    "exploratory_available": progress.get("exploratory_available"),
                    "gate": {
                        "exploratory": gate.get("exploratory"),
                        "provisional": gate.get("provisional"),
                        "canonical_proposal_eligible": gate.get("canonical_proposal_eligible"),
                        "canonical_switch_applied": gate.get("canonical_switch_applied"),
                        "reason_codes": list(gate.get("reason_codes") or []),
                    },
                },
                "statistics_available": stats is not None,
                "bias": stats.get("bias") if stats else None,
                "mae": stats.get("mae") if stats else None,
                "accepted_statistics_n": stats.get("n") if stats else None,
            }
        )
    if not report.get("available"):
        state = "unavailable" if report.get("mode") == "unavailable" else "insufficient"
    elif compact_groups:
        state = "present"
    else:
        state = "insufficient"
    facts: list[dict[str, Any]] = [
        {
            "code": "sleep_agreement_mode",
            "value": report.get("mode"),
            "unit": None,
            "availability": "present" if report.get("mode") else "unknown",
        },
        {
            "code": "sleep_agreement_available",
            "value": bool(report.get("available")),
            "unit": None,
            "availability": "present" if report.get("available") else "unavailable",
            "reason": report.get("reason"),
        },
        {
            "code": "sleep_agreement_group_count",
            "value": len(compact_groups),
            "unit": "count",
            "availability": "present",
        },
        {
            "code": "sleep_exploratory_uncertain_cohort_present",
            "value": bool(exploratory_cohorts),
            "unit": None,
            "availability": "present" if exploratory_cohorts else "absent",
        },
    ]
    for item in baseline_summaries:
        if not isinstance(item, Mapping):
            continue
        facts.append(
            {
                "code": f"garmin_sleep_baseline_{item.get('metric_code')}",
                "value": item.get("latest_value"),
                "unit": item.get("unit"),
                "availability": item.get("availability"),
                "personal_baseline_deviation": item.get("personal_baseline_deviation"),
                "trend_slope_per_day": item.get("trend_slope_per_day"),
                "result_hash": item.get("result_hash"),
                "reason": item.get("reason"),
            }
        )
    return {
        "section": "sleep",
        "state": state,
        "contracts": {
            "sleep_agreement_report": REPORT_CONTRACT_VERSION,
            "garmin_baselines": {
                "algorithm": R03_01_ALGORITHM,
                "rule_version": R03_01_RULE_VERSION,
            },
        },
        "coverage": {
            "source_data_quality": [
                {
                    "provider_code": item.get("provider_code"),
                    "state": item.get("state"),
                    "last_successful_sync": item.get("last_successful_sync"),
                    "last_attempt": item.get("last_attempt"),
                    "last_sync_status": item.get("last_sync_status"),
                    "last_actual_measurement_or_evidence_date": item.get(
                        "last_actual_measurement_or_evidence_date"
                    ),
                    "coverage_state_counts": item.get("coverage_state_counts") or {},
                }
                for item in source_dq
                if isinstance(item, Mapping)
            ],
            "period": period.as_dict(),
            "sync_vs_measurement_note": (
                "last_successful_sync is distinct from last_actual_measurement_or_evidence_date"
            ),
        },
        "summary_facts": facts,
        "groups": compact_groups,
        "claims": dict(report.get("claims") or {}),
        "exploratory_uncertain_cohorts": sorted(set(exploratory_cohorts)),
        "analytics_snapshot": {
            "report_contract_version": report.get("contract_version"),
            "mode": report.get("mode"),
            "available": bool(report.get("available")),
            "reason": report.get("reason"),
            "threshold": dict(report.get("threshold") or {}),
            "baseline_summaries": [dict(item) for item in baseline_summaries],
        },
    }


def _activity_section_state(
    *,
    has_sessions: bool,
    inventory_status: str | None,
) -> str:
    """Map inventory outcome to brief-local section state.

    ``confirmed_empty`` is reserved for an actual inventory of the window that
    found no sessions. Missing Garmin source / not inventoried must not use it.
    """

    if has_sessions:
        return "present"
    if inventory_status == "inventoried":
        return "confirmed_empty"
    if inventory_status == "unavailable":
        return "unavailable"
    if inventory_status == "not_requested":
        return "not_requested"
    if inventory_status == "unknown":
        return "unknown"
    # No inventory signal: never claim the window was explicitly empty.
    return "unknown"


def _activity_section_from_inventory(
    *,
    period: PeriodWindow,
    activities: Sequence[Mapping[str, Any]],
    comparison: Mapping[str, Any] | None,
    baseline_summaries: Sequence[Mapping[str, Any]] = (),
    selection_policy: str | None = None,
    inventory_status: str | None = None,
) -> dict[str, Any]:
    in_window: list[dict[str, Any]] = []
    type_counts: Counter[str] = Counter()
    for item in activities:
        if not isinstance(item, Mapping):
            continue
        local_date = item.get("source_local_date")
        if local_date is None:
            continue
        try:
            observed = date.fromisoformat(str(local_date))
        except ValueError:
            continue
        if observed < period.start_date or observed > period.end_date:
            continue
        activity_type = str(item.get("activity_type") or "unknown")
        type_counts[activity_type] += 1
        in_window.append(
            {
                "record_id": item.get("record_id"),
                "activity_type": activity_type,
                "source_local_date": observed.isoformat(),
                "external_record_id": item.get("external_record_id"),
            }
        )
    in_window.sort(key=lambda row: (row["source_local_date"], row["record_id"] or ""))
    resolved_inventory = inventory_status
    if resolved_inventory is None and in_window:
        # Sessions were supplied without an explicit inventory flag.
        resolved_inventory = "inventoried"
    state = _activity_section_state(
        has_sessions=bool(in_window),
        inventory_status=resolved_inventory,
    )
    comparison_state = "not_requested"
    comparison_snapshot: dict[str, Any] | None = None
    if comparison is not None:
        comparison_state = "present"
        coverage = (
            comparison.get("coverage") if isinstance(comparison.get("coverage"), Mapping) else {}
        )
        comparison_snapshot = {
            "algorithm": comparison.get("algorithm"),
            "rule_version": comparison.get("rule_version"),
            "result_hash": comparison.get("result_hash"),
            "session_count": len(comparison.get("sessions") or []),
            "comparison_count": len(comparison.get("comparisons") or []),
            "coverage": {
                "comparable_pair_count": coverage.get("comparable_pair_count"),
                "not_comparable_pair_count": coverage.get("not_comparable_pair_count"),
                "present_count": coverage.get("present_count"),
                "unavailable_count": coverage.get("unavailable_count"),
                "unsupported_count": coverage.get("unsupported_count"),
            },
            "selection_policy": selection_policy,
        }
    elif in_window and max(type_counts.values(), default=0) < MIN_SELECTED_ACTIVITIES:
        comparison_state = "insufficient"
    facts: list[dict[str, Any]] = [
        {
            "code": "activity_session_count",
            "value": len(in_window),
            "unit": "count",
            "availability": "present" if in_window else "absent",
        },
        {
            "code": "activity_type_counts",
            "value": dict(sorted(type_counts.items())),
            "unit": None,
            "availability": "present" if type_counts else "absent",
        },
        {
            "code": "activity_comparison_state",
            "value": comparison_state,
            "unit": None,
            "availability": comparison_state,
            "result_hash": (comparison_snapshot or {}).get("result_hash"),
        },
    ]
    for item in baseline_summaries:
        if not isinstance(item, Mapping):
            continue
        facts.append(
            {
                "code": f"garmin_activity_related_baseline_{item.get('metric_code')}",
                "value": item.get("latest_value"),
                "unit": item.get("unit"),
                "availability": item.get("availability"),
                "personal_baseline_deviation": item.get("personal_baseline_deviation"),
                "trend_slope_per_day": item.get("trend_slope_per_day"),
                "result_hash": item.get("result_hash"),
                "reason": item.get("reason"),
            }
        )
    return {
        "section": "activity",
        "state": state,
        "contracts": {
            "garmin_activity_comparison": {
                "algorithm": R03_02_ALGORITHM,
                "rule_version": R03_02_RULE_VERSION,
            },
            "garmin_baselines": {
                "algorithm": R03_01_ALGORITHM,
                "rule_version": R03_01_RULE_VERSION,
            },
        },
        "coverage": {
            "sessions_in_period": len(in_window),
            "comparison_state": comparison_state,
            "inventory_status": resolved_inventory or "unknown",
            "period": period.as_dict(),
        },
        "summary_facts": facts,
        "sessions": in_window,
        "comparison": comparison_snapshot,
        "analytics_snapshot": {
            "baseline_summaries": [dict(item) for item in baseline_summaries],
        },
    }


def _data_quality_section(
    *,
    period: PeriodWindow,
    weight_section: Mapping[str, Any],
    sleep_section: Mapping[str, Any],
    activity_section: Mapping[str, Any],
    import_queue: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    facts: list[dict[str, Any]] = [
        {
            "code": "weight_coverage_state",
            "value": weight_section.get("state"),
            "unit": None,
            "availability": weight_section.get("state"),
        },
        {
            "code": "sleep_coverage_state",
            "value": sleep_section.get("state"),
            "unit": None,
            "availability": sleep_section.get("state"),
        },
        {
            "code": "activity_coverage_state",
            "value": activity_section.get("state"),
            "unit": None,
            "availability": activity_section.get("state"),
        },
        {
            "code": "pending_import_candidates",
            "value": (import_queue or {}).get("pending_candidate_count"),
            "unit": "count",
            "availability": "present" if import_queue is not None else "unknown",
        },
    ]
    provider_states = []
    for item in (sleep_section.get("coverage") or {}).get("source_data_quality") or []:
        if not isinstance(item, Mapping):
            continue
        provider_states.append(
            {
                "provider_code": item.get("provider_code"),
                "state": item.get("state"),
                "last_successful_sync": item.get("last_successful_sync"),
                "last_actual_measurement_or_evidence_date": item.get(
                    "last_actual_measurement_or_evidence_date"
                ),
            }
        )
        facts.append(
            {
                "code": f"provider_{item.get('provider_code')}_dq_state",
                "value": item.get("state"),
                "unit": None,
                "availability": item.get("state") or "unknown",
                "last_successful_sync": item.get("last_successful_sync"),
                "last_actual_measurement_or_evidence_date": item.get(
                    "last_actual_measurement_or_evidence_date"
                ),
            }
        )
    return {
        "section": "data_quality",
        "state": "present",
        "contracts": {"coverage_rule_version": COVERAGE_RULE_VERSION},
        "coverage": {
            "period": period.as_dict(),
            "provider_states": provider_states,
            "weight_freshness_days": (weight_section.get("coverage") or {}).get("freshness_days"),
            "weight_sparse_note": (weight_section.get("coverage") or {}).get(
                "last_measurement_vs_sync_note"
            ),
            "distinctions": {
                "present": "evidence exists in the requested window",
                "confirmed_empty": "provider/window explicitly empty",
                "unknown": "not requested or not yet classified",
                "unavailable": "acquisition failed or source unavailable",
                "insufficient": "present evidence is not enough for the analytic",
                "last_sync_ne_last_measurement": True,
                "sparse_voluntary_weighing_is_not_broken": True,
            },
        },
        "summary_facts": facts,
        "import_queue": {
            "pending_candidate_count": (import_queue or {}).get("pending_candidate_count"),
            "confirmed_candidate_count": (import_queue or {}).get("confirmed_candidate_count"),
            "rejected_candidate_count": (import_queue or {}).get("rejected_candidate_count"),
            "batch_count": (import_queue or {}).get("batch_count"),
        }
        if import_queue is not None
        else None,
    }


def _notable_changes(
    weight_section: Mapping[str, Any],
    sleep_section: Mapping[str, Any],
    activity_section: Mapping[str, Any],
) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    for fact in weight_section.get("summary_facts") or []:
        if not isinstance(fact, Mapping):
            continue
        if fact.get("code") == "weight_rate_kg_per_week" and fact.get("availability") == "present":
            notes.append(
                {
                    "section": "weight",
                    "code": "weight_rate",
                    "summary": "Weight rate analytic available for the requested period.",
                    "value": fact.get("value"),
                    "unit": fact.get("unit"),
                    "contract": WEIGHT_RATE_ALGORITHM,
                }
            )
        if fact.get("code") == "weight_trend_available" and fact.get("value") is True:
            notes.append(
                {
                    "section": "weight",
                    "code": "weight_trend",
                    "summary": "Weight trend analytic available for the requested period.",
                    "contract": WEIGHT_TREND_ALGORITHM,
                }
            )
    for group in sleep_section.get("groups") or []:
        if not isinstance(group, Mapping):
            continue
        progress = group.get("progress") or {}
        if progress.get("exploratory_available"):
            notes.append(
                {
                    "section": "sleep",
                    "code": "sleep_exploratory_agreement",
                    "summary": "Exploratory sleep agreement threshold met for a metric group.",
                    "cohort": group.get("cohort"),
                    "metric_code": group.get("metric_code"),
                    "exploratory_label_required": group.get("exploratory_label_required"),
                    "contract": REPORT_CONTRACT_VERSION,
                }
            )
        if group.get("exploratory_label_required"):
            notes.append(
                {
                    "section": "sleep",
                    "code": "uncertain_account_cohort",
                    "summary": (
                        "Exploratory uncertain account/wearable cohort present; "
                        "not device agreement and not canonical-eligible."
                    ),
                    "cohort": group.get("cohort"),
                    "contract": REPORT_CONTRACT_VERSION,
                }
            )
    for fact in list(sleep_section.get("summary_facts") or []) + list(
        activity_section.get("summary_facts") or []
    ):
        if not isinstance(fact, Mapping):
            continue
        if fact.get("personal_baseline_deviation") is True:
            notes.append(
                {
                    "section": "baselines",
                    "code": "personal_baseline_deviation",
                    "summary": "Existing Garmin baseline flagged a personal deviation.",
                    "fact_code": fact.get("code"),
                    "value": fact.get("value"),
                    "contract": R03_01_ALGORITHM,
                    "result_hash": fact.get("result_hash"),
                }
            )
    comparison = activity_section.get("comparison")
    if isinstance(comparison, Mapping) and comparison.get("result_hash"):
        notes.append(
            {
                "section": "activity",
                "code": "activity_comparison",
                "summary": "Deterministic activity comparison packet available for the period.",
                "result_hash": comparison.get("result_hash"),
                "contract": R03_02_ALGORITHM,
            }
        )
    notes.sort(
        key=lambda item: (
            str(item.get("section") or ""),
            str(item.get("code") or ""),
            str(item.get("metric_code") or ""),
            str(item.get("fact_code") or ""),
            str(item.get("result_hash") or ""),
        )
    )
    return notes


def _owner_actions(
    *,
    weight_section: Mapping[str, Any],
    sleep_section: Mapping[str, Any],
    activity_section: Mapping[str, Any],
    data_quality_section: Mapping[str, Any],
) -> list[dict[str, Any]]:
    del activity_section  # reserved for future action rules; unused in v1
    actions: list[dict[str, Any]] = []
    pending = ((data_quality_section.get("import_queue") or {}) or {}).get(
        "pending_candidate_count"
    )
    if isinstance(pending, int) and pending > 0:
        actions.append(
            {
                "code": "confirm_pending_imports",
                "severity": "owner",
                "summary": "Pending import candidates need owner confirmation.",
                "pending_candidate_count": pending,
            }
        )
    for item in (sleep_section.get("coverage") or {}).get("source_data_quality") or []:
        if not isinstance(item, Mapping):
            continue
        if item.get("state") in {"failed", "unavailable"}:
            actions.append(
                {
                    "code": "investigate_provider_sync",
                    "severity": "owner",
                    "summary": "Provider sync/coverage indicates failed or unavailable evidence.",
                    "provider_code": item.get("provider_code"),
                    "state": item.get("state"),
                    "last_sync_status": item.get("last_sync_status"),
                }
            )
    if weight_section.get("state") == "unavailable":
        actions.append(
            {
                "code": "restore_weight_canonical_or_coverage",
                "severity": "owner",
                "summary": (
                    "Weight section is unavailable; check canonical run/coverage "
                    "rather than inventing values."
                ),
            }
        )
    actions.sort(
        key=lambda item: (str(item.get("code") or ""), str(item.get("provider_code") or ""))
    )
    return actions


def build_period_brief_packet(
    *,
    period: PeriodWindow,
    weight_summary: Mapping[str, Any],
    sleep_report: Mapping[str, Any],
    activities: Sequence[Mapping[str, Any]] = (),
    activity_comparison: Mapping[str, Any] | None = None,
    activity_selection_policy: str | None = None,
    activity_inventory_status: str | None = None,
    sleep_baselines: Sequence[Mapping[str, Any]] = (),
    activity_baselines: Sequence[Mapping[str, Any]] = (),
    import_queue: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble one deterministic period-brief evidence packet from frozen inputs."""

    weight_section = _weight_section_from_summary(period=period, summary=weight_summary)
    sleep_section = _sleep_section_from_report(
        period=period, report=sleep_report, baseline_summaries=sleep_baselines
    )
    activity_section = _activity_section_from_inventory(
        period=period,
        activities=activities,
        comparison=activity_comparison,
        baseline_summaries=activity_baselines,
        selection_policy=activity_selection_policy,
        inventory_status=activity_inventory_status,
    )
    data_quality_section = _data_quality_section(
        period=period,
        weight_section=weight_section,
        sleep_section=sleep_section,
        activity_section=activity_section,
        import_queue=import_queue,
    )
    body = {
        "contract_version": PERIOD_BRIEF_CONTRACT_VERSION,
        "algorithm": PERIOD_BRIEF_ALGORITHM,
        "period": period.as_dict(),
        "contracts_referenced": {
            "weight_analytics_version": WEIGHT_ANALYTICS_VERSION,
            "weight_trend_algorithm": WEIGHT_TREND_ALGORITHM,
            "weight_rate_algorithm": WEIGHT_RATE_ALGORITHM,
            "body_composition_algorithm": BODY_COMPOSITION_ALGORITHM,
            "coverage_rule_version": COVERAGE_RULE_VERSION,
            "sleep_agreement_report": REPORT_CONTRACT_VERSION,
            "garmin_baselines_algorithm": R03_01_ALGORITHM,
            "garmin_baselines_rule_version": R03_01_RULE_VERSION,
            "garmin_activity_comparison_algorithm": R03_02_ALGORITHM,
            "garmin_activity_comparison_rule_version": R03_02_RULE_VERSION,
        },
        "sections": {
            "weight": weight_section,
            "sleep": sleep_section,
            "activity": activity_section,
            "data_quality": data_quality_section,
        },
        "notable_changes": _notable_changes(weight_section, sleep_section, activity_section),
        "owner_actions": _owner_actions(
            weight_section=weight_section,
            sleep_section=sleep_section,
            activity_section=activity_section,
            data_quality_section=data_quality_section,
        ),
    }
    result_hash = stable_manifest_hash(body)
    packet = dict(body)
    packet["result_hash"] = result_hash
    return packet


def thin_period_brief_for_display(
    packet: Mapping[str, Any],
    *,
    max_display_points: int | None = 14,
    max_activity_sessions: int | None = 10,
) -> dict[str, Any]:
    """Return a display-only copy. Must not alter analytical summary numbers."""

    display = deepcopy(dict(packet))
    weight = display.get("sections", {}).get("weight")
    if isinstance(weight, dict) and max_display_points is not None:
        points = weight.get("display_points")
        original_count = len(points) if isinstance(points, list) else 0
        if isinstance(points, list) and len(points) > max_display_points:
            if max_display_points <= 2:
                weight["display_points"] = [points[0], points[-1]][:max_display_points]
            else:
                step = (len(points) - 1) / (max_display_points - 1)
                indices = sorted({round(i * step) for i in range(max_display_points)})
                weight["display_points"] = [points[i] for i in indices]
        weight["display_thinning"] = {
            "max_display_points": max_display_points,
            "original_point_count": original_count,
            "analytics_unchanged": True,
        }
    activity = display.get("sections", {}).get("activity")
    if isinstance(activity, dict) and max_activity_sessions is not None:
        sessions = activity.get("sessions")
        original_count = len(sessions) if isinstance(sessions, list) else 0
        if isinstance(sessions, list) and len(sessions) > max_activity_sessions:
            activity["sessions"] = sessions[-max_activity_sessions:]
            activity["display_thinning"] = {
                "max_activity_sessions": max_activity_sessions,
                "original_session_count": original_count,
                "analytics_unchanged": True,
            }
    display["display_only"] = True
    display["source_result_hash"] = packet.get("result_hash")
    display.pop("result_hash", None)
    return display


def render_period_brief_text(packet: Mapping[str, Any]) -> str:
    """Thin human-readable rendering derived only from the packet."""

    period = packet.get("period") or {}
    lines = [
        f"Health-Check period brief ({packet.get('contract_version')})",
        (
            f"Period: {period.get('start_date')} → {period.get('end_date')} "
            f"({period.get('calendar_days')} days)"
        ),
        f"Result hash: {packet.get('result_hash') or packet.get('source_result_hash')}",
        "",
    ]
    sections = packet.get("sections") or {}
    for key in ("weight", "sleep", "activity", "data_quality"):
        section = sections.get(key) or {}
        lines.append(f"## {key}")
        lines.append(f"State: {section.get('state')}")
        for fact in section.get("summary_facts") or []:
            if not isinstance(fact, Mapping):
                continue
            value = fact.get("value")
            avail = fact.get("availability")
            unit = fact.get("unit") or ""
            unit_s = f" {unit}" if unit else ""
            reason = fact.get("reason")
            extra = f" ({reason})" if reason else ""
            lines.append(f"- {fact.get('code')}: {value}{unit_s} [{avail}]{extra}")
        if key == "sleep":
            for cohort in section.get("exploratory_uncertain_cohorts") or []:
                lines.append(
                    f"- exploratory/uncertain cohort in use: {cohort} "
                    "(not device agreement; not canonical-eligible)"
                )
        lines.append("")
    lines.append("## notable_changes")
    notes = packet.get("notable_changes") or []
    if not notes:
        lines.append("- none")
    for note in notes:
        lines.append(f"- [{note.get('section')}/{note.get('code')}] {note.get('summary')}")
    lines.append("")
    lines.append("## owner_actions")
    actions = packet.get("owner_actions") or []
    if not actions:
        lines.append("- none")
    for action in actions:
        lines.append(f"- [{action.get('code')}] {action.get('summary')}")
    lines.append("")
    lines.append(
        "Renderer note: values above are copied from the evidence packet; "
        "no health formulas were recomputed."
    )
    return "\n".join(lines) + "\n"


def baseline_summary_from_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Project an R03-01 result dict into brief baseline summary facts."""

    deviation = result.get("deviation") if isinstance(result.get("deviation"), Mapping) else {}
    trend = result.get("trend") if isinstance(result.get("trend"), Mapping) else {}
    availability = (
        result.get("availability") if isinstance(result.get("availability"), Mapping) else {}
    )
    metric = (
        result.get("metric_definition")
        if isinstance(result.get("metric_definition"), Mapping)
        else {}
    )
    present = int(availability.get("present_count") or 0)
    if present <= 0:
        availability_state = "confirmed_empty"
        if int(availability.get("unavailable_count") or 0) > 0:
            availability_state = "unavailable"
        elif int(availability.get("unknown_count") or 0) > 0:
            availability_state = "unknown"
    elif deviation.get("available") or trend.get("available"):
        availability_state = "present"
    else:
        availability_state = "insufficient"
    return {
        "metric_code": metric.get("metric_code") or (result.get("query") or {}).get("metric_code"),
        "unit": metric.get("unit"),
        "availability": availability_state,
        "latest_value": deviation.get("latest_value"),
        "personal_baseline_deviation": bool(deviation.get("personal_baseline_deviation")),
        "trend_slope_per_day": trend.get("slope_per_day"),
        "result_hash": result.get("result_hash"),
        "reason": deviation.get("reason") or trend.get("reason"),
        "algorithm": result.get("algorithm"),
        "rule_version": result.get("rule_version"),
    }


__all__ = [
    "PERIOD_BRIEF_ACTIVITY_SELECTION_POLICY",
    "PERIOD_BRIEF_ALGORITHM",
    "PERIOD_BRIEF_CONTRACT_VERSION",
    "PeriodWindow",
    "SECTION_STATES",
    "baseline_summary_from_result",
    "build_period_brief_packet",
    "normalize_period",
    "render_period_brief_text",
    "thin_period_brief_for_display",
]
