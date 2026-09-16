"""Application service for the #119 deterministic period brief.

Routes/CLI stay thin. This module gathers inputs through existing weight,
Garmin, sleep-report and coverage services, then hands frozen section inputs
to the pure period-brief packet assembler.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.analytics.garmin_activity_comparison import (
    ACTIVITY_COMPARISON_METRIC_CODES,
    MAX_SELECTED_ACTIVITIES,
    MIN_SELECTED_ACTIVITIES,
    GarminActivityComparisonQuery,
    analyze_garmin_activity_comparison,
)
from healthcheck.analytics.garmin_baselines import (
    GarminSeriesQuery,
    analyze_garmin_metric_series,
)
from healthcheck.analytics.period_brief import (
    PERIOD_BRIEF_ACTIVITY_SELECTION_POLICY,
    baseline_summary_from_result,
    build_period_brief_packet,
    normalize_period,
    render_period_brief_text,
    thin_period_brief_for_display,
)
from healthcheck.analytics.sleep_agreement_report import SleepAgreementReportService
from healthcheck.config import Settings
from healthcheck.db.models import GarminProjectionStatus, GarminSourceRecord
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.web.garmin_query import DEFAULT_SCALAR_METRIC, GarminQueryService
from healthcheck.web.query import WeightQueryService

PERIOD_BRIEF_SLEEP_BASELINE_METRICS = ("sleep_duration_seconds", "sleep_score")
PERIOD_BRIEF_ACTIVITY_BASELINE_METRICS = (DEFAULT_SCALAR_METRIC, "spo2_daily_average")


class PeriodBriefService:
    """Session-backed assembler that only consumes existing analytics services."""

    def __init__(self, session: Session, settings: Settings | None = None):
        self.session = session
        self.settings = settings or Settings()
        self.weight = WeightQueryService(session, self.settings)
        self.garmin = GarminQueryService(session, self.settings)
        self.sleep = SleepAgreementReportService(session)

    def build(
        self,
        *,
        start_date: date,
        end_date: date,
        garmin_source_id: str | None = None,
    ) -> dict[str, Any]:
        period = normalize_period(start_date, end_date)
        weight_summary = self.weight.summary(start_date=start_date, end_date=end_date)
        import_queue = self.weight.import_queue_summary()
        sleep_report = self.sleep.report(start_date=start_date, end_date=end_date)

        activities: list[dict[str, Any]] = []
        comparison: dict[str, Any] | None = None
        selection_policy: str | None = None
        sleep_baselines: list[dict[str, Any]] = []
        activity_baselines: list[dict[str, Any]] = []
        source_selection = self.garmin.resolve_source(garmin_source_id)
        selected_id = source_selection.get("selected_source_id")
        if selected_id:
            activities = self._list_activities_in_period(
                selected_id, period.start_date, period.end_date
            )
            comparison, selection_policy = self._maybe_compare_activities(selected_id, activities)
            sleep_baselines = self._safe_baselines(
                selected_id, period.start_date, period.end_date, PERIOD_BRIEF_SLEEP_BASELINE_METRICS
            )
            activity_baselines = self._safe_baselines(
                selected_id,
                period.start_date,
                period.end_date,
                PERIOD_BRIEF_ACTIVITY_BASELINE_METRICS,
            )
            activity_inventory_status = "inventoried"
        elif (
            source_selection.get("status") == "no_data"
            or source_selection.get("reason") == "no_garmin_sources"
        ):
            # Source absent: do not conflate with an inventoried empty window.
            activity_inventory_status = "unavailable"
        else:
            # e.g. multiple sources require selection — inventory was not attempted.
            activity_inventory_status = "unknown"

        return build_period_brief_packet(
            period=period,
            weight_summary=weight_summary,
            sleep_report=sleep_report,
            activities=activities,
            activity_comparison=comparison,
            activity_selection_policy=selection_policy,
            activity_inventory_status=activity_inventory_status,
            sleep_baselines=sleep_baselines,
            activity_baselines=activity_baselines,
            import_queue=import_queue,
        )

    def build_with_render(
        self,
        *,
        start_date: date,
        end_date: date,
        garmin_source_id: str | None = None,
        thin_display: bool = False,
    ) -> dict[str, Any]:
        packet = self.build(
            start_date=start_date, end_date=end_date, garmin_source_id=garmin_source_id
        )
        display = thin_period_brief_for_display(packet) if thin_display else packet
        return {
            "packet": packet,
            "display": display if thin_display else None,
            "rendered_text": render_period_brief_text(display if thin_display else packet),
        }

    def _list_activities_in_period(
        self, garmin_source_id: str, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        rows = list(
            self.session.scalars(
                select(GarminSourceRecord)
                .where(
                    GarminSourceRecord.garmin_source_id == garmin_source_id,
                    GarminSourceRecord.stream_code == "activity",
                    GarminSourceRecord.projection_status == GarminProjectionStatus.CURRENT.value,
                    GarminSourceRecord.source_local_date >= start_date,
                    GarminSourceRecord.source_local_date <= end_date,
                )
                .order_by(
                    GarminSourceRecord.source_local_date.asc(),
                    GarminSourceRecord.id.asc(),
                )
                .limit(100)
            )
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            timestamp = restore_stored_utc(row.source_timestamp_utc)
            out.append(
                {
                    "record_id": row.id,
                    "external_record_id": row.external_record_id,
                    "activity_type": row.activity_type,
                    "source_local_date": (
                        row.source_local_date.isoformat()
                        if row.source_local_date is not None
                        else None
                    ),
                    "measured_at_utc": timestamp.isoformat() if timestamp is not None else None,
                }
            )
        return out

    def _maybe_compare_activities(
        self, garmin_source_id: str, activities: Sequence[Mapping[str, Any]]
    ) -> tuple[dict[str, Any] | None, str | None]:
        by_type: dict[str, list[Mapping[str, Any]]] = {}
        for item in activities:
            activity_type = str(item.get("activity_type") or "")
            if not activity_type or not item.get("record_id"):
                continue
            by_type.setdefault(activity_type, []).append(item)
        ranked = sorted(by_type.items(), key=lambda pair: (-len(pair[1]), pair[0]))
        if not ranked or len(ranked[0][1]) < MIN_SELECTED_ACTIVITIES:
            return None, None
        selected = ranked[0][1][:MAX_SELECTED_ACTIVITIES]
        record_ids = tuple(str(item["record_id"]) for item in selected)
        query = GarminActivityComparisonQuery(
            garmin_source_id=garmin_source_id,
            activity_record_ids=record_ids,
            reference_activity_id=record_ids[0],
            metric_codes=ACTIVITY_COMPARISON_METRIC_CODES,
        )
        try:
            result = analyze_garmin_activity_comparison(self.session, query)
        except Exception:  # noqa: BLE001 - optional comparison stays fail-soft
            return None, None
        return result.as_dict(), PERIOD_BRIEF_ACTIVITY_SELECTION_POLICY

    def _safe_baselines(
        self,
        garmin_source_id: str,
        start_date: date,
        end_date: date,
        metric_codes: Sequence[str],
    ) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        start = start_date
        end = end_date
        if (end - start).days + 1 > 180:
            start = end - timedelta(days=179)
        for metric_code in metric_codes:
            query = GarminSeriesQuery(
                metric_code=metric_code,
                start_date=start,
                end_date=end,
                garmin_source_id=garmin_source_id,
            )
            try:
                result = analyze_garmin_metric_series(self.session, query)
            except Exception:  # noqa: BLE001 - optional section inputs
                summaries.append(
                    {
                        "metric_code": metric_code,
                        "availability": "unavailable",
                        "latest_value": None,
                        "personal_baseline_deviation": False,
                        "trend_slope_per_day": None,
                        "result_hash": None,
                        "reason": "baseline_unavailable",
                    }
                )
                continue
            summaries.append(baseline_summary_from_result(result.as_dict()))
        return summaries


__all__ = ["PeriodBriefService"]
