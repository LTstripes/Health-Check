"""Owner-facing read model for the R05 exploratory agreement report.

The report is deliberately a presentation adapter, not a second agreement
calculator.  It validates and reads one or more published #102 runs, hands
their frozen metric evidence to the #103 statistics contract, and exposes the
result without reading mutable current sleep rows or making provider calls.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.analytics.sleep_agreement_statistics import (
    DEFAULT_EPOCH,
    EXPLORATORY_MIN_N,
    AgreementObservation,
    compute_sleep_agreement,
)
from healthcheck.db.models import (
    AgreementRun,
    AgreementRunExclusion,
    AgreementRunPair,
    CoverageInterval,
    Provider,
    RunStatus,
    SyncRun,
    SyncStreamState,
)
from healthcheck.db.repositories import AgreementRunRepository
from healthcheck.garmin.capabilities import GARMIN_PROVIDER_CODE
from healthcheck.google.contracts import GOOGLE_PROVIDER_CODE

REPORT_CONTRACT_VERSION = "r05-05-sleep-agreement-report-v1"
_COHORT_ORDER = {"device_pair": 0, "family_pair": 1}


def _json_object(value: str, field_name: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"persisted agreement {field_name} is malformed") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"persisted agreement {field_name} must be an object")
    return decoded


def _json_list(value: str, field_name: str) -> list[Any]:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"persisted agreement {field_name} is malformed") from exc
    if not isinstance(decoded, list):
        raise ValueError(f"persisted agreement {field_name} must be a list")
    return decoded


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _in_window(wake_date: date, start: date | None, end: date | None) -> bool:
    return (start is None or wake_date >= start) and (end is None or wake_date <= end)


def _epoch_for_observation(run: AgreementRun) -> str:
    """Keep arbitrary historical test/legacy epoch labels from changing stats semantics."""

    try:
        basis = _json_object(run.epoch_basis_json, "epoch basis")
    except ValueError:
        return DEFAULT_EPOCH
    if run.epoch_id == DEFAULT_EPOCH:
        return DEFAULT_EPOCH
    if basis.get("break_kind") in {"measurement", "device", "algorithm_method"} and basis.get(
        "evidence_reference"
    ):
        return run.epoch_id
    return DEFAULT_EPOCH


def _side_payload(side: Mapping[str, Any]) -> dict[str, Any]:
    """Expose metadata/value fields, never a raw provider payload body."""

    evidence = side.get("evidence")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    provenance = evidence.get("normalization_provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    return {
        "provider": side.get("provider"),
        "record_id": side.get("record_id"),
        "state": side.get("state"),
        "value": side.get("value"),
        "unit": side.get("unit"),
        "field_path": side.get("field_path"),
        "reason": side.get("reason"),
        "eligible": side.get("eligible"),
        "is_zero": side.get("is_zero"),
        "variant": side.get("variant"),
        "comparison_basis": side.get("comparison_basis"),
        "exclusion_basis": side.get("exclusion_basis"),
        "evidence": {
            "source_id": evidence.get("source_id"),
            "source_instance_id": evidence.get("source_instance_id"),
            "source_class": evidence.get("source_class"),
            "source_kind": evidence.get("source_kind"),
            "record_id": evidence.get("record_id"),
            "observation_id": evidence.get("observation_id"),
            "observation_key": evidence.get("observation_key"),
            "field_paths": evidence.get("field_paths", []),
            "normalization_status": provenance.get("status"),
            "immutable": evidence.get("immutable"),
            "exclusion_basis": evidence.get("exclusion_basis"),
        },
    }


class SleepAgreementReportService:
    """Build a deterministic report from published immutable agreement runs."""

    def __init__(self, session: Session):
        self.session = session
        self.repository = AgreementRunRepository(session)

    def report(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        cohort: str = "all",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        if (start_date is None) != (end_date is None):
            raise ValueError("report start_date and end_date must be supplied together")
        if start_date is not None and end_date is not None and end_date < start_date:
            raise ValueError("report end_date cannot precede start_date")
        if cohort not in {"all", "device_pair", "family_pair"}:
            raise ValueError("report cohort must be all, device_pair, or family_pair")

        runs = self._runs(run_id)
        if not runs:
            return unavailable_report(reason="no_published_agreement")

        run_payloads = []
        groups: list[dict[str, Any]] = []
        all_pairs: list[tuple[AgreementRun, AgreementRunPair]] = []
        all_exclusions: list[tuple[AgreementRun, AgreementRunExclusion]] = []
        for run in runs:
            self.repository.validate_published(run.id)
            pairs = self.repository.pairs_for_run(run.id)
            exclusions = self.repository.exclusions_for_run(run.id)
            all_pairs.extend((run, item) for item in pairs)
            all_exclusions.extend((run, item) for item in exclusions)
            run_payloads.append(self._run_payload(run, pairs, exclusions))
            groups.extend(self._groups(run, pairs, start_date, end_date, cohort))

        selected_pairs = [
            (run, pair)
            for run, pair in all_pairs
            if _in_window(pair.wake_date, start_date, end_date)
            and (cohort == "all" or pair.cohort == cohort)
        ]
        return {
            "contract_version": REPORT_CONTRACT_VERSION,
            "available": bool(groups),
            "mode": "exploratory"
            if any(item["progress"]["exploratory_available"] for item in groups)
            else "accumulating",
            "threshold": {
                "exploratory_n": EXPLORATORY_MIN_N,
                "available_groups": sum(
                    item["progress"]["exploratory_available"] for item in groups
                ),
            },
            "requested_window": {
                "start_date": _iso(start_date),
                "end_date": _iso(end_date),
            },
            "runs": run_payloads,
            "groups": sorted(
                groups,
                key=lambda item: (
                    item["run_id"],
                    _COHORT_ORDER.get(item["cohort"], 99),
                    item["metric_code"],
                    item["variant"] or "",
                ),
            ),
            "pairing_exclusions": [
                self._exclusion_payload(run, item)
                for run, item in all_exclusions
                if (item.wake_date is None or _in_window(item.wake_date, start_date, end_date))
                and (cohort == "all" or item.cohort in {None, cohort})
            ],
            "source_data_quality": self._source_data_quality(selected_pairs, start_date, end_date),
            "claims": {
                "accuracy": "not_assessed",
                "canonical_switch": "not_applied",
                "source_overlays_are_evidence_only": True,
            },
        }

    def night_detail(
        self,
        run_id: str,
        *,
        wake_date: date | None = None,
        metric_code: str | None = None,
    ) -> dict[str, Any]:
        run = self.repository.validate_published(run_id)
        pairs = self.repository.pairs_for_run(run_id)
        exclusions = self.repository.exclusions_for_run(run_id)
        metrics = self.repository.metrics_for_run(run_id)
        metric_by_pair: dict[str, list[Any]] = defaultdict(list)
        for metric in metrics:
            if metric_code is not None and metric.metric_code != metric_code:
                continue
            metric_by_pair[metric.pair_id].append(metric)
        nights = []
        for pair in pairs:
            if wake_date is not None and pair.wake_date != wake_date:
                continue
            pair_json = _json_object(pair.pair_json, f"pair {pair.id}")
            nights.append(
                {
                    "wake_date": pair.wake_date.isoformat(),
                    "cohort": pair.cohort,
                    "source_class": pair.source_class,
                    "pair_key": pair.pair_key,
                    "source_attribution": {
                        "garmin": pair_json.get("garmin_source_eligibility"),
                        "google": pair_json.get("google_source_eligibility"),
                    },
                    "google_manually_edited": pair_json.get("google_manually_edited"),
                    "metrics": [self._metric_detail(metric) for metric in metric_by_pair[pair.id]],
                }
            )
        return {
            "contract_version": REPORT_CONTRACT_VERSION,
            "available": bool(nights or exclusions),
            "run": self._run_payload(run, pairs, exclusions),
            "nights": nights,
            "exclusions": [self._exclusion_payload(run, item) for item in exclusions],
            "claims": {"accuracy": "not_assessed", "canonical_switch": "not_applied"},
        }

    def _runs(self, run_id: str | None) -> list[AgreementRun]:
        if run_id is not None:
            run = self.repository.get_by_id(run_id)
            return [] if run is None or run.status != RunStatus.SUCCEEDED.value else [run]
        candidates = list(
            self.session.scalars(
                select(AgreementRun)
                .where(AgreementRun.status == RunStatus.SUCCEEDED.value)
                .order_by(AgreementRun.completed_at.desc(), AgreementRun.id.desc())
            )
        )
        lineages = {item.scope_lineage_key for item in candidates}
        return [
            current
            for lineage in sorted(lineages)
            if (current := self.repository.latest_successful(lineage)) is not None
        ]

    @staticmethod
    def _run_payload(
        run: AgreementRun,
        pairs: Iterable[AgreementRunPair],
        exclusions: Iterable[AgreementRunExclusion],
    ) -> dict[str, Any]:
        pair_list = list(pairs)
        exclusion_list = list(exclusions)
        return {
            "run_id": run.id,
            "scope_key": run.scope_key,
            "cohort": run.cohort,
            "window_key": run.window_key,
            "requested_start_date": _iso(run.requested_start_date),
            "requested_end_date": _iso(run.requested_end_date),
            "completed_at": _iso(run.completed_at),
            "input_snapshot_hash": run.input_snapshot_hash,
            "pairing_version": run.pairing_version,
            "metric_version": run.metric_version,
            "statistic_version": run.statistic_version,
            "rule_version": run.rule_version,
            "epoch_id": run.epoch_id,
            "pair_count": len(pair_list),
            "exclusion_count": len(exclusion_list),
            "drilldown_url": f"/api/agreement/report/{run.id}/nights",
        }

    def _groups(
        self,
        run: AgreementRun,
        pairs: list[AgreementRunPair],
        start_date: date | None,
        end_date: date | None,
        cohort: str,
    ) -> list[dict[str, Any]]:
        metrics = self.repository.metrics_for_run(run.id)
        pair_by_id = {item.id: item for item in pairs}
        grouped: dict[tuple[str, str, str], list[AgreementObservation]] = defaultdict(list)
        metric_rows: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
        for metric in metrics:
            pair = pair_by_id.get(metric.pair_id)
            if pair is None or cohort != "all" and pair.cohort != cohort:
                continue
            if not _in_window(pair.wake_date, start_date, end_date):
                continue
            key = (pair.cohort, metric.metric_code, metric.variant or "__none__")
            grouped[key].append(self._observation(run, pair, metric))
            metric_rows[key].append(metric)

        result = []
        for (pair_cohort, metric_code, variant_key), observations in grouped.items():
            packet = compute_sleep_agreement(
                observations,
                requested_start_date=start_date or run.requested_start_date,
                requested_end_date=end_date or run.requested_end_date,
            )
            stats = packet.statistics[0]
            stats_payload = stats.as_dict() if stats.n >= EXPLORATORY_MIN_N else None
            metric_reason_counts = Counter(
                item.reason or ("metric_unavailable" if not item.comparable else "")
                for item in metric_rows[(pair_cohort, metric_code, variant_key)]
                if not item.comparable
            )
            metric_reason_counts.pop("", None)
            rows_by_date = {
                pair_by_id[item.pair_id].wake_date: item
                for item in metric_rows[(pair_cohort, metric_code, variant_key)]
            }
            chart_points = [
                {"wake_date": wake.isoformat(), "difference": difference}
                for wake, difference in zip(stats.wake_dates, stats.differences, strict=True)
            ]
            result.append(
                {
                    "run_id": run.id,
                    "metric_code": metric_code,
                    "variant": None if variant_key == "__none__" else variant_key,
                    "cohort": pair_cohort,
                    "source_attribution": {
                        "source_classes": sorted({
                            pair.source_class
                            for pair in pairs
                            if pair.cohort == pair_cohort
                            and _in_window(pair.wake_date, start_date, end_date)
                        }),
                        "cohort_label": (
                            "Fitbit device pair"
                            if pair_cohort == "device_pair"
                            else "Google wearable family pair"
                        ),
                    },
                    "n": stats.n,
                    "paired_nights": stats.coverage.source_eligible_paired_nights,
                    "coverage": stats.coverage.as_dict(),
                    "exclusions": dict(metric_reason_counts),
                    "progress": {
                        "status": "exploratory" if stats.n >= EXPLORATORY_MIN_N else "accumulating",
                        "exploratory_available": stats.n >= EXPLORATORY_MIN_N,
                        "n": stats.n,
                        "required_n": EXPLORATORY_MIN_N,
                        "remaining_n": max(0, EXPLORATORY_MIN_N - stats.n),
                        "gate": stats.gate.as_dict(),
                    },
                    "accepted_statistics": stats_payload,
                    "chart": {"points": chart_points, "point_count": len(chart_points)},
                    "drilldown_url": (
                        f"/api/agreement/report/{run.id}/nights?metric_code={metric_code}"
                    ),
                    "night_count": len(rows_by_date),
                }
            )
        return result

    @staticmethod
    def _observation(
        run: AgreementRun, pair: AgreementRunPair, metric: Any
    ) -> AgreementObservation:
        pair_json = _json_object(pair.pair_json, f"pair {pair.id}")
        manifest = _json_object(metric.manifest_json, f"metric {metric.id}")
        return AgreementObservation(
            wake_date=pair.wake_date,
            metric_code=metric.metric_code,
            cohort=pair.cohort,
            difference=metric.difference_number,
            epoch=_epoch_for_observation(run),
            variant=metric.variant,
            source_eligible=True,
            metric_valid=metric.status == "comparable" and metric.difference_number is not None,
            exclusion_reason=metric.reason or metric.exclusion_basis,
            google_value=(manifest.get("google") or {}).get("value"),
            garmin_value=(manifest.get("garmin") or {}).get("value"),
            google_manually_edited=pair_json.get("google_manually_edited"),
            canonical_candidate=(manifest.get("metric_definition") or {}).get(
                "canonical_candidate"
            ),
            _projection_evidence_verified=(
                metric.status == "comparable" and metric.difference_number is not None
            ),
        )

    @staticmethod
    def _metric_detail(metric: Any) -> dict[str, Any]:
        manifest = _json_object(metric.manifest_json, f"metric {metric.id}")
        return {
            "metric_code": metric.metric_code,
            "variant": metric.variant,
            "status": metric.status,
            "comparable": metric.comparable,
            "difference": metric.difference_number,
            "difference_unit": metric.difference_unit,
            "reason": metric.reason,
            "exclusion_basis": metric.exclusion_basis,
            "garmin": _side_payload(manifest.get("garmin", {})),
            "google": _side_payload(manifest.get("google", {})),
        }

    @staticmethod
    def _exclusion_payload(run: AgreementRun, item: AgreementRunExclusion) -> dict[str, Any]:
        return {
            "run_id": run.id,
            "wake_date": _iso(item.wake_date),
            "cohort": item.cohort,
            "reason": item.reason,
            "garmin_record_ids": _json_list(item.garmin_record_ids_json, "Garmin exclusion IDs"),
            "google_record_ids": _json_list(item.google_record_ids_json, "Google exclusion IDs"),
            "details": _json_object(item.details_json, "exclusion details"),
        }

    def _source_data_quality(
        self,
        selected_pairs: list[tuple[AgreementRun, AgreementRunPair]],
        start_date: date | None,
        end_date: date | None,
    ) -> list[dict[str, Any]]:
        providers = list(
            self.session.scalars(select(Provider).order_by(Provider.code, Provider.id))
        )
        states = list(self.session.scalars(select(SyncStreamState)))
        sync_runs = list(self.session.scalars(select(SyncRun)))
        intervals = list(self.session.scalars(select(CoverageInterval)))
        latest_evidence_date = max((pair.wake_date for _run, pair in selected_pairs), default=None)
        actual_by_provider = {
            GARMIN_PROVIDER_CODE: latest_evidence_date,
            GOOGLE_PROVIDER_CODE: latest_evidence_date,
        }
        result = []
        for provider in providers:
            provider_states = [item for item in states if item.provider_id == provider.id]
            provider_runs = [item for item in sync_runs if item.provider_id == provider.id]
            provider_intervals = [
                item
                for item in intervals
                if item.provider_id == provider.id
                and (
                    start_date is None
                    or end_date is None
                    or item.interval_end.date() >= start_date
                    and item.interval_start.date() <= end_date
                )
            ]
            interval_counts = Counter(item.status for item in provider_intervals)
            latest_success = max(
                [
                    item.last_success_at
                    for item in provider_states
                    if item.last_success_at is not None
                ]
                + [
                    item.completed_at
                    for item in provider_runs
                    if item.status == "succeeded" and item.completed_at is not None
                ],
                default=None,
            )
            latest_attempt = max(
                [
                    item.last_attempt_at
                    for item in provider_states
                    if item.last_attempt_at is not None
                ]
                + [item.completed_at for item in provider_runs if item.completed_at is not None],
                default=None,
            )
            latest_status = next(
                (
                    item.status
                    for item in sorted(
                        provider_runs,
                        key=lambda row: (row.completed_at or row.started_at, row.id),
                        reverse=True,
                    )
                ),
                None,
            )
            state = "unknown"
            if latest_status == "failed":
                state = "failed"
            elif latest_status == "partial" or interval_counts.get("unavailable"):
                state = "unavailable"
            elif interval_counts.get("present") or (
                provider_runs and latest_status == "succeeded"
            ):
                state = "usable"
            elif interval_counts.get("confirmed_empty"):
                state = "confirmed_empty"
            result.append(
                {
                    "provider_code": provider.code,
                    "provider_display_name": provider.display_name,
                    "state": state,
                    "last_successful_sync": _iso(latest_success),
                    "last_attempt": _iso(latest_attempt),
                    "last_sync_status": latest_status,
                    "last_actual_measurement_or_evidence_date": _iso(
                        actual_by_provider.get(provider.code)
                    ),
                    "coverage_state_counts": dict(sorted(interval_counts.items())),
                    "coverage_facts": [
                        {
                            "stream_code": item.stream_code,
                            "metric_code": item.metric_code,
                            "status": item.status,
                            "observed_count": item.observed_count,
                            "expected_count": item.expected_count,
                            "diagnostic_reason": item.diagnostic_reason,
                        }
                        for item in sorted(
                            provider_intervals,
                            key=lambda row: (row.interval_start, row.metric_code, row.id),
                        )
                    ],
                    "window": {"start_date": _iso(start_date), "end_date": _iso(end_date)},
                }
            )
        return result


def unavailable_report(*, reason: str = "no_published_agreement") -> dict[str, Any]:
    return {
        "contract_version": REPORT_CONTRACT_VERSION,
        "available": False,
        "mode": "unavailable",
        "reason": reason,
        "threshold": {"exploratory_n": EXPLORATORY_MIN_N, "available_groups": 0},
        "runs": [],
        "groups": [],
        "pairing_exclusions": [],
        "source_data_quality": [],
        "claims": {"accuracy": "not_assessed", "canonical_switch": "not_applied"},
    }


__all__ = ["REPORT_CONTRACT_VERSION", "SleepAgreementReportService", "unavailable_report"]
