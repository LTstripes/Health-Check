"""Bounded eligible persisted sessions for Statistics drilldown (#378).

Eligibility mirrors the originating #347 activity metric. Search completeness
describes this saved-record window only; it never establishes provider coverage.
"""

from collections import Counter, defaultdict
from datetime import date
from math import isfinite

from sqlalchemy import select

from healthcheck.analytics.period_summary import METRICS, SLEEP_CODE
from healthcheck.analytics.period_summary_read import IncompletePeriodRead, PeriodReadBudget
from healthcheck.db.models import GarminRecordMetric, GarminSource, GarminSourceRecord
from healthcheck.garmin.analytic_contract import project_activity_metric_quality
from healthcheck.web.read_snapshot import ensure_read_snapshot

MAX_CANDIDATE_RECORDS = 4096
MAX_DISPLAY_SESSIONS = 200
SPORTS = {"all": None, "cycling": {"cycling"}, "tennis": {"tennis", "tennis_v2"}}


def read_activity_period_sessions(
    session,
    *,
    source_id: str,
    start_date: date,
    end_date: date,
    metric_code: str,
    sport: str,
) -> dict:
    if (
        not source_id
        or metric_code not in METRICS
        or metric_code == SLEEP_CODE
        or sport not in SPORTS
        or not 1 <= (end_date - start_date).days + 1 <= 366
    ):
        raise ValueError("invalid activity period selection")
    required_sport = (
        "cycling"
        if metric_code == "cycling_distance_meters"
        else "tennis"
        if metric_code.startswith("tennis_")
        else None
    )
    if required_sport and sport != required_sport:
        raise ValueError("sport conflicts with originating metric")
    ensure_read_snapshot(session)
    source = session.get(GarminSource, source_id)
    if source is None or source.provider_code != "garmin_connect":
        raise ValueError("unknown Garmin source")
    packet = {
        "quality_rule_version": "garmin-activity-quality-v1",
        "source_id": source_id,
        "metric_code": metric_code,
        "sport": sport,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "sessions": [],
        "complete": False,
        "reason": None,
        "candidate_cap": MAX_CANDIDATE_RECORDS,
        "display_cap": MAX_DISPLAY_SESSIONS,
    }
    try:
        with PeriodReadBudget(session) as budget:
            # Include all sports before identity checks: a duplicate in another
            # sport must not make the selected session appear unique.
            records = budget.rows(
                select(GarminSourceRecord)
                .where(
                    GarminSourceRecord.garmin_source_id == source_id,
                    GarminSourceRecord.stream_code == "activity",
                    GarminSourceRecord.projection_status == "current",
                    GarminSourceRecord.source_local_date.between(start_date, end_date),
                )
                .order_by(GarminSourceRecord.source_local_date, GarminSourceRecord.id),
                MAX_CANDIDATE_RECORDS,
                "candidate_record_limit_exceeded",
            )
            identities = Counter(r.external_record_id or r.id for r in records)
            metrics = budget.related(
                GarminRecordMetric,
                GarminRecordMetric.record_id,
                [r.id for r in records],
                cap=MAX_CANDIDATE_RECORDS * 2,
                conditions=(
                    GarminRecordMetric.metric_code.in_(
                        ["duration_seconds", "distance_meters"],
                    ),
                ),
            )
            grouped = defaultdict(list)
            for metric in metrics:
                grouped[metric.record_id].append(metric)
            by_metric = {}
            for record in records:
                projected = project_activity_metric_quality(grouped[record.id])
                by_metric.update({(record.id, code): m for code, m in projected.items()})
            field = {
                "tennis_duration_seconds": "duration_seconds",
                "cycling_distance_meters": "distance_meters",
            }.get(metric_code)
            eligible = []
            for row in records:
                budget.check()
                if (
                    row.record_status == "invalid"
                    or identities[row.external_record_id or row.id] != 1
                    or (SPORTS[sport] is not None and row.activity_type not in SPORTS[sport])
                ):
                    continue
                metric = by_metric.get((row.id, field))
                if field and (
                    metric is None
                    or metric.state != "value"
                    or metric.unit != METRICS[metric_code][1]
                    or metric.value is None
                    or not isfinite(metric.value)
                    or metric.value < 0
                ):
                    continue
                eligible.append(
                    {
                        "record_id": row.id,
                        "external_record_id": row.external_record_id,
                        "source_local_date": row.source_local_date.isoformat(),
                        "activity_type": row.activity_type,
                        "record_status": row.record_status,
                        "metrics": {
                            code: {
                                "state": m.state.value,
                                "reason": m.reason,
                                "value": m.value,
                                "unit": m.unit,
                                "displayable": m.state == "value"
                                and m.value is not None
                                and isfinite(m.value)
                                and m.value >= 0,
                            }
                            if (m := by_metric.get((row.id, code))) is not None
                            else {
                                "state": "missing",
                                "value": None,
                                "unit": None,
                                "displayable": False,
                            }
                            for code in ("duration_seconds", "distance_meters")
                        },
                    }
                )
                # One extra eligible session proves that the display is capped.
                if len(eligible) > MAX_DISPLAY_SESSIONS:
                    break
            budget.check()
            packet["sessions"] = eligible[:MAX_DISPLAY_SESSIONS]
            packet["complete"] = len(eligible) <= MAX_DISPLAY_SESSIONS
            packet["reason"] = None if packet["complete"] else "display_session_limit_exceeded"
    except IncompletePeriodRead as exc:
        # Unknown input completeness cannot justify eligibility or an empty list.
        packet["reason"] = str(exc)
    return packet
