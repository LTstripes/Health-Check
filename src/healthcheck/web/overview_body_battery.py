"""Existing Overview card over saved Body Battery daily maxima."""

from datetime import date, datetime

from sqlalchemy.orm import Session

from healthcheck.garmin.body_battery_read import BodyBatteryQuery, read_body_battery_period
from healthcheck.web.overview_view import overview_number


def read_overview_body_battery(
    session: Session, *, start: date, end: date, garmin_source_id: str | None,
    evaluated_at_utc: datetime, evaluation_local_date: date,
) -> dict:
    dto = read_body_battery_period(session, BodyBatteryQuery(
        start, end, garmin_source_id, evaluated_at_utc, evaluation_local_date,
    ))
    mean_value = dto.pop("mean_value")
    dto["mean_display"] = overview_number(mean_value) if mean_value is not None else None
    return {"selected": dto}
