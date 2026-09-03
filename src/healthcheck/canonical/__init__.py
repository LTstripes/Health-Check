"""R01-04 canonical selection public surface."""

from healthcheck.canonical.dtos import (
    CanonicalCandidate,
    CanonicalExclusionDTO,
    CanonicalRuleSetDTO,
    CanonicalSelectionDTO,
    CanonicalSelectionRunDTO,
)
from healthcheck.canonical.rules import (
    COMPOSITION_METRICS,
    DEFAULT_ANALYTICS_VERSION,
    DEFAULT_RULE_DEFINITION,
    DEFAULT_RULE_NAME,
    DEFAULT_RULE_VERSION,
    build_selection_plan,
    candidate_content_hash,
    default_rule_definition,
    is_composition_metric,
    select_canonical_candidates,
    selection_reason,
)
from healthcheck.canonical.service import (
    CanonicalRunResult,
    CanonicalSelectionResult,
    CanonicalSelectionService,
    CanonicalService,
    canonical_rule_set_dto,
    canonical_run_dto,
    canonical_selection_dto,
)

__all__ = [
    "COMPOSITION_METRICS",
    "DEFAULT_ANALYTICS_VERSION",
    "DEFAULT_RULE_DEFINITION",
    "DEFAULT_RULE_NAME",
    "DEFAULT_RULE_VERSION",
    "CanonicalCandidate",
    "CanonicalExclusionDTO",
    "CanonicalRuleSetDTO",
    "CanonicalSelectionDTO",
    "CanonicalSelectionRunDTO",
    "CanonicalSelectionResult",
    "CanonicalSelectionService",
    "CanonicalService",
    "CanonicalRunResult",
    "build_selection_plan",
    "candidate_content_hash",
    "canonical_rule_set_dto",
    "canonical_run_dto",
    "canonical_selection_dto",
    "default_rule_definition",
    "is_composition_metric",
    "select_canonical_candidates",
    "selection_reason",
]
