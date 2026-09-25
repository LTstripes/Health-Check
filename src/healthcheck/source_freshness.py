"""Frozen source-freshness-v1 policy over sanitized, persisted observations.

The evaluator has no clock, database or provider dependency. Callers must supply
both evaluation clocks and facts whose scope attribution they have actually proved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Literal

POLICY_VERSION = "source-freshness-v1"
State = Literal["fresh", "quiet", "stale", "unavailable", "unknown", "not_requested"]
Family = Literal["daily", "activity", "weight"]
Role = Literal["required", "optional"]

REQUIRED_GARMIN = ("daily_summary", "sleep", "heart_rate")
OPTIONAL_GARMIN = (
    "resting_heart_rate", "hrv_status", "stress", "body_battery", "spo2", "respiration",
    "training_status", "training_readiness",
)
REQUIRED_GOOGLE = ("sleep", "heart_rate")
OPTIONAL_GOOGLE = (
    "hrv", "daily_hrv", "daily_resting_hr", "spo2", "daily_spo2",
    "respiratory_rate_sleep", "daily_respiratory_rate", "wearables_sleep_reconcile",
)


@dataclass(frozen=True)
class Scope:
    key: str
    provider: str
    family: Family
    role: Role


SCOPES = (
    *(Scope(f"garmin:{code}", "garmin", "daily", "required") for code in REQUIRED_GARMIN),
    *(Scope(f"garmin:{code}", "garmin", "daily", "optional") for code in OPTIONAL_GARMIN),
    Scope("garmin:activities", "garmin", "activity", "optional"),
    *(Scope(f"google:{code}", "google", "daily", "required") for code in REQUIRED_GOOGLE),
    *(Scope(f"google:{code}", "google", "daily", "optional") for code in OPTIONAL_GOOGLE),
    Scope("weight", "weight", "weight", "optional"),
)
SCOPE_BY_KEY = {scope.key: scope for scope in SCOPES}


@dataclass(frozen=True)
class Facts:
    """Only allowlisted chronology/disposition; no raw values or source identifiers."""

    requested: bool = True
    disabled: bool = False
    last_attempt_at_utc: datetime | None = None
    last_success_at_utc: datetime | None = None
    terminal_status: str | None = None
    evidence_at_utc: datetime | None = None
    evidence_local_date: date | None = None
    observed_once: bool = False
    coverage: str | None = None
    activity_count: int | None = None
    confirmed_weight: bool = False
    attribution_resolved: bool = True
    weight_cadence_days: int | None = None


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be aware")
    return value.astimezone(UTC)


def _fact_block(facts: Facts) -> dict[str, object]:
    return {
        "last_relevant_attempt_utc": _iso(facts.last_attempt_at_utc),
        "last_successful_refresh_utc": _iso(facts.last_success_at_utc),
        "latest_evidence_utc": _iso(facts.evidence_at_utc),
        "latest_evidence_local_date": _iso(facts.evidence_local_date),
        "terminal_status": facts.terminal_status,
        "coverage": facts.coverage,
        "activity_count": facts.activity_count,
        "observed_once": facts.observed_once,
        "confirmed_weight": facts.confirmed_weight,
        "attribution_resolved": facts.attribution_resolved,
        "weight_cadence_days": facts.weight_cadence_days,
        "requested": facts.requested,
        "disabled": facts.disabled,
    }


def evaluate_scope(
    scope: Scope, facts: Facts, *, evaluated_at_utc: datetime, evaluation_local_date: date,
    policy_version: str = POLICY_VERSION,
) -> dict[str, object]:
    now = _utc(evaluated_at_utc)
    if not policy_version:
        raise ValueError("policy version is required")
    if not isinstance(evaluation_local_date, date) or isinstance(evaluation_local_date, datetime):
        raise ValueError("evaluation_local_date must be a civil date")
    basis: dict[str, object] = {}
    if scope.family == "daily":
        basis = {"cadence_hours": 24, "due_hours": 36, "grace_hours": 72,
                 "refresh_overdue_hours": 48}
    elif scope.family == "activity":
        basis = {"inventory_civil_days": 7, "refresh_overdue_hours": 48}
    state: State = "unknown"
    reason = "never_observed"
    if facts.disabled or not facts.requested:
        state, reason = "not_requested", "disabled" if facts.disabled else "not_requested"
    else:
        try:
            attempt = _utc(facts.last_attempt_at_utc)
            success = _utc(facts.last_success_at_utc)
            evidence = _utc(facts.evidence_at_utc)
        except ValueError:
            state, reason = "unknown", "invalid_chronology"
        else:
            if any(value is not None and value > now for value in (attempt, success, evidence)) or (
                facts.evidence_local_date is not None
                and facts.evidence_local_date > evaluation_local_date
            ):
                state, reason = "unknown", "future_chronology"
            elif not facts.attribution_resolved:
                state, reason = "unknown", "scope_unresolved"
            elif attempt is not None and (success is None or attempt > success) and (
                facts.terminal_status
                in {"reauth_required", "required_stream_unavailable", "failed"}
            ):
                state = "unavailable"
                reason = {"failed": "refresh_failed"}.get(
                    facts.terminal_status, facts.terminal_status
                )
            elif attempt is not None and (success is None or attempt > success) and (
                facts.terminal_status in {"partial", "incomplete", "unknown"}
            ):
                state, reason = "unknown", "acquisition_incomplete"
            elif attempt is not None and success is not None and attempt > success and (
                facts.terminal_status == "succeeded"
            ):
                state, reason = "unknown", "chronology_unresolved"
            elif scope.family == "weight":
                state, reason = (
                    ("quiet", "voluntary_sampling") if facts.confirmed_weight
                    else ("unknown", "never_observed")
                )
            elif scope.family == "activity":
                if success is None:
                    state, reason = "unknown", (
                        "coverage_unknown" if facts.coverage != "complete"
                        else "chronology_unresolved"
                    )
                elif now - success > timedelta(hours=48):
                    state, reason = "stale", "refresh_overdue"
                elif facts.coverage != "complete" or facts.activity_count is None:
                    state, reason = "unknown", "coverage_unknown"
                elif facts.activity_count < 0:
                    state, reason = "unknown", "invalid_chronology"
                elif facts.activity_count:
                    state, reason = "fresh", "evidence_current"
                else:
                    state, reason = "quiet", "event_window_confirmed_empty"
            elif scope.role == "optional" and not facts.observed_once:
                state, reason = "unknown", "never_observed"
            elif success is None:
                state, reason = "unknown", (
                    "chronology_unresolved" if facts.observed_once else "never_observed"
                )
            elif evidence is None and facts.evidence_local_date is None:
                state, reason = "unknown", "never_observed"
            elif evidence is not None and facts.evidence_local_date is not None:
                state, reason = "unknown", "chronology_unresolved"
            elif now - success > timedelta(hours=48):
                state, reason = "stale", "refresh_overdue"
            elif evidence is not None:
                age = now - evidence
                if age <= timedelta(hours=36):
                    state, reason = "fresh", "evidence_current"
                elif age <= timedelta(hours=72):
                    state, reason = "quiet", "evidence_within_grace"
                else:
                    state, reason = "stale", "expected_evidence_absent"
            else:
                days = (evaluation_local_date - facts.evidence_local_date).days
                if days <= 1:
                    state, reason = "fresh", "evidence_current"
                elif days == 2:
                    state, reason = "quiet", "evidence_within_grace"
                else:
                    state, reason = "stale", "expected_evidence_absent"
    result: dict[str, object] = {
        "policy_version": policy_version,
        "evaluated_at_utc": now.isoformat(),
        "evaluation_local_date": evaluation_local_date.isoformat(),
        "scope_key": scope.key,
        "provider": scope.provider,
        "family": scope.family,
        "role": scope.role,
        "state": state,
        "reason_code": reason,
        "actionable": scope.role == "required" and state in {"stale", "unavailable", "unknown"},
        "policy_basis": basis,
        "facts": _fact_block(facts),
    }
    result["result_id"] = _hash(result)
    return result


def _hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True).encode()).hexdigest()


def aggregate(
    results: list[dict[str, object]], *, evaluated_at_utc: datetime,
    evaluation_local_date: date, policy_version: str = POLICY_VERSION,
) -> dict[str, object]:
    ordered = sorted(results, key=lambda item: str(item["scope_key"]))
    providers: dict[str, dict[str, object]] = {}
    priority = ("unavailable", "stale", "unknown", "quiet", "fresh")

    def summary(required: list[dict[str, object]]) -> dict[str, object]:
        active = [r for r in required if r["state"] != "not_requested"]
        state = next((s for s in priority if any(r["state"] == s for r in active)),
                     "not_requested") if required else "unknown"
        return {
            "state": state,
            "required": required,
            "actionable_reasons": [
                {"scope_key": r["scope_key"], "state": r["state"],
                 "reason_code": r["reason_code"]}
                for r in required if r["actionable"]
            ],
        }

    for provider in ("garmin", "google"):
        components = [r for r in ordered if r["provider"] == provider]
        required = [r for r in components if r["role"] == "required"]
        providers[provider] = {
            **summary(required),
            "optional": [r for r in components if r["role"] == "optional"],
        }
    result: dict[str, object] = {
        "policy_version": policy_version,
        "evaluated_at_utc": _utc(evaluated_at_utc).isoformat(),
        "evaluation_local_date": evaluation_local_date.isoformat(),
        "providers": providers,
        "owner": summary([r for r in ordered if r["role"] == "required"]),
        "components": ordered,
    }
    result["result_id"] = _hash(result)
    return result
