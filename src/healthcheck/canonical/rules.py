"""Pure deterministic canonical-selection rules for R01-04."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, date
from typing import Any

from healthcheck.canonical.dtos import CanonicalCandidate, CanonicalExclusionDTO
from healthcheck.db.repositories import canonical_json

DEFAULT_RULE_NAME = "r01-canonical-v1"
DEFAULT_RULE_VERSION = 1
DEFAULT_ANALYTICS_VERSION = "v1"

# R01 composition metrics are source/formula dependent.  The set is
# intentionally explicit: an unknown future metric is not silently treated as
# compatible composition data.
COMPOSITION_METRICS = frozenset(
    {
        "body_fat",
        "body_fat_pct",
        "body_fat_percentage",
        "body_water",
        "muscle_mass_kg",
        "muscle_mass",
        "body_water_pct",
        "fat_mass_kg",
        "lean_mass_kg",
        "visceral_fat",
        "visceral_fat_index",
        "bone_mass_kg",
        "protein_pct",
    }
)


def default_rule_definition() -> dict[str, Any]:
    """Return a fresh, serializable copy of the R01 canonical rule."""

    return {
        "rule": "canonical_selection",
        "version": 1,
        "eligible": ["confirmed", "current_head"],
        "weight": {"selection": "latest_confirmed_revision_per_semantic_key"},
        "composition": {
            "requires_compatibility_group": True,
            "cross_group": "reject",
        },
        "derived": {
            "requires_current_inputs": True,
            "requires_algorithm_version": DEFAULT_ANALYTICS_VERSION,
        },
    }


def is_composition_metric(metric_code: str) -> bool:
    return metric_code.strip() in COMPOSITION_METRICS


def candidate_content_hash(candidate: CanonicalCandidate) -> str:
    """Hash semantic evidence content without receive-time or database noise."""

    timestamp = candidate.source_timestamp_utc
    if timestamp is not None:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            # SQLite reloads DateTime(timezone=True) as a naive value.  The
            # repository only accepts aware UTC input before persistence, so
            # reattach UTC for a stable cross-session hash.
            timestamp = timestamp.replace(tzinfo=UTC)
        else:
            timestamp = timestamp.astimezone(UTC)
    payload = {
        "metric_code": candidate.metric_code,
        "semantic_key": candidate.semantic_key,
        "source_measurement_id": candidate.source_measurement_id,
        "derived_measurement_id": candidate.derived_measurement_id,
        "normalized_value": candidate.normalized_value,
        "normalized_unit": candidate.normalized_unit,
        "original_value": candidate.original_value,
        "original_unit": candidate.original_unit,
        "period_start_date": _date_text(candidate.period_start_date),
        "period_end_date": _date_text(candidate.period_end_date),
        "source_local_date": _date_text(candidate.source_local_date),
        "source_timestamp_utc": timestamp.isoformat() if timestamp else None,
        "algorithm_code": candidate.algorithm_code,
        "algorithm_version": candidate.algorithm_version,
        "compatibility_group": candidate.compatibility_group,
        "revision_number": candidate.revision_number,
        "input_measurement_ids": list(candidate.input_measurement_ids),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def build_selection_plan(
    candidates: Iterable[CanonicalCandidate],
    *,
    metric_code: str | None = None,
    compatibility_group: str | None = None,
    derived_algorithm_version: str | None = DEFAULT_ANALYTICS_VERSION,
) -> tuple[tuple[CanonicalCandidate, ...], tuple[CanonicalExclusionDTO, ...]]:
    """Filter and deterministically reduce evidence to canonical selections.

    The function is deliberately framework-free.  It accepts immutable DTOs,
    preserves every losing candidate in the exclusion metadata, and never
    uses insertion/receive order as a tie breaker.
    """

    normalized_metric = metric_code.strip() if metric_code is not None else None
    normalized_group = compatibility_group.strip() if compatibility_group else None
    if normalized_metric is not None and is_composition_metric(normalized_metric):
        if normalized_group is None:
            raise ValueError(
                "composition canonical selection requires an explicit compatibility_group"
            )
    selected_candidates: list[CanonicalCandidate] = []
    exclusions: list[CanonicalExclusionDTO] = []
    for candidate in candidates:
        if normalized_metric is not None and candidate.metric_code != normalized_metric:
            continue
        if not candidate.confirmed:
            exclusions.append(_exclusion(candidate, "not_confirmed"))
            continue
        if not candidate.current:
            exclusions.append(_exclusion(candidate, "superseded"))
            continue
        if is_composition_metric(candidate.metric_code):
            if normalized_group is None:
                raise ValueError(
                    "composition canonical selection requires an explicit compatibility_group"
                )
            if candidate.compatibility_group != normalized_group:
                exclusions.append(_exclusion(candidate, "incompatible_algorithm_group"))
                continue
        if candidate.is_derived:
            if not candidate.input_measurement_ids:
                exclusions.append(_exclusion(candidate, "missing_input_evidence"))
                continue
            if (
                derived_algorithm_version is not None
                and candidate.algorithm_version != derived_algorithm_version
            ):
                exclusions.append(_exclusion(candidate, "derivation_version_mismatch"))
                continue
        selected_candidates.append(candidate)

    # One canonical row is allowed per semantic key in a run.  A source can
    # have the same key as another source; use source-time/revision and then
    # the immutable evidence ID for a stable, explainable tie break.
    by_key: dict[tuple[str, str], CanonicalCandidate] = {}
    for candidate in selected_candidates:
        key = (candidate.metric_code, candidate.semantic_key)
        existing = by_key.get(key)
        if existing is None or _candidate_rank(candidate) > _candidate_rank(existing):
            if existing is not None:
                exclusions.append(_exclusion(existing, "competing_evidence"))
            by_key[key] = candidate
        else:
            exclusions.append(_exclusion(candidate, "competing_evidence"))

    ordered = tuple(
        sorted(
            by_key.values(),
            key=lambda candidate: (
                candidate.metric_code,
                candidate.semantic_key,
                candidate.evidence_id or "",
            ),
        )
    )
    return ordered, tuple(exclusions)


def select_canonical_candidates(
    candidates: Iterable[CanonicalCandidate],
    *,
    metric_code: str | None = None,
    compatibility_group: str | None = None,
    derived_algorithm_version: str | None = DEFAULT_ANALYTICS_VERSION,
) -> tuple[CanonicalCandidate, ...]:
    """Convenience wrapper returning only the deterministic selected values."""

    selected, _exclusions = build_selection_plan(
        candidates,
        metric_code=metric_code,
        compatibility_group=compatibility_group,
        derived_algorithm_version=derived_algorithm_version,
    )
    return selected


def selection_reason(candidate: CanonicalCandidate) -> str:
    if candidate.is_derived:
        return "r01-canonical-v1:eligible-derived-current-inputs"
    if is_composition_metric(candidate.metric_code):
        return f"r01-canonical-v1:latest-confirmed-revision:{candidate.compatibility_group}"
    return "r01-canonical-v1:latest-confirmed-revision"


def _candidate_rank(candidate: CanonicalCandidate) -> tuple[Any, ...]:
    timestamp = candidate.source_timestamp_utc
    if timestamp is None:
        timestamp_key = ""
    else:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        else:
            timestamp = timestamp.astimezone(UTC)
        timestamp_key = timestamp.isoformat()
    return (
        candidate.revision_number,
        timestamp_key,
        candidate.source_local_date or date.min,
        0 if candidate.is_derived else 1,
        candidate.evidence_id or "",
    )


def _exclusion(candidate: CanonicalCandidate, reason_code: str) -> CanonicalExclusionDTO:
    return CanonicalExclusionDTO(
        evidence_id=candidate.evidence_id,
        metric_code=candidate.metric_code,
        semantic_key=candidate.semantic_key,
        reason_code=reason_code,
    )


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


__all__ = [
    "COMPOSITION_METRICS",
    "DEFAULT_ANALYTICS_VERSION",
    "DEFAULT_RULE_DEFINITION",
    "DEFAULT_RULE_NAME",
    "DEFAULT_RULE_VERSION",
    "build_selection_plan",
    "candidate_content_hash",
    "default_rule_definition",
    "is_composition_metric",
    "select_canonical_candidates",
    "selection_reason",
]


DEFAULT_RULE_DEFINITION = default_rule_definition()
