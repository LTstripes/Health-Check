"""Overview Steps over the shared completed window, with separate source means."""

from datetime import date

from healthcheck.garmin.completed_steps_read import read_completed_steps_window
from healthcheck.garmin.observed_steps_read import MAX_WINDOW_DAYS
from healthcheck.garmin.steps_statistics import summarize_completed_days
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.google.steps_read import read_saved_steps_window
from healthcheck.web.steps_presentation import google_steps_view, steps_mean_display


def read_overview_steps(session, *, paths, window, source_id, evaluated_at):
    """Never clip a reader window, pool sources or fill missing dates with zero."""
    items = []
    for provider in ("Garmin", "Google"):
        item = {"provider": provider, "mean_display": None, "count": None,
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
            packet = read_saved_steps_window(session, start_date=start, end_date=end)
            view = google_steps_view(packet)
            item.update(mean_display=view["mean_display"], count=view["count"],
                        reason=packet["reason"] or view["reason"], technical=packet)
        elif not source_id:
            item["reason"] = "source_not_selected"
        elif window["calendar_days"] > MAX_WINDOW_DAYS:
            item["reason"] = "unsupported_garmin_period"
        else:
            packet = read_completed_steps_window(
                session, payload_store=ContentAddressedGarminPayloadStore(paths.root / "artifacts"),
                source_id=source_id, start_date=start, end_date=end, evaluated_at=evaluated_at,
            )
            item["technical"] = packet
            item["reason"] = packet.reason
            if packet.search_complete and packet.reason is None:
                summary = summarize_completed_days(packet)
                item.update(count=summary.eligible_day_count,
                            mean_display=(steps_mean_display(summary.total,
                                                           summary.eligible_day_count)
                                          if summary.total is not None else None),
                            reason=None if summary.mean is not None else "no_observations")
    return {"window": window, "items": items}
