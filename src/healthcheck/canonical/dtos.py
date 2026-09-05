"""Small transport-neutral DTOs for canonical evidence and selection results.

The database models remain persistence entities.  These immutable records are
the boundary consumed by later analytics and UI code, so callers do not need
to pass SQLAlchemy objects into pure selection logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class CanonicalCandidate:
    """One immutable source or derived value eligible for canonical selection."""

    metric_code: str
    semantic_key: str
    source_measurement_id: str | None = None
    derived_measurement_id: str | None = None
    evidence_id: str | None = None
    content_hash: str | None = None
    normalized_value: float | None = None
    normalized_unit: str | None = None
    original_value: str | None = None
    original_unit: str | None = None
    period_start_date: date | None = None
    period_end_date: date | None = None
    source_local_date: date | None = None
    source_timestamp_utc: datetime | None = None
    algorithm_code: str | None = None
    algorithm_version: str | None = None
    compatibility_group: str | None = None
    revision_number: int = 1
    created_at: datetime | None = None
    confirmed: bool = True
    current: bool = True
    input_measurement_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("period_start_date", "period_end_date", "source_local_date"):
            value = getattr(self, field_name)
            if isinstance(value, str):
                object.__setattr__(self, field_name, date.fromisoformat(value[:10]))
        timestamp = self.source_timestamp_utc
        if isinstance(timestamp, str):
            object.__setattr__(
                self,
                "source_timestamp_utc",
                datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
            )
        metric_code = self.metric_code.strip()
        semantic_key = self.semantic_key.strip()
        if not metric_code:
            raise ValueError("canonical candidate metric_code must not be empty")
        if not semantic_key:
            raise ValueError("canonical candidate semantic_key must not be empty")
        source_id = self.source_measurement_id
        derived_id = self.derived_measurement_id
        if source_id is None and derived_id is None and self.evidence_id is not None:
            source_id = self.evidence_id
        if (source_id is None) == (derived_id is None):
            raise ValueError("canonical candidate must reference exactly one evidence entity")
        if self.evidence_id is not None and self.evidence_id not in {source_id, derived_id}:
            raise ValueError("canonical candidate evidence_id disagrees with its entity reference")
        if self.revision_number < 1:
            raise ValueError("canonical candidate revision_number must be positive")
        if self.period_start_date is not None and self.period_end_date is not None:
            if self.period_end_date < self.period_start_date:
                raise ValueError("canonical candidate period end must not precede start")
        normalized_inputs = tuple(
            sorted({str(value) for value in (self.input_measurement_ids or ())})
        )
        object.__setattr__(self, "metric_code", metric_code)
        object.__setattr__(self, "semantic_key", semantic_key)
        object.__setattr__(self, "source_measurement_id", source_id)
        object.__setattr__(self, "derived_measurement_id", derived_id)
        object.__setattr__(self, "evidence_id", source_id or derived_id)
        object.__setattr__(
            self, "content_hash", self.content_hash.lower() if self.content_hash else None
        )
        if self.normalized_unit is not None:
            object.__setattr__(self, "normalized_unit", self.normalized_unit.strip())
        object.__setattr__(
            self,
            "compatibility_group",
            self.compatibility_group.strip() if self.compatibility_group else None,
        )
        object.__setattr__(self, "input_measurement_ids", normalized_inputs)

    @property
    def is_derived(self) -> bool:
        return self.derived_measurement_id is not None

    @property
    def is_current(self) -> bool:
        return self.current

    @property
    def algorithm_compatibility_group(self) -> str | None:
        return self.compatibility_group

    @property
    def id(self) -> str:
        if self.evidence_id is None:
            raise RuntimeError("canonical candidate has no evidence reference")
        return self.evidence_id

    @property
    def algorithm_identity(self) -> str | None:
        if self.algorithm_code is None and self.algorithm_version is None:
            return None
        return f"{self.algorithm_code or ''}@{self.algorithm_version or ''}"


@dataclass(frozen=True, slots=True)
class CanonicalRuleSetDTO:
    rule_name: str
    rule_version: int
    rule_definition_json: str
    rule_hash: str
    effective_start_date: date | None = None
    effective_end_date: date | None = None
    creation_reason: str = ""

    @classmethod
    def from_model(cls, rule_set: Any) -> CanonicalRuleSetDTO:
        return cls(
            rule_name=rule_set.rule_name,
            rule_version=rule_set.rule_version,
            rule_definition_json=rule_set.rule_definition_json,
            rule_hash=rule_set.rule_hash,
            effective_start_date=rule_set.effective_start_date,
            effective_end_date=rule_set.effective_end_date,
            creation_reason=rule_set.creation_reason,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_name": self.rule_name,
            "rule_version": self.rule_version,
            "rule_definition_json": self.rule_definition_json,
            "rule_hash": self.rule_hash,
            "effective_start_date": self.effective_start_date.isoformat()
            if self.effective_start_date
            else None,
            "effective_end_date": self.effective_end_date.isoformat()
            if self.effective_end_date
            else None,
            "creation_reason": self.creation_reason,
        }


@dataclass(frozen=True, slots=True)
class CanonicalSelectionDTO:
    id: str
    selection_run_id: str
    metric_code: str
    semantic_key: str
    period_start_date: date | None
    period_end_date: date | None
    source_measurement_id: str | None
    derived_measurement_id: str | None
    selection_reason: str

    @property
    def evidence_id(self) -> str:
        evidence_id = self.source_measurement_id or self.derived_measurement_id
        if evidence_id is None:
            raise RuntimeError("canonical selection has no evidence reference")
        return evidence_id

    @classmethod
    def from_model(cls, selection: Any) -> CanonicalSelectionDTO:
        return cls(
            id=selection.id,
            selection_run_id=selection.selection_run_id,
            metric_code=selection.metric_code,
            semantic_key=selection.semantic_key,
            period_start_date=selection.period_start_date,
            period_end_date=selection.period_end_date,
            source_measurement_id=selection.source_measurement_id,
            derived_measurement_id=selection.derived_measurement_id,
            selection_reason=selection.selection_reason,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "selection_run_id": self.selection_run_id,
            "metric_code": self.metric_code,
            "semantic_key": self.semantic_key,
            "period_start_date": self.period_start_date.isoformat()
            if self.period_start_date
            else None,
            "period_end_date": self.period_end_date.isoformat() if self.period_end_date else None,
            "source_measurement_id": self.source_measurement_id,
            "derived_measurement_id": self.derived_measurement_id,
            "selection_reason": self.selection_reason,
        }


@dataclass(frozen=True, slots=True)
class CanonicalSelectionRunDTO:
    id: str
    scope_key: str
    requested_start_date: date | None
    requested_end_date: date | None
    rule_name: str
    rule_version: int
    rule_hash: str
    input_snapshot_hash: str
    status: str
    selection_count: int | None
    failure_reason: str | None
    supersedes_run_id: str | None
    started_at: datetime | None
    completed_at: datetime | None

    @property
    def run_id(self) -> str:
        return self.id

    @classmethod
    def from_model(cls, run: Any) -> CanonicalSelectionRunDTO:
        return cls(
            id=run.id,
            scope_key=run.scope_key,
            requested_start_date=run.requested_start_date,
            requested_end_date=run.requested_end_date,
            rule_name=run.rule_name,
            rule_version=run.rule_version,
            rule_hash=run.rule_hash,
            input_snapshot_hash=run.input_snapshot_hash,
            status=run.status,
            selection_count=run.selection_count,
            failure_reason=run.failure_reason,
            supersedes_run_id=run.supersedes_run_id,
            started_at=run.started_at,
            completed_at=run.completed_at,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scope_key": self.scope_key,
            "requested_start_date": self.requested_start_date.isoformat()
            if self.requested_start_date
            else None,
            "requested_end_date": self.requested_end_date.isoformat()
            if self.requested_end_date
            else None,
            "rule_name": self.rule_name,
            "rule_version": self.rule_version,
            "rule_hash": self.rule_hash,
            "input_snapshot_hash": self.input_snapshot_hash,
            "status": self.status,
            "selection_count": self.selection_count,
            "failure_reason": self.failure_reason,
            "supersedes_run_id": self.supersedes_run_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass(frozen=True, slots=True)
class CanonicalExclusionDTO:
    evidence_id: str | None
    metric_code: str | None
    semantic_key: str | None
    reason_code: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "metric_code": self.metric_code,
            "semantic_key": self.semantic_key,
            "reason_code": self.reason_code,
        }


__all__ = [
    "CanonicalCandidate",
    "CanonicalExclusionDTO",
    "CanonicalRuleSetDTO",
    "CanonicalSelectionDTO",
    "CanonicalSelectionRunDTO",
]
