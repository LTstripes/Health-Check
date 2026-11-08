"""Owner calendar clock, separate from versioned analysis-day policies."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from healthcheck.config import Settings


def owner_zone(settings: Settings) -> ZoneInfo:
    return ZoneInfo(settings.owner_timezone)


def owner_now(settings: Settings) -> datetime:
    return datetime.now(UTC).astimezone(owner_zone(settings))


def owner_today(settings: Settings) -> date:
    return owner_now(settings).date()
