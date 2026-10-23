"""Exact saved-day presentation; consumes packets, never reads or selects sources."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from healthcheck.garmin.completed_steps_read import DISPLAY_ZONE
from healthcheck.garmin.steps_statistics import summarize_completed_days
from healthcheck.google.steps_summary import summarize_saved_steps_window


def _mean(total: int, count: int) -> str:
    tenths, remainder = divmod(total * 10, count)
    if remainder * 2 > count or (remainder * 2 == count and tenths % 2):
        tenths += 1
    return "<0.1" if total > 0 and tenths == 0 else f"{tenths // 10}.{tenths % 10}"


def _group(value: str | None) -> str | None:
    """Group a decimal string without passing exact counts through a float."""
    if value is None:
        return None
    integer, dot, fraction = value.partition('.')
    groups = []
    while integer:
        groups.append(integer[-3:])
        integer = integer[:-3]
    return "\u202f".join(reversed(groups)) + (dot + fraction if dot else "")


def _chart(cells: list[dict]) -> dict:
    """Only bounded geometry is numeric in browser data; counts stay strings."""
    maximum = max((c["value"] for c in cells if c["state"] == "value"), default=0)
    scale = max(1, maximum)
    left = 340 if len(str(scale)) > 12 else 100
    ticks = [{"value": str(value), "label": _group(str(value)),
              "y": 150 - value * 130 // scale}
             for value in sorted({0, scale // 2, scale})]
    rows, segments = [], []
    previous = None
    for index, cell in enumerate(cells):
        value = cell["value"] if cell["state"] == "value" else None
        x = left + index * (880 - left) // max(1, len(cells) - 1)
        y = 150 - value * 130 // max(1, maximum) if value is not None else None
        row = {
            "date": cell["date"].isoformat(), "state": cell["state"],
            "value": str(value) if value is not None else None,
            "display": _group(str(value)) if value is not None else None,
            "x": x, "y": y, "index": index,
        }
        rows.append(row)
        if previous is not None and y is not None:
            segments.append({"x1": previous["x"], "y1": previous["y"], "x2": x, "y2": y})
        previous = row if y is not None else None
    return {"rows": rows, "segments": segments, "selected_index": None,
            "selected": None, "ticks": ticks, "left": left}



def google_steps_view(packet) -> dict | None:
    if packet is None:
        return None
    summary = summarize_saved_steps_window(packet)
    assessed = summary["state"] != "unassessed"
    chart = _chart([
        {"date": cell["calendar_date"], "state": cell["state"], "value": cell["value"]}
        for cell in packet["cells"]
    ]) if assessed else _chart([])
    return {
        "provider": "Google", "assessed": assessed,
        "total": summary["total_display"], "mean": summary["mean_display"],
        "total_display": _group(summary["total_display"]),
        "mean_display": _group(summary["mean_display"]),
        "count": summary["observed_day_count"], "days": summary["requested_day_count"],
        "contract": summary["contract_version"], "reason": summary["reason"],
        "start": summary["start_date"], "end": summary["end_date"],
        "invalid_days": sum(row["state"] in {"invalid", "ambiguous"} for row in chart["rows"]),
        **chart,
    }


def garmin_steps_view(packet) -> dict:
    result = {"provider": "Garmin", "assessed": False, "total": None, "mean": None,
              "total_display": None, "mean_display": None,
              "count": None, "days": None, "start": packet.start_date, "end": packet.end_date,
              "contract": "garmin-completed-steps-summary-v1", "reason": packet.reason,
              "invalid_days": 0, **_chart([])}
    if (packet.reason or packet.search_complete is not True
            or not packet.source_id or not packet.source_identity):
        return result
    span = (packet.end_date - packet.start_date).days + 1
    if span not in {7, 30} or packet.source_identity.source_id != packet.source_id:
        return {**result, "reason": "invalid_daily_packet"}
    # The window reader emits every completed day, including unavailable cells.
    # Unlike all-history, a missing cell here is an incomplete daily grid.
    today = packet.evaluated_at.astimezone(ZoneInfo(DISPLAY_ZONE)).date()
    expected = {packet.start_date + timedelta(days=i) for i in range(span)
                if packet.start_date + timedelta(days=i) < today}
    if {cell.calendar_date for cell in packet.cells} != expected:
        return {**result, "reason": "invalid_daily_packet"}
    try:
        summary = summarize_completed_days(packet)
    except ValueError:
        return {**result, "reason": "invalid_daily_packet"}
    chart = _chart([
        {"date": cell.calendar_date, "state": cell.state, "value": cell.value}
        for cell in packet.cells
    ])
    return {
        **result, "assessed": True,
        "total": str(summary.total) if summary.total is not None else None,
        "mean": (_mean(summary.total, summary.eligible_day_count)
                 if summary.total is not None else None),
        "total_display": _group(str(summary.total)) if summary.total is not None else None,
        "mean_display": (_group(_mean(summary.total, summary.eligible_day_count))
                         if summary.total is not None else None),
        "count": summary.eligible_day_count, "days": summary.calendar_day_count,
        "invalid_days": sum(row["state"] in {"invalid", "ambiguous"} for row in chart["rows"]),
        **chart,
    }
