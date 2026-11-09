"""Offline compatibility checks for the consumed python-garminconnect surface."""

from __future__ import annotations

import io
import json
import logging
from types import SimpleNamespace

import pytest
import requests
from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)
from garminconnect.client.sso import _MFARequired, _raise_if_rate_limited

from healthcheck.garmin.auth import _silence_provider_logging, classify_garmin_error
from healthcheck.garmin.probe import GarminCapabilityProbe, _bounded_provider_requests
from healthcheck.garmin.sync import _disable_provider_retries
from healthcheck.garmin.training_probe import (
    _disable_provider_retries as _disable_training_provider_retries,
)

DAY = "2026-01-01"


@pytest.fixture(autouse=True)
def no_network_or_ambient_tokens(monkeypatch):
    monkeypatch.delenv("GARMINTOKENS", raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail("compatibility tests must remain offline")

    monkeypatch.setattr(requests.Session, "request", forbidden)
    from curl_cffi import requests as cffi_requests

    monkeypatch.setattr(cffi_requests.Session, "request", forbidden)


# Golden wire requests reviewed against both upstream tags; zero/null and GMT
# versus Local fields deliberately remain untouched at the provider boundary.
READS = [
    (
        "get_devices",
        (),
        "/device-service/deviceregistration/devices",
        None,
        [{"deviceId": 123, "displayName": "synthetic"}],
    ),
    (
        "get_primary_training_device",
        (),
        "/web-gateway/device-info/primary-training-device",
        None,
        {"primaryTrainingDevice": None},
    ),
    (
        "get_max_metrics_range",
        (DAY, "2026-01-02"),
        "/metrics-service/metrics/maxmet/daily/2026-01-01/2026-01-02",
        None,
        {"maxMetrics": []},
    ),
    (
        "get_user_summary",
        (DAY,),
        "/usersummary-service/usersummary/daily/synthetic",
        {"calendarDate": DAY},
        {"calendarDate": DAY, "totalSteps": 0, "restingHeartRate": None},
    ),
    (
        "get_sleep_data",
        (DAY,),
        "/wellness-service/wellness/dailySleepData/synthetic",
        {"date": DAY, "nonSleepBufferMinutes": 60},
        {
            "dailySleepDTO": {
                "calendarDate": DAY,
                "sleepTimeSeconds": 0,
                "sleepStartTimestampGMT": 1767214800000,
                "sleepStartTimestampLocal": 1767225600000,
            }
        },
    ),
    (
        "get_heart_rates",
        (DAY,),
        "/wellness-service/wellness/dailyHeartRate/synthetic",
        {"date": DAY},
        {"heartRateValues": [[1767225600000, 60], [1767225660000, None]]},
    ),
    (
        "get_rhr_day",
        (DAY,),
        "/userstats-service/wellness/daily/synthetic",
        {"fromDate": DAY, "untilDate": DAY, "metricId": 60},
        {"allMetrics": {"metricsMap": {"WELLNESS_RESTING_HEART_RATE": [{"value": 60}]}}},
    ),
    (
        "get_hrv_data",
        (DAY,),
        "/hrv-service/hrv/2026-01-01",
        None,
        {"hrvSummary": {"calendarDate": DAY, "lastNightAvg": None}},
    ),
    (
        "get_stress_data",
        (DAY,),
        "/wellness-service/wellness/dailyStress/2026-01-01",
        None,
        {"stressValuesArray": [[1767225600000, 0]]},
    ),
    (
        "get_body_battery",
        (DAY,),
        "/wellness-service/wellness/bodyBattery/reports/daily",
        {"startDate": DAY, "endDate": DAY},
        [
            {
                "date": DAY,
                "charged": 0,
                "drained": None,
                "bodyBatteryValuesArray": [[1767225600000, 50]],
            }
        ],
    ),
    (
        "get_body_battery_events",
        (DAY,),
        "/wellness-service/wellness/bodyBattery/events/2026-01-01",
        None,
        [{"eventType": "SLEEP", "durationInMilliseconds": 0}],
    ),
    (
        "get_spo2_data",
        (DAY,),
        "/wellness-service/wellness/daily/spo2/2026-01-01",
        None,
        {"averageSpO2": None, "spo2Values": []},
    ),
    (
        "get_respiration_data",
        (DAY,),
        "/wellness-service/wellness/daily/respiration/2026-01-01",
        None,
        {"avgSleepRespirationValue": None, "respirationValues": []},
    ),
    (
        "get_max_metrics",
        (DAY,),
        "/metrics-service/metrics/maxmet/daily/2026-01-01/2026-01-01",
        None,
        {"maxMetrics": {"vo2MaxRunning": None}},
    ),
    (
        "get_training_readiness",
        (DAY,),
        "/metrics-service/metrics/trainingreadiness/2026-01-01",
        None,
        [{"score": 0, "level": None}],
    ),
    (
        "get_training_status",
        (DAY,),
        "/metrics-service/metrics/trainingstatus/aggregated/2026-01-01",
        None,
        {"trainingStatus": None},
    ),
    (
        "get_activity",
        ("123",),
        "/activity-service/activity/123",
        None,
        {"activityId": 123, "startTimeGMT": "2025-12-31 21:00:00", "distance": 0},
    ),
    (
        "get_activity_details",
        ("123", 1, 0),
        "/activity-service/activity/123/details",
        {"maxChartSize": "1", "maxPolylineSize": "0"},
        {"metricDescriptors": [], "activityDetailMetrics": []},
    ),
    (
        "connectapi",
        ("/activitylist-service/activities/search/activities",),
        None,
        None,
        [{"activityId": 123, "startTimeGMT": "2025-12-31 21:00:00", "duration": 0}],
    ),
]


@pytest.mark.parametrize("timezone", ["Pacific/Kiritimati", "America/Los_Angeles"])
@pytest.mark.parametrize("method,args,path,params,payload", READS, ids=[r[0] for r in READS])
def test_consumed_reads_keep_wire_dates_and_payloads(
    monkeypatch,
    timezone,
    method,
    args,
    path,
    params,
    payload,
):
    provider = Garmin()
    provider.display_name = "synthetic"
    provider.time_zone = timezone
    calls = []

    def wire_read(endpoint, **kwargs):
        calls.append((endpoint, kwargs))
        return payload

    monkeypatch.setattr(provider.client, "connectapi", wire_read)
    monkeypatch.setattr(
        provider,
        "get_user_timezone",
        lambda: pytest.fail("explicit-date reads must not fetch timezone"),
    )
    kwargs = {}
    if method == "connectapi":
        path = args[0]
        params = {"startDate": DAY, "endDate": DAY, "start": "0", "limit": "1"}
        kwargs = {"params": params}
    assert getattr(provider, method)(*args, **kwargs) is payload
    assert calls == [
        (
            path,
            {"params": params} if params is not None or method == "get_max_metrics_range" else {},
        )
    ]


@pytest.mark.parametrize("status", [427, 429])
@pytest.mark.parametrize(
    "bounded",
    [_bounded_provider_requests, _disable_provider_retries, _disable_training_provider_retries],
)
def test_rate_limits_fail_fast_inside_existing_request_bounds(monkeypatch, caplog, status, bounded):
    provider = Garmin()
    calls = []
    response = requests.Response()
    response.status_code = status

    def blocked(*args, **kwargs):
        calls.append(args)
        raise requests.HTTPError("synthetic-secret-ticket", response=response)

    monkeypatch.setattr(provider.client, "connectapi", blocked)
    monkeypatch.setattr("garminconnect.time.sleep", lambda _: pytest.fail("unexpected retry"))
    with bounded(provider), _silence_provider_logging():
        assert provider.retry_attempts == 0
        with pytest.raises(Exception) as caught:
            provider.connectapi("/synthetic")
    error = classify_garmin_error(caught.value)
    assert error.error_code == "rate_limited"
    assert "synthetic-secret" not in json.dumps(error.as_dict()) + caplog.text
    assert len(calls) == 1
    assert provider.retry_attempts == 3
    with pytest.raises(GarminConnectTooManyRequestsError) as sso_error:
        _raise_if_rate_limited(SimpleNamespace(status_code=status), "synthetic SSO")
    assert classify_garmin_error(sso_error.value).error_code == "rate_limited"
    assert classify_garmin_error(requests.HTTPError(response=response)).http_status == status


def test_transient_retry_remains_bounded_and_sanitized(monkeypatch, caplog):
    provider = Garmin(retry_attempts=2)
    calls, waits = [], []

    def unavailable(*args, **kwargs):
        calls.append(args)
        response = requests.Response()
        response.status_code = 503
        raise requests.HTTPError("synthetic-secret-password", response=response)

    monkeypatch.setattr(provider.client, "connectapi", unavailable)
    monkeypatch.setattr("garminconnect.time.sleep", waits.append)
    with _silence_provider_logging(), pytest.raises(Exception) as caught:
        provider.connectapi("/synthetic")
    assert len(calls) == 3 and len(waits) == 2
    assert all(0 <= wait <= provider.retry_max_wait for wait in waits)
    error = classify_garmin_error(caught.value)
    assert error.error_code == "provider_unavailable"
    assert "synthetic-secret" not in json.dumps(error.as_dict()) + caplog.text


@pytest.mark.parametrize(
    "name",
    [
        "garminconnect.api._common",
        "garminconnect.client.session",
        "garminconnect.client.sso",
        "garminconnect.client.tokens",
        "garminconnect.client.transport",
    ],
)
def test_split_provider_loggers_with_own_handlers_are_silenced_and_restored(name):
    logger = logging.getLogger(name)
    original = (logger.disabled, logger.level, logger.propagate, logger.handlers[:])
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.disabled = False
    before = (logger.disabled, logger.level, logger.propagate, logger.handlers[:])
    try:
        with pytest.raises(ValueError), _silence_provider_logging():
            logger.exception("synthetic-secret-token")
            raise ValueError("synthetic-secret-password")
        assert stream.getvalue() == ""
        assert (logger.disabled, logger.level, logger.propagate, logger.handlers[:]) == before
    finally:
        logger.disabled, logger.level, logger.propagate, logger.handlers = original


def test_real_provider_mfa_callback_and_same_instance_resume(monkeypatch):
    provider = Garmin(
        email="synthetic@example.invalid",
        password="synthetic-password",
        prompt_mfa=lambda: "123456",
    )
    codes = []

    def needs_mfa(*args):
        raise _MFARequired()

    def complete(code):
        codes.append(code)
        provider.client.di_token = "synthetic-token"

    for name in (
        "_mobile_login_cffi",
        "_mobile_login_requests",
        "_widget_web_login",
        "_portal_web_login_cffi",
        "_portal_web_login_requests",
    ):
        monkeypatch.setattr(provider.client, name, needs_mfa)
    monkeypatch.setattr(provider.client, "_complete_mfa", complete)
    monkeypatch.setattr(provider.client, "_verify_token", lambda: True)
    monkeypatch.setattr(provider, "_load_profile_and_settings", lambda: None)
    assert provider.login(tokenstore=None) == (None, None)
    assert codes == ["123456"]
    assert provider.password is None
    provider.client._mfa_pending = True
    assert provider.resume_login({"unused_same_instance_state": True}, "654321") == (None, None)
    assert codes == ["123456", "654321"]
    assert provider.client._mfa_pending is False


def test_refreshed_inline_session_round_trip_never_uses_provider_files(monkeypatch):
    provider = Garmin()
    snapshot = json.dumps(
        {
            "di_token": "synthetic-old-token",
            "di_refresh_token": "synthetic-refresh",
            "di_client_id": "synthetic-id",
        }
    )
    refreshes = []

    def refresh():
        refreshes.append(True)
        provider.client.di_token = "synthetic-refreshed-token"

    monkeypatch.setattr(provider.client, "_token_expires_soon", lambda: True)
    monkeypatch.setattr(provider.client, "_refresh_session", refresh)
    monkeypatch.setattr(provider, "_load_profile_and_settings", lambda: None)
    monkeypatch.setattr(provider.client, "load", lambda _: pytest.fail("unexpected file read"))
    monkeypatch.setattr(provider.client, "dump", lambda _: pytest.fail("unexpected file write"))
    assert provider.login(tokenstore=snapshot) == (None, None)
    assert refreshes == [True]
    saved = json.loads(provider.client.dumps())
    assert saved == {
        "di_token": "synthetic-refreshed-token",
        "di_refresh_token": "synthetic-refresh",
        "di_client_id": "synthetic-id",
    }
    restored = Garmin()
    restored.client.loads(json.dumps(saved))
    assert json.loads(restored.client.dumps()) == saved


@pytest.mark.parametrize("status", [427, 429])
def test_real_transport_errors_are_safe_in_public_probe_report(monkeypatch, caplog, status):
    provider = Garmin()
    provider.display_name = "synthetic"
    provider.client.di_token = "synthetic-secret-token"
    response = requests.Response()
    response.status_code = status
    response._content = b'{"message":"synthetic-secret-password","token":"synthetic-secret-token"}'
    monkeypatch.setattr(provider.client, "_token_expires_soon", lambda: False)
    monkeypatch.setattr(provider.client._api_session, "request", lambda *a, **kw: response)
    monkeypatch.setattr("garminconnect.time.sleep", lambda _: pytest.fail("unexpected retry"))
    with caplog.at_level(logging.DEBUG):
        report = GarminCapabilityProbe(provider).run([DAY])
    rendered = json.dumps(report.as_dict())
    assert "rate_limited" in rendered
    assert "synthetic-secret" not in rendered + caplog.text
    assert provider.retry_attempts == 3


@pytest.mark.parametrize(
    "method,payload,error_type",
    [
        ("get_user_summary", {}, GarminConnectConnectionError),
        ("get_user_summary", {"privacyProtected": True}, GarminConnectAuthenticationError),
        ("get_heart_rates", None, GarminConnectConnectionError),
        ("get_hrv_data", None, None),
        ("get_body_battery", [], None),
        ("get_sleep_data", {}, None),
    ],
)
def test_consumed_empty_and_private_payload_behavior(monkeypatch, method, payload, error_type):
    provider = Garmin()
    provider.display_name = "synthetic"
    monkeypatch.setattr(provider.client, "connectapi", lambda *a, **kw: payload)
    if error_type:
        with pytest.raises(error_type):
            getattr(provider, method)(DAY)
    else:
        assert getattr(provider, method)(DAY) is payload


def test_spo2_string_conversion_remains_compatible(monkeypatch):
    provider = Garmin()
    monkeypatch.setattr(
        provider.client, "connectapi", lambda *a, **kw: {"lastSevenDaysAvgSpO2": "97.5"}
    )
    assert provider.get_spo2_data(DAY) == {"lastSevenDaysAvgSpO2": 97.5}


@pytest.mark.parametrize("method", ["get_activity", "get_activity_details"])
@pytest.mark.parametrize("activity_id", [1.9, "1.9"])
def test_fractional_activity_ids_are_rejected_before_transport(monkeypatch, method, activity_id):
    provider = Garmin()
    monkeypatch.setattr(
        provider.client, "connectapi", lambda *a, **kw: pytest.fail("invalid ID reached transport")
    )
    with pytest.raises(ValueError):
        getattr(provider, method)(activity_id)
