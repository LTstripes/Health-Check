"""Application service for the local weight dashboard and review APIs.

Routes stay thin.  This module transacts through repositories, runs the
established canonical/coverage services, and feeds typed records into the
pure analytics functions.  Framework request objects never enter analytics.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from healthcheck.analytics.coverage import (
    DEFAULT_WEIGHT_CADENCE_DAYS,
    CoverageService,
)
from healthcheck.analytics.weight import (
    BODY_FAT_METRIC_CODES,
    MUSCLE_METRIC_CODES,
    WEIGHT_METRIC_CODES,
    BodyCompositionResult,
    CompositionInput,
    CompositionPoint,
    SimilarWeightComparison,
    build_weight_series,
    build_weight_summary,
    coerce_weight_observations,
    derive_body_composition,
    similar_weight_comparison,
)
from healthcheck.canonical import (
    DASHBOARD_COMPOSITION_SCOPE_PREFIX,
    DASHBOARD_WEIGHT_SCOPE,
    CanonicalCandidate,
    dashboard_composition_scope,
    is_composition_metric,
)
from healthcheck.config import Settings
from healthcheck.db.models import ScalarMeasurement
from healthcheck.db.repositories import repositories_for, restore_stored_utc
from healthcheck.web.common import ALGORITHM_BOUNDARY_WARNING, BIA_UNCERTAINTY


class WeightQueryService:
    def __init__(self, session: Session, settings: Settings | None = None):
        self.session = session
        self.settings = settings or Settings()
        self.repos = repositories_for(session)
        self.coverage = CoverageService(session)

    def series(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        compatibility_group: str | None = None,
    ) -> dict[str, Any]:
        return self._payload(
            start_date=start_date,
            end_date=end_date,
            compatibility_group=compatibility_group,
        )["series"]

    def summary(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        compatibility_group: str | None = None,
    ) -> dict[str, Any]:
        return self._payload(
            start_date=start_date,
            end_date=end_date,
            compatibility_group=compatibility_group,
        )["summary"]

    def dashboard(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        payload = self._payload(start_date=start_date, end_date=end_date)
        payload["imports"] = self.import_queue_summary()
        return payload

    def import_queue_summary(self) -> dict[str, Any]:
        batches = self.repos.ingest_batches.list_recent(limit=50)
        pending = 0
        confirmed = 0
        rejected = 0
        for batch in batches:
            for candidate in self.repos.import_candidates.list_for_batch(batch.id):
                if candidate.user_decision == "pending":
                    pending += 1
                elif candidate.user_decision == "confirmed":
                    confirmed += 1
                elif candidate.user_decision == "rejected":
                    rejected += 1
        return {
            "batch_count": len(batches),
            "pending_candidate_count": pending,
            "confirmed_candidate_count": confirmed,
            "rejected_candidate_count": rejected,
            "batches": [
                {
                    "id": batch.id,
                    "status": batch.status,
                    "received_count": batch.received_count,
                    "parsed_count": batch.parsed_count,
                    "committed_count": batch.committed_count,
                    "failed_count": batch.failed_count,
                    "started_at": batch.started_at.isoformat() if batch.started_at else None,
                    "extractor_name": batch.extractor_name,
                    "extractor_version": batch.extractor_version,
                }
                for batch in batches
            ],
        }

    def _payload(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        compatibility_group: str | None = None,
    ) -> dict[str, Any]:
        as_of = end_date or date.today()
        records = self._current_records(start_date=start_date, end_date=end_date)
        canonical, selected_weight_ids, selected_composition_ids = (
            self._established_canonical()
        )
        overlay_weights = tuple(
            item["candidate"]
            for item in records
            if item["candidate"].metric_code in WEIGHT_METRIC_CODES
        )
        if compatibility_group:
            normalized = compatibility_group.strip()
            overlay_weights = tuple(
                item
                for item in overlay_weights
                if item.compatibility_group == normalized
            )
        selected_weights = tuple(
            item for item in overlay_weights if item.evidence_id in selected_weight_ids
        )
        composition_records = [
            item
            for item in records
            if item["candidate"].evidence_id in selected_weight_ids
            or item["candidate"].evidence_id in selected_composition_ids
        ]
        if compatibility_group:
            normalized = compatibility_group.strip()
            composition_records = [
                item
                for item in composition_records
                if item["candidate"].compatibility_group == normalized
                or item["candidate"].metric_code in WEIGHT_METRIC_CODES
            ]
        composition_sessions = self._composition_sessions(composition_records)
        series = build_weight_series(
            selected_weights,
            compatibility_group=compatibility_group,
            composition_sessions=composition_sessions,
        )
        overlay_raw, _overlay_exclusions = coerce_weight_observations(
            overlay_weights, compatibility_group=compatibility_group
        )
        latest_composition = self._latest_composition(series.composition_by_group)
        similar_pair, similar_result = self._similar_weight(series.composition_by_group)
        coverage_start = start_date
        if coverage_start is None:
            if overlay_raw:
                coverage_start = overlay_raw[0].observed_date
            else:
                coverage_start = as_of - timedelta(days=180)
        coverage = self.coverage.summarize(
            start_date=coverage_start,
            end_date=as_of,
            metric_code="weight",
            cadence_days=self.settings.weight_cadence_days or DEFAULT_WEIGHT_CADENCE_DAYS,
            as_of_date=as_of,
        )
        if not canonical["available"]:
            latest_composition = BodyCompositionResult(
                available=False, reason="no_canonical_run"
            )
            similar_pair = None
            similar_result = SimilarWeightComparison(
                available=False, reason="no_canonical_run"
            )
        summary = build_weight_summary(
            selected_weights,
            compatibility_group=compatibility_group,
            composition_sessions=composition_sessions,
            latest_composition=latest_composition,
            similar_pair=similar_pair,
            coverage=coverage,
            as_of_date=as_of,
        )
        if similar_pair is not None:
            similar_payload = summary.similar_weight.as_dict()
        else:
            similar_payload = similar_result.as_dict()

        provenance = {
            item["candidate"].evidence_id: item["provenance"]
            for item in records
            if item["candidate"].evidence_id
        }
        groups = list(series.composition_by_group)
        boundary = len(groups) > 1
        current = _current_weight(series.raw_points)
        raw_points = []
        for point in overlay_raw:
            payload = point.as_dict()
            payload["metric_origin"] = "source-provider"
            payload["canonical_selected"] = point.evidence_id in selected_weight_ids
            payload["provenance"] = provenance.get(point.evidence_id)
            raw_points.append(payload)
        composition_payload = {
            group: [_composition_point_payload(point) for point in points]
            for group, points in series.composition_by_group.items()
        }
        if canonical["available"]:
            trend_available = series.trend_available
            trend_reason = series.trend_reason
        elif overlay_raw:
            trend_available = False
            trend_reason = "no_canonical_run"
        else:
            trend_available = series.trend_available
            trend_reason = series.trend_reason
        series_payload = {
            **series.as_dict(),
            "raw_points": raw_points,
            "trend_available": trend_available,
            "trend_reason": trend_reason,
            "composition_by_group": composition_payload,
            "goal_kg": self.settings.weight_goal_kg,
            "current": current,
            "canonical": canonical,
            "algorithm_boundary": {
                "present": boundary,
                "groups": groups,
                "warning": ALGORITHM_BOUNDARY_WARNING if boundary else None,
            },
            "bia_uncertainty": BIA_UNCERTAINTY,
            "metric_labels": {
                "raw_weight": "Raw confirmed weight (source)",
                "trend": "21-day time-aware trend (Health-Check derived)",
                "goal": "Configured goal",
                "body_fat": "Body fat (source / provider algorithm)",
                "estimated_fat_mass": "Estimated fat mass (Health-Check derived)",
                "estimated_lean_mass": "Estimated lean mass (Health-Check derived)",
                "source_muscle": "Source muscle mass (provider, not lean mass)",
            },
        }
        summary_payload = summary.as_dict()
        summary_payload["trend"]["available"] = trend_available
        summary_payload["trend"]["reason"] = trend_reason
        summary_payload["similar_weight"] = similar_payload
        summary_payload["goal_kg"] = self.settings.weight_goal_kg
        summary_payload["current"] = current
        summary_payload["algorithm_boundary"] = series_payload["algorithm_boundary"]
        summary_payload["bia_uncertainty"] = BIA_UNCERTAINTY
        summary_payload["canonical"] = canonical
        summary_payload["composition_by_group"] = composition_payload
        return {
            "series": series_payload,
            "summary": summary_payload,
            "bia_uncertainty": BIA_UNCERTAINTY,
            "algorithm_boundary": series_payload["algorithm_boundary"],
            "goal_kg": self.settings.weight_goal_kg,
            "current": current,
        }

    def _current_records(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> list[dict[str, Any]]:
        measurements = self.repos.scalar_measurements.current_heads(
            start_date=start_date,
            end_date=end_date,
        )
        records: list[dict[str, Any]] = []
        for measurement in measurements:
            projected = self._project(measurement)
            if projected is None:
                continue
            records.append(projected)
        return records

    def _project(self, measurement: ScalarMeasurement) -> dict[str, Any] | None:
        session = self.repos.measurement_sessions.get_by_id(measurement.measurement_session_id)
        algorithm = self.repos.measurement_algorithms.get_by_id(
            measurement.measurement_algorithm_id
        )
        if session is None or algorithm is None or not session.semantic_key:
            return None
        if session.confirmation_status != "confirmed":
            return None
        timestamp = restore_stored_utc(session.source_timestamp_utc)
        candidate = CanonicalCandidate(
            metric_code=measurement.metric_code,
            semantic_key=session.semantic_key,
            source_measurement_id=measurement.id,
            normalized_value=measurement.normalized_value,
            normalized_unit=measurement.normalized_unit,
            original_value=measurement.original_value,
            original_unit=measurement.original_unit,
            source_local_date=session.source_local_date,
            source_timestamp_utc=timestamp,
            algorithm_code=algorithm.code,
            algorithm_version=algorithm.version,
            compatibility_group=algorithm.compatibility_group,
            revision_number=session.revision_number,
            created_at=restore_stored_utc(measurement.created_at),
            confirmed=True,
            current=True,
        )
        source = self.repos.acquisition_sources.get_by_id(session.acquisition_source_id)
        provider = self.repos.providers.get(source.provider_id) if source is not None else None
        device = None
        if source is not None and source.physical_device_id is not None:
            device = self.repos.physical_devices.get(source.physical_device_id)
        artifact = None
        if session.raw_artifact_id is not None:
            artifact = self.repos.raw_artifacts.get(session.raw_artifact_id)
        event = None
        if session.ingest_event_id is not None:
            event = self.repos.ingest_events.get(session.ingest_event_id)
        provenance = {
            "evidence_id": measurement.id,
            "session_id": session.id,
            "semantic_key": session.semantic_key,
            "metric_code": measurement.metric_code,
            "metric_origin": "source-provider",
            "provider_code": provider.code if provider is not None else None,
            "provider_display_name": provider.display_name if provider is not None else None,
            "device_code": device.code if device is not None else None,
            "device_display_name": device.display_name if device is not None else None,
            "input_method": source.input_method if source is not None else None,
            "source_application": source.source_application if source is not None else None,
            "source_application_version": (
                source.source_application_version if source is not None else None
            ),
            "algorithm_code": algorithm.code,
            "algorithm_version": algorithm.version,
            "compatibility_group": algorithm.compatibility_group,
            "algorithm_producer": algorithm.producer,
            "temporal_precision": session.temporal_precision,
            "source_local_date": session.source_local_date.isoformat(),
            "source_timestamp_utc": timestamp.isoformat() if timestamp is not None else None,
            "artifact_id": artifact.id if artifact is not None else None,
            "artifact_content_hash": artifact.content_hash if artifact is not None else None,
            "ingest_event_id": event.id if event is not None else None,
            "ingest_batch_id": event.ingest_batch_id if event is not None else None,
        }
        return {
            "measurement": measurement,
            "session": session,
            "algorithm": algorithm,
            "candidate": candidate,
            "provenance": provenance,
        }

    def _composition_sessions(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for item in records:
            session = item["session"]
            candidate = item["candidate"]
            bucket = grouped.setdefault(
                session.id,
                {
                    "session_id": session.id,
                    "observed_date": session.source_local_date,
                    "compatibility_group": None,
                    "algorithm_code": None,
                    "algorithm_version": None,
                    "weight": {},
                    "body_fat": {},
                    "muscle": {},
                },
            )
            metric = candidate.metric_code
            payload = {
                "measurement_id": candidate.evidence_id,
                "value": candidate.normalized_value,
                "unit": candidate.normalized_unit,
                "algorithm_code": candidate.algorithm_code,
                "algorithm_version": candidate.algorithm_version,
                "compatibility_group": candidate.compatibility_group,
            }
            if metric in WEIGHT_METRIC_CODES:
                bucket["weight"] = payload
            elif metric in BODY_FAT_METRIC_CODES:
                bucket["body_fat"] = payload
                bucket["compatibility_group"] = candidate.compatibility_group
                bucket["algorithm_code"] = candidate.algorithm_code
                bucket["algorithm_version"] = candidate.algorithm_version
            elif metric in MUSCLE_METRIC_CODES:
                bucket["muscle"] = payload
        return [value for value in grouped.values() if value["observed_date"] is not None]

    def _latest_composition(
        self, grouped: dict[str, tuple[CompositionPoint, ...]]
    ) -> BodyCompositionResult:
        latest: CompositionPoint | None = None
        for points in grouped.values():
            for point in points:
                if point.weight_kg is None or point.body_fat_pct is None:
                    continue
                if latest is None or (point.observed_date, point.session_id) > (
                    latest.observed_date,
                    latest.session_id,
                ):
                    latest = point
        if latest is None:
            return BodyCompositionResult(available=False, reason="no_data")
        return derive_body_composition(
            CompositionInput(
                measurement_id=latest.weight_measurement_id or f"{latest.session_id}:weight",
                metric_code="weight",
                value=latest.weight_kg,
                unit="kg",
                session_id=latest.session_id,
                compatibility_group=latest.compatibility_group,
                algorithm_code=latest.algorithm_code,
                algorithm_version=latest.algorithm_version,
                observed_date=latest.observed_date,
            ),
            CompositionInput(
                measurement_id=latest.body_fat_measurement_id or f"{latest.session_id}:fat",
                metric_code="body_fat_pct",
                value=latest.body_fat_pct,
                unit="pct",
                session_id=latest.session_id,
                compatibility_group=latest.compatibility_group,
                algorithm_code=latest.algorithm_code,
                algorithm_version=latest.algorithm_version,
                observed_date=latest.observed_date,
            ),
        )

    def _similar_weight(
        self, grouped: dict[str, tuple[CompositionPoint, ...]]
    ) -> tuple[tuple[CompositionPoint, CompositionPoint] | None, SimilarWeightComparison]:
        fallback = SimilarWeightComparison(available=False, reason="no_data")
        best_pair: tuple[CompositionPoint, CompositionPoint] | None = None
        best: SimilarWeightComparison | None = None
        last_reason = fallback
        for points in grouped.values():
            ordered = tuple(sorted(points, key=lambda item: (item.observed_date, item.session_id)))
            if len(ordered) < 2:
                continue
            later = ordered[-1]
            for earlier in ordered[:-1]:
                result = similar_weight_comparison(earlier, later)
                last_reason = result
                if not result.available:
                    continue
                if best is None or (result.days_apart or 0) > (best.days_apart or 0):
                    best = result
                    best_pair = (earlier, later)
        if best_pair is not None and best is not None:
            return best_pair, best
        return None, last_reason

    def _established_canonical(
        self,
    ) -> tuple[dict[str, Any], frozenset[str], frozenset[str]]:
        """Read durable canonical evidence IDs.  GET paths must not write."""

        runs = self.repos.canonical_selection_runs
        run = runs.latest_successful(DASHBOARD_WEIGHT_SCOPE)
        if run is None:
            latest = runs.latest_for_scope(DASHBOARD_WEIGHT_SCOPE)
            if latest is not None and latest.status == "failed":
                meta = {
                    "available": False,
                    "reason": "canonical_selection_failed",
                    "run_id": None,
                    "status": None,
                    "selection_count": 0,
                    "fresh": False,
                    "stale": False,
                    "warning": "canonical_recompute_failed",
                    "latest_attempt_status": latest.status,
                    "latest_attempt_run_id": latest.id,
                    "failure_reason": latest.failure_reason,
                }
            elif latest is not None and latest.status == "running":
                meta = {
                    "available": False,
                    "reason": "canonical_selection_in_progress",
                    "run_id": None,
                    "status": None,
                    "selection_count": 0,
                    "fresh": False,
                    "stale": False,
                    "warning": "canonical_recompute_in_progress",
                    "latest_attempt_status": latest.status,
                    "latest_attempt_run_id": latest.id,
                    "failure_reason": None,
                }
            else:
                meta = {
                    "available": False,
                    "reason": "no_canonical_run",
                    "run_id": None,
                    "status": None,
                    "selection_count": 0,
                    "fresh": False,
                    "stale": False,
                    "warning": None,
                    "latest_attempt_status": None,
                    "latest_attempt_run_id": None,
                    "failure_reason": None,
                }
            return meta, frozenset(), frozenset()
        weight_ids = {
            selection.source_measurement_id
            for selection in self.repos.canonical_selections.for_run(run.id)
            if selection.source_measurement_id
        }
        composition_ids: set[str] = set()
        groups: set[str] = set()
        for measurement in self.repos.scalar_measurements.current_heads():
            if not is_composition_metric(measurement.metric_code):
                continue
            algorithm = self.repos.measurement_algorithms.get_by_id(
                measurement.measurement_algorithm_id
            )
            if algorithm is not None and algorithm.compatibility_group:
                groups.add(algorithm.compatibility_group)
        composition_scopes = {
            dashboard_composition_scope(group) for group in groups
        }
        composition_scopes.update(
            runs.successful_scope_keys(prefix=DASHBOARD_COMPOSITION_SCOPE_PREFIX)
        )
        for scope_key in sorted(composition_scopes):
            composition_run = runs.latest_successful(scope_key)
            if composition_run is None:
                continue
            composition_ids.update(
                selection.source_measurement_id
                for selection in self.repos.canonical_selections.for_run(
                    composition_run.id
                )
                if selection.source_measurement_id
            )
        freshness = _canonical_freshness_meta(runs, DASHBOARD_WEIGHT_SCOPE, run)
        for scope_key in sorted(composition_scopes):
            composition_run = runs.latest_successful(scope_key)
            if composition_run is None:
                continue
            freshness = _merge_canonical_freshness(
                freshness,
                _canonical_freshness_meta(runs, scope_key, composition_run),
            )
        meta = {
            "available": True,
            "reason": None,
            "run_id": run.id,
            "status": run.status,
            "selection_count": run.selection_count or 0,
            "rule_name": run.rule_name,
            "rule_version": run.rule_version,
            "scope_key": run.scope_key,
            "input_snapshot_hash": run.input_snapshot_hash,
            **freshness,
        }
        return meta, frozenset(weight_ids), frozenset(composition_ids)


def _canonical_freshness_meta(
    runs_repo: Any, scope_key: str, successful_run: Any
) -> dict[str, Any]:
    """Describe whether the latest attempt leaves established success stale.

    Failed runs never become the active selection set, but a newer failed
    recompute must not look like a fresh successful establishment on GET.
    """

    latest = runs_repo.latest_for_scope(scope_key)
    if latest is None or latest.id == successful_run.id:
        return {
            "fresh": True,
            "stale": False,
            "warning": None,
            "latest_attempt_status": successful_run.status,
            "latest_attempt_run_id": successful_run.id,
            "failure_reason": None,
        }
    if latest.status == "failed":
        return {
            "fresh": False,
            "stale": True,
            "warning": "canonical_recompute_failed",
            "latest_attempt_status": latest.status,
            "latest_attempt_run_id": latest.id,
            "failure_reason": latest.failure_reason,
        }
    if latest.status == "running":
        return {
            "fresh": False,
            "stale": True,
            "warning": "canonical_recompute_in_progress",
            "latest_attempt_status": latest.status,
            "latest_attempt_run_id": latest.id,
            "failure_reason": None,
        }
    return {
        "fresh": False,
        "stale": latest.id != successful_run.id,
        "warning": None,
        "latest_attempt_status": latest.status,
        "latest_attempt_run_id": latest.id,
        "failure_reason": getattr(latest, "failure_reason", None),
    }


def _merge_canonical_freshness(
    current: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    """Prefer any stale/failed attempt signal across dashboard scopes."""

    if not candidate.get("stale"):
        return current
    if not current.get("stale"):
        return candidate
    if (
        candidate.get("latest_attempt_status") == "failed"
        and current.get("latest_attempt_status") != "failed"
    ):
        return candidate
    return current


def empty_dashboard_payload(*, reason: str = "no_data") -> dict[str, Any]:
    unavailable = {"available": False, "reason": reason}
    current = {
        "available": False,
        "reason": reason,
        "value_kg": None,
        "observed_date": None,
        "metric_origin": "source-provider",
    }
    series = {
        "raw_points": [],
        "daily_points": [],
        "trend_points": [],
        "trend_algorithm": "weight_trend_taewma_v1",
        "trend_available": False,
        "trend_reason": reason,
        "input_count": 0,
        "covered_span_days": None,
        "exclusions": [],
        "composition_by_group": {},
        "goal_kg": None,
        "current": current,
        "canonical": {
            "available": False,
            "reason": reason,
            "selection_count": 0,
            "fresh": False,
            "stale": False,
            "warning": None,
            "latest_attempt_status": None,
            "latest_attempt_run_id": None,
            "failure_reason": None,
        },
        "algorithm_boundary": {
            "present": False,
            "groups": [],
            "warning": None,
        },
        "bia_uncertainty": BIA_UNCERTAINTY,
        "metric_labels": {},
    }
    summary = {
        "trend": {"algorithm": "weight_trend_taewma_v1", **unavailable, "points": []},
        "rate": {
            "algorithm": "weight_rate_theil_sen_90d_v1",
            **unavailable,
            "slope_kg_per_week": None,
            "observation_count": 0,
            "covered_span_days": None,
        },
        "latest_composition": {"algorithm": "body_composition_decomposition_v1", **unavailable},
        "similar_weight": {**unavailable, "caution": BIA_UNCERTAINTY},
        "coverage": None,
        "goal_kg": None,
        "current": current,
        "algorithm_boundary": series["algorithm_boundary"],
        "bia_uncertainty": BIA_UNCERTAINTY,
        "canonical": series["canonical"],
        "composition_by_group": {},
    }
    return {
        "series": series,
        "summary": summary,
        "bia_uncertainty": BIA_UNCERTAINTY,
        "algorithm_boundary": series["algorithm_boundary"],
        "goal_kg": None,
        "current": current,
        "imports": {
            "batch_count": 0,
            "pending_candidate_count": 0,
            "confirmed_candidate_count": 0,
            "rejected_candidate_count": 0,
            "batches": [],
        },
        "unavailable_reason": reason,
    }


def effective_candidate(view: dict[str, Any]) -> dict[str, Any]:
    payload = dict(view)
    payload["effective_value"] = (
        view["edited_value"] if view.get("edited_value") is not None else view.get("proposed_value")
    )
    payload["effective_unit"] = view.get("edited_unit") or view.get("proposed_unit")
    payload["effective_date"] = view.get("edited_source_local_date") or view.get(
        "proposed_source_local_date"
    )
    payload["effective_timestamp"] = view.get("edited_source_timestamp") or view.get(
        "proposed_source_timestamp"
    )
    payload["is_pending"] = view.get("user_decision") == "pending"
    payload["already_committed"] = view.get("scalar_measurement_id") is not None
    return payload


def group_review_events(batch: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = {item["id"]: item for item in batch.get("artifacts") or []}
    events = list(batch.get("events") or [])
    candidates_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in batch.get("candidates") or []:
        candidates_by_event[candidate["ingest_event_id"]].append(effective_candidate(candidate))
    groups = []
    for event in events:
        artifact = artifacts.get(event.get("raw_artifact_id"))
        groups.append(
            {
                "event": event,
                "artifact": artifact,
                "candidates": candidates_by_event.get(event["id"], []),
            }
        )
    return groups


def _current_weight(points: tuple[Any, ...]) -> dict[str, Any]:
    if not points:
        return {
            "available": False,
            "reason": "no_data",
            "value_kg": None,
            "observed_date": None,
            "metric_origin": "source-provider",
        }
    latest = points[-1]
    return {
        "available": True,
        "reason": None,
        "value_kg": latest.value_kg,
        "observed_date": latest.observed_date.isoformat(),
        "evidence_id": latest.evidence_id,
        "metric_origin": "source-provider",
    }


def _composition_point_payload(point: CompositionPoint) -> dict[str, Any]:
    payload = point.as_dict()
    payload["metric_origins"] = {
        "weight_kg": "source-provider",
        "body_fat_pct": "source-provider",
        "source_muscle_mass_kg": "source-provider",
        "estimated_fat_mass_kg": "healthcheck-derived",
        "estimated_lean_mass_kg": "healthcheck-derived",
    }
    return payload
