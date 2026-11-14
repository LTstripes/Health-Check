"""Overview Steps over the shared completed window, with separate source means."""

from datetime import date
from decimal import Decimal

from healthcheck.garmin.completed_steps_read import (
    read_completed_steps_window,
    read_completed_steps_windows,
)
from healthcheck.garmin.observed_steps_read import MAX_WINDOW_DAYS
from healthcheck.garmin.steps_statistics import summarize_completed_days
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.google.steps_read import read_saved_steps_window, read_saved_steps_windows
from healthcheck.google.steps_summary import summarize_saved_steps_window
from healthcheck.web.steps_presentation import google_steps_view, steps_mean_display


def read_overview_steps(session, *, paths, window, source_id, evaluated_at,
                        google_source_id=None, _packets=None):
    """Never clip a reader window, pool sources or fill missing dates with zero."""
    items = []
    for provider in ("Garmin", "Google"):
        item = {"provider": provider, "mean_display": None, "mean_value": None, "count": None,
                "days": window["calendar_days"], "reason": None, "technical": None}
        items.append(item)
        if window["empty"]:
            item["reason"] = "no_completed_days"
            continue
        start, end = (date.fromisoformat(window[key]) for key in ("start_date", "end_date"))
        if provider == "Google":
            if window["calendar_days"] not in {7, 30}:
                item["reason"] = "unsupported_google_period"
                continue
            packet = (_packets["Google"] if _packets is not None else
                      read_saved_steps_window(session, start_date=start, end_date=end,
                                              source_id=google_source_id))
            view = google_steps_view(packet)
            summary = summarize_saved_steps_window(packet)
            item.update(mean_display=view["mean_display"], count=view["count"],
                        mean_value=(Decimal(summary["total"]) / summary["observed_day_count"]
                                    if summary["total"] is not None else None),
                        reason=packet["reason"] or view["reason"], technical=packet)
        elif not source_id:
            item["reason"] = "source_not_selected"
        elif window["calendar_days"] > MAX_WINDOW_DAYS:
            item["reason"] = "unsupported_garmin_period"
        else:
            packet = _packets["Garmin"] if _packets is not None else read_completed_steps_window(
                session, payload_store=ContentAddressedGarminPayloadStore(paths.root / "artifacts"),
                source_id=source_id, start_date=start, end_date=end, evaluated_at=evaluated_at,
            )
            item["technical"] = packet
            item["reason"] = packet.reason
            if packet.search_complete and packet.reason is None:
                summary = summarize_completed_days(packet)
                item.update(count=summary.eligible_day_count,
                            mean_value=summary.mean,
                            mean_display=(steps_mean_display(summary.total,
                                                           summary.eligible_day_count)
                                          if summary.total is not None else None),
                            reason=None if summary.mean is not None else "no_observations")
    return {"window": window, "items": items}


def read_overview_steps_pair(session, *, paths, window, previous_window,
                             source_id, evaluated_at):
    """Summary, chart and comparison consume the same per-day request results."""
    if window["empty"] or window["calendar_days"] > MAX_WINDOW_DAYS:
        current = read_overview_steps(session, paths=paths, window=window,
                                      source_id=source_id, evaluated_at=evaluated_at)
        previous = current if window["empty"] else read_overview_steps(
            session, paths=paths, window=previous_window, source_id=source_id,
            evaluated_at=evaluated_at,
        )
        return current, previous
    windows = [tuple(date.fromisoformat(bounds[key]) for key in ("start_date", "end_date"))
               for bounds in (window, previous_window)]
    packets = [{}, {}]
    if source_id:
        for packet, result in zip(packets, read_completed_steps_windows(
            session, payload_store=ContentAddressedGarminPayloadStore(paths.root / "artifacts"),
            source_id=source_id, windows=windows, evaluated_at=evaluated_at,
        ), strict=True):
            packet["Garmin"] = result
    if window["calendar_days"] in {7, 30}:
        for packet, result in zip(packets, read_saved_steps_windows(
            session, windows=windows,
        ), strict=True):
            packet["Google"] = result
    return tuple(read_overview_steps(
        session, paths=paths, window=bounds, source_id=source_id,
        evaluated_at=evaluated_at, _packets=packet,
    ) for bounds, packet in zip((window, previous_window), packets, strict=True))
