"""Read saved daily Garmin estimates, without provider calls or inferred values."""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from math import isfinite

from sqlalchemy import select

from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord

FIELDS = {"total": "totalKilocalories", "active": "activeKilocalories", "bmr": "bmrKilocalories"}
MAX_DAYS = 366
MAX_METRICS = 12000


def energy_display(value):
    if value is None:
        return None
    whole = Decimal(str(value)).to_integral_value(rounding=ROUND_HALF_UP)
    return f"{int(whole):,}".replace(",", " ")


def read_daily_energy(session, *, source_id, start: date | None, end: date | None):
    """One current record per source/date; collisions withhold that date, never pool.

    Dates are provider calendar labels, not proof of full-day acquisition. Missing
    components are independent; no total/component is reconstructed from siblings.
    """
    days = (end - start).days + 1 if start and end else 0
    packet = {"days": days, "rows": [],
              "summary": {key: {"count": 0, "mean_display": None} for key in FIELDS},
              "reason": None,
              "source_id": source_id, "start": start, "end": end}
    if days < 0 or days > MAX_DAYS:
        return dict(packet, reason="unsupported_period")
    candidates = []
    if source_id and days:
        candidates = session.execute(select(GarminSourceRecord, GarminRecordMetric).join(
            GarminRecordMetric, GarminRecordMetric.record_id == GarminSourceRecord.id,
        ).where(
            GarminSourceRecord.garmin_source_id == source_id,
            GarminSourceRecord.stream_code == "daily_health",
            GarminSourceRecord.surface_code.in_(["daily_summary"])
            | GarminSourceRecord.surface_code.is_(None),
            GarminSourceRecord.projection_status == "current",
            GarminSourceRecord.source_local_date.between(start, end),
            GarminRecordMetric.metric_code.in_([f"daily_{key}_kcal" for key in FIELDS]),
        ).limit(MAX_METRICS + 1)).all()
    if len(candidates) > MAX_METRICS:
        candidates = []
        packet["reason"] = "search_incomplete"
    elif not source_id:
        packet["reason"] = "source_not_selected"
    by_day = {}
    for record, metric in candidates:
        by_day.setdefault(record.source_local_date, {}).setdefault(record.id, []).append(
            (record, metric))
    for index in range(days):
        day = start + timedelta(days=index)
        row = {"date": day, "evidence": [], **dict.fromkeys(FIELDS)}
        records = by_day.get(day, {})
        if len(records) == 1:
            for record, metric in next(iter(records.values())):
                key = metric.metric_code.removeprefix("daily_").removesuffix("_kcal")
                row["evidence"].append({"raw_payload_id": record.raw_payload_id,
                    "path": metric.field_path, "state": metric.state,
                    "contract": record.normalization_contract_version})
                number = metric.value_number
                if (record.record_status in {"ok", "partial"} and metric.state == "value"
                        and metric.unit == "kcal" and metric.capability_code == "daily_energy"
                        and metric.field_path == f"payload.{FIELDS[key]}"
                        and isinstance(number, (int, float)) and not isinstance(number, bool)
                        and isfinite(number) and number >= 0):
                    row[key] = number
        row["display"] = {key: energy_display(row[key]) for key in FIELDS}
        row["label"] = (f"{('пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс')[day.weekday()]} "
                        f"{day:%d.%m} · "
                        + (f"{row['display']['total']} ккал" if row["total"] is not None
                           else "нет данных")
                        + f" · активные {row['display']['active'] or 'нет данных'}"
                        + f" · BMR {row['display']['bmr'] or 'нет данных'}")
        packet["rows"].append(row)
    for key in FIELDS:
        values = [Decimal(str(row[key])) for row in packet["rows"] if row[key] is not None]
        mean = sum(values) / len(values) if values else None
        packet["summary"][key] = {"count": len(values), "mean_display": energy_display(mean)}
    # Geometry only: the two independently reported components are never used as total.
    scale = max([Decimal(1)] + [Decimal(str(row["total"])) for row in packet["rows"]
                               if row["total"] is not None]
                + [Decimal(str(row["active"])) + Decimal(str(row["bmr"]))
                   for row in packet["rows"]
                   if row["active"] is not None and row["bmr"] is not None])
    for row in packet["rows"]:
        row["split"] = all(row[key] is not None for key in FIELDS)
        row["widths"] = {key: round(Decimal(str(row[key])) / scale * 100, 3)
                         if row[key] is not None else None for key in FIELDS}
    return packet
