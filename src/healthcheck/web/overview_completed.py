"""Overview-only means over completed Moscow days; stored dates stay unchanged.

The UI owns the window. Existing bounded readers receive that entire window;
neither Period Brief packets, source projections nor other screens are changed.
"""

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction
from zoneinfo import ZoneInfo

from healthcheck.analytics.garmin_baselines import MAX_SERIES_CALENDAR_DAYS
from healthcheck.web.garmin_query import GarminQueryError, GarminQueryService
from healthcheck.web.overview_body_battery import read_overview_body_battery
from healthcheck.web.overview_charts import dated_chart
from healthcheck.web.overview_view import overview_number, overview_whole_number
from healthcheck.web.sleep_view import metric_value, night_metric


def completed_overview_window(*, start: date, end: date, preset: str | None,
                              evaluated_at: datetime) -> dict:
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("Overview evaluation clock must be timezone-aware")
    if end < start:
        raise ValueError("Overview period is reversed")
    yesterday = evaluated_at.astimezone(ZoneInfo("Europe/Moscow")).date() - timedelta(days=1)
    if preset in {"7", "30", "90"}:
        effective_end = yesterday
        effective_start = effective_end - timedelta(days=int(preset) - 1)
    else:
        effective_start, effective_end = start, min(end, yesterday)
    empty = effective_end < effective_start
    return {
        "requested_start": start.isoformat(), "requested_end": end.isoformat(),
        "start_date": None if empty else effective_start.isoformat(),
        "end_date": None if empty else effective_end.isoformat(),
        "calendar_days": 0 if empty else (effective_end - effective_start).days + 1,
        "empty": empty, "timezone": "Europe/Moscow",
    }


def _period_mean(session, settings, *, window, source_id, metric_code, cached_series=None):
    result = {
        "mean_display": None, "mean_value": None, "eligible_days": 0,
        "partial_days": 0, "days": window["calendar_days"], "figure": None,
        "reason": None, "technical": None,
    }
    if window["empty"]:
        return dict(result, reason="no_completed_days")
    if not source_id:
        return dict(result, reason="source_not_selected")
    if window["calendar_days"] > MAX_SERIES_CALENDAR_DAYS:
        return dict(result, reason="range_exceeds_max")
    start, end = (date.fromisoformat(window[key]) for key in ("start_date", "end_date"))
    try:
        query = (cached_series or {}).get("query", {})
        matches = (query.get("garmin_source_id") == source_id
                   and query.get("metric_code") == metric_code
                   and query.get("start_date") == start.isoformat()
                   and query.get("end_date") == end.isoformat())
        series = cached_series if matches else GarminQueryService(session, settings).scalar_series(
            garmin_source_id=source_id, metric_code=metric_code,
            start_date=start, end_date=end,
        )
    except GarminQueryError as exc:
        return dict(result, reason="read_unavailable", technical={"reason": exc.code})
    # Reuse the accepted one-value-per-date guard, including partial and zero.
    # A date collision never becomes an intraday mean or a latest-value fallback.
    days = sorted({point["analytic_date"] for point in series.get("points", [])
                   if point.get("analytic_date")
                   and start.isoformat() <= point["analytic_date"] <= end.isoformat()})
    rows = [{"date": day, **night_metric(series, date.fromisoformat(day))} for day in days]
    eligible = [row for row in rows if row["value"] is not None]
    mean = None
    if eligible:
        exact = sum((Fraction(str(row["value"])) for row in eligible), Fraction()) / len(eligible)
        with localcontext() as context:
            context.prec = 40
            mean = Decimal(exact.numerator) / Decimal(exact.denominator)
    figure = dated_chart(rows, start=start, end=end, zero_axis=metric_code.startswith("sleep"))
    return dict(result, mean_value=mean,
                mean_display=overview_number(mean) if mean is not None else None,
                eligible_days=len(eligible), partial_days=sum(
                    row["state"] == "partial" for row in eligible),
                figure=figure, reason=None if eligible else "no_observations", technical=series)


def read_completed_overview(session, settings, *, start, end, preset, source_id,
                            evaluated_at, sleep_series=None):
    window = completed_overview_window(start=start, end=end, preset=preset,
                                       evaluated_at=evaluated_at)
    sleep = _period_mean(session, settings, window=window, source_id=source_id,
                         metric_code="sleep_duration_seconds", cached_series=sleep_series)
    sleep["duration_display"] = metric_value(
        "sleep_duration_seconds",
        int(sleep["mean_value"].to_integral_value(rounding=ROUND_HALF_UP)),
    ) if sleep["mean_value"] is not None else None
    stress = _period_mean(session, settings, window=window, source_id=source_id,
                          metric_code="stress_daily_average")
    if stress["mean_value"] is not None:
        stress["mean_display"] = overview_whole_number(stress["mean_value"])
    if window["empty"]:
        battery = {"selected": None, "figure": None}
    else:
        lower, upper = (date.fromisoformat(window[key]) for key in ("start_date", "end_date"))
        battery = read_overview_body_battery(
            session, start=lower, end=upper, garmin_source_id=source_id,
            evaluated_at_utc=evaluated_at,
        )
        dto = battery["selected"]
        battery["figure"] = dated_chart([
            {"date": point["source_local_date"], "value": point["value"],
             "state": "partial" if any(item["record_status"] == "partial"
                                       for item in point["evidence"]) else "present"}
            for point in dto["daily_maxima"]
        ], start=lower, end=upper, include_zero=True) if dto["search"]["complete"] else None
    return {"completed_window": window, "period_sleep": sleep,
            "period_stress": stress, "body_battery": battery}
