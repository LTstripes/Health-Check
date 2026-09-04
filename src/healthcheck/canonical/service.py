"""Persistence service for deterministic R01 canonical selection."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from healthcheck.canonical.dtos import (
    CanonicalCandidate,
    CanonicalExclusionDTO,
    CanonicalRuleSetDTO,
    CanonicalSelectionDTO,
    CanonicalSelectionRunDTO,
)
from healthcheck.canonical.rules import (
    DEFAULT_ANALYTICS_VERSION,
    DEFAULT_RULE_NAME,
    DEFAULT_RULE_VERSION,
    build_selection_plan,
    candidate_content_hash,
    default_rule_definition,
    is_composition_metric,
    selection_reason,
)
from healthcheck.db.models import (
    CanonicalRuleSet,
    CanonicalSelection,
    CanonicalSelectionRun,
    DerivedMeasurement,
    MeasurementSession,
    RunStatus,
    ScalarMeasurement,
)
from healthcheck.db.repositories import (
    build_input_snapshot_hash,
    repositories_for,
)

DASHBOARD_WEIGHT_SCOPE = "r01-weight"
DASHBOARD_COMPOSITION_SCOPE_PREFIX = "r01-composition:"


def dashboard_composition_scope(compatibility_group: str) -> str:
    return f"{DASHBOARD_COMPOSITION_SCOPE_PREFIX}{compatibility_group}"


@dataclass(frozen=True, slots=True)
class CanonicalSelectionResult:
    """Persisted run plus ordered selections and non-fatal exclusions.

    Selection persistence failures are represented by this same typed result
    with ``status == "failed"`` and a sanitized ``failure_reason``.  That
    lets the caller commit the failed audit run through its outer transaction.
    """

    rule_set: CanonicalRuleSet
    run: CanonicalSelectionRun
    selections: tuple[CanonicalSelection, ...]
    exclusions: tuple[CanonicalExclusionDTO, ...] = ()
    replayed: bool = False

    def __post_init__(self) -> None:
        # Repository queries and caller-provided candidate iterables may use
        # different transport order.  Keep the DTO boundary byte-stable for
        # later API/UI consumers as well as for persisted selection rows.
        object.__setattr__(
            self,
            "selections",
            tuple(sorted(self.selections, key=_selection_sort_key)),
        )
        object.__setattr__(
            self,
            "exclusions",
            tuple(sorted(self.exclusions, key=_exclusion_sort_key)),
        )

    @property
    def id(self) -> str:
        return self.run.id

    @property
    def status(self) -> str:
        return self.run.status

    @property
    def input_snapshot_hash(self) -> str:
        return self.run.input_snapshot_hash

    @property
    def failure_reason(self) -> str | None:
        return self.run.failure_reason

    @property
    def run_dto(self) -> CanonicalSelectionRunDTO:
        return canonical_run_dto(self.run)

    @property
    def selection_dtos(self) -> tuple[CanonicalSelectionDTO, ...]:
        return tuple(canonical_selection_dto(item) for item in self.selections)

    @property
    def rule_set_dto(self) -> CanonicalRuleSetDTO:
        return canonical_rule_set_dto(self.rule_set)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run": canonical_run_dto(self.run).as_dict(),
            "rule_set": canonical_rule_set_dto(self.rule_set).as_dict(),
            "selections": [canonical_selection_dto(item).as_dict() for item in self.selections],
            "exclusions": [item.as_dict() for item in self.exclusions],
            "replayed": self.replayed,
        }


class CanonicalSelectionService:
    """Coordinate pure selection rules with the #5 repositories.

    The service flushes but does not commit.  Selection writes are enclosed in
    a savepoint so a failed attempt can roll those writes back while leaving a
    sanitized failed run for the caller's outer transaction to commit.
    """

    def __init__(self, session: Session):
        self.session = session
        self.repositories = repositories_for(session)

    def select(
        self,
        *,
        scope_key: str,
        candidates: Iterable[Any] | None = None,
        metric_code: str | None = None,
        rule_set: CanonicalRuleSet | None = None,
        rule_name: str = DEFAULT_RULE_NAME,
        rule_version: int = DEFAULT_RULE_VERSION,
        rule_definition: Any = None,
        creation_reason: str = "R01-04 canonical selection v1",
        requested_start_date: date | None = None,
        requested_end_date: date | None = None,
        scope: Any = None,
        compatibility_group: str | None = None,
        algorithm_compatibility_group: str | None = None,
        derived_algorithm_version: str | None = DEFAULT_ANALYTICS_VERSION,
        analytics_version: str | None = None,
        software_version: str | None = None,
        build_version: str | None = None,
        supersedes_run_id: str | None = None,
        include_derived: bool = True,
    ) -> CanonicalSelectionResult:
        """Create or replay one deterministic canonical selection run.

        ``candidates=None`` loads current confirmed repository heads.  Passing
        DTO candidates is useful for deterministic unit tests and for a later
        application service that already assembled a bounded evidence scope.
        A changed revision or rule changes the input/rule identity and creates
        a new run whose predecessor is the latest successful run for the same
        scope.  A selection-write failure returns a failed result with no
        persisted selections; the caller's outer transaction owns its commit.
        """

        if algorithm_compatibility_group is not None:
            if compatibility_group is not None and (
                compatibility_group != algorithm_compatibility_group
            ):
                raise ValueError("compatibility_group aliases disagree")
            compatibility_group = algorithm_compatibility_group
        if analytics_version is not None:
            if (
                derived_algorithm_version is not None
                and derived_algorithm_version != DEFAULT_ANALYTICS_VERSION
                and derived_algorithm_version != analytics_version
            ):
                raise ValueError("analytics version aliases disagree")
            derived_algorithm_version = analytics_version
        derived_algorithm_version = _rule_derived_algorithm_version(
            rule_definition,
            rule_set,
            fallback=derived_algorithm_version,
        )
        normalized_metric_code = metric_code.strip() if metric_code is not None else None
        normalized_scope_key = scope_key.strip()
        if not normalized_scope_key:
            raise ValueError("canonical scope key must not be empty")
        if (
            requested_start_date is not None
            and requested_end_date is not None
            and requested_end_date < requested_start_date
        ):
            raise ValueError("canonical requested end date must not precede start date")

        current_exclusions: tuple[CanonicalExclusionDTO, ...] = ()
        if candidates is None:
            candidate_values, current_exclusions = self._current_candidates(
                metric_code=normalized_metric_code,
                start_date=requested_start_date,
                end_date=requested_end_date,
                include_derived=include_derived,
                derived_algorithm_version=derived_algorithm_version,
            )
        else:
            candidate_values = tuple(self._coerce_candidate(value) for value in candidates)
            candidate_values, period_exclusions = _filter_requested_period(
                candidate_values,
                start_date=requested_start_date,
                end_date=requested_end_date,
            )
            current_exclusions += period_exclusions

        selected, plan_exclusions = build_selection_plan(
            candidate_values,
            metric_code=normalized_metric_code,
            compatibility_group=compatibility_group,
            derived_algorithm_version=derived_algorithm_version,
        )
        eligible_for_snapshot = _eligible_snapshot_candidates(
            candidate_values,
            metric_code=normalized_metric_code,
            compatibility_group=compatibility_group,
            derived_algorithm_version=derived_algorithm_version,
        )
        input_snapshot_hash = build_input_snapshot_hash(
            (
                candidate.evidence_id or "",
                candidate.content_hash or candidate_content_hash(candidate),
            )
            for candidate in eligible_for_snapshot
        )
        effective_rule_definition = (
            default_rule_definition() if rule_definition is None else rule_definition
        )
        effective_rule = rule_set or self.repositories.canonical_rule_sets.get_or_create(
            rule_name=rule_name,
            rule_version=rule_version,
            rule_definition=effective_rule_definition,
            creation_reason=creation_reason,
        )
        if rule_set is not None and rule_definition is not None:
            expected_rule_hash = self.repositories.canonical_rule_sets.get_or_create(
                rule_name=rule_set.rule_name,
                rule_version=rule_set.rule_version,
                rule_definition=rule_definition,
                creation_reason=rule_set.creation_reason,
            ).rule_hash
            if expected_rule_hash != rule_set.rule_hash:
                raise ValueError("provided canonical rule_set does not match rule_definition")

        existing = self.repositories.canonical_selection_runs.get_successful(
            scope_key=normalized_scope_key,
            rule_hash=effective_rule.rule_hash,
            input_snapshot_hash=input_snapshot_hash,
        )
        if existing is not None:
            return CanonicalSelectionResult(
                rule_set=effective_rule,
                run=existing,
                selections=tuple(self.repositories.canonical_selections.for_run(existing.id)),
                exclusions=current_exclusions + plan_exclusions,
                replayed=True,
            )

        predecessor_id = supersedes_run_id
        if predecessor_id is None:
            predecessor = self.repositories.canonical_selection_runs.latest_successful(
                normalized_scope_key
            )
            predecessor_id = predecessor.id if predecessor is not None else None
        run, created = self.repositories.canonical_selection_runs.start_or_get(
            scope_key=normalized_scope_key,
            rule_set=effective_rule,
            input_snapshot_hash=input_snapshot_hash,
            requested_start_date=requested_start_date,
            requested_end_date=requested_end_date,
            scope=scope,
            software_version=software_version,
            build_version=build_version,
            supersedes_run_id=predecessor_id,
        )
        if not created:
            return CanonicalSelectionResult(
                rule_set=effective_rule,
                run=run,
                selections=tuple(self.repositories.canonical_selections.for_run(run.id)),
                exclusions=current_exclusions + plan_exclusions,
                replayed=True,
            )

        try:
            with self.session.begin_nested():
                for candidate in selected:
                    self.repositories.canonical_selections.add(
                        selection_run_id=run.id,
                        metric_code=candidate.metric_code,
                        semantic_key=candidate.semantic_key,
                        period_start_date=candidate.period_start_date,
                        period_end_date=candidate.period_end_date,
                        selection_reason=selection_reason(candidate),
                        source_measurement_id=candidate.source_measurement_id,
                        derived_measurement_id=candidate.derived_measurement_id,
                    )
                self.repositories.canonical_selection_runs.finish(
                    run.id,
                    status=RunStatus.SUCCEEDED,
                    selection_count=len(selected),
                )
        except Exception as exc:
            # The savepoint has removed any partial selections.  Return a
            # typed failed result rather than re-raising, so session_scope can
            # commit this durable audit row.  BaseException subclasses still
            # escape and preserve the normal rollback behaviour.
            failed_run = self.repositories.canonical_selection_runs.finish(
                run.id,
                status=RunStatus.FAILED,
                failure_reason=_failure_reason(exc),
            )
            return CanonicalSelectionResult(
                rule_set=effective_rule,
                run=failed_run,
                selections=tuple(self.repositories.canonical_selections.for_run(run.id)),
                exclusions=current_exclusions + plan_exclusions,
                replayed=False,
            )

        return CanonicalSelectionResult(
            rule_set=effective_rule,
            run=run,
            selections=tuple(self.repositories.canonical_selections.for_run(run.id)),
            exclusions=current_exclusions + plan_exclusions,
            replayed=False,
        )

    def select_current(self, **kwargs: Any) -> CanonicalSelectionResult:
        """Explicit alias for selecting repository current heads."""

        kwargs.pop("candidates", None)
        return self.select(candidates=None, **kwargs)

    def recompute(self, **kwargs: Any) -> CanonicalSelectionResult:
        """Run the same scope again after a revision or rule/input change."""

        return self.select(**kwargs)

    def recompute_dashboard(self) -> tuple[CanonicalSelectionResult, ...]:
        """Write-side refresh of the durable R01 dashboard canonical scopes.

        Confirmation and other application writes call this.  Dashboard GET
        paths must not.  Weight is one scope; each composition compatibility
        group is a separate scope so groups are never mixed.

        Previously successful composition scopes are reconsidered even when
        their final evidence was tombstoned, so a newer empty successful run
        can supersede deleted evidence rather than leaving it canonical.
        """

        results = [
            self.select(
                scope_key=DASHBOARD_WEIGHT_SCOPE,
                metric_code="weight",
                include_derived=False,
            )
        ]
        candidates, _exclusions = self._current_candidates(
            metric_code=None,
            start_date=None,
            end_date=None,
            include_derived=False,
            derived_algorithm_version=None,
        )
        groups = {
            candidate.compatibility_group
            for candidate in candidates
            if is_composition_metric(candidate.metric_code) and candidate.compatibility_group
        }
        prefix = DASHBOARD_COMPOSITION_SCOPE_PREFIX
        for scope_key in self.repositories.canonical_selection_runs.successful_scope_keys(
            prefix=prefix
        ):
            group = scope_key[len(prefix) :]
            if group:
                groups.add(group)
        for group in sorted(groups):
            group_candidates = tuple(
                candidate
                for candidate in candidates
                if is_composition_metric(candidate.metric_code)
                and candidate.compatibility_group == group
            )
            results.append(
                self.select(
                    scope_key=dashboard_composition_scope(group),
                    candidates=group_candidates,
                    compatibility_group=group,
                    include_derived=False,
                )
            )
        return tuple(results)

    execute = select
    run = select

    def fail(
        self, run_id: str, *, reason_code: str = "canonical_selection_failed"
    ) -> CanonicalSelectionRun:
        """Mark an in-progress run failed with a sanitized diagnostic code."""

        normalized = reason_code.strip()
        if not normalized or len(normalized) > 120 or not normalized.replace("_", "").isalnum():
            raise ValueError("canonical failure reason must be a short code")
        return self.repositories.canonical_selection_runs.finish(
            run_id,
            status=RunStatus.FAILED,
            failure_reason=normalized,
        )

    def _current_candidates(
        self,
        *,
        metric_code: str | None,
        start_date: date | None,
        end_date: date | None,
        include_derived: bool,
        derived_algorithm_version: str | None,
    ) -> tuple[tuple[CanonicalCandidate, ...], tuple[CanonicalExclusionDTO, ...]]:
        values: list[CanonicalCandidate] = []
        exclusions: list[CanonicalExclusionDTO] = []
        source_measurements = self.repositories.scalar_measurements.current_heads(
            metric_code,
            start_date=start_date,
            end_date=end_date,
        )
        for measurement in source_measurements:
            session = self.repositories.measurement_sessions.get_by_id(
                measurement.measurement_session_id
            )
            algorithm = self.repositories.measurement_algorithms.get_by_id(
                measurement.measurement_algorithm_id
            )
            if session is None or algorithm is None:
                exclusions.append(
                    CanonicalExclusionDTO(
                        evidence_id=measurement.id,
                        metric_code=measurement.metric_code,
                        semantic_key=session.semantic_key if session else None,
                        reason_code="missing_provenance",
                    )
                )
                continue
            if not session.semantic_key:
                exclusions.append(
                    CanonicalExclusionDTO(
                        evidence_id=measurement.id,
                        metric_code=measurement.metric_code,
                        semantic_key=None,
                        reason_code="missing_semantic_key",
                    )
                )
                continue
            values.append(
                CanonicalCandidate(
                    metric_code=measurement.metric_code,
                    semantic_key=session.semantic_key,
                    source_measurement_id=measurement.id,
                    content_hash=_source_content_hash(measurement, session, algorithm),
                    normalized_value=measurement.normalized_value,
                    normalized_unit=measurement.normalized_unit,
                    original_value=measurement.original_value,
                    original_unit=measurement.original_unit,
                    source_local_date=session.source_local_date,
                    source_timestamp_utc=session.source_timestamp_utc,
                    algorithm_code=algorithm.code,
                    algorithm_version=algorithm.version,
                    compatibility_group=algorithm.compatibility_group,
                    revision_number=session.revision_number,
                    created_at=measurement.created_at,
                )
            )

        if include_derived:
            derived_values = self.repositories.derived_measurements.all(metric_code)
            for derived in derived_values:
                candidate, exclusion = self._derived_candidate(
                    derived,
                    start_date=start_date,
                    end_date=end_date,
                    derived_algorithm_version=derived_algorithm_version,
                )
                if candidate is not None:
                    values.append(candidate)
                elif exclusion is not None:
                    exclusions.append(exclusion)
        return tuple(values), tuple(exclusions)

    def _derived_candidate(
        self,
        derived: DerivedMeasurement,
        *,
        start_date: date | None,
        end_date: date | None,
        derived_algorithm_version: str | None,
    ) -> tuple[CanonicalCandidate | None, CanonicalExclusionDTO | None]:
        if (
            derived_algorithm_version is not None
            and derived.algorithm_version != derived_algorithm_version
        ):
            return None, CanonicalExclusionDTO(
                evidence_id=derived.id,
                metric_code=derived.metric_code,
                semantic_key=None,
                reason_code="derivation_version_mismatch",
            )
        if not derived.input_measurement_ids_json:
            return None, CanonicalExclusionDTO(
                evidence_id=derived.id,
                metric_code=derived.metric_code,
                semantic_key=None,
                reason_code="missing_input_evidence",
            )
        try:
            raw_input_ids = json.loads(derived.input_measurement_ids_json)
        except (TypeError, json.JSONDecodeError):
            return None, CanonicalExclusionDTO(
                evidence_id=derived.id,
                metric_code=derived.metric_code,
                semantic_key=None,
                reason_code="malformed_input_evidence",
            )
        if not isinstance(raw_input_ids, list) or not raw_input_ids:
            return None, CanonicalExclusionDTO(
                evidence_id=derived.id,
                metric_code=derived.metric_code,
                semantic_key=None,
                reason_code="missing_input_evidence",
            )
        input_ids = tuple(str(value) for value in raw_input_ids)
        if not all(
            self.repositories.scalar_measurements.is_current_head(value) for value in input_ids
        ):
            return None, CanonicalExclusionDTO(
                evidence_id=derived.id,
                metric_code=derived.metric_code,
                semantic_key=None,
                reason_code="ineligible_input_evidence",
            )
        source_session = None
        if derived.source_session_id is not None:
            source_session = self.repositories.measurement_sessions.get_by_id(
                derived.source_session_id
            )
            if source_session is None or not self.repositories.measurement_sessions.is_current_head(
                derived.source_session_id
            ):
                return None, CanonicalExclusionDTO(
                    evidence_id=derived.id,
                    metric_code=derived.metric_code,
                    semantic_key=None,
                    reason_code="ineligible_source_session",
                )
        source_date = source_session.source_local_date if source_session else None
        if start_date is not None and (source_date is None or source_date < start_date):
            return None, None
        if end_date is not None and (source_date is None or source_date > end_date):
            return None, None
        semantic_key = source_session.semantic_key if source_session else f"derived:{derived.id}"
        if not semantic_key:
            return None, CanonicalExclusionDTO(
                evidence_id=derived.id,
                metric_code=derived.metric_code,
                semantic_key=None,
                reason_code="missing_semantic_key",
            )
        compatibility_group = None
        if derived.parameters_json:
            try:
                parameters = json.loads(derived.parameters_json)
            except (TypeError, json.JSONDecodeError):
                parameters = None
            if isinstance(parameters, Mapping):
                raw_group = parameters.get("compatibility_group")
                if isinstance(raw_group, str):
                    compatibility_group = raw_group
        return (
            CanonicalCandidate(
                metric_code=derived.metric_code,
                semantic_key=semantic_key,
                derived_measurement_id=derived.id,
                content_hash=_derived_content_hash(derived),
                normalized_value=derived.normalized_value,
                normalized_unit=derived.normalized_unit,
                source_local_date=source_date,
                source_timestamp_utc=(
                    source_session.source_timestamp_utc if source_session else None
                ),
                algorithm_code=derived.algorithm_code,
                algorithm_version=derived.algorithm_version,
                compatibility_group=compatibility_group,
                input_measurement_ids=input_ids,
            ),
            None,
        )

    def _coerce_candidate(self, value: Any) -> CanonicalCandidate:
        if isinstance(value, CanonicalCandidate):
            return value
        if isinstance(value, ScalarMeasurement):
            session = self.repositories.measurement_sessions.get_by_id(value.measurement_session_id)
            algorithm = self.repositories.measurement_algorithms.get_by_id(
                value.measurement_algorithm_id
            )
            if session is None or algorithm is None or not session.semantic_key:
                raise ValueError("source candidate lacks canonical provenance")
            return CanonicalCandidate(
                metric_code=value.metric_code,
                semantic_key=session.semantic_key,
                source_measurement_id=value.id,
                content_hash=_source_content_hash(value, session, algorithm),
                normalized_value=value.normalized_value,
                normalized_unit=value.normalized_unit,
                original_value=value.original_value,
                original_unit=value.original_unit,
                source_local_date=session.source_local_date,
                source_timestamp_utc=session.source_timestamp_utc,
                algorithm_code=algorithm.code,
                algorithm_version=algorithm.version,
                compatibility_group=algorithm.compatibility_group,
                revision_number=session.revision_number,
                created_at=value.created_at,
                confirmed=session.confirmation_status == "confirmed",
                current=self.repositories.scalar_measurements.is_current_head(value.id),
            )
        if isinstance(value, DerivedMeasurement):
            candidate, exclusion = self._derived_candidate(
                value,
                start_date=None,
                end_date=None,
                derived_algorithm_version=None,
            )
            if candidate is None:
                raise ValueError(
                    exclusion.reason_code if exclusion else "derived candidate excluded"
                )
            return candidate
        if isinstance(value, Mapping):
            data = dict(value)
            if "evidence_id" not in data and "id" in data:
                data["evidence_id"] = data.pop("id")
            return CanonicalCandidate(**data)
        raise TypeError(f"unsupported canonical candidate type: {type(value).__name__}")


def canonical_rule_set_dto(rule_set: CanonicalRuleSet) -> CanonicalRuleSetDTO:
    return CanonicalRuleSetDTO(
        rule_name=rule_set.rule_name,
        rule_version=rule_set.rule_version,
        rule_definition_json=rule_set.rule_definition_json,
        rule_hash=rule_set.rule_hash,
        effective_start_date=rule_set.effective_start_date,
        effective_end_date=rule_set.effective_end_date,
        creation_reason=rule_set.creation_reason,
    )


def canonical_selection_dto(selection: CanonicalSelection) -> CanonicalSelectionDTO:
    return CanonicalSelectionDTO(
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


def canonical_run_dto(run: CanonicalSelectionRun) -> CanonicalSelectionRunDTO:
    return CanonicalSelectionRunDTO(
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


def _selection_sort_key(selection: CanonicalSelection) -> tuple[Any, ...]:
    return (
        selection.metric_code,
        selection.semantic_key,
        selection.period_start_date or date.min,
        selection.period_end_date or date.min,
        selection.source_measurement_id or "",
        selection.derived_measurement_id or "",
        selection.id,
    )


def _exclusion_sort_key(exclusion: CanonicalExclusionDTO) -> tuple[str, str, str, str]:
    return (
        exclusion.metric_code or "",
        exclusion.semantic_key or "",
        exclusion.evidence_id or "",
        exclusion.reason_code,
    )


def _eligible_snapshot_candidates(
    candidates: Iterable[CanonicalCandidate],
    *,
    metric_code: str | None,
    compatibility_group: str | None,
    derived_algorithm_version: str | None,
) -> tuple[CanonicalCandidate, ...]:
    normalized_metric = metric_code.strip() if metric_code is not None else None
    normalized_group = compatibility_group.strip() if compatibility_group else None
    values = []
    for candidate in candidates:
        if not candidate.confirmed or not candidate.current:
            continue
        if normalized_metric is not None and candidate.metric_code != normalized_metric:
            continue
        if (
            is_composition_metric(candidate.metric_code)
            and candidate.compatibility_group != normalized_group
        ):
            continue
        if candidate.is_derived:
            if not candidate.input_measurement_ids:
                continue
            if (
                derived_algorithm_version is not None
                and candidate.algorithm_version != derived_algorithm_version
            ):
                continue
        values.append(candidate)
    return tuple(values)


def _filter_requested_period(
    candidates: Iterable[CanonicalCandidate],
    *,
    start_date: date | None,
    end_date: date | None,
) -> tuple[tuple[CanonicalCandidate, ...], tuple[CanonicalExclusionDTO, ...]]:
    if start_date is None and end_date is None:
        return tuple(candidates), ()
    values: list[CanonicalCandidate] = []
    exclusions: list[CanonicalExclusionDTO] = []
    for candidate in candidates:
        candidate_date = candidate.source_local_date
        if candidate_date is None:
            exclusions.append(
                CanonicalExclusionDTO(
                    evidence_id=candidate.evidence_id,
                    metric_code=candidate.metric_code,
                    semantic_key=candidate.semantic_key,
                    reason_code="missing_period_date",
                )
            )
            continue
        if start_date is not None and candidate_date < start_date:
            exclusions.append(_period_exclusion(candidate))
            continue
        if end_date is not None and candidate_date > end_date:
            exclusions.append(_period_exclusion(candidate))
            continue
        values.append(candidate)
    return tuple(values), tuple(exclusions)


def _period_exclusion(candidate: CanonicalCandidate) -> CanonicalExclusionDTO:
    return CanonicalExclusionDTO(
        evidence_id=candidate.evidence_id,
        metric_code=candidate.metric_code,
        semantic_key=candidate.semantic_key,
        reason_code="outside_requested_period",
    )


def _source_content_hash(
    measurement: ScalarMeasurement,
    session: MeasurementSession,
    algorithm: Any,
) -> str:
    candidate = CanonicalCandidate(
        metric_code=measurement.metric_code,
        semantic_key=session.semantic_key or measurement.id,
        source_measurement_id=measurement.id,
        normalized_value=measurement.normalized_value,
        normalized_unit=measurement.normalized_unit,
        original_value=measurement.original_value,
        original_unit=measurement.original_unit,
        source_local_date=session.source_local_date,
        source_timestamp_utc=session.source_timestamp_utc,
        algorithm_code=algorithm.code,
        algorithm_version=algorithm.version,
        compatibility_group=algorithm.compatibility_group,
        revision_number=session.revision_number,
    )
    return candidate_content_hash(candidate)


def _derived_content_hash(derived: DerivedMeasurement) -> str:
    payload = {
        "metric_code": derived.metric_code,
        "normalized_value": derived.normalized_value,
        "normalized_unit": derived.normalized_unit,
        "algorithm_code": derived.algorithm_code,
        "algorithm_version": derived.algorithm_version,
        "parameters_json": derived.parameters_json,
        "input_measurement_ids_json": derived.input_measurement_ids_json,
        "input_set_hash": derived.input_set_hash,
        "source_session_id": derived.source_session_id,
    }
    from hashlib import sha256

    from healthcheck.db.repositories import canonical_json

    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _failure_reason(exc: Exception) -> str:
    if isinstance(exc, KeyError):
        return "canonical_selection_reference_missing"
    if isinstance(exc, ValueError):
        return "canonical_selection_validation_failed"
    return "canonical_selection_failed"


def _rule_derived_algorithm_version(
    rule_definition: Any,
    rule_set: CanonicalRuleSet | None,
    *,
    fallback: str | None,
) -> str | None:
    """Read an explicit derived-version requirement from a custom rule."""

    definition = rule_definition
    if definition is None and rule_set is not None:
        try:
            definition = json.loads(rule_set.rule_definition_json)
        except (TypeError, json.JSONDecodeError):
            definition = None
    if isinstance(definition, Mapping):
        derived = definition.get("derived")
        if isinstance(derived, Mapping):
            for key in ("requires_algorithm_version", "algorithm_version"):
                value = derived.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        for key in ("derived_algorithm_version", "analytics_version"):
            value = definition.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return fallback


# Public aliases used by application-layer callers.
CanonicalService = CanonicalSelectionService
CanonicalRunResult = CanonicalSelectionResult


__all__ = [
    "DASHBOARD_COMPOSITION_SCOPE_PREFIX",
    "DASHBOARD_WEIGHT_SCOPE",
    "CanonicalRunResult",
    "CanonicalSelectionResult",
    "CanonicalSelectionService",
    "CanonicalService",
    "canonical_rule_set_dto",
    "canonical_run_dto",
    "canonical_selection_dto",
    "dashboard_composition_scope",
]
