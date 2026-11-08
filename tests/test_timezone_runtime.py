from __future__ import annotations

import zoneinfo
from datetime import UTC, date, datetime, timedelta
from importlib.metadata import version

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from healthcheck import owner_time
from healthcheck.config import Settings
from healthcheck.garmin.sync import validate_sync_date as garmin_date
from healthcheck.google.sync import validate_sync_date as google_date
from test_garmin_query_dashboard import _ui


@pytest.fixture
def owner_clock(monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is UTC  # The machine's local clock must never select the date.
            return cls(2026, 11, 8, 23, 30, tzinfo=UTC)

    monkeypatch.setattr(owner_time, "datetime", FrozenDatetime)


@pytest.mark.parametrize(("zone", "expected"), [
    ("Europe/Moscow", date(2026, 11, 9)),
    ("America/New_York", date(2026, 11, 8)),
    ("Pacific/Kiritimati", date(2026, 11, 9)),
])
def test_owner_clock_and_sync_defaults(owner_clock, zone, expected):
    settings = Settings(owner_timezone=zone)
    assert owner_time.owner_zone(settings).key == zone
    assert owner_time.owner_now(settings).tzinfo.key == zone
    assert owner_time.owner_today(settings) == expected
    assert garmin_date(None, settings=settings) == expected
    assert google_date(None, settings=settings) == expected
    explicit = date(2026, 1, 2)
    assert garmin_date(explicit, settings=settings) == explicit
    assert google_date(explicit, settings=settings) == explicit
    assert garmin_date(None, default=explicit, settings=settings) == explicit


def test_owner_timezone_environment_and_validation(monkeypatch):
    monkeypatch.delenv("HEALTHCHECK_OWNER_TIMEZONE", raising=False)
    assert Settings().owner_timezone == "Europe/Moscow"
    monkeypatch.setenv("HEALTHCHECK_OWNER_TIMEZONE", "America/New_York")
    assert Settings().owner_timezone == "America/New_York"
    for zone in ("Unknown/Nowhere", "", "../Europe/Moscow"):
        monkeypatch.setenv("HEALTHCHECK_OWNER_TIMEZONE", zone)
        with pytest.raises(ValidationError, match="known IANA zone"):
            Settings()


@pytest.mark.parametrize(("zone", "expected"), [
    ("Europe/Moscow", "2026-11-09"), ("America/New_York", "2026-11-08"),
])
def test_sleep_default_wake_date_uses_owner_day(tmp_path, monkeypatch, owner_clock, zone, expected):
    from healthcheck.web import pages

    app, _, _ = _ui(tmp_path, owner_timezone=zone)
    ends = []
    original = pages._render_sleep_timeline

    def capture(request, **kwargs):
        ends.append(kwargs["end"].isoformat())
        return original(request, **kwargs)

    monkeypatch.setattr(pages, "_render_sleep_timeline", capture)
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        assert client.get("/sleep").status_code == 200
        assert client.get("/sleep?wake_date=2026-01-02").status_code == 200
    assert ends == [expected, "2026-01-02"]


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
