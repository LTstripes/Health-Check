"""Saved Garmin minutes, with calendar-week coverage and attributed weighted totals."""

from datetime import date, timedelta
from decimal import Decimal
from math import isfinite

from sqlalchemy import and_, select

from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord

FIELDS = {
    "moderate": ("daily_moderate_intensity_min", "moderateIntensityMinutes"),
    "vigorous": ("daily_vigorous_intensity_min", "vigorousIntensityMinutes"),
    "goal": ("intensity_minutes_goal", "intensityMinutesGoal"),
}
MAX_DAYS = 366
MAX_METRICS = 12000


def minutes_display(value):
    if value is None:
        return None
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _sum(values):
    return sum(values, Decimal(0)) if values else None


def _week(rows):
    paired = [row["total"] for row in rows if row["total"] is not None]
    goals = [row for row in rows if row["goal"] is not None]
    week = {"start": rows[0]["date"], "end": rows[-1]["date"], "days": len(rows),
            "count": len(paired), "complete": len(paired) == len(rows),
            "total": _sum(paired), "goal": goals[-1]["goal"] if goals else None,
            "goal_date": goals[-1]["date"] if goals else None}
    for key in ("moderate", "vigorous"):
        values = [row[key] for row in rows if row[key] is not None]
        week[key] = _sum(values)
        week[f"{key}_count"] = len(values)
    week["display"] = {key: minutes_display(week[key])
                       for key in ("moderate", "vigorous", "total", "goal")}
    return week


def read_intensity_minutes(session, *, source_id, start: date, end: date):
    """Expand the first week to Monday; the final week stops at the supplied date.

    Calendar labels stay local as saved. One selected source, current daily-summary
    records only. Colliding records withhold the day, including metricless legacy
    records. A goal is the latest usable report within its week, never carried over.
    No provider calls, normalization, writes, or inference of missing components.
    """
    packet = {"source_id": source_id, "requested_start": start, "start": start, "end": end,
              "rows": [], "weeks": [], "reason": None}
    days = (end - start).days + 1
    if days < 1 or days > MAX_DAYS:
        return dict(packet, reason="unsupported_period")
    lower = start - timedelta(days=start.weekday())
    packet["start"] = lower
    codes = {code: (key, leaf) for key, (code, leaf) in FIELDS.items()}
    candidates = []
    if source_id:
        candidates = session.execute(select(GarminSourceRecord, GarminRecordMetric).outerjoin(
            GarminRecordMetric, and_(
                GarminRecordMetric.record_id == GarminSourceRecord.id,
                GarminRecordMetric.metric_code.in_(codes),
            ),
        ).where(
            GarminSourceRecord.garmin_source_id == source_id,
            GarminSourceRecord.stream_code == "daily_health",
            GarminSourceRecord.surface_code.in_(["daily_summary"])
            | GarminSourceRecord.surface_code.is_(None),
            GarminSourceRecord.projection_status == "current",
            GarminSourceRecord.source_local_date.between(lower, end),
        ).limit(MAX_METRICS + 1)).all()
    else:
        packet["reason"] = "source_not_selected"
    if len(candidates) > MAX_METRICS:
        candidates = []
        packet["reason"] = "search_incomplete"
    by_day = {}
    for record, metric in candidates:
        by_day.setdefault(record.source_local_date, {}).setdefault(record.id, []).append(
            (record, metric))
    for index in range((end - lower).days + 1):
        day = lower + timedelta(days=index)
        row = {"date": day, **dict.fromkeys(FIELDS), "total": None, "evidence": []}
        records = by_day.get(day, {})
        if len(records) == 1:
            for record, metric in next(iter(records.values())):
                if metric is None:
                    continue
                key, leaf = codes[metric.metric_code]
                row["evidence"].append({"record_id": record.id,
                    "raw_payload_id": record.raw_payload_id, "path": metric.field_path,
                    "state": metric.state, "contract": record.normalization_contract_version})
                number = metric.value_number
                if (record.record_status in {"ok", "partial"} and metric.state == "value"
                        and metric.unit == "min" and metric.capability_code == "intensity_minutes"
                        and metric.field_path == f"payload.{leaf}"
                        and isinstance(number, (int, float)) and not isinstance(number, bool)
                        and isfinite(number) and number >= 0):
                    row[key] = Decimal(str(number))
        if row["moderate"] is not None and row["vigorous"] is not None:
            row["total"] = row["moderate"] + 2 * row["vigorous"]
        row["display"] = {key: minutes_display(row[key]) for key in (*FIELDS, "total")}
        packet["rows"].append(row)
    for offset in range(0, len(packet["rows"]), 7):
        packet["weeks"].append(_week(packet["rows"][offset:offset + 7]))
    return packet
