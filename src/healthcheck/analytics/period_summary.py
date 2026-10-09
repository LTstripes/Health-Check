"""Read-only #347 B1 saved-source summaries; never a combined provider total.

Version 1 accepts 7/30 inclusive source-local days. Activity types are frozen to
cycling and tennis|tennis_v2. Sleep uses R05 account-observation scalar/role
eligibility, independently of Agreement. Acquisition coverage is separate from
observed values. Provider-wide coverage cannot establish a device's coverage.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from math import fsum, isfinite
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from healthcheck.analytics.coverage import COVERAGE_STATUSES, calculate_coverage
from healthcheck.analytics.sleep_source_view import read_source_sleep_night
from healthcheck.db.models import (
    CoverageInterval,
    GarminPayloadObservation,
    GarminRecordMetric,
    GarminSleepRecord,
    GarminSource,
    GarminSourceRecord,
    GooglePayloadObservation,
    GoogleSleepRecord,
    GoogleSource,
    GoogleSourceRecord,
)
from healthcheck.web.period_brief_query import PeriodBriefService
from healthcheck.web.read_snapshot import ensure_read_snapshot

CONTRACT_VERSION = "source-period-summary-v1"
SLEEP_CODE = "sleep_duration_asleep_seconds"
METRICS = {
    "activity_session_count": ("count", "sessions", "eligible_saved_sessions"),
    "activity_type_counts": ("counts_by_type", "sessions", "eligible_saved_sessions"),
    "cycling_distance_meters": ("total", "meters", "eligible_saved_sessions"),
    "tennis_session_count": ("count", "sessions", "eligible_saved_sessions"),
    "tennis_duration_seconds": ("total", "seconds", "eligible_saved_sessions"),
    SLEEP_CODE: ("mean", "seconds", "eligible_saved_nights"),
}


def _bounds(dates: list[str]) -> dict[str, str | None]:
    return {
        "min_observed": min(dates) if dates else None,
        "max_observed": max(dates) if dates else None,
    }


def _coverage_unknown(days: int, state: str = "unestablished") -> dict[str, Any]:
    return {
        "state": state,
        "complete": False,
        "status_counts": {s: days if s == "unknown" else 0 for s in COVERAGE_STATUSES},
        "rule_versions": [],
    }


def _identity(source: GarminSource | GoogleSource) -> dict[str, Any]:
    return {
        "source_id": source.id,
        "source_kind": source.source_kind,
        "source_instance_id": source.source_instance_id,
        "device_attributed": source.device_attributed,
        "device_attribution_basis": "persisted_source_identity",
        "device_code": source.device_code,
        "device_model": source.device_model,
        "recording_method": getattr(source, "recording_method", None),
    }


def _cell(
    metric: str,
    *,
    values: list[float],
    dates: list[str],
    observed_dates: list[str],
    observed_count: int,
    exclusions: Counter,
    partial: int = 0,
    uncertain: int = 0,
    retired: int = 0,
    history_reasons: Counter | None = None,
    type_counts: Counter | None = None,
    proven_empty: bool = False,
) -> dict[str, Any]:
    kind, unit, denominator = METRICS[metric]
    count = len(values)
    numerator = fsum(values) if values else (0 if proven_empty else None)
    value: Any = numerator
    if kind == "mean":
        value = numerator / count if count else None
    elif kind == "counts_by_type":
        value = dict(sorted((type_counts or {}).items())) if count or proven_empty else None
    reasons = Counter(exclusions)
    reasons.update({f"retired:{k}": v for k, v in (history_reasons or {}).items()})
    return {
        "canonical_metric_code": metric,
        "unit": unit,
        "aggregation": {
            "kind": kind,
            "value": value,
            "numerator": numerator,
            "denominator": denominator,
            "eligible_count": count,
            "excluded_count": sum(exclusions.values()) + retired,
        },
        "observed_count": observed_count,
        "observed_day_count": len(set(observed_dates)),
        "observed_calendar_dates": sorted(set(observed_dates)),
        "eligible_dates": sorted(set(dates)),
        "effective_dates": _bounds(dates),
        "observed_dates": _bounds(observed_dates),
        "availability_counts": {
            "candidate": observed_count,
            "usable": count,
            "zero": sum(v == 0 for v in values),
            "excluded": sum(exclusions.values()),
            "missing": exclusions["metric_missing"],
            "null": exclusions["metric_null"],
            "invalid": exclusions["metric_invalid"],
            "partial": partial,
            "uncertain": uncertain,
            "retired": retired,
        },
        "exclusions": [{"reason_code": k, "count": v} for k, v in sorted(reasons.items())],
    }


class PeriodSummaryService:
    """Consumer-neutral packet from existing typed persistence in one snapshot."""

    def __init__(self, session: Session):
        self.session = session

    def build(
        self,
        *,
        end_date: date,
        days: int,
        garmin_source_id: str | None = None,
        google_source_id: str | None = None,
    ) -> dict[str, Any]:
        if type(end_date) is not date or type(days) is not int or days not in {7, 30}:
            raise ValueError("period summary requires an end date and 7 or 30 inclusive days")
        start = end_date - timedelta(days=days - 1)
        ensure_read_snapshot(self.session)
        sides = []
        for position, provider, model, selected in (
            ("left", "garmin_connect", GarminSource, garmin_source_id),
            ("right", "google_health", GoogleSource, google_source_id),
        ):
            sources = list(
                self.session.scalars(
                    select(model).where(model.provider_code == provider).order_by(model.id)
                )
            )
            source = (
                next((s for s in sources if s.id == selected), None)
                if selected
                else (sources[0] if len(sources) == 1 else None)
            )
            if selected and source is None:
                raise ValueError(f"unknown selected {provider} source")
            side = {
                "position": position,
                "provider_code": provider,
                "source_identity": _identity(source) if source else None,
                "available_sources": [_identity(s) for s in sources],
                "state": "selected"
                if source
                else ("selection_required" if sources else "source_missing"),
                "requested_dates": {
                    "start_date": start.isoformat(),
                    "end_date": end_date.isoformat(),
                },
                "freshness": {"state": "unknown", "reason": "saved_period_not_live_freshness"},
                "metrics": {},
            }
            for metric in METRICS:
                cell = _cell(
                    metric,
                    values=[],
                    dates=[],
                    observed_dates=[],
                    observed_count=0,
                    exclusions=Counter(),
                )
                cell["state"] = side["state"]
                cell["coverage"] = _coverage_unknown(days)
                cell["snapshot_evidence"] = self._snapshot_evidence([], google=False)
                side["metrics"][metric] = cell
            if provider == "google_health":
                for metric, cell in side["metrics"].items():
                    if metric != SLEEP_CODE:
                        cell["state"] = "not_collected"
                        cell["coverage"] = _coverage_unknown(days, "not_collected")
            if source:
                if provider == "garmin_connect":
                    side["metrics"].update(self._activities(source, start, end_date))
                side["metrics"][SLEEP_CODE] = self._sleep(source, start, end_date)
            for metric, cell in side["metrics"].items():
                observed_dates = set(cell["observed_calendar_dates"])
                cell["missing_dates"] = [
                    day.isoformat()
                    for offset in range(days)
                    if (day := start + timedelta(days=offset)).isoformat() not in observed_dates
                ]
                cell["missing_day_count"] = len(cell["missing_dates"])
                cell["source_metric_code"] = (
                    (
                        "sleep_duration_seconds"
                        if provider == "garmin_connect"
                        else "sleep_summary_minutes_asleep"
                    )
                    if metric == SLEEP_CODE
                    else {
                        "cycling_distance_meters": "distance_meters",
                        "tennis_duration_seconds": "duration_seconds",
                    }.get(metric, "activity_type")
                )
                cell["source_unit"] = (
                    "min"
                    if (provider == "google_health" and metric == SLEEP_CODE)
                    else cell["unit"]
                )
                cell["conversion"] = (
                    "minutes_times_60_v1"
                    if (provider == "google_health" and metric == SLEEP_CODE)
                    else "identity_v1"
                )
            sides.append(side)
        deltas = {
            metric: self._delta(sides[0]["metrics"][metric], sides[1]["metrics"][metric])
            for metric in METRICS
        }
        return {
            "contract_version": CONTRACT_VERSION,
            "requested_window": {
                "start_date": start.isoformat(),
                "end_date": end_date.isoformat(),
                "inclusive_days": days,
            },
            "evaluated_at": datetime.now(UTC).isoformat(),
            "sides": sides,
            "deltas": deltas,
            "blocked_metrics": {
                "steps": "typed_stream_not_available",
                "calories": "pending_319_source_fields_units",
            },
        }

    def _coverage(self, source, start: date, end: date, surface: str) -> dict[str, Any]:
        days = (end - start).days + 1
        google = isinstance(source, GoogleSource)
        # Google sync currently stores provider/query-family coverage without
        # actual-source attribution. Do not reinterpret it as device coverage.
        rows = list(
            self.session.scalars(
                select(CoverageInterval).where(
                    CoverageInterval.provider_id == source.provider_id,
                    CoverageInterval.acquisition_source_id == source.acquisition_source_id,
                    CoverageInterval.metric_code == ("google_coverage" if google else surface),
                    CoverageInterval.interval_start
                    < datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC),
                    CoverageInterval.interval_end > datetime.combine(start, time.min, tzinfo=UTC),
                )
            )
        )
        if google:
            rows = [r for r in rows if ":sleep:" in r.stream_code]
        # An acquisition identity shared by multiple actual sources is not a
        # source-specific completeness proof, even after explicit selection.
        model = GoogleSource if google else GarminSource
        siblings = list(
            self.session.scalars(
                select(model.id).where(model.acquisition_source_id == source.acquisition_source_id)
            )
        )
        if not rows or len(siblings) != 1:
            return _coverage_unknown(days)
        summary = calculate_coverage(
            start, end, observations=(), coverage_intervals=rows, cadence_days=1, as_of_date=end
        )
        counts = dict(summary.status_counts)
        complete = all(b.status in {"present", "confirmed_empty"} for b in summary.bins)
        state = (
            ("confirmed_empty" if counts["confirmed_empty"] == days else "present")
            if (complete)
            else ("unavailable" if counts["failed"] or counts["unavailable"] else "unknown")
        )
        return {
            "state": state,
            "complete": complete,
            "status_counts": counts,
            "day_statuses": {b.start_date.isoformat(): b.status for b in summary.bins},
            "rule_versions": sorted({r.calculation_rule_version for r in rows}),
        }

    @staticmethod
    def _observed_coverage(coverage: dict, observed_dates: list[str]) -> dict:
        conflicts = sorted(
            {
                d
                for d in observed_dates
                if coverage.get("day_statuses", {}).get(d) == "confirmed_empty"
            }
        )
        if conflicts:
            return {
                **coverage,
                "complete": False,
                "state": "contradictory",
                "observed_on_confirmed_empty_dates": conflicts,
            }
        return coverage

    def _activities(self, source: GarminSource, start: date, end: date) -> dict[str, Any]:
        inventory = PeriodBriefService(self.session)._list_activities_in_period(
            source.id, start, end
        )
        records = list(
            self.session.scalars(
                select(GarminSourceRecord).where(
                    GarminSourceRecord.garmin_source_id == source.id,
                    GarminSourceRecord.stream_code == "activity",
                    GarminSourceRecord.source_local_date.between(start, end),
                )
            )
        )
        by_id = {r.id: r for r in records}
        current = [by_id[item["record_id"]] for item in inventory]
        identity_counts = Counter(r.external_record_id or r.id for r in current)
        metric_rows = {
            (m.record_id, m.metric_code): m
            for m in self.session.scalars(
                select(GarminRecordMetric).where(
                    GarminRecordMetric.record_id.in_([r.id for r in current]),
                    GarminRecordMetric.metric_code.in_(["distance_meters", "duration_seconds"]),
                )
            )
        }
        coverage = self._observed_coverage(
            self._coverage(source, start, end, "activities"),
            [r.source_local_date.isoformat() for r in current],
        )
        result = {}
        for code in METRICS:
            if code == SLEEP_CODE:
                continue
            types = (
                {"cycling"}
                if code == "cycling_distance_meters"
                else ({"tennis", "tennis_v2"} if code.startswith("tennis_") else None)
            )
            candidates = [
                r
                for r in current
                if types is None or r.activity_type in types or not (r.activity_type or "").strip()
            ]
            history = Counter(
                r.retire_reason or "unspecified"
                for r in records
                if r.projection_status == "retired" and (types is None or r.activity_type in types)
            )
            values, dates = [], []
            exclusions, type_counts = Counter(), Counter()
            partial = 0
            for row in candidates:
                reason = None
                value = 1
                if row.record_status == "invalid":
                    reason = "record_invalid"
                elif identity_counts[row.external_record_id or row.id] != 1:
                    reason = "duplicate_current_identity"
                elif types is not None and not (row.activity_type or "").strip():
                    reason = "activity_type_missing"
                elif code in {"cycling_distance_meters", "tennis_duration_seconds"}:
                    field = (
                        "distance_meters"
                        if code == "cycling_distance_meters"
                        else ("duration_seconds")
                    )
                    metric = metric_rows.get((row.id, field))
                    if metric is None or metric.state != "value":
                        reason = f"metric_{metric.state if metric else 'missing'}"
                    elif metric.unit != METRICS[code][1]:
                        reason = "metric_unit_mismatch"
                    elif (
                        metric.value_number is None
                        or not isfinite(metric.value_number)
                        or metric.value_number < 0
                    ):
                        reason = "metric_invalid"
                    else:
                        value = metric.value_number
                if reason:
                    exclusions[reason] += 1
                else:
                    values.append(value)
                    dates.append(row.source_local_date.isoformat())
                    partial += row.record_status == "partial"
                    activity_type = (
                        row.activity_type if (row.activity_type or "").strip() else "unknown"
                    )
                    type_counts[activity_type] += 1
            cell = _cell(
                code,
                values=values,
                dates=dates,
                observed_dates=[r.source_local_date.isoformat() for r in candidates],
                observed_count=len(candidates),
                exclusions=exclusions,
                partial=partial,
                retired=sum(history.values()),
                history_reasons=history,
                type_counts=type_counts,
                proven_empty=not candidates
                and coverage["complete"]
                and METRICS[code][0] in {"count", "counts_by_type"},
            )
            cell["coverage"] = coverage
            cell["snapshot_evidence"] = self._snapshot_evidence(
                [r for r in records if types is None or r.activity_type in types], google=False
            )
            cell["state"] = (
                "observed"
                if values
                else (
                    "confirmed_empty"
                    if cell["aggregation"]["value"] is not None
                    else "no_eligible_values"
                )
            )
            result[code] = cell
        return result

    def _sleep(self, source, start: date, end: date) -> dict[str, Any]:
        google = isinstance(source, GoogleSource)
        provider = "google" if google else "garmin"
        model, typed, column = (
            (GoogleSourceRecord, GoogleSleepRecord, GoogleSourceRecord.google_source_id)
            if google
            else (GarminSourceRecord, GarminSleepRecord, GarminSourceRecord.garmin_source_id)
        )
        records = list(
            self.session.execute(
                select(model, typed.wake_date)
                .outerjoin(typed, typed.record_id == model.id)
                .where(
                    column == source.id,
                    model.stream_code == "sleep",
                    or_(
                        typed.wake_date.between(start, end),
                        typed.wake_date.is_(None) & model.source_local_date.between(start, end),
                    ),
                )
            )
        )
        by_date = defaultdict(list)
        history = Counter()
        missing_wake = 0
        for record, wake_date in records:
            if record.projection_status == "current":
                if wake_date is None:
                    missing_wake += 1
                else:
                    by_date[wake_date].append(record)
            else:
                history[record.retire_reason or "unspecified"] += 1
        values, dates, observed_dates = [], [], []
        exclusions = Counter()
        exclusions["wake_date_missing"] = missing_wake
        partial = uncertain = 0
        observed = missing_wake
        for wake_date, rows in sorted(by_date.items()):
            observed += len(rows)
            observed_dates.append(wake_date.isoformat())
            night = read_source_sleep_night(
                self.session, provider=provider, wake_date=wake_date, source_id=source.id
            )
            if night["state"] == "read_limit_exceeded":
                exclusions["read_limit_exceeded"] += len(rows)
                continue
            sessions = [s for group in night["sources"] for s in group["sessions"]]
            candidates = []
            for item in sessions:
                # Source/record/role gates precede the date uniqueness gate;
                # a missing scalar cannot resolve competing session identity.
                if item["reason"]:
                    exclusions[item["reason"]] += 1
                else:
                    candidates.append(item)
            exclusions["typed_input_unavailable"] += len(rows) - len(sessions)
            if google and any(i["role"]["selection"] == "explicit_main" for i in candidates):
                preferred = [i for i in candidates if i["role"]["selection"] == "explicit_main"]
                exclusions["google_explicit_main_preferred"] += len(candidates) - len(preferred)
                candidates = preferred
            if len(candidates) > 1:
                exclusions[f"ambiguous_{provider}_main"] += len(candidates)
                continue
            if not candidates:
                continue
            item = candidates[0]
            cell = item["metrics"][SLEEP_CODE]
            if not cell["eligible"]:
                reason = (
                    f"metric_{cell['state']}"
                    if cell["state"] != "value"
                    else (cell["reason"] or "metric_invalid")
                )
                exclusions[reason] += 1
            elif cell["value"] < 0:
                exclusions["metric_invalid"] += 1
            else:
                values.append(cell["value"])
                dates.append(wake_date.isoformat())
                partial += item["record_status"] == "partial"
                uncertain += google and item["role"]["selection"] != "explicit_main"
        result = _cell(
            SLEEP_CODE,
            values=values,
            dates=dates,
            observed_dates=observed_dates,
            observed_count=observed,
            exclusions=+exclusions,
            partial=partial,
            uncertain=uncertain,
            retired=sum(history.values()),
            history_reasons=history,
        )
        result["coverage"] = self._observed_coverage(
            self._coverage(source, start, end, "sleep"), observed_dates
        )
        result["snapshot_evidence"] = self._snapshot_evidence(
            [r for r, _wake in records], google=google
        )
        result["state"] = "observed" if values else "no_eligible_values"
        return result

    def _snapshot_evidence(self, records: list, *, google: bool) -> dict[str, Any]:
        """Count saved observation metadata, never payload bodies or extra sessions.

        Replays of a snapshot remain acquisition observations, not another
        activity/night. Counts describe snapshots backing selected-period rows;
        received-at timestamps do not decide their source-local eligibility.
        """
        model = GooglePayloadObservation if google else GarminPayloadObservation
        raw_column = model.google_raw_payload_id if google else model.garmin_raw_payload_id
        counts = (
            list(
                self.session.execute(
                    select(raw_column, func.count(model.id))
                    .where(raw_column.in_({r.raw_payload_id for r in records}))
                    .group_by(raw_column)
                )
            )
            if records
            else []
        )
        return {
            "duplicate_payload_observation_count": sum(max(0, n - 1) for _id, n in counts),
            "normalization_versions": sorted({r.normalization_contract_version for r in records}),
            "retirement_reason_counts": dict(
                sorted(
                    Counter(
                        r.retire_reason or "unspecified"
                        for r in records
                        if r.projection_status == "retired"
                    ).items()
                )
            ),
        }

    @staticmethod
    def _delta(left: dict, right: dict) -> dict[str, Any]:
        reason = None
        if left["aggregation"]["value"] is None or right["aggregation"]["value"] is None:
            reason = "side_without_eligible_value"
        elif left["unit"] != right["unit"]:
            reason = "incompatible_units"
        elif (
            left["canonical_metric_code"] != right["canonical_metric_code"]
            or left["aggregation"]["kind"] != right["aggregation"]["kind"]
        ):
            reason = "incompatible_metric_meaning"
        elif (
            left["aggregation"]["denominator"] != right["aggregation"]["denominator"]
            or left["aggregation"]["eligible_count"] != right["aggregation"]["eligible_count"]
            or left["eligible_dates"] != right["eligible_dates"]
        ):
            reason = "different_observed_windows_or_denominators"
        elif not left["coverage"]["complete"] or not right["coverage"]["complete"]:
            reason = "acquisition_coverage_not_established"
        elif any(
            c["availability_counts"][k]
            for c in (left, right)
            for k in ("partial", "uncertain", "excluded")
        ):
            reason = "partial_uncertain_or_excluded_inputs"
        elif not all(type(c["aggregation"]["value"]) in {int, float} for c in (left, right)):
            reason = "non_numeric_metric"
        return {
            "direction": "right_minus_left",
            "value": None
            if reason
            else (right["aggregation"]["value"] - left["aggregation"]["value"]),
            "reason": reason,
        }
