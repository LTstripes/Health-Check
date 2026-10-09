"""Owner-only display of persisted Garmin snapshots and the accepted Google read.

No statistics, provider calls or canonical selection. Incompatible windows stay
labelled; colliding Garmin snapshots never become one guessed value.
"""

from datetime import date, timedelta
from math import isfinite
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord
from healthcheck.google.daily_vitals import (
    GOOGLE_DAILY_VITALS,
    MAX_GOOGLE_DAILY_VITALS_CALENDAR_DAYS,
    read_google_daily_vitals,
)
from healthcheck.web.garmin_training_overview import training_overview_for_selection
from healthcheck.web.sleep_view import google_vitals_view

# code, source capability, stored unit, Owner meaning
GARMIN_OVERVIEW_METRICS = (
    ("resting_heart_rate_bpm", "resting_heart_rate", "bpm", "Пульс в покое"),
    ("hrv_weekly_average_ms", "hrv_status", "ms", "HRV · среднее за неделю"),
    ("spo2_daily_average", "spo2", "%", "Кислород · среднее за день"),
    ("respiration_bpm", "respiration", "breaths/min", "Дыхание · снимок источника"),
    ("stress_daily_average", "stress", "points", "Стресс Garmin · среднее за день"),
    ("body_battery", "body_battery", "points", "Body Battery Garmin · последний снимок"),
)


def overview_number(value: int | float) -> str:
    """At most two decimals for display; never alter the source value."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def read_overview_values(
    session: Session, *, start: date, end: date, selected_id: str | None,
) -> dict[str, Any]:
    # Bound only this display read; /brief analytics retain the selected period.
    google_start = start
    if (end - start).days + 1 > MAX_GOOGLE_DAILY_VITALS_CALENDAR_DAYS:
        google_start = end - timedelta(days=MAX_GOOGLE_DAILY_VITALS_CALENDAR_DAYS - 1)
    google_results = [
        read_google_daily_vitals(
            session, metric_code=definition.metric_code, start_date=google_start, end_date=end,
        )
        for definition in GOOGLE_DAILY_VITALS
    ]
    google_view = google_vitals_view(google_results)
    google_view["window_limited"] = google_start != start
    garmin: dict[str, Any] = {}
    technical: list[dict[str, Any]] = []
    if selected_id:
        rows = session.execute(
            select(GarminSourceRecord, GarminRecordMetric)
            .join(GarminRecordMetric, GarminRecordMetric.record_id == GarminSourceRecord.id)
            .where(
                GarminSourceRecord.garmin_source_id == selected_id,
                GarminSourceRecord.projection_status == "current",
                GarminSourceRecord.source_local_date >= start,
                GarminSourceRecord.source_local_date <= end,
                GarminRecordMetric.metric_code.in_([item[0] for item in GARMIN_OVERVIEW_METRICS]),
            )
        ).all()
        for code, capability, unit, label in GARMIN_OVERVIEW_METRICS:
            is_rhr = code == "resting_heart_rate_bpm"
            # RHR acquisition surface and metric capability are distinct.
            # Match typed identity before selecting/validating the latest snapshot.
            candidates = [
                (record, metric) for record, metric in rows
                if metric.metric_code == code
                and (
                    record.stream_code == "daily_health"
                    and record.surface_code in (None, "daily_summary", "resting_heart_rate")
                    and metric.capability_code == "resting_heart_rate"
                    if is_rhr else record.surface_code in (None, capability)
                )
            ]
            cell: dict[str, Any] = {
                "label": label, "state": "unknown", "value": None, "date": None,
                "note": "Garmin: нет записи этого показателя в выбранном периоде.",
            }
            if candidates:
                # An explicit instant can order intraday snapshots. Date-only
                # collisions remain ambiguous; UUID/ingestion order is no evidence.
                latest_day = max(record.source_local_date for record, _ in candidates)
                latest = [(r, m) for r, m in candidates if r.source_local_date == latest_day]
                if all(r.source_timestamp_utc is not None for r, _ in latest):
                    stamp = max(r.source_timestamp_utc for r, _ in latest)
                    latest = [(r, m) for r, m in latest if r.source_timestamp_utc == stamp]
                cell["date"] = latest_day.isoformat()
                if len(latest) != 1:
                    cell["note"] = "Garmin: несколько снимков; единое значение не выбрано."
                else:
                    record, metric = latest[0]
                    number = metric.value_number
                    usable = (
                        metric.state == "value" and metric.unit == unit
                        and (not is_rhr or isinstance(number, (int, float)))
                        and number is not None and isfinite(number)
                        and record.record_status in ("ok", "partial")
                    )
                    cell.update(
                        state=("partial" if record.record_status == "partial" else "present")
                        if usable else "unavailable",
                        value=number if usable else None,
                        note=None if usable else {
                            "missing": "Garmin: источник не передал этот показатель.",
                            "null": "Garmin: источник передал пустое значение.",
                            "invalid": "Garmin: значение непригодно.",
                        }.get(metric.state, "Garmin: число или единица измерения непригодны."),
                    )
                    if record.record_status == "invalid":
                        cell["note"] = "Garmin: запись показателя непригодна."
                    if usable and code == "respiration_bpm":
                        cell["note"] = (
                            "Среднее во сне" if "avgSleepRespirationValue" in metric.field_path
                            else "Снимок; суточное среднее не подтверждено"
                        )
            garmin[code] = cell
            technical.extend({
                "metric_code": code, "record_id": r.id, "state": m.state,
                "value": m.value_number, "unit": m.unit, "field_path": m.field_path,
                "source_local_date": r.source_local_date.isoformat(),
                "source_timestamp_utc": r.source_timestamp_utc.isoformat()
                if r.source_timestamp_utc else None,
            } for r, m in candidates)
    return {
        "google": google_view, "garmin": garmin,
        "training": training_overview_for_selection(
            session, source_selection={"selected_source_id": selected_id}, activity_limit=5,
        ),
        "technical": {"google": [r.as_dict() for r in google_results], "garmin": technical},
    }
