"""Read-only Overview comparisons; existing readers own eligibility and aggregates.

Coverage is eligible saved dates, never wear/acquisition completeness. Each row
discloses its actual window: RHR retains the requested period, completed-day
cards retain the completed Moscow period. Intensity uses the existing paired-day
Garmin rule over the selected dates, without importing the leading partial week.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext

from healthcheck.analytics.period_summary import read_sleep_source_selection
from healthcheck.analytics.sleep_source_view import (
    read_source_sleep_night,
    resolve_source_sleep_point,
)
from healthcheck.garmin.daily_energy import read_daily_energy
from healthcheck.garmin.intensity_minutes import read_intensity_minutes
from healthcheck.owner_time import owner_zone
from healthcheck.saved_rhr_period import SavedRhrPeriodQuery, read_saved_rhr_period
from healthcheck.saved_values import GARMIN_RHR, GOOGLE_RHR
from healthcheck.web.overview_completed import read_completed_overview
from healthcheck.web.overview_coverage import (
    OVERVIEW_COVERAGE_THRESHOLD,
    overview_low_coverage,
)
from healthcheck.web.overview_steps import read_overview_steps


def previous_overview_window(window):
    """Immediately preceding equal inclusive calendar span, including leap days."""
    if window["empty"]:
        return dict(window)
    start = date.fromisoformat(window["start_date"])
    end = start - timedelta(days=1)
    lower = start - timedelta(days=window["calendar_days"])
    return dict(window, start_date=lower.isoformat(), end_date=end.isoformat(),
                requested_start=lower.isoformat(), requested_end=end.isoformat())


def _value(value, count, window, reason=None):
    return {"value": value, "coverage": {"count": count, "days": window["calendar_days"]},
            "window": window, "reason": reason,
            "low_coverage": overview_low_coverage(count, window["calendar_days"])}


def _comparison(metric, provider, source_id, unit, aggregation, current, previous):
    reason = None
    difference = None
    if current["value"] is None or previous["value"] is None or source_id is None:
        reason = "missing"
    elif current["low_coverage"]:
        reason = "low_coverage_current"
    elif previous["low_coverage"]:
        reason = "low_coverage_previous"
    else:
        left, right = (Decimal(str(item["value"])) for item in (current, previous))
        with localcontext() as context:
            context.prec = max(40, len(left.as_tuple().digits) + len(right.as_tuple().digits))
            difference = left - right
    return {"metric": metric, "provider": provider, "source_id": source_id,
            "unit": unit, "aggregation": aggregation, "current": current, "previous": previous,
            "difference": difference, "reason": reason}


def _scalar(packet, window):
    count = packet["eligible_days"] if packet["reason"] in {
        None, "no_observations", "no_completed_days",
    } else None
    return _value(packet["mean_value"], count, window, packet["reason"])


def _battery(packet, window):
    dto = packet["selected"]
    return _value(dto["mean_value"] if dto else None,
                  dto["eligible_day_count"] if dto else None, window,
                  dto["reason"] if dto else "no_completed_days")


def _sleep(session, *, provider, window, source_id=None):
    if window["empty"] or window["calendar_days"] > 366:
        return None
    return read_sleep_source_selection(
        session, provider=provider, start=date.fromisoformat(window["start_date"]),
        end=date.fromisoformat(window["end_date"]), source_id=source_id,
    )


def _sleep_value(packet, window):
    if packet is None:
        return _value(None, None, window, "no_completed_days" if window["empty"] else "missing")
    complete = packet["search"]["complete"] and packet["source_identity"] is not None
    value = packet["aggregation"]["value"] if complete else None
    return _value(value,
                  len(packet["eligible_dates"]) if complete else None, window,
                  None if value is not None else packet["search"]["reason"] or packet["state"])


def _intensity(session, *, source_id, window):
    if window["empty"]:
        return _value(None, None, window, "no_completed_days")
    start, end = (date.fromisoformat(window[key]) for key in ("start_date", "end_date"))
    packet = read_intensity_minutes(session, source_id=source_id, start=start, end=end)
    values = [row["total"] for row in packet["rows"]
              if start <= row["date"] <= end and row["total"] is not None]
    return _value(sum(values, Decimal(0)) if values and not packet["reason"] else None,
                  len(values) if not packet["reason"] else None, window, packet["reason"])


def _endpoint(cell, night, endpoint):
    """Retain an endpoint's own saved zone/offset, including a mid-night change."""
    if not cell["eligible"]:
        return {"at_utc": None, "local_datetime": None, "timezone": None,
                "utc_offset_minutes": None, "reason": cell["reason"] or "bounds_unavailable"}
    instant = datetime.fromisoformat(cell["value"])
    candidates = []
    record = night["temporal_evidence"]
    if endpoint == "start":
        candidates.append(dict(record, measured_at_utc=record.get("source_timestamp_utc")))
    for metric in night["metrics"].values():
        evidence = metric.get("evidence") or {}
        boundary = (evidence.get("quality_inputs") or {}).get("summary_boundary") or {}
        candidates.append(boundary.get(endpoint))
        for interval in evidence.get("interval_snapshots") or []:
            if interval.get(f"{endpoint}_precision") == "instant":
                candidates.append(interval.get(f"{endpoint}_temporal"))
    offsets, zones = set(), set()
    for temporal in candidates:
        if not temporal or temporal.get("precision") != "instant":
            continue
        offset = temporal.get("source_utc_offset_minutes")
        if type(offset) is not int or abs(offset) > 1439:
            continue
        try:
            proved = datetime.fromisoformat(str(temporal.get("measured_at_utc")))
        except ValueError:
            continue
        if proved.utcoffset() is not None and proved == instant:
            offsets.add(offset)
            if temporal.get("source_timezone"):
                zones.add(temporal["source_timezone"])
    local = instant.astimezone(timezone(timedelta(minutes=next(iter(offsets))))) \
        if len(offsets) == 1 else None
    return {"at_utc": cell["value"], "local_datetime": local.isoformat() if local else None,
            "timezone": (next(iter(zones)) if len(zones) == 1 else local.strftime("%z"))
            if local else None,
            "utc_offset_minutes": next(iter(offsets)) if local else None,
            "reason": None if local else "local_zone_unavailable"}


def _last_night(session, *, provider, packet):
    result = {"provider": provider, "source_id": None, "wake_date": None, "record_id": None,
              "start": None, "end": None, "duration_seconds": None, "reason": "missing"}
    if packet is None:
        return dict(result, reason="unsupported_period")
    identity = packet["source_identity"]
    if identity is None or not packet["search"]["complete"]:
        return dict(result, reason=packet["search"]["reason"] or packet["state"])
    result["source_id"] = identity["source_id"]
    if not packet["eligible_dates"]:
        return result
    day = max(packet["eligible_dates"])
    view = read_source_sleep_night(session, provider=provider, wake_date=date.fromisoformat(day),
                                   source_id=identity["source_id"])
    if view["state"] == "read_limit_exceeded" or len(view["sources"]) != 1:
        return dict(result, reason="night_unavailable")
    source = view["sources"][0]
    point = resolve_source_sleep_point(source, provider=provider)
    if point["state"] != "value":
        return dict(result, reason=point["reason"] or "night_unavailable")
    night = next(item for item in source["sessions"] if item["record_id"] == point["record_id"])
    # The accepted singleton fallback is disclosed, never relabelled explicit main.
    start = _endpoint(night["metrics"]["sleep_start_at"], night, "start")
    end = _endpoint(night["metrics"]["sleep_end_at"], night, "end")
    return dict(result, wake_date=day, record_id=point["record_id"],
                duration_seconds=point["value"], role_uncertain=point["role_uncertain"],
                start=start, end=end,
                reason="bounds_unavailable" if start["reason"] or end["reason"] else None)


def read_overview_comparison(session, settings, *, paths, overview, start, end,
                              source_id, evaluated_at, prior_steps=None):
    """Reuse current card reads; only the preceding window is read again."""
    window = overview["completed_window"]
    previous_window = previous_overview_window(window)
    if window["empty"]:
        previous = overview
    else:
        previous = read_completed_overview(
            session, settings, start=date.fromisoformat(previous_window["start_date"]),
            end=date.fromisoformat(previous_window["end_date"]), preset=None,
            source_id=source_id, evaluated_at=evaluated_at,
        )
    rows = [
        _comparison(metric, "garmin", source_id, unit, aggregation,
                    reader(overview[key], window), reader(previous[key], previous_window))
        for metric, key, unit, aggregation, reader in (
            ("sleep_duration", "period_sleep", "seconds", "mean", _scalar),
            ("stress", "period_stress", "points", "mean", _scalar),
            ("body_battery", "body_battery", "points", "mean_daily_maximum", _battery),
        )
    ]
    google_sleep = _sleep(session, provider="google", window=window)
    google_identity = google_sleep["source_identity"] if google_sleep else None
    previous_google_sleep = _sleep(
        session, provider="google", window=previous_window,
        source_id=google_identity["source_id"],
    ) if google_identity else None
    rows.append(_comparison(
        "sleep_duration", "google", google_identity["source_id"] if google_identity else None,
        "seconds", "mean", _sleep_value(google_sleep, window),
        _sleep_value(previous_google_sleep, previous_window),
    ))
    requested = {"start_date": start.isoformat(), "end_date": end.isoformat(),
                 "calendar_days": (end - start).days + 1, "empty": False,
                 "timezone": "source_local_date"}
    previous_requested = previous_overview_window(requested)
    for item in overview["rhr"]["items"]:
        current = item["dto"]
        provider = "garmin" if item["label"] == "Garmin" else "google"
        identity = current["source_identity"]
        selected = identity["source_id"] if identity else None
        prior = read_saved_rhr_period(session, SavedRhrPeriodQuery(
            provider_code="garmin_connect" if provider == "garmin" else "google_health",
            metric_code=GARMIN_RHR if provider == "garmin" else GOOGLE_RHR,
            source_id=selected, requested_start_date=date.fromisoformat(
                previous_requested["start_date"]), requested_end_date=date.fromisoformat(
                previous_requested["end_date"]), evaluated_at_utc=evaluated_at,
            evaluation_local_date=evaluated_at.astimezone(owner_zone(settings)).date(),
        )) if selected else current

        def rhr_value(dto, bounds):
            exact = dto["mean_exact"]
            return _value(Decimal(exact["decimal"]) if exact else None,
                          dto["eligible_day_count"], bounds, dto["reason"])

        rows.append(_comparison("resting_heart_rate", provider, selected, "bpm", "mean",
                                rhr_value(current, requested),
                                rhr_value(prior, previous_requested)))
    current_steps = overview["steps"]["items"]
    google_steps_id = (current_steps[1]["technical"] or {}).get("source_id")
    prior_steps = prior_steps if prior_steps is not None else (read_overview_steps(
        session, paths=paths, window=previous_window, source_id=source_id,
        evaluated_at=evaluated_at, google_source_id=google_steps_id,
    )["items"] if not window["empty"] else current_steps)
    for current, prior in zip(current_steps, prior_steps, strict=True):
        provider = "garmin" if current["provider"] == "Garmin" else "google"
        prior_value = _value(prior["mean_value"], prior["count"], previous_window, prior["reason"])
        if provider == "google" and google_steps_id is None:
            prior_value = _value(None, None, previous_window, "source_not_selected")
        rows.append(_comparison(
            "steps", provider, source_id if provider == "garmin" else google_steps_id,
            "steps", "mean", _value(current["mean_value"], current["count"], window,
                                    current["reason"]),
            prior_value,
        ))
    prior_energy = read_daily_energy(
        session, source_id=source_id,
        start=date.fromisoformat(previous_window["start_date"]) if not window["empty"] else None,
        end=date.fromisoformat(previous_window["end_date"]) if not window["empty"] else None,
    )
    current_energy = overview["energy"]["summary"]["total"]
    rows.append(_comparison(
        "daily_calories_garmin_estimate", "garmin", source_id, "kcal", "mean",
        _value(current_energy["mean_value"], current_energy["count"]
               if overview["energy"]["reason"] is None else None, window,
               overview["energy"]["reason"]),
        _value(prior_energy["summary"]["total"]["mean_value"],
               prior_energy["summary"]["total"]["count"]
               if prior_energy["reason"] is None else None,
               previous_window, prior_energy["reason"]),
    ))
    rows.append(_comparison(
        "intensity_minutes", "garmin", source_id, "min", "garmin_moderate_plus_2_vigorous_total",
        _intensity(session, source_id=source_id, window=window),
        _intensity(session, source_id=source_id, window=previous_window),
    ))
    garmin_sleep = _sleep(session, provider="garmin", window=window,
                          source_id=source_id) if source_id else None
    return {"coverage_threshold": {"numerator": OVERVIEW_COVERAGE_THRESHOLD.numerator,
                                    "denominator": OVERVIEW_COVERAGE_THRESHOLD.denominator},
            "current_window": window, "previous_window": previous_window, "items": rows,
            "last_nights": [
                _last_night(session, provider="garmin", packet=garmin_sleep) if source_id else {
                    "provider": "garmin", "source_id": None, "wake_date": None, "record_id": None,
                    "start": None, "end": None, "duration_seconds": None,
                    "reason": "source_not_selected",
                },
                _last_night(session, provider="google", packet=google_sleep),
            ]}
