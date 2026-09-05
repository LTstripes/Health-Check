from __future__ import annotations

import zoneinfo
from datetime import datetime, timedelta
from importlib.metadata import version


def test_iana_zoneinfo_resolves_from_packaged_tzdata() -> None:
    original_tzpath = zoneinfo.TZPATH
    try:
        zoneinfo.reset_tzpath(to=())
        zoneinfo.ZoneInfo.clear_cache()
        zone = zoneinfo.ZoneInfo("Europe/Moscow")
    finally:
        zoneinfo.reset_tzpath(to=original_tzpath)
        zoneinfo.ZoneInfo.clear_cache()

    assert version("tzdata")
    assert zone.key == "Europe/Moscow"
    assert datetime(2026, 1, 1, tzinfo=zone).utcoffset() == timedelta(hours=3)
