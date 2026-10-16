"""Bounded exact-source choice after metric/window eligibility, never pooling.

Readers own eligibility, units, dates, family exclusions and work limits. This
shared decision is the Sleep discovery rule: a unique usable candidate may be
selected only after every source was examined. An ambiguous-only source still
competes. Neither matching values nor source ordering establishes lineage.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceCandidate:
    source: Any
    payload: dict
    eligible_count: int
    ambiguous_count: int = 0
    complete: bool = True
    reason: str | None = None


@dataclass(frozen=True)
class SourceSelection:
    state: str
    candidates: tuple[SourceCandidate, ...]
    chosen: SourceCandidate | None = None
    reason: str | None = None


def select_metric_source(sources, read_candidate, *, requested=None, source_cap=32):
    """Caller supplies a complete capped inventory, or just the exact override.

    No prefix is selected on any reader limit. Per-source payloads stay separate
    for bounded disclosure; consumers never combine their observations.
    """
    if len(sources) > source_cap:
        return SourceSelection("search_incomplete", (), reason="source_inventory_cap")
    candidates = []
    for source in sources:
        candidate = read_candidate(source)
        candidates.append(candidate)
        if not candidate.complete:
            return SourceSelection("search_incomplete", tuple(candidates), reason=candidate.reason)
    candidates = tuple(candidates)
    if requested is not None:
        exact = next((c for c in candidates if c.source.id == requested), None)
        return SourceSelection("explicit" if exact else "source_missing", candidates, exact)
    competing = [c for c in candidates if c.eligible_count or c.ambiguous_count]
    if len(competing) == 1 and competing[0].eligible_count:
        return SourceSelection("unique_eligible_source", candidates, competing[0])
    return SourceSelection(
        ("selection_required" if competing
         else "no_eligible_values" if sources else "source_missing"),
        candidates,
    )
