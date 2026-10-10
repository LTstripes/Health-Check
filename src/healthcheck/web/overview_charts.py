"""Read-only A+ figures from accepted services, outside both brief hash packets."""

from collections import Counter
from datetime import date, timedelta
from typing import Any

from healthcheck.web.garmin_query import GarminQueryError, GarminQueryService
from healthcheck.web.query import WeightQueryService
from healthcheck.web.sleep_view import nightly_rows


def dated_chart(rows, *, start: date, end: date, zero_axis=False, weight_layout=False):
    """Only coordinates: preserve dates, values, missing days and partial states.

    A gap is an interval without a supplied observation, never a zero. EWMA lines
    connect only adjacent calendar days. Weight observation connectors are dashed
    across unmeasured dates. No interpolation or smoothing here.
    """
    rows = sorted(rows, key=lambda row: row["date"])
    values = [row[key] for row in rows for key in ("value", "trend")
              if row.get(key) is not None]
    low = 0 if zero_axis or not values else min(values)
    high = max(values, default=1)
    if low == high:
        high = low + 1
    if weight_layout and values:
        padding = max(.2, (max(values) - min(values)) * .15)
        low, high = min(values) - padding, max(values) + padding
    span = max(1, (end - start).days)

    def x(day):
        return round((62 if weight_layout else 38)
                     + (264 if weight_layout else 284) * (day - start).days / span, 2)

    def y(value):
        return round((134 if weight_layout else 104)
                     - (100 if weight_layout else 80) * (value - low) / (high - low), 2)

    points, gaps, segments = [], [], []
    observed_segments = []
    previous_observed = None
    cursor = start
    previous = None
    for row in rows:
        day = date.fromisoformat(row["date"])
        if day > cursor:
            gaps.append({"start": cursor.isoformat(), "end": (day - timedelta(days=1)).isoformat(),
                         "x": x(cursor), "width": max(2, x(day) - x(cursor))})
        point = {**row, "x": x(day), "y": y(row["value"]) if row["value"] is not None else None,
                 "trend_y": y(row["trend"]) if row.get("trend") is not None else None}
        if previous and (day - date.fromisoformat(previous["date"])).days == 1:
            if previous["trend_y"] is not None and point["trend_y"] is not None:
                segments.append({"x1": previous["x"], "y1": previous["trend_y"],
                                 "x2": point["x"], "y2": point["trend_y"]})
        if weight_layout and point["y"] is not None:
            if previous_observed is not None:
                observed_segments.append({
                    "x1": previous_observed["x"], "y1": previous_observed["y"],
                    "x2": point["x"], "y2": point["y"],
                    "start": previous_observed["date"], "end": point["date"],
                    "gap": (day - date.fromisoformat(previous_observed["date"])).days > 1,
                })
            previous_observed = point
        points.append(point)
        previous = point
        cursor = day + timedelta(days=1)
    if cursor <= end:
        gaps.append({"start": cursor.isoformat(), "end": end.isoformat(),
                     "x": x(cursor), "width": max(2, x(end) - x(cursor))})
    figure = {"points": points, "gaps": gaps, "segments": segments, "low": low, "high": high,
              "start": start.isoformat(), "end": end.isoformat()}
    if weight_layout:
        figure["observed_segments"] = observed_segments
        months = ("янв", "фев", "мар", "апр", "май", "июн",
                  "июл", "авг", "сен", "окт", "ноя", "дек")
        days = sorted({start, start + timedelta(days=(end - start).days // 2), end})
        figure["date_ticks"] = [{"x": x(day), "label": f"{day.day} {months[day.month - 1]}",
                                 "date": day.isoformat()} for day in days]
        figure["value_ticks"] = [{"y": y(value), "value": value}
                                  for value in (high, (low + high) / 2, low)] if values else []
        figure["years"] = (str(start.year) if start.year == end.year
                           else f"{start.year} — {end.year}")
    return figure


def read_overview_charts(session, settings, *, packet, selected_id, brief_inputs=None):
    """Reuse Weight and Sleep presentation contracts; never interpret raw payloads.

    Sleep uses the packet's existing bounded baseline window and the same
    per-wake-date ambiguity guard as /sleep. Secondary snapshots remain single
    observations in overview_view; no new eligibility rules are introduced.
    """
    start = date.fromisoformat(packet["period"]["start_date"])
    end = date.fromisoformat(packet["period"]["end_date"])
    if brief_inputs is not None:
        brief_inputs.validate(session, packet, selected_id)
        weight = brief_inputs.weight_summary
    else:
        weight = WeightQueryService(session, settings).summary(start_date=start, end_date=end)
    trend = weight["trend"]
    trend_by_day = {p["observed_date"]: p["trend_kg"] for p in trend["points"]}
    weight_rows = [{"date": p["observed_date"], "value": p["median_kg"], "state": "present",
                    "trend": trend_by_day.get(p["observed_date"]) if trend["available"] else None}
                   for p in trend.get("daily_points", [])]
    sleep_results: dict[str, Any] = {}
    sleep_start, sleep_end = start, end
    sleep_error = False
    baselines = packet["sections"]["sleep"].get("analytics_snapshot", {}).get(
        "baseline_summaries", [])
    if selected_id:
        service = GarminQueryService(session, settings)
        for baseline in baselines:
            code = baseline["metric_code"]
            if code not in {"sleep_duration_seconds", "sleep_score"}:
                continue
            window = baseline["effective_window"]
            sleep_start = date.fromisoformat(window["start_date"])
            sleep_end = date.fromisoformat(window["end_date"])
            if baseline.get("reason") == "baseline_unavailable":
                sleep_error = True
                continue
            try:
                if brief_inputs is None:
                    sleep_results[code] = service.scalar_series(
                        garmin_source_id=selected_id, metric_code=code,
                        start_date=sleep_start, end_date=sleep_end,
                    )
                else:
                    body = brief_inputs.sleep_series[code]
                    query = body["query"]
                    if (query["garmin_source_id"] != selected_id
                            or query["metric_code"] != code
                            or query["start_date"] != sleep_start.isoformat()
                            or query["end_date"] != sleep_end.isoformat()
                            or body["result_hash"] != baseline["result_hash"]):
                        raise ValueError("Brief sleep series does not match its baseline")
                    # Preserve scalar_series source validation and presentation,
                    # including sanitization and provider-native score evidence.
                    service._require_source_id(selected_id)
                    sleep_results[code] = service._present_scalar_result(body)
            except GarminQueryError:
                sleep_error = True
    nights = nightly_rows(sleep_results)
    sleep_rows = [{"date": row["wake_date"], **row["metrics"]["sleep_duration_seconds"]}
                  for row in nights]
    latest = {}
    for code in ("sleep_duration_seconds", "sleep_score"):
        latest[code] = next(({"date": row["wake_date"], **row["metrics"][code]}
                             for row in nights if row["metrics"][code]["value"] is not None), None)
    activity = packet["sections"]["activity"]
    counts = Counter(row["source_local_date"] for row in activity["sessions"])
    # The existing packet proves whole-window coverage, not individual gap days.
    # Without it, a day with no saved sessions stays unknown (including partial windows).
    complete = activity.get("coverage", {}).get("acquisition", {}).get("complete") is True
    activity_rows = []
    for offset in range((end - start).days + 1):
        day = (start + timedelta(days=offset)).isoformat()
        count = counts.get(day)
        # A saved session is present evidence even when whole-period coverage is unknown.
        state = "present" if count is not None or complete else "unknown"
        activity_rows.append({"date": day, "value": count if count else (0 if complete else None),
                              "state": state})
    sleep_figure = dated_chart(sleep_rows, start=sleep_start, end=sleep_end, zero_axis=True)
    # Axis formatting only: coordinates and all source values stay in seconds.
    sleep_hours = sleep_figure["high"] / 3600
    step = 1 if sleep_hours <= 4 else (2 if sleep_hours <= 12 else 4)
    sleep_figure["hour_ticks"] = [
        {"label": f"{hour} ч", "y": round(104 - 80 * hour * 3600 / sleep_figure["high"], 2)}
        for hour in range(0, int(sleep_hours) + 1, step)
    ] if any(row["value"] is not None for row in sleep_rows) else []
    return {
        "weight": dated_chart(weight_rows, start=start, end=end, weight_layout=True),
        "weight_current": weight.get("current"), "weight_trend": trend,
        "sleep": sleep_figure,
        "sleep_nights": nights, "sleep_latest": latest, "sleep_error": sleep_error,
        "sleep_limited": sleep_start != start,
        "sleep_newer_unusable": any(row["value"] is None and latest["sleep_duration_seconds"]
                                    and row["date"] > latest["sleep_duration_seconds"]["date"]
                                    for row in sleep_rows),
        "activity": dated_chart(activity_rows, start=start, end=end, zero_axis=True),
        "activity_complete": complete,
        "technical": {"weight_trend": trend, "sleep": sleep_results},
    }
