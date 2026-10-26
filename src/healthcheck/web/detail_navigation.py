"""Bounded local return links for Overview and saved-session drilldown."""

from urllib.parse import parse_qsl, urlsplit


def local_return_href(value: str | None, path: str) -> str | None:
    if value is None:
        return None
    if len(value) > 4096 or any(ord(char) < 32 for char in value) or "\\" in value:
        raise ValueError("invalid return context")
    parsed = urlsplit(value)
    allowed = {
        "/brief": {"preset", "start_date", "end_date", "period_at", "garmin_source_id",
                   "google_rhr_source_id", "weekly_end"},
        "/statistics/sessions": {"garmin_source_id", "start_date", "end_date", "metric_code",
                                 "sport", "origin_period", "origin_calendar_year",
                                 "origin_end_date", "google_source_id",
                                 "origin_garmin_source_id", "return_to"},
    }[path]
    params = parse_qsl(parsed.query, keep_blank_values=True)
    keys = [key for key, _ in params]
    if (parsed.scheme or parsed.netloc or parsed.path != path or parsed.fragment
            or len(keys) != len(set(keys)) or not set(keys) <= allowed):
        raise ValueError("invalid return context")
    if path == "/statistics/sessions" and "return_to" in keys:
        local_return_href(dict(params)["return_to"], "/brief")
    return value
