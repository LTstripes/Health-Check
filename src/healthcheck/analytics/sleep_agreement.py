"""Immutable R05 agreement-run persistence and historical replay.

The pairing and metric readers remain read-only.  This module is the bounded
bridge that freezes their complete result into additive ``agreement_*`` rows.
Replay reads only those rows; it never consults mutable current Garmin or
Google projections.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from healthcheck.analytics.sleep_metrics import (
    R05_SLEEP_METRIC_PROJECTION_CONTRACT_VERSION,
    SleepMetricProjectionResult,
)
from healthcheck.analytics.sleep_pairing import R05_SLEEP_PAIRING_CONTRACT_VERSION
from healthcheck.db.models import AgreementRun, RunStatus
from healthcheck.db.repositories import AgreementRunRepository, canonical_json
from healthcheck.garmin.analytic_contract import stable_manifest_hash

R05_SLEEP_AGREEMENT_CONTRACT_VERSION = "r05-03-sleep-agreement-run-v1"
R05_SLEEP_AGREEMENT_RULE_NAME = "r05-sleep-agreement"
R05_SLEEP_AGREEMENT_RULE_VERSION = "r05-03-sleep-agreement-rules-v1"
R05_SLEEP_AGREEMENT_STATISTIC_VERSION = "r05-03-sleep-statistics-contract-v1"
R05_SLEEP_AGREEMENT_ALGORITHM = R05_SLEEP_AGREEMENT_CONTRACT_VERSION


def _required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _variant_key(variant: str | None) -> str:
    return "__none__" if variant is None else _required_text(variant, "metric variant")


def _window_key(start: date | None, end: date | None) -> str:
    return f"{start.isoformat() if start else '*'}:{end.isoformat() if end else '*'}"


def _decode_json(value: str, field_name: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"persisted agreement {field_name} is malformed") from exc


@dataclass(frozen=True, slots=True)
class AgreementPersistenceResult:
    """Result of creating or finding one semantically idempotent run."""

    run: AgreementRun
    created: bool

    @property
    def id(self) -> str:
        return self.run.id

    @property
    def input_snapshot_hash(self) -> str:
        return self.run.input_snapshot_hash

    @property
    def status(self) -> str:
        return self.run.status


@dataclass(frozen=True, slots=True)
class AgreementReplay:
    """Frozen run contents reconstructed without reading current source rows."""

    run: AgreementRun
    snapshot: Mapping[str, Any]
    pairs: tuple[Mapping[str, Any], ...]
    exclusions: tuple[Mapping[str, Any], ...]
    metric_results: tuple[Mapping[str, Any], ...]
    coverage: tuple[Mapping[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": R05_SLEEP_AGREEMENT_CONTRACT_VERSION,
            "run_id": self.run.id,
            "status": self.run.status,
            "input_snapshot_hash": self.run.input_snapshot_hash,
            "snapshot": dict(self.snapshot),
            "pairs": [dict(item) for item in self.pairs],
            "exclusions": [dict(item) for item in self.exclusions],
            "metric_results": [dict(item) for item in self.metric_results],
            "coverage": [dict(item) for item in self.coverage],
        }


class PersistedSleepAgreementService:
    """Persist #101's complete projection as one immutable R05 agreement run."""

    def __init__(self, session: Session):
        self.session = session
        self.repository = AgreementRunRepository(session)

    def persist(
        self,
        projection: SleepMetricProjectionResult,
        *,
        scope_key: str,
        statistic_version: str | None = None,
        stat_version: str | None = None,
        pairing_version: str = R05_SLEEP_PAIRING_CONTRACT_VERSION,
        metric_version: str = R05_SLEEP_METRIC_PROJECTION_CONTRACT_VERSION,
        rule_name: str = R05_SLEEP_AGREEMENT_RULE_NAME,
        rule_version: str = R05_SLEEP_AGREEMENT_RULE_VERSION,
        rule_definition: Mapping[str, Any] | None = None,
        epoch_id: str = "unknown",
        epoch_basis: Mapping[str, Any] | None = None,
        supersedes_run_id: str | None = None,
    ) -> AgreementPersistenceResult:
        """Freeze a projection, returning an existing success on exact replay."""

        if statistic_version is not None and stat_version is not None:
            if statistic_version != stat_version:
                raise ValueError("statistic_version and stat_version disagree")
        normalized_statistic_version = _required_text(
            statistic_version or stat_version or R05_SLEEP_AGREEMENT_STATISTIC_VERSION,
            "agreement statistic version",
        )
        normalized_scope = _required_text(scope_key, "agreement scope key")
        normalized_pairing = _required_text(pairing_version, "agreement pairing version")
        normalized_metric = _required_text(metric_version, "agreement metric version")
        normalized_rule_name = _required_text(rule_name, "agreement rule name")
        normalized_rule_version = _required_text(rule_version, "agreement rule version")
        normalized_epoch = _required_text(epoch_id, "agreement epoch id")
        query = projection.query
        cohort = _required_text(query.cohort, "agreement cohort")
        window_key = _window_key(query.start_date, query.end_date)
        epoch_body: Mapping[str, Any] = epoch_basis or {"status": "unknown"}
        definition = rule_definition or {
            "contract_version": R05_SLEEP_AGREEMENT_CONTRACT_VERSION,
            "rule_name": normalized_rule_name,
            "rule_version": normalized_rule_version,
        }

        snapshot: dict[str, Any] = {
            "contract_version": R05_SLEEP_AGREEMENT_CONTRACT_VERSION,
            "algorithm": R05_SLEEP_AGREEMENT_ALGORITHM,
            "scope_key": normalized_scope,
            "requested_window": {
                "start_date": query.start_date.isoformat() if query.start_date else None,
                "end_date": query.end_date.isoformat() if query.end_date else None,
                "window_key": window_key,
            },
            "cohort": cohort,
            "versions": {
                "pairing": normalized_pairing,
                "metric": normalized_metric,
                "statistic": normalized_statistic_version,
                "rule_name": normalized_rule_name,
                "rule": normalized_rule_version,
            },
            "epoch": {"id": normalized_epoch, "basis": dict(epoch_body)},
            "rule_definition": dict(definition),
            "projection": projection.as_dict(),
        }
        input_snapshot_hash = stable_manifest_hash(snapshot)
        identity_body = {
            "scope_key": normalized_scope,
            "window_key": window_key,
            "cohort": cohort,
            "pairing_version": normalized_pairing,
            "metric_version": normalized_metric,
            "statistic_version": normalized_statistic_version,
            "rule_name": normalized_rule_name,
            "rule_version": normalized_rule_version,
            "epoch_id": normalized_epoch,
            "input_snapshot_hash": input_snapshot_hash,
        }
        identity_hash = stable_manifest_hash(identity_body)
        lineage_key = stable_manifest_hash(
            {
                key: identity_body[key]
                for key in (
                    "scope_key",
                    "window_key",
                    "cohort",
                    "pairing_version",
                    "metric_version",
                    "statistic_version",
                    "rule_name",
                    "rule_version",
                    "epoch_id",
                )
            }
        )
        rule_set = self.repository.get_or_create_rule_set(
            rule_name=normalized_rule_name,
            rule_version=normalized_rule_version,
            definition=definition,
        )
        run, created = self.repository.start_or_get(
            scope_key=normalized_scope,
            scope_lineage_key=lineage_key,
            window_key=window_key,
            requested_start_date=query.start_date,
            requested_end_date=query.end_date,
            cohort=cohort,
            pairing_version=normalized_pairing,
            metric_version=normalized_metric,
            statistic_version=normalized_statistic_version,
            rule_set=rule_set,
            rule_version=normalized_rule_version,
            epoch_id=normalized_epoch,
            epoch_basis_json=canonical_json(epoch_body),
            input_snapshot_hash=input_snapshot_hash,
            input_snapshot_json=canonical_json(snapshot),
            coverage_json=canonical_json([item.as_dict() for item in projection.coverage]),
            identity_hash=identity_hash,
            supersedes_run_id=supersedes_run_id,
        )
        if not created:
            return AgreementPersistenceResult(run=run, created=False)

        pair_rows: dict[tuple[date, str, str, str], Any] = {}
        for ordinal, pair in enumerate(projection.pairing.pairs):
            pair_dict = pair.as_dict()
            pair_key = ":".join(
                (
                    pair.wake_date.isoformat(),
                    pair.cohort,
                    pair.garmin_record_id,
                    pair.google_record_id,
                )
            )
            pair_row = self.repository.add_pair(
                run_id=run.id,
                values={
                    "ordinal": ordinal,
                    "pair_key": pair_key,
                    "wake_date": pair.wake_date,
                    "cohort": pair.cohort,
                    "source_class": pair.source_class,
                    "garmin_record_id": pair.garmin_record_id,
                    "google_record_id": pair.google_record_id,
                    "garmin_source_id": pair.garmin_source_id,
                    "google_source_id": pair.google_source_id,
                    "eligibility": {
                        "garmin": pair.garmin_source_eligibility.as_dict(),
                        "google": pair.google_source_eligibility.as_dict(),
                    },
                    "pair": pair_dict,
                },
            )
            pair_rows[
                (pair.wake_date, pair.cohort, pair.garmin_record_id, pair.google_record_id)
            ] = pair_row

        for ordinal, exclusion in enumerate(projection.pairing.exclusions):
            exclusion_dict = exclusion.as_dict()
            self.repository.add_exclusion(
                run_id=run.id,
                values={
                    "ordinal": ordinal,
                    **exclusion_dict,
                    "exclusion": exclusion_dict,
                },
            )

        for ordinal, metric in enumerate(projection.projections):
            pair = metric.pair
            pair_row = pair_rows[
                (pair.wake_date, pair.cohort, pair.garmin_record_id, pair.google_record_id)
            ]
            metric_dict = metric.as_dict()
            self.repository.add_metric_result(
                run_id=run.id,
                pair_id=pair_row.id,
                values={
                    "ordinal": ordinal,
                    "metric_code": metric.metric_code,
                    "variant": metric.variant,
                    "status": metric.status,
                    "comparable": metric.comparable,
                    "difference": metric.difference,
                    "difference_unit": metric.difference_unit,
                    "reason": metric.reason,
                    "exclusion_basis": metric.manifest.exclusion_basis,
                    "garmin": metric.garmin.as_dict(),
                    "google": metric.google.as_dict(),
                    "manifest": metric.manifest.as_dict(),
                    "manifest_hash": metric.manifest.manifest_hash,
                    "projection": metric_dict,
                },
            )

        for ordinal, coverage in enumerate(projection.coverage):
            self.repository.add_coverage(
                run_id=run.id,
                values={"ordinal": ordinal, **coverage.as_dict()},
            )

        self.repository.finish(
            run.id,
            status=RunStatus.SUCCEEDED,
            pair_count=len(projection.pairing.pairs),
            exclusion_count=len(projection.pairing.exclusions),
            metric_count=len(projection.projections),
            coverage_count=len(projection.coverage),
            supersedes_run_id=supersedes_run_id,
        )
        return AgreementPersistenceResult(run=run, created=True)

    persist_projection = persist
    create_or_get = persist

    def fail(self, run_id: str, reason: str) -> AgreementRun:
        """Terminally record a failed construction without publishing it."""

        return self.repository.finish(
            run_id,
            status=RunStatus.FAILED,
            failure_reason=_required_text(reason, "agreement failure reason"),
        )

    def replay(
        self,
        run_id: str,
        *,
        pairing_version: str | None = None,
        metric_version: str | None = None,
        statistic_version: str | None = None,
        stat_version: str | None = None,
        rule_name: str | None = None,
        rule_version: str | None = None,
        rule_definition: Mapping[str, Any] | None = None,
        epoch_id: str | None = None,
        epoch_basis: Mapping[str, Any] | None = None,
        supersedes_run_id: str | None = None,
    ) -> AgreementReplay:
        """Create or find a versioned run from one persisted snapshot only.

        The replay marker and explicit versions make the operation itself
        semantically idempotent while keeping the source run and its child
        rows immutable.  Historical replays are audit runs; callers must
        explicitly provide a successor edge if they intend publication as a
        current refresh.
        """

        source = self.repository.validate_published(run_id)
        source_snapshot = _decode_json(source.input_snapshot_json, "input snapshot")
        if not isinstance(source_snapshot, dict):
            raise ValueError("persisted agreement input snapshot must be an object")
        source_versions = source_snapshot.get("versions")
        if not isinstance(source_versions, Mapping):
            raise ValueError("persisted agreement input snapshot has no versions")
        source_epoch = source_snapshot.get("epoch")
        if not isinstance(source_epoch, Mapping):
            raise ValueError("persisted agreement input snapshot has no epoch")
        if statistic_version is not None and stat_version is not None:
            if statistic_version != stat_version:
                raise ValueError("statistic_version and stat_version disagree")
        normalized_statistic = _required_text(
            statistic_version
            or stat_version
            or str(source_versions.get("statistic")),
            "agreement statistic version",
        )
        normalized_pairing = _required_text(
            pairing_version or str(source_versions.get("pairing")),
            "agreement pairing version",
        )
        normalized_metric = _required_text(
            metric_version or str(source_versions.get("metric")),
            "agreement metric version",
        )
        normalized_rule_name = _required_text(
            rule_name or str(source_versions.get("rule_name")),
            "agreement rule name",
        )
        normalized_rule_version = _required_text(
            rule_version or str(source_versions.get("rule")),
            "agreement rule version",
        )
        normalized_epoch = _required_text(
            epoch_id or str(source_epoch.get("id")),
            "agreement epoch id",
        )
        definition_value = rule_definition or source_snapshot.get("rule_definition")
        if not isinstance(definition_value, Mapping):
            raise ValueError("historical replay requires a rule definition object")
        definition = dict(definition_value)
        epoch_body = dict(epoch_basis or source_epoch.get("basis") or {})

        replay_snapshot = json.loads(canonical_json(source_snapshot))
        replay_snapshot["versions"] = {
            "pairing": normalized_pairing,
            "metric": normalized_metric,
            "statistic": normalized_statistic,
            "rule_name": normalized_rule_name,
            "rule": normalized_rule_version,
        }
        replay_snapshot["epoch"] = {"id": normalized_epoch, "basis": epoch_body}
        replay_snapshot["rule_definition"] = definition
        previous_replay = source_snapshot.get("replay")
        if isinstance(previous_replay, Mapping):
            historical_source_id = _required_text(
                str(previous_replay.get("source_run_id") or source.id),
                "historical replay source run ID",
            )
            historical_snapshot_hash = _required_text(
                str(
                    previous_replay.get("source_snapshot_hash")
                    or source.input_snapshot_hash
                ),
                "historical replay source snapshot hash",
            )
        else:
            historical_source_id = source.id
            historical_snapshot_hash = source.input_snapshot_hash
        replay_snapshot["replay"] = {
            "kind": "historical_persisted_snapshot",
            "source_run_id": historical_source_id,
            "source_snapshot_hash": historical_snapshot_hash,
        }
        input_snapshot_hash = stable_manifest_hash(replay_snapshot)
        identity_body = {
            "operation": "historical_persisted_snapshot_replay",
            "source_run_id": historical_source_id,
            "source_snapshot_hash": historical_snapshot_hash,
            "scope_key": source.scope_key,
            "window_key": source.window_key,
            "cohort": source.cohort,
            "pairing_version": normalized_pairing,
            "metric_version": normalized_metric,
            "statistic_version": normalized_statistic,
            "rule_name": normalized_rule_name,
            "rule_version": normalized_rule_version,
            "epoch_id": normalized_epoch,
            "input_snapshot_hash": input_snapshot_hash,
        }
        identity_hash = stable_manifest_hash(identity_body)
        lineage_key = stable_manifest_hash(
            {
                key: identity_body[key]
                for key in (
                    "scope_key",
                    "window_key",
                    "cohort",
                    "pairing_version",
                    "metric_version",
                    "statistic_version",
                    "rule_name",
                    "rule_version",
                    "epoch_id",
                )
            }
        )
        rule_set = self.repository.get_or_create_rule_set(
            rule_name=normalized_rule_name,
            rule_version=normalized_rule_version,
            definition=definition,
        )
        run, created = self.repository.start_or_get(
            scope_key=source.scope_key,
            scope_lineage_key=lineage_key,
            window_key=source.window_key,
            requested_start_date=source.requested_start_date,
            requested_end_date=source.requested_end_date,
            cohort=source.cohort,
            pairing_version=normalized_pairing,
            metric_version=normalized_metric,
            statistic_version=normalized_statistic,
            rule_set=rule_set,
            rule_version=normalized_rule_version,
            epoch_id=normalized_epoch,
            epoch_basis_json=canonical_json(epoch_body),
            input_snapshot_hash=input_snapshot_hash,
            input_snapshot_json=canonical_json(replay_snapshot),
            coverage_json=canonical_json(replay_snapshot["projection"]["coverage"]),
            identity_hash=identity_hash,
            supersedes_run_id=supersedes_run_id,
        )
        if not created:
            if run.status != RunStatus.SUCCEEDED.value:
                raise ValueError("historical replay is already being constructed")
            return self._load_replay(run)

        counts = self.repository.clone_frozen_rows(
            source_run_id=source.id,
            target_run_id=run.id,
        )
        self.repository.finish(
            run.id,
            status=RunStatus.SUCCEEDED,
            pair_count=counts["pair_count"],
            exclusion_count=counts["exclusion_count"],
            metric_count=counts["metric_count"],
            coverage_count=counts["coverage_count"],
            supersedes_run_id=supersedes_run_id,
        )
        return self._load_replay(run)

    def _load_replay(self, run: AgreementRun) -> AgreementReplay:
        """Read one already-published run exclusively from agreement rows."""

        snapshot = _decode_json(run.input_snapshot_json, "input snapshot")
        pairs = tuple(
            _decode_json(item.pair_json, "pair")
            for item in self.repository.pairs_for_run(run.id)
        )
        exclusions = tuple(
            _decode_json(item.exclusion_json, "exclusion")
            for item in self.repository.exclusions_for_run(run.id)
        )
        metrics = tuple(
            _decode_json(item.manifest_json, "metric manifest")
            for item in self.repository.metrics_for_run(run.id)
        )
        coverage = tuple(
            _decode_json(item.coverage_json, "coverage")
            for item in self.repository.coverage_for_run(run.id)
        )
        if not isinstance(snapshot, dict):
            raise ValueError("persisted agreement input snapshot must be an object")
        return AgreementReplay(
            run=run,
            snapshot=snapshot,
            pairs=pairs,
            exclusions=exclusions,
            metric_results=metrics,
            coverage=coverage,
        )

    replay_snapshot = replay
    load_frozen = replay

    def current(self, *, scope_lineage_key: str) -> AgreementRun | None:
        return self.repository.latest_successful(scope_lineage_key)


__all__ = [
    "AgreementPersistenceResult",
    "AgreementReplay",
    "PersistedSleepAgreementService",
    "R05_SLEEP_AGREEMENT_ALGORITHM",
    "R05_SLEEP_AGREEMENT_CONTRACT_VERSION",
    "R05_SLEEP_AGREEMENT_RULE_NAME",
    "R05_SLEEP_AGREEMENT_RULE_VERSION",
    "R05_SLEEP_AGREEMENT_STATISTIC_VERSION",
]
