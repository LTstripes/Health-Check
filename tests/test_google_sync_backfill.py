"""Synthetic Google Health sync/backfill/refresh regressions for issue #88."""

from __future__ import annotations

import errno
import hashlib
import json
import sqlite3
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine

from healthcheck import cli
from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine
from healthcheck.db.models import (
    CoverageInterval,
    GarminRawPayload,
    GarminSource,
    GarminSourceRecord,
    GooglePayloadObservation,
    GoogleRawPayload,
    GoogleRecordMetric,
    GoogleSource,
    GoogleSourceRecord,
    RawArtifact,
    SyncStreamState,
)
from healthcheck.external_runtime_lock import (
    ExternalRuntimeOperationBusyError,
    ExternalRuntimeOperationLock,
)
from healthcheck.google.auth import (
    ALLOWED_SCOPES,
    DEFAULT_SCOPE_ORDER,
    SCOPE_METRICS,
    GoogleAuthResult,
    GoogleAuthService,
    GoogleAuthStatus,
    GoogleClientCredentials,
    GoogleHttpResponse,
    GoogleOAuthError,
    GoogleTokenHealth,
    GoogleTokenSet,
)
from healthcheck.google.backfill import (
    GoogleHistoricalBackfill,
    plan_google_historical_backfill,
)
from healthcheck.google.contracts import (
    FAMILY_GOOGLE_WEARABLES,
    GoogleQueryMode,
    GoogleStream,
)
from healthcheck.google.persistence import GooglePersistenceRepository
from healthcheck.google.protection import GoogleLocalKeyFileProtection
from healthcheck.google.sync import (
    MAX_PAGES_PER_FETCH,
    MAX_RETRY_ATTEMPTS,
    MAX_SYNC_PROVIDER_REQUESTS,
    RETRY_BACKOFF_SECONDS,
    SLEEP_PAGE_SIZE,
    UNATTRIBUTED_SOURCE_INSTANCE,
    GoogleHealthSync,
    GoogleHrPhaseTiming,
    GoogleRunKind,
    GoogleSafeError,
    GoogleSyncStatus,
    _owner_heart_rate_day_refresh,
    checkpoint_stream_code,
    parse_page_envelope,
    run_google_incremental_sync,
    run_google_refresh,
)
from healthcheck.runtime import prepare_runtime

AS_OF = "2099-01-02"
SYNTHETIC_ACCESS = "synthetic-access-token-value"
SYNTHETIC_REFRESH = "synthetic-refresh-token-value"
SYNTHETIC_SECRET = "synthetic-client-secret-value"


def _civil(day: int = 2, hour: int = 8) -> dict[str, object]:
    return {
        "date": {"year": 2099, "month": 1, "day": day},
        "time": {"hours": hour, "minutes": 0, "seconds": 0, "nanos": 0},
    }


def _sample_time(day: int = 2, hour: int = 8) -> dict[str, object]:
    return {
        "physicalTime": f"2099-01-{day:02d}T05:00:00Z",
        "utcOffset": "10800s",
        "civilTime": _civil(day=day, hour=hour),
    }


def _data_source() -> dict[str, object]:
    return {
        "recordingMethod": "PASSIVELY_MEASURED",
        "device": {
            "formFactor": "WATCH",
            "manufacturer": "Synthetic Devices",
            "displayName": "Synthetic Watch",
        },
        "application": {"packageName": "org.synthetic.health"},
        "platform": "GOOGLE_WEB_API",
    }


def _named_data_source(resource: str, **overrides: object) -> dict[str, object]:
    value = _data_source()
    value["name"] = resource
    value.update(overrides)
    return value


def _hr_point(
    *,
    name: str,
    bpm: str,
    day: int = 2,
    hour: int = 8,
    data_source: Mapping[str, object] | None = None,
) -> dict[str, object]:
    # Frozen #156 identity is sample-time based.  Keep each synthetic page
    # point distinct even when a test omits an explicit timestamp dimension.
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    seconds = int(digest[:2], 16) % 60
    micros = int(digest[2:8], 16) % 1_000_000
    sample_time = _sample_time(day=day, hour=hour)
    sample_time["physicalTime"] = f"2099-01-{day:02d}T05:00:{seconds:02d}.{micros:06d}Z"
    return {
        "name": name,
        "dataSource": dict(data_source) if data_source is not None else _data_source(),
        "heartRate": {
            "sampleTime": sample_time,
            "beatsPerMinute": bpm,
        },
    }


def _sleep_point(*, name: str, day: int = 2) -> dict[str, object]:
    return {
        "name": name,
        "dataSource": _data_source(),
        "sleep": {
            "interval": {
                "startTime": "2099-01-01T22:00:00Z",
                "startUtcOffset": "10800s",
                "endTime": "2099-01-02T05:00:00Z",
                "endUtcOffset": "10800s",
                "civilStartTime": _civil(day=day, hour=1),
                "civilEndTime": _civil(day=day, hour=8),
            },
            "type": "STAGES",
            "stages": [
                {
                    "startTime": "2099-01-01T22:00:00Z",
                    "startUtcOffset": "10800s",
                    "endTime": "2099-01-01T23:00:00Z",
                    "endUtcOffset": "10800s",
                    "type": "LIGHT",
                }
            ],
            "metadata": {"stagesStatus": "SUCCEEDED", "processed": True, "nap": False},
            "summary": {
                "minutesInSleepPeriod": "420",
                "minutesAsleep": "410",
                "minutesAwake": "10",
            },
        },
    }


def _daily_point(field: str, component: dict[str, object], *, name: str) -> dict[str, object]:
    return {"name": name, "dataSource": _data_source(), field: component}


class FakeGoogleHealthTransport:
    """Deterministic fake Google Health HTTP transport for CI."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._queues: dict[tuple[str, str, str], list[GoogleHttpResponse | Exception]] = {}
        self.default_empty = True

    def queue(
        self,
        data_type: str,
        payload: Mapping[str, Any] | int,
        *,
        page_token: str | None = None,
        status: int = 200,
        operation: str = "list",
    ) -> None:
        key = (operation, data_type, page_token or "")
        if isinstance(payload, int):
            response = GoogleHttpResponse(payload, b'{"error":"synthetic"}')
        else:
            response = GoogleHttpResponse(status, json.dumps(dict(payload)).encode())
        self._queues.setdefault(key, []).append(response)

    def queue_raw(
        self,
        data_type: str,
        body: bytes,
        *,
        status: int = 200,
        page_token: str | None = None,
        operation: str = "list",
    ) -> None:
        key = (operation, data_type, page_token or "")
        self._queues.setdefault(key, []).append(GoogleHttpResponse(status, body))

    def queue_error(
        self, data_type: str, error: Exception, *, page_token: str | None = None
    ) -> None:
        self._queues.setdefault(("list", data_type, page_token or ""), []).append(error)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        form: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> GoogleHttpResponse:
        del timeout, form
        safe_headers = {
            key: ("<redacted>" if key.lower() == "authorization" else value)
            for key, value in dict(headers or {}).items()
        }
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        operation = "list"
        if url.endswith(":reconcile") or ":reconcile?" in url:
            operation = "reconcile"
        elif ":rollUp" in url:
            operation = "rollUp"
        elif ":dailyRollUp" in url:
            operation = "dailyRollUp"
        data_type = ""
        marker = "/dataTypes/"
        if marker in parsed.path:
            remainder = parsed.path.split(marker, 1)[1]
            data_type = remainder.split("/", 1)[0]
        page_token = ""
        if json_body and json_body.get("pageToken"):
            page_token = str(json_body["pageToken"])
        elif query.get("pageToken"):
            page_token = query["pageToken"][0]
        self.calls.append(
            {
                "method": method,
                "url": url,
                "path": parsed.path,
                "headers": safe_headers,
                "json_body": json.loads(json.dumps(json_body)) if json_body is not None else None,
                "operation": operation,
                "data_type": data_type,
                "page_size": (json_body or {}).get("pageSize")
                or (query.get("pageSize") or [None])[0],
                "has_page_token": bool(page_token),
                "family": (json_body or {}).get("dataSourceFamily")
                or (query.get("dataSourceFamily") or [None])[0],
                "filter": unquote(query.get("filter", [""])[0]),
            }
        )
        if "googleapis.com/token" in url:
            return GoogleHttpResponse(
                200,
                json.dumps(
                    {
                        "access_token": SYNTHETIC_ACCESS + "-refreshed",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "scope": " ".join(DEFAULT_SCOPE_ORDER),
                    }
                ).encode(),
            )
        key = (operation, data_type, page_token)
        queue = self._queues.get(key)
        if queue:
            result = queue.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        if self.default_empty:
            if operation in {"rollUp", "dailyRollUp"}:
                envelope = "rollupDataPoints"
            else:
                envelope = "dataPoints"
            return GoogleHttpResponse(200, json.dumps({envelope: []}).encode())
        return GoogleHttpResponse(404, b'{"error":"not_found"}')

    def health_calls(self) -> list[dict[str, Any]]:
        return [item for item in self.calls if "health.googleapis.com" in item["url"]]


def _auth_result() -> GoogleAuthResult:
    return GoogleAuthResult(
        status=GoogleAuthStatus.AUTHENTICATED,
        token_health=GoogleTokenHealth.VALID,
        session_reused=True,
        granted_scope_count=2,
        missing_scope_count=0,
    )


def _runtime(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    return Settings(data_dir=paths.root), paths


def _sync(
    tmp_path,
    transport: FakeGoogleHealthTransport,
    *,
    kind: GoogleRunKind = GoogleRunKind.INCREMENTAL,
    scopes: frozenset[str] | None = None,
    max_provider_requests: int = MAX_SYNC_PROVIDER_REQUESTS,
    sleeper=None,
) -> tuple[Settings, GoogleHealthSync]:
    settings, _paths = _runtime(tmp_path)
    service = GoogleHealthSync(
        settings,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=scopes if scopes is not None else ALLOWED_SCOPES,
        sleeper=sleeper,
        max_provider_requests=max_provider_requests,
        run_kind=kind,
    )
    return settings, service


def _session(settings: Settings):
    from healthcheck.db.engine import migrate_database

    paths = prepare_runtime(settings)
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    factory = create_session_factory(engine)
    return engine, factory


def test_heart_rate_empty_first_page_with_token_is_not_confirmed_empty(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", {"nextPageToken": "page-two"})
    transport.queue(
        "heart-rate",
        {"dataPoints": [_hr_point(name="hr-1", bpm="72")]},
        page_token="page-two",
    )
    _settings, service = _sync(tmp_path, transport)
    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert report.status is GoogleSyncStatus.SUCCEEDED
    attempt = report.attempts[0]
    assert attempt.coverage_status == "present"
    assert attempt.coverage_status != "confirmed_empty"
    assert attempt.page_count == 2
    assert attempt.record_count == 1
    assert [item["has_page_token"] for item in transport.health_calls()] == [False, True]
    parsed = parse_page_envelope({"nextPageToken": "page-two"}, GoogleQueryMode.LIST)
    assert parsed == ([], "page-two", "continue")


def test_multi_page_list_follows_tokens_without_gap_or_duplicate(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue(
        "heart-rate",
        {
            "dataPoints": [_hr_point(name="hr-a", bpm="60", hour=7)],
            "nextPageToken": "p2",
        },
    )
    transport.queue(
        "heart-rate",
        {"dataPoints": [_hr_point(name="hr-b", bpm="80", hour=9)]},
        page_token="p2",
    )
    settings, service = _sync(tmp_path, transport)
    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert report.status is GoogleSyncStatus.SUCCEEDED
    assert report.attempts[0].record_count == 2
    engine, factory = _session(settings)
    try:
        with factory() as session:
            names = {
                row.external_record_id
                for row in session.scalars(select(GoogleSourceRecord)).all()
            }
            assert names == {"hr-a", "hr-b"}
            assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 2
    finally:
        engine.dispose()


def test_sleep_page_cap_does_not_truncate(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    first = [_sleep_point(name=f"sleep-{index}") for index in range(SLEEP_PAGE_SIZE)]
    rest = [_sleep_point(name=f"sleep-{index}") for index in range(SLEEP_PAGE_SIZE, 30)]
    transport.queue("sleep", {"dataPoints": first, "nextPageToken": "sleep-2"})
    transport.queue("sleep", {"dataPoints": rest}, page_token="sleep-2")
    settings, service = _sync(tmp_path, transport)
    report = service.run(start=AS_OF, end=AS_OF, streams=["sleep"])
    assert report.status is GoogleSyncStatus.SUCCEEDED
    assert report.attempts[0].record_count == 30
    assert all(str(item["page_size"]) == str(SLEEP_PAGE_SIZE) for item in transport.health_calls())
    engine, factory = _session(settings)
    try:
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 30
    finally:
        engine.dispose()


def test_budget_stop_is_unknown_and_does_not_advance_success_checkpoint(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue(
        "heart-rate",
        {"dataPoints": [_hr_point(name="hr-1", bpm="70")], "nextPageToken": "more"},
    )
    transport.queue(
        "heart-rate",
        {"dataPoints": [_hr_point(name="hr-2", bpm="71")]},
        page_token="more",
    )
    settings, service = _sync(tmp_path, transport, max_provider_requests=1)
    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert report.status is GoogleSyncStatus.PARTIAL
    attempt = report.attempts[0]
    assert attempt.coverage_status == "unknown"
    assert attempt.resume_cursor_present is True
    engine, factory = _session(settings)
    try:
        with factory() as session:
            states = list(session.scalars(select(SyncStreamState)))
            assert states
            assert states[0].watermark is None
            coverage = list(session.scalars(select(CoverageInterval)))
            assert any(row.status == "unknown" for row in coverage)
            assert not any(row.status in {"present", "confirmed_empty"} for row in coverage)
    finally:
        engine.dispose()
    report2 = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert report2.status is GoogleSyncStatus.SUCCEEDED
    assert report2.attempts[0].coverage_status == "present"
    assert any(item["has_page_token"] for item in transport.health_calls()[1:])


def test_retry_429_and_504_then_success(tmp_path) -> None:
    sleeps: list[float] = []
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", 429)
    transport.queue("heart-rate", 504)
    transport.queue("heart-rate", {"dataPoints": [_hr_point(name="hr-1", bpm="64")]})
    _settings, service = _sync(tmp_path, transport, sleeper=sleeps.append)
    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert report.status is GoogleSyncStatus.SUCCEEDED
    assert report.attempts[0].coverage_status == "present"
    assert sleeps == [RETRY_BACKOFF_SECONDS[0], RETRY_BACKOFF_SECONDS[1]]
    assert len(transport.health_calls()) == 3


def test_refresh_hr_phase_timing_uses_monotonic_boundaries_without_changing_retry(
    monkeypatch, tmp_path
) -> None:
    import healthcheck.google.sync as google_sync

    ticks = iter(range(0, 100_000_000, 1_000_000))
    monkeypatch.setattr(google_sync, "monotonic_ns", lambda: next(ticks))
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", 503)
    transport.queue("heart-rate", {"dataPoints": [_hr_point(name="hr-1", bpm="64")]})
    settings, _service = _sync(tmp_path, transport)
    sleeps: list[float] = []
    timing = GoogleHrPhaseTiming()

    report = run_google_refresh(
        settings,
        start=AS_OF,
        end=AS_OF,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
        sleeper=sleeps.append,
        phase_timing=timing,
    )

    assert report.status is GoogleSyncStatus.SUCCEEDED
    assert report.request_count == 2
    assert report.attempts[0].page_count == 1
    assert sleeps == [RETRY_BACKOFF_SECONDS[0]]
    assert len(transport.health_calls()) == 2
    assert timing.as_dict() == {
        "provider_acquisition_ms": 2,
        "retry_backoff_ms": 1,
        "page_processing_staging_ms": 3,
        "promotion_apply_ms": 1,
    }


def test_refresh_hr_phase_timing_clock_failure_is_diagnostic_only(monkeypatch, tmp_path) -> None:
    import healthcheck.google.sync as google_sync

    def unavailable_clock() -> int:
        raise RuntimeError("unavailable")

    monkeypatch.setattr(google_sync, "monotonic_ns", unavailable_clock)
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", {"dataPoints": [_hr_point(name="hr-1", bpm="64")]})
    settings, _service = _sync(tmp_path, transport)
    timing = GoogleHrPhaseTiming()
    report = run_google_refresh(
        settings,
        start=AS_OF,
        end=AS_OF,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
        phase_timing=timing,
    )
    assert report.status is GoogleSyncStatus.SUCCEEDED
    assert report.request_count == 1
    assert all(value is None for value in timing.as_dict().values())


def test_refresh_hr_phase_timing_preserves_partial_failed_and_reauth(tmp_path) -> None:
    cases = (
        (
            "partial",
            {"dataPoints": [_hr_point(name="hr-partial", bpm="64")], "nextPageToken": "next"},
            1,
            GoogleSyncStatus.PARTIAL,
        ),
        ("failed", 400, 1, GoogleSyncStatus.FAILED),
        ("reauth", 401, 1, GoogleSyncStatus.REAUTH_REQUIRED),
    )
    for label, response, budget, expected in cases:
        transport = FakeGoogleHealthTransport()
        transport.queue("heart-rate", response)
        settings, _service = _sync(tmp_path / label, transport)
        timing = GoogleHrPhaseTiming()
        report = run_google_refresh(
            settings,
            start=AS_OF,
            end=AS_OF,
            transport=transport,
            auth_result=_auth_result(),
            access_token=SYNTHETIC_ACCESS,
            granted_scopes=ALLOWED_SCOPES,
            streams=["heart_rate"],
            max_provider_requests=budget,
            phase_timing=timing,
        )
        assert report.status is expected
        assert report.request_count == 1
        assert len(transport.health_calls()) == 1
        assert timing.as_dict()["provider_acquisition_ms"] is not None
        assert timing.as_dict()["promotion_apply_ms"] is None
        assert all(
            key.endswith("_ms") and (value is None or type(value) is int)
            for key, value in timing.as_dict().items()
        )


def test_retry_transient_provider_5xx_then_success(tmp_path) -> None:
    for status in (500, 502, 503):
        sleeps: list[float] = []
        transport = FakeGoogleHealthTransport()
        transport.queue("heart-rate", status)
        transport.queue(
            "heart-rate",
            {"dataPoints": [_hr_point(name=f"hr-{status}", bpm="64")]},
        )
        _settings, service = _sync(tmp_path / str(status), transport, sleeper=sleeps.append)

        report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])

        assert report.status is GoogleSyncStatus.SUCCEEDED
        assert report.request_count == 2
        assert report.attempts[0].coverage_status == "present"
        assert sleeps == [RETRY_BACKOFF_SECONDS[0]]
        assert len(transport.health_calls()) == 2


def test_repeated_transient_provider_5xx_exhausts_existing_retry_count(tmp_path) -> None:
    sleeps: list[float] = []
    transport = FakeGoogleHealthTransport()
    for _ in range(MAX_RETRY_ATTEMPTS):
        transport.queue("heart-rate", 503)
    _settings, service = _sync(tmp_path, transport, sleeper=sleeps.append)

    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])

    assert report.status is GoogleSyncStatus.FAILED
    assert report.request_count == MAX_RETRY_ATTEMPTS
    assert report.attempts[0].error == GoogleSafeError("provider", "retryable", 503)
    assert sleeps == list(RETRY_BACKOFF_SECONDS[: MAX_RETRY_ATTEMPTS - 1])
    assert len(transport.health_calls()) == MAX_RETRY_ATTEMPTS


def test_transient_provider_5xx_retry_respects_request_budget(tmp_path) -> None:
    sleeps: list[float] = []
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", 503)
    transport.queue("heart-rate", 503)
    transport.queue("heart-rate", {"dataPoints": []})
    _settings, service = _sync(
        tmp_path,
        transport,
        max_provider_requests=2,
        sleeper=sleeps.append,
    )

    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])

    assert report.status is GoogleSyncStatus.FAILED
    assert report.request_count == 2
    assert report.attempts[0].error == GoogleSafeError("budget", "request_ceiling")
    assert sleeps == list(RETRY_BACKOFF_SECONDS[:2])
    assert len(transport.health_calls()) == 2


def test_transport_unavailable_retries_same_page_and_completes_checkpoint(
    monkeypatch, tmp_path
) -> None:
    import healthcheck.google.sync as google_sync

    ticks = iter(range(0, 100_000_000, 1_000_000))
    monkeypatch.setattr(google_sync, "monotonic_ns", lambda: next(ticks))
    transport = FakeGoogleHealthTransport()
    transport.queue(
        "heart-rate",
        {"dataPoints": [_hr_point(name="hr-1", bpm="64")], "nextPageToken": "p2"},
    )
    transport.queue_error("heart-rate", TimeoutError("synthetic transport detail"), page_token="p2")
    transport.queue(
        "heart-rate", {"dataPoints": [_hr_point(name="hr-2", bpm="65")]}, page_token="p2"
    )
    sleeps: list[float] = []
    timing = GoogleHrPhaseTiming()
    settings, _service = _sync(tmp_path, transport)

    report = run_google_refresh(
        settings,
        start=AS_OF,
        end=AS_OF,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
        sleeper=sleeps.append,
        phase_timing=timing,
    )

    assert report.status is GoogleSyncStatus.SUCCEEDED
    assert report.request_count == 3
    assert report.attempts[0].page_count == 2
    assert report.attempts[0].record_count == 2
    assert sleeps == [RETRY_BACKOFF_SECONDS[0]]
    assert [call["has_page_token"] for call in transport.health_calls()] == [False, True, True]
    assert timing.as_dict()["retry_backoff_ms"] == 1
    assert "synthetic transport detail" not in report.to_json()
    assert "p2" not in report.to_json()

    engine, factory = _session(settings)
    try:
        with factory() as session:
            state = session.scalar(
                select(SyncStreamState).where(
                    SyncStreamState.stream_code
                    == checkpoint_stream_code(
                        namespace="refresh",
                        stream=GoogleStream.HEART_RATE,
                        query_mode=GoogleQueryMode.LIST,
                        data_source_family=None,
                    )
                )
            )
            assert state is not None
            assert state.watermark is not None
            assert state.cursor is None
    finally:
        engine.dispose()


def test_transport_unavailable_exhausts_existing_retry_count(tmp_path) -> None:
    sleeps: list[float] = []
    transport = FakeGoogleHealthTransport()
    for _ in range(MAX_RETRY_ATTEMPTS):
        transport.queue_error("heart-rate", TimeoutError("synthetic transport detail"))
    _settings, service = _sync(tmp_path, transport, sleeper=sleeps.append)

    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])

    assert report.status is GoogleSyncStatus.FAILED
    assert report.request_count == MAX_RETRY_ATTEMPTS
    assert report.attempts[0].error == GoogleSafeError("provider", "provider_unavailable")
    assert sleeps == list(RETRY_BACKOFF_SECONDS[: MAX_RETRY_ATTEMPTS - 1])
    assert len(transport.health_calls()) == MAX_RETRY_ATTEMPTS
    assert "synthetic transport detail" not in report.to_json()


def test_transport_unavailable_retry_respects_request_budget(tmp_path) -> None:
    sleeps: list[float] = []
    transport = FakeGoogleHealthTransport()
    transport.queue_error("heart-rate", TimeoutError("synthetic transport detail"))
    transport.queue("heart-rate", {"dataPoints": []})
    _settings, service = _sync(tmp_path, transport, max_provider_requests=1, sleeper=sleeps.append)

    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])

    assert report.status is GoogleSyncStatus.FAILED
    assert report.request_count == 1
    assert report.attempts[0].error == GoogleSafeError("budget", "request_ceiling")
    assert sleeps == [RETRY_BACKOFF_SECONDS[0]]
    assert len(transport.health_calls()) == 1


def test_transport_retry_on_resumed_page_preserves_checkpoint(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue(
        "heart-rate",
        {"dataPoints": [_hr_point(name="hr-1", bpm="64")], "nextPageToken": "p2"},
    )
    settings, first_service = _sync(tmp_path, transport, max_provider_requests=1)
    first = first_service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert first.status is GoogleSyncStatus.PARTIAL
    assert first.attempts[0].resume_cursor_present is True

    transport.queue_error("heart-rate", TimeoutError("synthetic"), page_token="p2")
    transport.queue(
        "heart-rate", {"dataPoints": [_hr_point(name="hr-2", bpm="65")]}, page_token="p2"
    )
    sleeps: list[float] = []
    _settings, resumed_service = _sync(
        tmp_path, transport, max_provider_requests=2, sleeper=sleeps.append
    )
    second = resumed_service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])

    assert second.status is GoogleSyncStatus.SUCCEEDED
    assert second.request_count == 2
    assert second.attempts[0].record_count == 1
    assert second.attempts[0].resume_cursor_present is False
    assert sleeps == [RETRY_BACKOFF_SECONDS[0]]
    assert [call["has_page_token"] for call in transport.health_calls()] == [
        False,
        True,
        True,
    ]
    engine, factory = _session(settings)
    try:
        with factory() as session:
            state = session.scalar(
                select(SyncStreamState).where(
                    SyncStreamState.stream_code
                    == checkpoint_stream_code(
                        namespace="incremental",
                        stream=GoogleStream.HEART_RATE,
                        query_mode=GoogleQueryMode.LIST,
                        data_source_family=None,
                    )
                )
            )
            assert state is not None
            assert state.watermark is not None
            assert state.cursor is None
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            GoogleOAuthError("authentication", "invalid_grant"),
            GoogleSafeError("authentication", "invalid_grant"),
        ),
        (
            GoogleOAuthError("authentication", "authentication_failed"),
            GoogleSafeError("authentication", "authentication_failed"),
        ),
        (
            PermissionError("synthetic storage detail"),
            GoogleSafeError("storage", "storage_permission"),
        ),
        (
            GoogleOAuthError("storage", "provider_unavailable"),
            GoogleSafeError("storage", "provider_unavailable"),
        ),
        (ValueError("synthetic input detail"), GoogleSafeError("input", "invalid_input")),
        (RuntimeError("synthetic provider detail"), GoogleSafeError("provider", "provider_error")),
    ],
)
def test_non_transport_exceptions_are_not_retried(tmp_path, error, expected) -> None:
    sleeps: list[float] = []
    transport = FakeGoogleHealthTransport()
    transport.queue_error("heart-rate", error)
    transport.queue("heart-rate", {"dataPoints": []})
    _settings, service = _sync(tmp_path, transport, sleeper=sleeps.append)

    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])

    assert report.request_count == 1
    assert report.attempts[0].error == expected
    assert sleeps == []
    assert len(transport.health_calls()) == 1
    assert "synthetic" not in report.to_json()


def test_invalid_response_shape_is_not_retried(tmp_path) -> None:
    sleeps: list[float] = []
    transport = FakeGoogleHealthTransport()
    transport.queue_raw("heart-rate", b"not-json")
    transport.queue("heart-rate", {"dataPoints": []})
    _settings, service = _sync(tmp_path, transport, sleeper=sleeps.append)

    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])

    assert report.status is GoogleSyncStatus.FAILED
    assert report.request_count == 1
    assert report.attempts[0].error == GoogleSafeError("provider", "response_invalid", 200)
    assert sleeps == []
    assert len(transport.health_calls()) == 1


def test_non_retryable_4xx_remains_terminal_provider_error(tmp_path) -> None:
    sleeps: list[float] = []
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", 400)
    transport.queue("heart-rate", {"dataPoints": []})
    _settings, service = _sync(tmp_path, transport, sleeper=sleeps.append)

    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])

    assert report.status is GoogleSyncStatus.FAILED
    assert report.request_count == 1
    assert report.attempts[0].error == GoogleSafeError("provider", "provider_error", 400)
    assert sleeps == []
    assert len(transport.health_calls()) == 1


def test_historical_and_incremental_namespaces_are_isolated(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", {"dataPoints": [_hr_point(name="hr-inc", bpm="70")]})
    settings, incremental = _sync(tmp_path, transport)
    first = incremental.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert first.status is GoogleSyncStatus.SUCCEEDED
    calls_after_incremental = len(transport.health_calls())
    historical = GoogleHealthSync(
        settings,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        run_kind=GoogleRunKind.HISTORICAL,
    )
    transport.queue("heart-rate", {"dataPoints": [_hr_point(name="hr-hist", bpm="71")]})
    second = historical.run_window(
        start=date.fromisoformat(AS_OF),
        end_exclusive=date.fromisoformat("2099-01-03"),
        streams=["heart_rate"],
        skip_complete=True,
    )
    assert second.status is GoogleSyncStatus.SUCCEEDED
    assert len(transport.health_calls()) > calls_after_incremental
    engine, factory = _session(settings)
    try:
        with factory() as session:
            codes = {row.stream_code for row in session.scalars(select(SyncStreamState))}
            assert checkpoint_stream_code(
                namespace="incremental",
                stream=GoogleStream.HEART_RATE,
                query_mode=GoogleQueryMode.LIST,
                data_source_family=None,
            ) in codes
            assert any(code.startswith("google:historical:") for code in codes)
            assert any(code.startswith("google:incremental:") for code in codes)
    finally:
        engine.dispose()
    third = incremental.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert third.attempts[0].skipped is True
    assert third.request_count == 0


def test_completed_exact_rerun_makes_zero_provider_calls(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", {"dataPoints": [_hr_point(name="hr-1", bpm="66")]})
    _settings, service = _sync(tmp_path, transport)
    first = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert first.request_count == 1
    second = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert second.request_count == 0
    assert second.attempts[0].skipped is True
    assert len(transport.health_calls()) == 1


def test_bounded_refresh_late_correction_preserves_prior_raw(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", {"dataPoints": [_hr_point(name="hr-1", bpm="72")]})
    settings, incremental = _sync(tmp_path, transport)
    incremental.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    transport.queue("heart-rate", {"dataPoints": [_hr_point(name="hr-1", bpm="81")]})
    refresh = run_google_refresh(
        settings,
        start=AS_OF,
        end=AS_OF,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
    )
    assert refresh.status is GoogleSyncStatus.SUCCEEDED
    assert refresh.request_count >= 1
    engine, factory = _session(settings)
    try:
        with factory() as session:
            metrics = list(session.scalars(select(GoogleRecordMetric)))
            current = [item for item in metrics if item.metric_code == "heart_rate_bpm"]
            assert len(current) == 1
            assert current[0].value_number == 81
            assert session.scalar(select(func.count()).select_from(GoogleRawPayload)) >= 2
            assert session.scalar(select(func.count()).select_from(GooglePayloadObservation)) >= 2
            records = list(session.scalars(select(GoogleSourceRecord)))
            assert len(records) == 1
    finally:
        engine.dispose()


def test_repeat_successful_refresh_is_idempotent_for_current_projection(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    payload = {"dataPoints": [_hr_point(name="hr-1", bpm="77")]}
    transport.queue("heart-rate", payload)
    settings, incremental = _sync(tmp_path, transport)
    incremental.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    transport.queue("heart-rate", payload)
    first = run_google_refresh(
        settings,
        start=AS_OF,
        end=AS_OF,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
    )
    transport.queue("heart-rate", payload)
    second = run_google_refresh(
        settings,
        start=AS_OF,
        end=AS_OF,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
    )
    assert first.status is GoogleSyncStatus.SUCCEEDED
    assert second.status is GoogleSyncStatus.SUCCEEDED
    engine, factory = _session(settings)
    try:
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 1
            metric = session.scalar(
                select(GoogleRecordMetric).where(GoogleRecordMetric.metric_code == "heart_rate_bpm")
            )
            assert metric is not None
            assert metric.value_number == 77
    finally:
        engine.dispose()


def test_failed_refresh_leaves_current_projection_and_checkpoint_intact(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", {"dataPoints": [_hr_point(name="hr-1", bpm="72")]})
    settings, incremental = _sync(tmp_path, transport)
    incremental.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    transport.queue("heart-rate", {"unexpected": True})
    refresh = run_google_refresh(
        settings,
        start=AS_OF,
        end=AS_OF,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
    )
    assert refresh.status is GoogleSyncStatus.FAILED
    assert refresh.attempts[0].coverage_status == "failed"
    assert refresh.attempts[0].error is not None
    assert refresh.attempts[0].error.error_code == "shape_drift_page_envelope"
    engine, factory = _session(settings)
    try:
        with factory() as session:
            metric = session.scalar(
                select(GoogleRecordMetric).where(GoogleRecordMetric.metric_code == "heart_rate_bpm")
            )
            assert metric is not None
            assert metric.value_number == 72
            incremental_code = checkpoint_stream_code(
                namespace="incremental",
                stream=GoogleStream.HEART_RATE,
                query_mode=GoogleQueryMode.LIST,
                data_source_family=None,
            )
            state = session.scalar(
                select(SyncStreamState).where(SyncStreamState.stream_code == incremental_code)
            )
            assert state is not None
            assert state.watermark is not None
            raw_count = session.scalar(select(func.count()).select_from(GoogleRawPayload))
            assert raw_count >= 2
    finally:
        engine.dispose()


def test_shape_drift_diagnosis_distinguishes_page_envelope_from_normalization(
    tmp_path,
) -> None:
    envelope_transport = FakeGoogleHealthTransport()
    envelope_transport.queue("heart-rate", {"unexpected": True})
    _settings, envelope_service = _sync(tmp_path / "envelope", envelope_transport)
    envelope_report = envelope_service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])

    normalization_transport = FakeGoogleHealthTransport()
    normalization_transport.queue(
        "heart-rate",
        {
            "dataPoints": [
                {
                    "name": "hr-invalid",
                    "dataSource": _data_source(),
                    "heartRate": {"sampleTime": _sample_time()},
                }
            ]
        },
    )
    _settings, normalization_service = _sync(tmp_path / "normalization", normalization_transport)
    normalization_report = normalization_service.run(
        start=AS_OF, end=AS_OF, streams=["heart_rate"]
    )

    envelope_error = envelope_report.attempts[0].error
    normalization_error = normalization_report.attempts[0].error
    assert envelope_error is not None
    assert normalization_error is not None
    assert envelope_error.error_code == "shape_drift_page_envelope"
    assert normalization_error.error_code == "shape_drift_normalization"
    assert envelope_error.http_status == 200
    assert normalization_error.http_status == 200
    assert envelope_report.to_json().count("shape_drift_page_envelope") == 1
    assert normalization_report.to_json().count("shape_drift_normalization") == 1


def test_source_family_and_query_mode_contexts_remain_separate(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", {"dataPoints": [_hr_point(name="hr-list", bpm="61")]})
    settings, service = _sync(tmp_path, transport)
    service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"], query_mode="list")
    transport.queue(
        "heart-rate",
        {
            "dataPoints": [
                {
                    "dataPointName": "hr-rec",
                    "heartRate": {
                        "sampleTime": _sample_time(hour=9),
                        "beatsPerMinute": "62",
                    },
                }
            ]
        },
        operation="reconcile",
    )
    service.run(
        start=AS_OF,
        end=AS_OF,
        streams=["heart_rate"],
        query_mode="reconcile",
        data_source_family=FAMILY_GOOGLE_WEARABLES,
    )
    engine, factory = _session(settings)
    try:
        with factory() as session:
            records = list(session.scalars(select(GoogleSourceRecord)))
            assert len(records) == 2
            modes = {row.query_mode for row in records}
            families = {row.data_source_family for row in records}
            assert modes == {"list", "reconcile"}
            assert None in families
            assert FAMILY_GOOGLE_WEARABLES in families
            codes = {row.stream_code for row in session.scalars(select(SyncStreamState))}
            assert any(":list:any" in code for code in codes)
            assert any(":reconcile:google-wearables" in code for code in codes)
    finally:
        engine.dispose()


def test_page_reorder_does_not_change_current_projection(tmp_path) -> None:
    page_a = {"dataPoints": [_hr_point(name="hr-a", bpm="50", hour=7)], "nextPageToken": "p2"}
    page_b = {"dataPoints": [_hr_point(name="hr-b", bpm="90", hour=9)]}
    transport_one = FakeGoogleHealthTransport()
    transport_one.queue("heart-rate", page_a)
    transport_one.queue("heart-rate", page_b, page_token="p2")
    settings_one, service_one = _sync(tmp_path / "one", transport_one)
    service_one.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    transport_two = FakeGoogleHealthTransport()
    reversed_b = {
        "dataPoints": [_hr_point(name="hr-b", bpm="90", hour=9)],
        "nextPageToken": "p2",
    }
    reversed_a = {"dataPoints": [_hr_point(name="hr-a", bpm="50", hour=7)]}
    transport_two.queue("heart-rate", reversed_b)
    transport_two.queue("heart-rate", reversed_a, page_token="p2")
    settings_two, service_two = _sync(tmp_path / "two", transport_two)
    service_two.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])

    def identities(settings: Settings) -> set[str]:
        engine, factory = _session(settings)
        try:
            with factory() as session:
                return {
                    f"{row.external_record_id}:{row.record_identity_key}"
                    for row in session.scalars(select(GoogleSourceRecord))
                }
        finally:
            engine.dispose()

    assert identities(settings_one) == identities(settings_two)


def test_partial_consent_disables_only_sleep(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", {"dataPoints": [_hr_point(name="hr-1", bpm="55")]})
    _settings, service = _sync(tmp_path, transport, scopes=frozenset({SCOPE_METRICS}))
    report = service.run(start=AS_OF, end=AS_OF, streams=["sleep", "heart_rate"])
    by_stream = {item.stream: item for item in report.attempts}
    assert by_stream["sleep"].status is GoogleSyncStatus.SCOPE_REQUIRED
    assert by_stream["heart_rate"].status is GoogleSyncStatus.SUCCEEDED
    assert all(item["data_type"] != "sleep" for item in transport.health_calls())


def test_reauth_stops_without_retry_storm(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", 401)
    transport.queue("sleep", {"dataPoints": [_sleep_point(name="sleep-1")]})
    _settings, service = _sync(tmp_path, transport)
    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate", "sleep"])
    assert report.status is GoogleSyncStatus.REAUTH_REQUIRED
    assert report.abort_reason == "reauth_required"
    assert len(transport.health_calls()) == 1
    assert report.attempts[1].status is GoogleSyncStatus.NOT_RUN


def test_unsupported_rollup_for_sleep_does_not_call_provider(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    _settings, service = _sync(tmp_path, transport)
    report = service.run(
        start=AS_OF,
        end=AS_OF,
        streams=["sleep"],
        query_mode="rollUp",
    )
    assert report.attempts[0].status is GoogleSyncStatus.UNAVAILABLE
    assert transport.health_calls() == []


def test_confirmed_empty_complete_page_without_token(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", {"dataPoints": []})
    _settings, service = _sync(tmp_path, transport)
    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert report.attempts[0].coverage_status == "confirmed_empty"
    assert report.attempts[0].status is GoogleSyncStatus.EMPTY


def test_missing_collection_without_token_is_terminal_empty_only_for_list_reconcile(
    tmp_path,
) -> None:
    for query_mode in (GoogleQueryMode.LIST, GoogleQueryMode.RECONCILE):
        transport = FakeGoogleHealthTransport()
        transport.queue("heart-rate", {})
        _settings, service = _sync(tmp_path / query_mode.value, transport)
        report = service.run(
            start=AS_OF,
            end=AS_OF,
            streams=["heart_rate"],
            query_mode=query_mode.value,
        )

        assert report.attempts[0].coverage_status == "confirmed_empty"
        assert report.attempts[0].status is GoogleSyncStatus.EMPTY
        assert parse_page_envelope({}, query_mode) == ([], None, "complete")

    assert parse_page_envelope({}, GoogleQueryMode.ROLL_UP) == ([], None, "invalid")
    assert parse_page_envelope({"dataPoints": None}, GoogleQueryMode.LIST) == (
        [],
        None,
        "invalid",
    )
    assert parse_page_envelope({"dataPoints": {}}, GoogleQueryMode.LIST) == (
        [],
        None,
        "invalid",
    )


def test_no_garmin_writes(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", {"dataPoints": [_hr_point(name="hr-1", bpm="40")]})
    settings, service = _sync(tmp_path, transport)
    service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    engine, factory = _session(settings)
    try:
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(GarminSource)) == 0
            assert session.scalar(select(func.count()).select_from(GarminSourceRecord)) == 0
            assert session.scalar(select(func.count()).select_from(GarminRawPayload)) == 0
            assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 1
    finally:
        engine.dispose()


def test_historical_backfill_chunks_and_skips_completed_coverage(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", {"dataPoints": [_hr_point(name="hr-1", bpm="41")]})
    settings, _service = _sync(tmp_path, transport)
    backfill = GoogleHistoricalBackfill(
        settings,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
    )
    first = backfill.run(
        start="2099-01-01",
        end="2099-01-02",
        streams=["heart_rate"],
        chunk_days=1,
    )
    assert first.status is GoogleSyncStatus.SUCCEEDED
    first_calls = len(transport.health_calls())
    assert first_calls == 2
    second = backfill.run(
        start="2099-01-01",
        end="2099-01-02",
        streams=["heart_rate"],
        chunk_days=1,
    )
    assert second.request_count == 0
    assert second.skipped_complete_count == 2
    plan = plan_google_historical_backfill(
        start="2099-01-01", end="2099-01-02", streams=["heart_rate"], chunk_days=1
    )
    assert plan.dry_run is True
    assert plan.request_count == 0


def test_cli_google_commands_and_trailing_window_rejection(tmp_path) -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["google-sync", "--start", AS_OF, "--end", AS_OF, "--stream", "sleep"])
    assert args.command == "google-sync"
    assert args.family is None
    code = cli.main(
        [
            "google-sync",
            "--data-dir",
            str(tmp_path / "runtime"),
            "--trailing-window-days",
            "7",
        ]
    )
    assert code == 2
    refresh_code = cli.main(
        [
            "google-refresh",
            "--data-dir",
            str(tmp_path / "runtime"),
        ]
    )
    assert refresh_code == 2


def test_report_privacy_surface_has_no_page_tokens_or_values(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue(
        "heart-rate",
        {"dataPoints": [_hr_point(name="secret-id", bpm="88")], "nextPageToken": "secret-token"},
    )
    transport.queue("heart-rate", {"dataPoints": []}, page_token="secret-token")
    _settings, service = _sync(tmp_path, transport)
    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    dumped = report.to_json()
    assert "secret-token" not in dumped
    assert "secret-id" not in dumped
    assert SYNTHETIC_ACCESS not in dumped
    assert "beatsPerMinute" not in dumped
    assert report.as_dict()["privacy"]["page_tokens_emitted"] is False
    assert report.as_dict()["privacy"]["raw_values_emitted"] is False


def test_run_google_incremental_sync_helper(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue("daily-resting-heart-rate", {"dataPoints": []})
    settings, _paths = _runtime(tmp_path)
    report = run_google_incremental_sync(
        settings,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        start=AS_OF,
        end=AS_OF,
        streams=["daily_resting_hr"],
    )
    assert report.attempts[0].coverage_status == "confirmed_empty"


def test_auth_service_constructor_still_accepts_seeded_tokens(tmp_path) -> None:
    settings, paths = _runtime(tmp_path)
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", {"dataPoints": []})
    protector = GoogleLocalKeyFileProtection(
        paths.root / "google" / "auth" / ".google_protection_key"
    )
    service = GoogleAuthService(
        settings,
        transport=transport,
        protector=protector,
        client_credentials=GoogleClientCredentials(
            client_id="synthetic-client-id.apps.googleusercontent.com",
            client_secret=SYNTHETIC_SECRET,
        ),
    )
    service._write_tokens(
        GoogleTokenSet(
            access_token=SYNTHETIC_ACCESS,
            refresh_token=SYNTHETIC_REFRESH,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(DEFAULT_SCOPE_ORDER),
        )
    )
    report = GoogleHealthSync(
        settings,
        auth_service=service,
        transport=transport,
        run_kind=GoogleRunKind.INCREMENTAL,
    ).run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert report.auth is not None
    assert report.attempts[0].coverage_status == "confirmed_empty"


class RecoveryTransport(FakeGoogleHealthTransport):
    """Fake OAuth plus data; record bearer versions, never credential values."""

    def __init__(self, oauth_responses=()) -> None:
        super().__init__()
        self.oauth_responses = list(oauth_responses)
        self.oauth_calls = 0
        self.bearer_versions: list[int] = []

    def request(self, method, url, **kwargs):
        from healthcheck.google.auth import GOOGLE_TOKEN_ENDPOINT

        if url == GOOGLE_TOKEN_ENDPOINT:
            assert method == "POST" and kwargs["form"]["grant_type"] == "refresh_token"
            self.oauth_calls += 1
            if self.oauth_responses:
                result = self.oauth_responses.pop(0)
                if isinstance(result, Exception):
                    raise result
                return result
            return GoogleHttpResponse(200, json.dumps({
                "access_token": f"{SYNTHETIC_ACCESS}-{self.oauth_calls}",
                "token_type": "Bearer",
                # Deliberately omitted scope must retain the existing grant.
            }).encode())
        bearer = kwargs["headers"]["Authorization"]
        version = next((i for i in range(1, 4) if bearer == f"Bearer {SYNTHETIC_ACCESS}-{i}"), 0)
        self.bearer_versions.append(version)
        return super().request(method, url, **kwargs)


def _recovery_sync(tmp_path, transport, *, scopes=ALLOWED_SCOPES, **kwargs):
    settings, paths = _runtime(tmp_path)
    auth = GoogleAuthService(
        settings, transport=transport,
        protector=GoogleLocalKeyFileProtection(paths.root / "google/auth/.google_protection_key"),
        client_credentials=GoogleClientCredentials("synthetic-client", SYNTHETIC_SECRET),
    )
    auth._write_tokens(GoogleTokenSet(
        SYNTHETIC_ACCESS, SYNTHETIC_REFRESH, "Bearer", 3600, " ".join(sorted(scopes))
    ))
    sync = GoogleHealthSync(settings, auth_service=auth, sleeper=lambda _seconds: None, **kwargs)
    return settings, sync, auth


def test_cached_access_can_succeed_without_claiming_refresh(tmp_path) -> None:
    transport = RecoveryTransport([GoogleHttpResponse(503, b'{"error":"canary-oauth-secret"}')])
    transport.queue("heart-rate", {"dataPoints": []})
    _settings, sync, _auth = _recovery_sync(tmp_path, transport)
    report = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert report.status is GoogleSyncStatus.SUCCEEDED
    assert report.auth.token_health is GoogleTokenHealth.CACHED_UNVERIFIED
    assert not report.auth.refresh_succeeded
    assert report.auth.error == GoogleSafeError("authentication", "token_exchange_failed", 503)
    assert transport.oauth_calls == 1 and transport.bearer_versions == [0]
    assert report.auth_recovery["startup_refresh_attempts"] == 1
    assert report.auth_recovery["recovery_refresh_attempts"] == 0


def test_scope_storage_failure_preserves_first_startup_refresh_error(tmp_path, monkeypatch):
    transport = RecoveryTransport([GoogleHttpResponse(503, b'{"error":"oauth-canary"}')])
    _settings, sync, auth = _recovery_sync(tmp_path, transport)
    original = auth._read_tokens
    reads = 0

    def read():
        nonlocal reads
        reads += 1
        if reads == 3:
            raise PermissionError("storage-canary")
        return original()

    monkeypatch.setattr(auth, "_read_tokens", read)
    report = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate", "sleep"])
    assert report.status is GoogleSyncStatus.FAILED and report.request_count == 0
    assert transport.oauth_calls == 1
    assert report.auth.error.error_code == "storage_permission"
    assert report.auth_recovery["startup_error"]["error_code"] == "token_exchange_failed"
    assert report.auth_recovery["startup_error"]["http_status"] == 503
    assert "storage-canary" not in report.to_json() + repr(report)


@pytest.mark.parametrize("io_error", [errno.ENOSPC, errno.EIO])
@pytest.mark.parametrize("phase", ["startup", "recovery"])
@pytest.mark.parametrize("boundary", ["tokens", "atomic_write"])
def test_token_store_io_failure_stops_without_cached_fallback_or_replay(
    tmp_path, monkeypatch, caplog, io_error, phase, boundary
):
    import healthcheck.google.auth as google_auth

    transport = RecoveryTransport()
    settings, sync, auth = _recovery_sync(tmp_path, transport)
    if phase == "recovery":
        transport.queue("heart-rate", 401)
    transport.queue("heart-rate", {"dataPoints": []})
    writes = 0
    original = auth._write_tokens if boundary == "tokens" else google_auth._atomic_write_text

    def failing_write(*args, **kwargs):
        nonlocal writes
        writes += 1
        if phase == "startup" or writes == 2:
            raise OSError(io_error, "synthetic-storage-canary", "secret-path-canary")
        return original(*args, **kwargs)

    if boundary == "tokens":
        monkeypatch.setattr(auth, "_write_tokens", failing_write)
    else:
        monkeypatch.setattr(google_auth, "_atomic_write_text", failing_write)
    report = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate", "sleep"])
    assert report.status is GoogleSyncStatus.FAILED
    assert report.auth.status is GoogleAuthStatus.FAILED
    assert report.auth.error == GoogleSafeError("storage", "storage_write_failed")
    assert report.auth.refresh_attempted and not report.auth.refresh_succeeded
    expected_requests = 0 if phase == "startup" else 1
    assert report.request_count == expected_requests
    assert len(transport.health_calls()) == expected_requests
    assert transport.oauth_calls == (1 if phase == "startup" else 2)
    assert report.auth_recovery["startup_refresh_attempts"] == 1
    if phase == "startup":
        assert report.auth_recovery["startup_error"] == report.auth.error.as_dict()
        assert report.auth_recovery["recovery_refresh_attempts"] == 0
    else:
        assert report.auth_recovery["recovery_error"] == report.auth.error.as_dict()
        assert report.auth_recovery["first_data_error"]["http_status"] == 401
        assert report.auth_recovery["recovery_refresh_attempts"] == 1
        assert report.attempts[0].page_count == 0
        assert report.attempts[1].status is GoogleSyncStatus.NOT_RUN
    persisted_token = auth._read_tokens().access_token
    assert persisted_token == SYNTHETIC_ACCESS + ("" if phase == "startup" else "-1")
    public = report.to_json() + repr(report) + caplog.text
    assert all(canary not in public for canary in (
        "synthetic-storage-canary", "secret-path-canary", SYNTHETIC_ACCESS, SYNTHETIC_REFRESH
    ))
    engine, factory = _session(settings)
    try:
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(GoogleRawPayload)) == 0
            assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("io_error", [errno.ENOSPC, errno.EIO])
def test_oauth_transport_oserror_remains_provider_failure_with_truthful_cached_fallback(
    tmp_path, io_error
):
    transport = RecoveryTransport([OSError(io_error, "provider-secret-canary")])
    _settings, sync, _auth = _recovery_sync(tmp_path, transport)
    transport.queue("heart-rate", {"dataPoints": []})
    report = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert report.status is GoogleSyncStatus.SUCCEEDED and report.request_count == 1
    assert report.auth.error == GoogleSafeError("provider", "provider_error")
    assert report.auth.token_health is GoogleTokenHealth.CACHED_UNVERIFIED
    assert not report.auth.refresh_succeeded and transport.oauth_calls == 1
    assert "provider-secret-canary" not in report.to_json() + repr(report)


@pytest.mark.parametrize("mode,family", [("list", None), ("reconcile", FAMILY_GOOGLE_WEARABLES)])
def test_get401_verified_refresh_replays_exact_page_and_carries_bearer(tmp_path, mode, family):
    transport = RecoveryTransport([GoogleHttpResponse(503, b'{"error":"startup-canary"}')])
    transport.queue("heart-rate", {"nextPageToken": "cursor-canary"}, operation=mode)
    transport.queue("heart-rate", 401, page_token="cursor-canary", operation=mode)
    point = _hr_point(name="hr-recovered", bpm="71")
    if mode == "reconcile":
        point.pop("dataSource")
        point["dataPointName"] = point.pop("name")
    transport.queue("heart-rate", {"dataPoints": [point]},
                    page_token="cursor-canary", operation=mode)
    transport.queue("daily-resting-heart-rate", {"dataPoints": []}, operation=mode)
    settings, sync, _auth = _recovery_sync(tmp_path, transport)
    report = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate", "daily_resting_hr"],
                      query_mode=mode, data_source_family=family)
    assert report.status is GoogleSyncStatus.SUCCEEDED
    assert report.request_count == 4 and transport.oauth_calls == 2
    assert report.attempts[0].page_count == 2 and report.attempts[0].request_count == 3
    assert transport.bearer_versions == [0, 0, 2, 2]
    calls = transport.health_calls()
    assert calls[1] == calls[2] and calls[1]["method"] == "GET"
    assert report.auth.refresh_succeeded and report.auth.access_verified
    assert report.auth_recovery["startup_error"]["error_code"] == "token_exchange_failed"
    assert report.auth_recovery["first_data_error"]["http_status"] == 401
    assert report.auth_recovery["recovery_refresh_attempts"] == 1
    assert all(word not in report.to_json() + repr(report) for word in
               ("startup-canary", "cursor-canary", SYNTHETIC_ACCESS, SYNTHETIC_REFRESH))
    engine, factory = _session(settings)
    try:
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 1
            assert all(
                b"startup-canary" not in body for body in _artifact_bodies(settings, session)
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("later_page", [False, True])
def test_repeated401_aborts_run_with_later_streams_not_run(tmp_path, later_page) -> None:
    transport = RecoveryTransport()
    transport.queue("heart-rate", 401)
    if later_page:
        transport.queue("heart-rate", {"nextPageToken": "later-canary"})
        transport.queue("heart-rate", 401, page_token="later-canary")
    else:
        transport.queue("heart-rate", 401)
    _settings, sync, _auth = _recovery_sync(tmp_path, transport)
    report = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate", "sleep"])
    assert report.status is GoogleSyncStatus.REAUTH_REQUIRED
    assert report.abort_reason == "reauth_required" and transport.oauth_calls == 2
    assert report.request_count == (3 if later_page else 2)
    assert report.attempts[1].status is GoogleSyncStatus.NOT_RUN
    assert report.auth_recovery["recovery_refresh_attempts"] == 1


@pytest.mark.parametrize("response,code,status", [
    (GoogleHttpResponse(400, b'{"error":"invalid_grant","detail":"oauth-canary"}'),
     "invalid_grant", GoogleSyncStatus.REAUTH_REQUIRED),
    (GoogleHttpResponse(503, b'{"error":"oauth-canary"}'),
     "token_exchange_failed", GoogleSyncStatus.FAILED),
    (GoogleHttpResponse(200, b'{"access_token":null,"secret":"oauth-canary"}'),
     "token_response_invalid", GoogleSyncStatus.FAILED),
    (GoogleHttpResponse(200, b'oauth-canary'), "token_response_invalid", GoogleSyncStatus.FAILED),
    (GoogleHttpResponse(200, b'{"access_token":"oauth-canary\\r\\nheader"}'),
     "token_response_invalid", GoogleSyncStatus.FAILED),
    (GoogleHttpResponse(200, b'{"access_token":"oauth-canary","token_type":"wrong"}'),
     "token_response_invalid", GoogleSyncStatus.FAILED),
    (GoogleHttpResponse(302, b'{"access_token":"oauth-canary"}'),
     "token_exchange_failed", GoogleSyncStatus.FAILED),
    (TimeoutError("oauth-canary https://token.invalid/?secret=oauth-canary"),
     "provider_unavailable", GoogleSyncStatus.FAILED),
])
def test_recovery_failure_no_fallback_ingestion_or_later_streams(
    tmp_path, caplog, response, code, status
) -> None:
    transport = RecoveryTransport()
    settings, sync, _auth = _recovery_sync(tmp_path, transport)
    # First startup succeeds; only the explicit recovery receives this response.
    original_request = transport.request

    def request(method, url, **kwargs):
        if transport.oauth_calls == 1 and url.endswith("/token"):
            transport.oauth_responses.append(response)
        return original_request(method, url, **kwargs)

    transport.request = request
    transport.queue_raw("heart-rate", b'{"error":"data-auth-canary"}', status=401)
    report = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate", "sleep"])
    assert report.status is status and report.request_count == 1 and transport.oauth_calls == 2
    assert report.attempts[0].error.error_code == code
    assert report.attempts[0].page_count == 0
    assert report.attempts[1].status is GoogleSyncStatus.NOT_RUN
    assert report.auth_recovery["first_data_error"]["http_status"] == 401
    assert report.auth_recovery["recovery_error"]["error_code"] == code
    text = report.to_json() + repr(report) + caplog.text
    assert "oauth-canary" not in text and "data-auth-canary" not in text
    engine, factory = _session(settings)
    try:
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(GoogleRawPayload)) == 0
            assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 0
            state = session.scalar(select(SyncStreamState))
            assert state.watermark is None
            assert json.loads(state.cursor)["page_token"] is None
    finally:
        engine.dispose()


@pytest.mark.parametrize("mode,status", [("list", 403), ("rollUp", 401),
                                       ("dailyRollUp", 401), ("list", 400)])
def test_no_recovery_for403_post_or_non_auth_errors(tmp_path, mode, status) -> None:
    transport = RecoveryTransport()
    transport.queue("heart-rate", status, operation=mode)
    _settings, sync, _auth = _recovery_sync(tmp_path, transport)
    report = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate"], query_mode=mode)
    assert report.request_count == 1 and transport.oauth_calls == 1
    assert report.auth_recovery["recovery_refresh_attempts"] == 0


@pytest.mark.parametrize("prior_statuses,budget,refreshes", [
    ([], 1, 1), ([503], 2, 1), ([503], 3, 2), ([503, 503], 10, 1)
])
def test_recovery_shares_request_and_transient_attempt_budgets(
    tmp_path, prior_statuses, budget, refreshes
) -> None:
    transport = RecoveryTransport()
    sleeps = []
    for status in prior_statuses:
        transport.queue("heart-rate", status)
    transport.queue("heart-rate", 401)
    transport.queue("heart-rate", {"dataPoints": []})
    _settings, sync, _auth = _recovery_sync(tmp_path, transport, max_provider_requests=budget)
    sync.sleeper = sleeps.append
    report = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate", "sleep"])
    assert transport.oauth_calls == refreshes
    assert report.request_count <= budget
    assert report.attempts[0].request_count == len(prior_statuses) + (2 if refreshes == 2 else 1)
    assert sleeps == list(RETRY_BACKOFF_SECONDS[:len(prior_statuses)])
    assert report.attempts[0].page_count == (1 if refreshes == 2 else 0)


def test_recovery_failure_storage_and_unverified_loader_are_terminal(tmp_path, monkeypatch):
    transport = RecoveryTransport()
    _settings, sync, auth = _recovery_sync(tmp_path, transport)
    transport.queue("heart-rate", 401)
    original = auth.load_access_token

    def load(**kwargs):
        if not kwargs.get("allow_cached_fallback", True):
            # Deliberately auth.ok cached token: never proof of refresh success.
            return SYNTHETIC_ACCESS, _auth_result()
        return original(**kwargs)

    monkeypatch.setattr(auth, "load_access_token", load)
    report = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate", "sleep"])
    assert report.status is GoogleSyncStatus.FAILED and report.request_count == 1
    assert report.attempts[0].error.error_code == "refresh_unverified"
    assert report.attempts[1].status is GoogleSyncStatus.NOT_RUN


def test_recovery_preserves_partial_scopes_and_limits_next_stream(tmp_path):
    transport = RecoveryTransport()
    transport.queue("heart-rate", 401)
    transport.queue("heart-rate", {"dataPoints": []})
    _settings, sync, _auth = _recovery_sync(tmp_path, transport, scopes=frozenset({SCOPE_METRICS}))
    report = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate", "sleep"])
    assert report.auth.missing_scope_count == 1 and report.auth.refresh_succeeded
    assert report.attempts[1].status is GoogleSyncStatus.SCOPE_REQUIRED
    assert report.request_count == 2 and transport.oauth_calls == 2


def test_historical_chunks_share_auth_recovery_allowance(tmp_path):
    transport = RecoveryTransport()
    transport.queue("heart-rate", 401)
    transport.queue("heart-rate", {"dataPoints": []})
    transport.queue("heart-rate", 401)
    settings, _sync_service, auth = _recovery_sync(tmp_path, transport)
    report = GoogleHistoricalBackfill(settings, auth_service=auth, transport=transport).run(
        start="2099-01-01", end="2099-01-03", streams=["heart_rate"], chunk_days=1
    )
    assert report.status is GoogleSyncStatus.REAUTH_REQUIRED and report.request_count == 3
    assert transport.oauth_calls == 2 and transport.bearer_versions == [1, 2, 2]
    assert report.attempts[2].status is GoogleSyncStatus.NOT_RUN
    assert report.auth_recovery["startup_refresh_attempts"] == 1
    assert report.auth_recovery["recovery_refresh_attempts"] == 1


@pytest.mark.parametrize("failure", ["storage", "missing_refresh", "scope_lost"])
def test_protected_recovery_failure_stops_without_replay(tmp_path, monkeypatch, failure):
    transport = RecoveryTransport()
    _settings, sync, auth = _recovery_sync(tmp_path, transport)
    original = auth.load_access_token

    def load(**kwargs):
        if not kwargs.get("allow_cached_fallback", True):
            if failure == "storage":
                def fail_write(_tokens):
                    raise PermissionError("protected-secret-canary")
                monkeypatch.setattr(auth, "_write_tokens", fail_write)
            elif failure == "missing_refresh":
                tokens = auth._read_tokens()
                tokens.refresh_token = None
                auth._write_tokens(tokens)
            else:
                transport.oauth_responses.append(GoogleHttpResponse(200, json.dumps({
                    "access_token": SYNTHETIC_ACCESS + "-2", "scope": DEFAULT_SCOPE_ORDER[0]
                }).encode()))
        return original(**kwargs)

    monkeypatch.setattr(auth, "load_access_token", load)
    transport.queue("heart-rate", 401)
    report = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate", "sleep"])
    assert report.request_count == 1 and report.status is GoogleSyncStatus.FAILED
    assert report.attempts[1].status is GoogleSyncStatus.NOT_RUN
    expected = {"storage": "storage_permission", "missing_refresh": "refresh_token_missing",
                "scope_lost": "scope_required"}
    assert report.attempts[0].error.error_code == expected[failure]
    assert "protected-secret-canary" not in report.to_json() + repr(report)


def test_resumed_get401_keeps_cursor_identity_and_exact_rerun_is_idempotent(tmp_path):
    transport = RecoveryTransport()
    transport.queue("heart-rate", {
        "dataPoints": [_hr_point(name="resume-a", bpm="61")], "nextPageToken": "resume-canary"
    })
    settings, sync, _auth = _recovery_sync(tmp_path, transport, max_provider_requests=1)
    first = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert first.status is GoogleSyncStatus.PARTIAL and first.attempts[0].page_count == 1
    transport.queue("heart-rate", 401, page_token="resume-canary")
    transport.queue("heart-rate", {"dataPoints": [_hr_point(name="resume-b", bpm="62")]},
                    page_token="resume-canary")
    sync.max_provider_requests = 3
    second = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert second.status is GoogleSyncStatus.SUCCEEDED and second.request_count == 2
    calls = transport.health_calls()
    assert calls[1] == calls[2] and calls[1]["has_page_token"]
    assert second.attempts[0].page_count == 1 and second.attempts[0].record_count == 1
    third = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert third.status is GoogleSyncStatus.SUCCEEDED and third.request_count == 0
    assert len(transport.health_calls()) == 3
    assert "resume-canary" not in first.to_json() + second.to_json()
    engine, factory = _session(settings)
    try:
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 2
            assert session.scalar(select(func.count()).select_from(GooglePayloadObservation)) == 2
            state = session.scalar(select(SyncStreamState))
            assert state.cursor is None and state.watermark is not None
    finally:
        engine.dispose()


def test_failed401_refresh_preserves_accepted_projection_then_success_converges(tmp_path):
    transport = RecoveryTransport()
    settings, sync, _auth = _recovery_sync(tmp_path, transport, run_kind=GoogleRunKind.REFRESH)
    accepted = {"dataPoints": [_hr_point(name="accepted", bpm="61")]}
    transport.queue("heart-rate", accepted)
    first = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    engine, factory = _session(settings)
    try:
        with factory() as session:
            state = session.scalar(select(SyncStreamState))
            accepted_state = state.watermark, state.last_success_at
            record = session.scalar(select(GoogleSourceRecord))
            accepted_id = record.id, record.record_identity_key
    finally:
        engine.dispose()
    transport.queue("heart-rate", 401)
    transport.queue("heart-rate", 401)
    failed = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert failed.status is GoogleSyncStatus.REAUTH_REQUIRED
    engine, factory = _session(settings)
    try:
        with factory() as session:
            state = session.scalar(select(SyncStreamState))
            assert (state.watermark, state.last_success_at) == accepted_state
            record = session.scalar(select(GoogleSourceRecord))
            assert (record.id, record.record_identity_key) == accepted_id
            assert session.scalar(select(func.count()).select_from(GoogleRawPayload)) == 1
    finally:
        engine.dispose()
    for _ in range(2):
        transport.queue("heart-rate", 401)
        transport.queue("heart-rate", accepted)
        report = sync.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
        assert report.status is GoogleSyncStatus.SUCCEEDED and report.request_count == 2
    assert first.status is GoogleSyncStatus.SUCCEEDED
    assert failed.status is GoogleSyncStatus.REAUTH_REQUIRED
    engine, factory = _session(settings)
    try:
        with factory() as session:
            record = session.scalar(select(GoogleSourceRecord))
            assert (record.id, record.record_identity_key) == accepted_id
            assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 1
    finally:
        engine.dispose()


def test_hr_continuation_keeps_one_startup_and_one_recovery(tmp_path, monkeypatch):
    import healthcheck.google.sync as google_sync

    monkeypatch.setattr(google_sync, "MAX_PAGES_PER_FETCH", 1)
    transport = RecoveryTransport()
    settings, _sync_service, auth = _recovery_sync(tmp_path, transport)
    transport.queue("heart-rate", 401)
    transport.queue("heart-rate", {"nextPageToken": "continuation-canary"})
    # A resumed REFRESH revalidates its head before following the saved cursor.
    transport.queue("heart-rate", 401)
    with _owner_heart_rate_day_refresh(
        settings, day=date(2099, 1, 2), auth_service=auth,
        query_mode=None, data_source_family=None, phase_timing=None,
    ) as refresh:
        first = refresh()
        second = refresh()
        third = refresh()
    assert first.status is GoogleSyncStatus.PARTIAL and first.request_count == 2
    assert second.status is GoogleSyncStatus.REAUTH_REQUIRED and second.request_count == 1
    assert third.status is GoogleSyncStatus.REAUTH_REQUIRED and third.request_count == 0
    assert transport.oauth_calls == 2 and transport.bearer_versions == [1, 2, 2]
    assert second.auth_recovery["startup_refresh_attempts"] == 1
    assert second.auth_recovery["recovery_refresh_attempts"] == 1
    assert "continuation-canary" not in second.to_json()


def test_normal_refresh_consumer_stops_hr_days_after_recovery_failure(tmp_path):
    from healthcheck.owner_refresh import _run_normal_google_refresh

    transport = RecoveryTransport()
    settings, _sync_service, auth = _recovery_sync(tmp_path, transport)
    original = transport.request

    def request(method, url, **kwargs):
        if transport.oauth_calls == 1 and url.endswith("/token"):
            transport.oauth_responses.append(GoogleHttpResponse(503, b'{"error":"oauth-canary"}'))
        return original(method, url, **kwargs)

    transport.request = request
    transport.queue("sleep", 401)
    report = _run_normal_google_refresh(
        settings, auth_service=auth, start="2099-01-01", end=AS_OF,
        streams=["sleep", "heart_rate"], query_mode=None, data_source_family=None,
    )
    assert report.status is GoogleSyncStatus.FAILED and report.request_count == 1
    assert report.abort_reason == "auth_recovery_failed"
    assert transport.oauth_calls == 2
    assert [item.status for item in report.attempts if item.stream == "heart_rate"] == [
        GoogleSyncStatus.NOT_RUN, GoogleSyncStatus.NOT_RUN
    ]
    assert report.auth_recovery["startup_refresh_attempts"] == 1
    assert "oauth-canary" not in report.to_json()


def test_normal_refresh_days_share_recovery_without_rewriting_earlier_success(tmp_path):
    from healthcheck.owner_refresh import _run_normal_google_refresh

    transport = RecoveryTransport()
    settings, _sync_service, auth = _recovery_sync(tmp_path, transport)
    transport.queue("heart-rate", 401)
    transport.queue("heart-rate", {"dataPoints": []})
    transport.queue("heart-rate", 401)
    report = _run_normal_google_refresh(
        settings, auth_service=auth, start="2099-01-01", end="2099-01-03",
        streams=["heart_rate"], query_mode=None, data_source_family=None,
    )
    assert report.status is GoogleSyncStatus.REAUTH_REQUIRED and report.request_count == 3
    assert transport.oauth_calls == 2 and transport.bearer_versions == [1, 2, 2]
    assert [attempt.status for attempt in report.attempts] == [
        GoogleSyncStatus.EMPTY, GoogleSyncStatus.REAUTH_REQUIRED, GoogleSyncStatus.NOT_RUN
    ]
    assert report.auth_recovery["startup_refresh_attempts"] == 1
    assert report.auth_recovery["recovery_refresh_attempts"] == 1


SOURCE_A = "users/me/dataSources/raw:com.google.heart_rate.bpm:fitbit:AAA"
SOURCE_B = "users/me/dataSources/raw:com.google.heart_rate.bpm:pixel:BBB"


def _artifact_bodies(settings: Settings, session) -> list[bytes]:
    paths = prepare_runtime(settings)
    bodies: list[bytes] = []
    for row in session.scalars(select(GoogleRawPayload)):
        artifact = session.get(RawArtifact, row.raw_artifact_id)
        assert artifact is not None
        bodies.append((paths.root / "artifacts" / artifact.relative_storage_path).read_bytes())
    return bodies


def test_two_explicit_datasources_same_type_remain_distinct(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue(
        "heart-rate",
        {
            "dataPoints": [
                _hr_point(
                    name="hr-a",
                    bpm="61",
                    hour=7,
                    data_source=_named_data_source(SOURCE_A),
                ),
                _hr_point(
                    name="hr-b",
                    bpm="62",
                    hour=8,
                    data_source=_named_data_source(SOURCE_B, platform="FITBIT"),
                ),
            ]
        },
    )
    settings, service = _sync(tmp_path, transport)
    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert report.status is GoogleSyncStatus.SUCCEEDED
    engine, factory = _session(settings)
    try:
        with factory() as session:
            sources = list(session.scalars(select(GoogleSource)))
            instances = {row.source_instance_id for row in sources}
            assert instances == {SOURCE_A, SOURCE_B}
            assert all(row.source_kind == "data_source" for row in sources)
            assert "users/me/dataTypes/heart-rate" not in instances
            assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 2
    finally:
        engine.dispose()


def test_same_explicit_source_across_acquisition_contexts_is_one_logical_source(
    tmp_path,
) -> None:
    transport = FakeGoogleHealthTransport()
    point = _hr_point(
        name="hr-shared",
        bpm="70",
        data_source=_named_data_source(SOURCE_A),
    )
    transport.queue("heart-rate", {"dataPoints": [point]})
    settings, service = _sync(tmp_path, transport)
    first = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert first.status is GoogleSyncStatus.SUCCEEDED
    transport.queue("heart-rate", {"dataPoints": [point]})
    second = service.run(
        start=AS_OF,
        end=AS_OF,
        streams=["heart_rate"],
        data_source_family=FAMILY_GOOGLE_WEARABLES,
    )
    assert second.status is GoogleSyncStatus.SUCCEEDED
    engine, factory = _session(settings)
    try:
        with factory() as session:
            sources = list(session.scalars(select(GoogleSource)))
            assert [row.source_instance_id for row in sources] == [SOURCE_A]
            records = list(session.scalars(select(GoogleSourceRecord)))
            assert len(records) == 2
            families = {row.data_source_family for row in records}
            assert None in families
            assert FAMILY_GOOGLE_WEARABLES in families
    finally:
        engine.dispose()


def test_budget_stopped_refresh_restarts_and_applies_page1_correction(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    original = _hr_point(name="hr-1", bpm="72", data_source=_named_data_source(SOURCE_A))
    corrected = _hr_point(name="hr-1", bpm="81", data_source=_named_data_source(SOURCE_A))
    transport.queue("heart-rate", {"dataPoints": [original]})
    settings, incremental = _sync(tmp_path, transport)
    incremental.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    page1 = {"dataPoints": [corrected], "nextPageToken": "p2"}
    page2 = {"dataPoints": []}
    transport.queue("heart-rate", page1)
    first = run_google_refresh(
        settings,
        start=AS_OF,
        end=AS_OF,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
        max_provider_requests=1,
    )
    assert first.status is GoogleSyncStatus.PARTIAL
    assert first.attempts[0].resume_cursor_present is True
    assert "p2" not in first.to_json()
    engine, factory = _session(settings)
    try:
        with factory() as session:
            metric = session.scalar(
                select(GoogleRecordMetric).where(GoogleRecordMetric.metric_code == "heart_rate_bpm")
            )
            assert metric is not None
            assert metric.value_number == 72
            raw_before = session.scalar(select(func.count()).select_from(GoogleRawPayload))
    finally:
        engine.dispose()
    transport.queue("heart-rate", page1)
    transport.queue("heart-rate", page2, page_token="p2")
    second = run_google_refresh(
        settings,
        start=AS_OF,
        end=AS_OF,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
    )
    assert second.status is GoogleSyncStatus.SUCCEEDED
    engine, factory = _session(settings)
    try:
        with factory() as session:
            metric = session.scalar(
                select(GoogleRecordMetric).where(GoogleRecordMetric.metric_code == "heart_rate_bpm")
            )
            assert metric is not None
            assert metric.value_number == 81
            assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 1
            raw_after = session.scalar(select(func.count()).select_from(GoogleRawPayload))
            assert raw_after >= raw_before
    finally:
        engine.dispose()


def test_owner_hr_day_context_reuses_setup_and_matches_standalone_continuation(
    monkeypatch, tmp_path
) -> None:
    import healthcheck.google.sync as google_sync

    def transport_with_correction() -> FakeGoogleHealthTransport:
        transport = FakeGoogleHealthTransport()
        for index in range(MAX_PAGES_PER_FETCH + 2):
            token = None if index == 0 else f"page-{index}"
            next_token = (
                f"page-{index + 1}" if index < MAX_PAGES_PER_FETCH + 1 else None
            )
            point = _hr_point(name=f"point-{index}", bpm="61")
            payload: dict[str, Any] = {"dataPoints": [point]}
            if next_token is not None:
                payload["nextPageToken"] = next_token
            transport.queue("heart-rate", payload, page_token=token)
            if index == 0:
                corrected = dict(payload)
                corrected["dataPoints"] = [_hr_point(name="point-0", bpm="81")]
                transport.queue("heart-rate", corrected, page_token=token)
        return transport

    def database_state(settings: Settings) -> tuple[dict[str, Any], int | None, int]:
        database = prepare_runtime(settings).database
        with sqlite3.connect(database) as connection:
            cursor = connection.execute(
                "SELECT cursor FROM sync_stream_state WHERE stream_code = ?",
                ("google:refresh:heart_rate:list:any:day:2099-01-02",),
            ).fetchone()
            metric = connection.execute(
                "SELECT value_number FROM google_record_metrics "
                "WHERE metric_code = 'heart_rate_bpm' ORDER BY value_number DESC LIMIT 1"
            ).fetchone()
            count = connection.execute("SELECT COUNT(*) FROM google_source_records").fetchone()
        assert cursor is not None and count is not None
        return json.loads(cursor[0] or "{}"), metric[0] if metric else None, count[0]

    standalone_transport = transport_with_correction()
    standalone_settings, _ = _sync(tmp_path / "standalone", standalone_transport)
    standalone_args = dict(
        start=AS_OF,
        end=AS_OF,
        transport=standalone_transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
        checkpoint_partition=AS_OF,
    )
    standalone_first = run_google_refresh(standalone_settings, **standalone_args)
    standalone_partial = database_state(standalone_settings)
    standalone_second = run_google_refresh(standalone_settings, **standalone_args)
    standalone_final = database_state(standalone_settings)

    shared_transport = transport_with_correction()
    shared_settings, _ = _sync(tmp_path / "shared", shared_transport)
    auth = SimpleNamespace(
        transport=shared_transport,
        token_health=lambda: _auth_result(),
        load_access_token=lambda **_kwargs: (SYNTHETIC_ACCESS, _auth_result()),
        _read_tokens=lambda: SimpleNamespace(granted_scopes=lambda: ALLOWED_SCOPES),
    )
    counts = {name: 0 for name in ("prepare", "migrate", "engine", "factory", "store", "dispose")}
    for name, key in (
        ("prepare_runtime", "prepare"),
        ("migrate_database", "migrate"),
        ("create_session_factory", "factory"),
    ):
        original = getattr(google_sync, name)

        def counted(*args, _original=original, _key=key, **kwargs):
            counts[_key] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(google_sync, name, counted)
    original_engine = google_sync.create_sqlite_engine

    def counted_engine(*args, **kwargs):
        counts["engine"] += 1
        engine = original_engine(*args, **kwargs)
        original_dispose = engine.dispose

        def dispose():
            counts["dispose"] += 1
            return original_dispose()

        engine.dispose = dispose
        return engine

    monkeypatch.setattr(google_sync, "create_sqlite_engine", counted_engine)
    original_store = google_sync.ContentAddressedGooglePayloadStore

    def counted_store(*args, **kwargs):
        counts["store"] += 1
        return original_store(*args, **kwargs)

    monkeypatch.setattr(google_sync, "ContentAddressedGooglePayloadStore", counted_store)
    with _owner_heart_rate_day_refresh(
        shared_settings,
        day=date(2099, 1, 2),
        auth_service=auth,
        query_mode=None,
        data_source_family=None,
        phase_timing=None,
    ) as refresh:
        shared_first = refresh()
        shared_partial = database_state(shared_settings)
        shared_second = refresh()
    shared_final = database_state(shared_settings)

    assert counts == dict.fromkeys(counts, 1)
    assert [standalone_first.status, standalone_second.status] == [
        shared_first.status,
        shared_second.status,
    ] == [GoogleSyncStatus.PARTIAL, GoogleSyncStatus.SUCCEEDED]
    assert [standalone_first.request_count, standalone_second.request_count] == [
        shared_first.request_count,
        shared_second.request_count,
    ] == [MAX_PAGES_PER_FETCH, 3]
    assert [
        attempt.page_count for attempt in (shared_first.attempts[0], shared_second.attempts[0])
    ] == [
        MAX_PAGES_PER_FETCH,
        3,
    ]
    assert standalone_first.sync_run_id != standalone_second.sync_run_id
    assert shared_first.sync_run_id != shared_second.sync_run_id
    assert standalone_partial[0]["page_token"] == shared_partial[0]["page_token"] == "page-40"
    assert (
        len(standalone_partial[0]["staged_run_ids"])
        == len(shared_partial[0]["staged_run_ids"])
        == 1
    )
    assert standalone_first.sync_run_id in standalone_partial[0]["staged_run_ids"]
    assert shared_first.sync_run_id in shared_partial[0]["staged_run_ids"]
    assert standalone_partial[1:] == shared_partial[1:] == (None, 0)
    assert standalone_final[1:] == shared_final[1:] == (81, MAX_PAGES_PER_FETCH + 2)
    assert standalone_final[0] == shared_final[0]
    assert [call["has_page_token"] for call in standalone_transport.health_calls()] == [
        call["has_page_token"] for call in shared_transport.health_calls()
    ]


def test_owner_hr_day_context_one_call_matches_standalone_empty_day(tmp_path) -> None:
    standalone_transport = FakeGoogleHealthTransport()
    standalone_settings, _ = _sync(tmp_path / "standalone", standalone_transport)
    standalone = run_google_refresh(
        standalone_settings,
        start=AS_OF,
        end=AS_OF,
        transport=standalone_transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
        checkpoint_partition=AS_OF,
    )
    shared_transport = FakeGoogleHealthTransport()
    shared_settings, _ = _sync(tmp_path / "shared", shared_transport)
    auth = SimpleNamespace(
        transport=shared_transport,
        token_health=lambda: _auth_result(),
        load_access_token=lambda **_kwargs: (SYNTHETIC_ACCESS, _auth_result()),
        _read_tokens=lambda: SimpleNamespace(granted_scopes=lambda: ALLOWED_SCOPES),
    )
    with _owner_heart_rate_day_refresh(
        shared_settings,
        day=date(2099, 1, 2),
        auth_service=auth,
        query_mode=None,
        data_source_family=None,
        phase_timing=None,
    ) as refresh:
        shared = refresh()

    assert shared.status is standalone.status is GoogleSyncStatus.SUCCEEDED
    assert shared.request_count == standalone.request_count == 1
    assert shared.attempts == standalone.attempts
    shared_report = shared.as_dict()
    standalone_report = standalone.as_dict()
    assert shared_report["sync"].pop("sync_run_id") != standalone_report["sync"].pop(
        "sync_run_id"
    )
    assert shared_report == standalone_report
    assert shared_transport.health_calls() == standalone_transport.health_calls()


def test_owner_hr_day_context_keeps_lock_and_checkpoint_on_continuation_reauth(
    tmp_path,
) -> None:
    transport = FakeGoogleHealthTransport()
    for index in range(MAX_PAGES_PER_FETCH):
        transport.queue(
            "heart-rate",
            {"dataPoints": [], "nextPageToken": f"page-{index + 1}"},
            page_token=None if index == 0 else f"page-{index}",
        )
    settings, _ = _sync(tmp_path, transport)
    paths = prepare_runtime(settings)
    reauth = GoogleAuthResult(
        status=GoogleAuthStatus.REAUTH_REQUIRED,
        error=GoogleSafeError("auth", "reauth_required"),
    )
    auth_calls = 0

    def token_health():
        nonlocal auth_calls
        auth_calls += 1
        return _auth_result() if auth_calls == 1 else reauth

    auth = SimpleNamespace(
        transport=transport,
        token_health=token_health,
        load_access_token=lambda **_kwargs: (SYNTHETIC_ACCESS, _auth_result()),
        _read_tokens=lambda: SimpleNamespace(granted_scopes=lambda: ALLOWED_SCOPES),
    )
    with _owner_heart_rate_day_refresh(
        settings,
        day=date(2099, 1, 2),
        auth_service=auth,
        query_mode=None,
        data_source_family=None,
        phase_timing=None,
    ) as refresh:
        with pytest.raises(ExternalRuntimeOperationBusyError):
            with ExternalRuntimeOperationLock(paths, allow_reentrant=False):
                pass
        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(RuntimeError, match="context is unavailable"):
                pool.submit(refresh).result()
        first = refresh()
        second = refresh()
        assert first.status is GoogleSyncStatus.PARTIAL
        assert first.attempts[0].resume_cursor_present is True
        assert second.status is GoogleSyncStatus.REAUTH_REQUIRED
        assert second.request_count == 0 and second.attempts == ()
        assert second.sync_run_id != first.sync_run_id
    with ExternalRuntimeOperationLock(paths, allow_reentrant=False):
        pass
    with sqlite3.connect(paths.database) as connection:
        row = connection.execute(
            "SELECT cursor FROM sync_stream_state WHERE stream_code = ?",
            ("google:refresh:heart_rate:list:any:day:2099-01-02",),
        ).fetchone()
    assert row is not None
    checkpoint = json.loads(row[0])
    assert checkpoint["page_token"] == f"page-{MAX_PAGES_PER_FETCH}"
    assert checkpoint["staged_run_ids"] == [first.sync_run_id]
    assert auth_calls == 2


def test_owner_hr_day_context_cleans_up_on_continuation_and_setup_errors(
    monkeypatch, tmp_path
) -> None:
    import healthcheck.google.sync as google_sync

    transport = FakeGoogleHealthTransport()
    settings, _ = _sync(tmp_path, transport)
    paths = prepare_runtime(settings)
    auth = SimpleNamespace(
        transport=transport, token_health=_auth_result,
        load_access_token=lambda **_kwargs: (SYNTHETIC_ACCESS, _auth_result()),
        _read_tokens=lambda: SimpleNamespace(granted_scopes=lambda: ALLOWED_SCOPES),
    )
    disposals = 0
    original_engine = google_sync.create_sqlite_engine

    def counted_engine(*args, **kwargs):
        nonlocal disposals
        engine = original_engine(*args, **kwargs)
        original_dispose = engine.dispose

        def dispose():
            nonlocal disposals
            disposals += 1
            return original_dispose()

        engine.dispose = dispose
        return engine

    monkeypatch.setattr(google_sync, "create_sqlite_engine", counted_engine)

    def fail_continuation(*_args, **_kwargs):
        raise RuntimeError("synthetic continuation failure")

    monkeypatch.setattr(GoogleHealthSync, "_run", fail_continuation)
    with pytest.raises(RuntimeError, match="synthetic continuation failure"):
        with _owner_heart_rate_day_refresh(
            settings,
            day=date(2099, 1, 2),
            auth_service=auth,
            query_mode=None,
            data_source_family=None,
            phase_timing=None,
        ) as refresh:
            refresh()
    assert disposals == 1
    with pytest.raises(RuntimeError, match="context is unavailable"):
        refresh()
    with ExternalRuntimeOperationLock(paths, allow_reentrant=False):
        pass

    def fail_setup(_engine):
        raise RuntimeError("synthetic setup failure")

    monkeypatch.setattr(google_sync, "create_session_factory", fail_setup)
    with pytest.raises(RuntimeError, match="synthetic setup failure"):
        with _owner_heart_rate_day_refresh(
            settings,
            day=date(2099, 1, 2),
            auth_service=auth,
            query_mode=None,
            data_source_family=None,
            phase_timing=None,
        ):
            pass
    assert disposals == 2
    with ExternalRuntimeOperationLock(paths, allow_reentrant=False):
        pass


def test_dense_refresh_converges_with_staged_correction_and_idempotent_projection(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    dense_page_count = (MAX_PAGES_PER_FETCH * 2) + 2
    for index in range(dense_page_count):
        page_token = None if index == 0 else f"refresh-page-{index}"
        next_token = (
            f"refresh-page-{index + 1}" if index + 1 < dense_page_count else None
        )
        point = _hr_point(
            name=f"refresh-hr-{index}",
            bpm="81" if index == 0 else str(60 + (index % 20)),
        )
        payload: dict[str, Any] = {"dataPoints": [point]}
        if next_token is not None:
            payload["nextPageToken"] = next_token
        if index == 0:
            original = dict(payload)
            original["dataPoints"] = [_hr_point(name="refresh-hr-0", bpm="61")]
            transport.queue("heart-rate", original, page_token=page_token)
            transport.queue("heart-rate", payload, page_token=page_token)
            transport.queue("heart-rate", payload, page_token=page_token)
            transport.queue("heart-rate", payload, page_token=page_token)
            transport.queue("heart-rate", payload, page_token=page_token)
            transport.queue("heart-rate", payload, page_token=page_token)
        else:
            transport.queue("heart-rate", payload, page_token=page_token)
            transport.queue("heart-rate", payload, page_token=page_token)

    settings, _service = _sync(tmp_path, transport)
    first = run_google_refresh(
        settings,
        start=AS_OF,
        end=AS_OF,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
        max_provider_requests=MAX_PAGES_PER_FETCH,
        checkpoint_partition=AS_OF,
    )
    assert first.status is GoogleSyncStatus.PARTIAL
    assert first.request_count == MAX_PAGES_PER_FETCH
    assert first.attempts[0].resume_cursor_present is True

    engine, factory = _session(settings)
    try:
        with factory() as session:
            metric = session.scalar(
                select(GoogleRecordMetric).where(
                    GoogleRecordMetric.metric_code == "heart_rate_bpm"
                )
            )
            assert metric is None
            state = session.scalar(
                select(SyncStreamState).where(
                    SyncStreamState.stream_code
                    == "google:refresh:heart_rate:list:any:day:2099-01-02"
                )
            )
            assert state is not None
            checkpoint = json.loads(state.cursor or "{}")
            assert checkpoint["page_token"] == "refresh-page-40"
            assert checkpoint["staged_run_ids"]
    finally:
        engine.dispose()

    second = run_google_refresh(
        settings,
        start=AS_OF,
        end=AS_OF,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
        max_provider_requests=MAX_PAGES_PER_FETCH,
        checkpoint_partition=AS_OF,
    )
    assert second.status is GoogleSyncStatus.PARTIAL
    assert second.request_count == MAX_PAGES_PER_FETCH
    assert second.attempts[0].resume_cursor_present is True

    third = run_google_refresh(
        settings,
        start=AS_OF,
        end=AS_OF,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
        max_provider_requests=MAX_PAGES_PER_FETCH,
        checkpoint_partition=AS_OF,
    )
    assert third.status is GoogleSyncStatus.SUCCEEDED
    assert third.request_count == 4
    assert third.attempts[0].resume_cursor_present is False
    assert "refresh-page-" not in third.to_json()

    engine, factory = _session(settings)
    try:
        with factory() as session:
            metric = session.scalar(
                select(GoogleRecordMetric).where(
                    GoogleRecordMetric.metric_code == "heart_rate_bpm"
                )
            )
            assert metric is not None
            assert metric.value_number == 81
            assert (
                session.scalar(select(func.count()).select_from(GoogleSourceRecord))
                == dense_page_count
            )
            record_snapshot = tuple(
                sorted(
                    (
                        row.record_identity_key,
                        row.record_status,
                        row.projection_status,
                    )
                    for row in session.scalars(select(GoogleSourceRecord))
                )
            )
            metric_snapshot = tuple(
                sorted(
                    (
                        row.record_id,
                        row.metric_code,
                        row.state,
                        row.value_number,
                    )
                    for row in session.scalars(select(GoogleRecordMetric))
                )
            )
    finally:
        engine.dispose()

    # Explicit refresh remains provider-facing for late-correction discovery.
    # Queue the same dense provider result for an exact second epoch and prove
    # bounded convergence is projection-idempotent, not merely empty-response safe.
    rerun_first = run_google_refresh(
        settings,
        start=AS_OF,
        end=AS_OF,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
        max_provider_requests=MAX_PAGES_PER_FETCH,
        checkpoint_partition=AS_OF,
    )
    assert rerun_first.status is GoogleSyncStatus.PARTIAL
    assert rerun_first.request_count == MAX_PAGES_PER_FETCH
    assert rerun_first.attempts[0].resume_cursor_present is True
    rerun_second = run_google_refresh(
        settings,
        start=AS_OF,
        end=AS_OF,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
        max_provider_requests=MAX_PAGES_PER_FETCH,
        checkpoint_partition=AS_OF,
    )
    assert rerun_second.status is GoogleSyncStatus.PARTIAL
    assert rerun_second.request_count == MAX_PAGES_PER_FETCH
    rerun = run_google_refresh(
        settings,
        start=AS_OF,
        end=AS_OF,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
        max_provider_requests=MAX_PAGES_PER_FETCH,
        checkpoint_partition=AS_OF,
    )
    assert rerun.status is GoogleSyncStatus.SUCCEEDED
    assert rerun.request_count == 4
    assert rerun.attempts[0].inserted_count == 0
    # The persistence layer counts replayed upserts as updates; the snapshots
    # below prove the exact refresh is semantically idempotent.
    assert rerun.attempts[0].updated_count == dense_page_count
    assert "refresh-page-" not in rerun.to_json()
    engine, factory = _session(settings)
    try:
        with factory() as session:
            assert (
                session.scalar(select(func.count()).select_from(GoogleSourceRecord))
                == dense_page_count
            )
            assert record_snapshot == tuple(
                sorted(
                    (
                        row.record_identity_key,
                        row.record_status,
                        row.projection_status,
                    )
                    for row in session.scalars(select(GoogleSourceRecord))
                )
            )
            assert metric_snapshot == tuple(
                sorted(
                    (
                        row.record_id,
                        row.metric_code,
                        row.state,
                        row.value_number,
                    )
                    for row in session.scalars(select(GoogleRecordMetric))
                )
            )
            metric = session.scalar(
                select(GoogleRecordMetric).where(
                    GoogleRecordMetric.metric_code == "heart_rate_bpm"
                )
            )
            assert metric is not None
            assert metric.value_number == 81
    finally:
        engine.dispose()


def test_dense_completed_hr_promotion_selects_do_not_grow_per_record(monkeypatch, tmp_path) -> None:
    """One dense page keeps projection lookups bounded on insert and replay."""

    original = GoogleHealthSync._promote_refresh_staging
    promotion_selects: list[int] = []

    def count_promotion(self, *args, **kwargs):
        selects = 0

        def count_sql(_connection, _cursor, statement, _parameters, _context, _many):
            nonlocal selects
            if statement.lstrip().upper().startswith("SELECT"):
                selects += 1

        event.listen(Engine, "before_cursor_execute", count_sql)
        try:
            return original(self, *args, **kwargs)
        finally:
            event.remove(Engine, "before_cursor_execute", count_sql)
            promotion_selects.append(selects)

    monkeypatch.setattr(GoogleHealthSync, "_promote_refresh_staging", count_promotion)

    for size in (12, 48):
        transport = FakeGoogleHealthTransport()
        points = [_hr_point(name=f"dense-{index}", bpm="72") for index in range(size)]
        payload = {"dataPoints": points}
        settings, _service = _sync(tmp_path / f"size-{size}", transport)
        for _ in range(2):
            transport.queue("heart-rate", payload)
            report = run_google_refresh(
                settings,
                start=AS_OF,
                end=AS_OF,
                transport=transport,
                auth_result=_auth_result(),
                access_token=SYNTHETIC_ACCESS,
                granted_scopes=ALLOWED_SCOPES,
                streams=["heart_rate"],
                checkpoint_partition=AS_OF,
            )
            assert report.status is GoogleSyncStatus.SUCCEEDED
        engine, factory = _session(settings)
        try:
            with factory() as session:
                assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == size
                assert (
                    session.scalar(select(func.count()).select_from(GoogleRecordMetric)) == 3 * size
                )
        finally:
            engine.dispose()

    small_insert, small_replay, dense_insert, dense_replay = promotion_selects
    original_persist = GooglePersistenceRepository.persist_result

    def without_preload(self, result, **kwargs):
        kwargs["preload_heart_rate_page"] = False
        return original_persist(self, result, **kwargs)

    monkeypatch.setattr(GooglePersistenceRepository, "persist_result", without_preload)
    baseline_transport = FakeGoogleHealthTransport()
    baseline_payload = {
        "dataPoints": [_hr_point(name=f"baseline-{index}", bpm="72") for index in range(48)]
    }
    baseline_settings, _service = _sync(tmp_path / "baseline", baseline_transport)
    for _ in range(2):
        baseline_transport.queue("heart-rate", baseline_payload)
        report = run_google_refresh(
            baseline_settings,
            start=AS_OF,
            end=AS_OF,
            transport=baseline_transport,
            auth_result=_auth_result(),
            access_token=SYNTHETIC_ACCESS,
            granted_scopes=ALLOWED_SCOPES,
            streams=["heart_rate"],
            checkpoint_partition=AS_OF,
        )
        assert report.status is GoogleSyncStatus.SUCCEEDED
    baseline_insert, baseline_replay = promotion_selects[4:]

    # Previously, identity alone took one SELECT for every record, with
    # additional per-record metric/evidence/epoch queries on replay.
    assert dense_insert < 48 // 2
    assert dense_replay < 48 // 2
    assert dense_insert - small_insert <= 4
    assert dense_replay - small_replay <= 4
    assert dense_insert * 2 < baseline_insert
    assert dense_replay * 2 < baseline_replay


def test_owner_refresh_daily_hr_partitions_converge_newest_first_and_rerun_idempotently(
    tmp_path,
) -> None:
    import healthcheck.owner_refresh as owner_refresh

    transport = FakeGoogleHealthTransport()
    dense_page_count = MAX_PAGES_PER_FETCH + 2

    def queue_epoch(*, corrected_only: bool) -> None:
        for day in (2, 1):
            prefix = f"daily-{day}"
            for index in range(dense_page_count):
                page_token = None if index == 0 else f"{prefix}-page-{index}"
                next_token = (
                    f"{prefix}-page-{index + 1}"
                    if index + 1 < dense_page_count
                    else None
                )
                corrected_bpm = str(80 + day) if index == 0 else str(60 + (index % 20))
                corrected: dict[str, Any] = {
                    "dataPoints": [
                        _hr_point(
                            name=f"{prefix}-hr-{index}",
                            bpm=corrected_bpm,
                            day=day,
                        )
                    ]
                }
                if next_token is not None:
                    corrected["nextPageToken"] = next_token
                if index == 0:
                    first = corrected
                    if not corrected_only:
                        first = dict(corrected)
                        first["dataPoints"] = [
                            _hr_point(name=f"{prefix}-hr-0", bpm="61", day=day)
                        ]
                    transport.queue("heart-rate", first)
                    transport.queue("heart-rate", corrected)
                else:
                    transport.queue("heart-rate", corrected, page_token=page_token)

    settings, _service = _sync(tmp_path, transport)

    auth = SimpleNamespace(
        transport=transport,
        token_health=lambda: _auth_result(),
        load_access_token=lambda **_kwargs: (SYNTHETIC_ACCESS, _auth_result()),
        _read_tokens=lambda: SimpleNamespace(granted_scopes=lambda: ALLOWED_SCOPES),
    )
    queue_epoch(corrected_only=False)
    first = owner_refresh._run_normal_google_refresh(
        settings,
        auth_service=auth,
        start="2099-01-01",
        end="2099-01-02",
        streams=["heart_rate"],
        query_mode=None,
        data_source_family=None,
    )

    assert first.status is GoogleSyncStatus.SUCCEEDED
    assert first.request_count == 2 * (MAX_PAGES_PER_FETCH + 3)
    assert [item.window_start for item in first.attempts] == ["2099-01-02", "2099-01-01"]
    assert all(item.status is GoogleSyncStatus.SUCCEEDED for item in first.attempts)
    filters = [item["filter"] for item in transport.health_calls()]
    filter_transitions = [
        value for index, value in enumerate(filters) if index == 0 or value != filters[index - 1]
    ]
    assert len(filter_transitions) == 2
    assert "2099-01-02" in filter_transitions[0]
    assert "2099-01-01" in filter_transitions[1]

    engine, factory = _session(settings)
    try:
        with factory() as session:
            assert (
                session.scalar(select(func.count()).select_from(GoogleSourceRecord))
                == 2 * dense_page_count
            )
            state_codes = {
                row.stream_code
                for row in session.scalars(
                    select(SyncStreamState).where(
                        SyncStreamState.stream_code.like(
                            "google:refresh:heart_rate:list:any:day:%"
                        )
                    )
                )
            }
            assert state_codes == {
                "google:refresh:heart_rate:list:any:day:2099-01-01",
                "google:refresh:heart_rate:list:any:day:2099-01-02",
            }
            projection_before = tuple(
                sorted(
                    session.execute(
                        select(
                            GoogleSourceRecord.external_record_id,
                            GoogleRecordMetric.value_number,
                        ).join(
                            GoogleRecordMetric,
                            GoogleRecordMetric.record_id == GoogleSourceRecord.id,
                        ).where(GoogleRecordMetric.metric_code == "heart_rate_bpm")
                    ).all()
                )
            )
            assert dict(projection_before)["daily-2-hr-0"] == 82
            assert dict(projection_before)["daily-1-hr-0"] == 81
    finally:
        engine.dispose()

    queue_epoch(corrected_only=True)
    rerun = owner_refresh._run_normal_google_refresh(
        settings,
        auth_service=auth,
        start="2099-01-01",
        end="2099-01-02",
        streams=["heart_rate"],
        query_mode=None,
        data_source_family=None,
    )
    assert rerun.status is GoogleSyncStatus.SUCCEEDED
    assert all(item.inserted_count == 0 for item in rerun.attempts)
    engine, factory = _session(settings)
    try:
        with factory() as session:
            projection_after = tuple(
                sorted(
                    session.execute(
                        select(
                            GoogleSourceRecord.external_record_id,
                            GoogleRecordMetric.value_number,
                        ).join(
                            GoogleRecordMetric,
                            GoogleRecordMetric.record_id == GoogleSourceRecord.id,
                        ).where(GoogleRecordMetric.metric_code == "heart_rate_bpm")
                    ).all()
                )
            )
            assert projection_after == projection_before
            assert (
                session.scalar(select(func.count()).select_from(GoogleSourceRecord))
                == 2 * dense_page_count
            )
    finally:
        engine.dispose()


def test_refresh_named_datasource_does_not_create_unattributed_source(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    point = _hr_point(name="hr-1", bpm="72", data_source=_named_data_source(SOURCE_A))
    transport.queue("heart-rate", {"dataPoints": [point]})
    settings, incremental = _sync(tmp_path, transport)
    incremental.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    transport.queue(
        "heart-rate",
        {"dataPoints": [point], "nextPageToken": "p2"},
    )
    transport.queue("heart-rate", {"dataPoints": []}, page_token="p2")
    report = run_google_refresh(
        settings,
        start=AS_OF,
        end=AS_OF,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        streams=["heart_rate"],
    )
    assert report.status is GoogleSyncStatus.SUCCEEDED
    engine, factory = _session(settings)
    try:
        with factory() as session:
            instances = {
                row.source_instance_id for row in session.scalars(select(GoogleSource))
            }
            assert instances == {SOURCE_A}
            assert UNATTRIBUTED_SOURCE_INSTANCE not in instances
            assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 1
    finally:
        engine.dispose()


def test_historical_backfill_budget_exhaustion_is_not_success(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", {"dataPoints": [_hr_point(name="hr-1", bpm="41")]})
    settings, _service = _sync(tmp_path, transport)
    report = GoogleHistoricalBackfill(
        settings,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        max_provider_requests=1,
    ).run(
        start="2099-01-01",
        end="2099-01-02",
        streams=["heart_rate"],
        chunk_days=1,
    )
    assert report.status is GoogleSyncStatus.PARTIAL
    assert report.abort_reason == "request_ceiling"
    assert any(item.status is GoogleSyncStatus.NOT_RUN for item in report.attempts)
    assert any(
        item.status in {GoogleSyncStatus.SUCCEEDED, GoogleSyncStatus.EMPTY}
        for item in report.attempts
    )


def test_historical_backfill_exact_budget_for_completed_work_is_success(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", {"dataPoints": [_hr_point(name="hr-1", bpm="41")]})
    transport.queue("heart-rate", {"dataPoints": [_hr_point(name="hr-2", bpm="42")]})
    settings, _service = _sync(tmp_path, transport)
    report = GoogleHistoricalBackfill(
        settings,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
        max_provider_requests=2,
    ).run(
        start="2099-01-01",
        end="2099-01-02",
        streams=["heart_rate"],
        chunk_days=1,
    )
    assert report.status is GoogleSyncStatus.SUCCEEDED
    assert report.abort_reason is None
    assert report.request_count == 2
    assert all(item.status is not GoogleSyncStatus.NOT_RUN for item in report.attempts)
    assert all(
        item.status in {GoogleSyncStatus.SUCCEEDED, GoogleSyncStatus.EMPTY}
        for item in report.attempts
    )


def test_dense_historical_window_resumes_across_bounded_invocations(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    dense_page_count = (MAX_PAGES_PER_FETCH * 2) + 2
    for index in range(dense_page_count):
        page_token = None if index == 0 else f"synthetic-page-{index}"
        next_token = (
            f"synthetic-page-{index + 1}" if index + 1 < dense_page_count else None
        )
        payload: dict[str, Any] = {
            "dataPoints": [_hr_point(name=f"hr-{index}", bpm=str(60 + (index % 20)))]
        }
        if next_token is not None:
            payload["nextPageToken"] = next_token
        transport.queue("heart-rate", payload, page_token=page_token)

    settings, _service = _sync(tmp_path, transport)
    backfill = GoogleHistoricalBackfill(
        settings,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
    )

    first = backfill.run(
        start="2099-01-02",
        end="2099-01-03",
        streams=["heart_rate"],
        chunk_days=1,
    )
    assert first.status is GoogleSyncStatus.PARTIAL
    assert first.request_count == MAX_PAGES_PER_FETCH
    assert first.request_count <= MAX_SYNC_PROVIDER_REQUESTS
    assert first.attempts[0].page_count == MAX_PAGES_PER_FETCH
    assert first.attempts[0].error == GoogleSafeError("budget", "page_ceiling")
    assert first.attempts[1].status is GoogleSyncStatus.NOT_RUN
    assert "synthetic-page-" not in first.to_json()

    engine, factory = _session(settings)
    try:
        with factory() as session:
            state = session.scalar(
                select(SyncStreamState).where(
                    SyncStreamState.stream_code.like("google:historical:heart_rate:%")
                )
            )
            assert state is not None
            assert json.loads(state.cursor or "{}")["page_token"] == (
                f"synthetic-page-{MAX_PAGES_PER_FETCH}"
            )
    finally:
        engine.dispose()

    second = backfill.run(
        start="2099-01-02",
        end="2099-01-03",
        streams=["heart_rate"],
        chunk_days=1,
    )
    assert second.status is GoogleSyncStatus.PARTIAL
    assert second.request_count == MAX_PAGES_PER_FETCH
    assert second.request_count <= MAX_SYNC_PROVIDER_REQUESTS
    assert second.attempts[0].page_count == MAX_PAGES_PER_FETCH
    assert second.attempts[0].error == GoogleSafeError("budget", "page_ceiling")
    assert second.attempts[1].status is GoogleSyncStatus.NOT_RUN
    assert "synthetic-page-" not in second.to_json()

    engine, factory = _session(settings)
    try:
        with factory() as session:
            state = session.scalar(
                select(SyncStreamState).where(
                    SyncStreamState.stream_code.like("google:historical:heart_rate:%")
                )
            )
            assert state is not None
            assert json.loads(state.cursor or "{}")["page_token"] == (
                f"synthetic-page-{MAX_PAGES_PER_FETCH * 2}"
            )
    finally:
        engine.dispose()

    third = backfill.run(
        start="2099-01-02",
        end="2099-01-03",
        streams=["heart_rate"],
        chunk_days=1,
    )
    assert third.status is GoogleSyncStatus.SUCCEEDED
    assert third.request_count == 3
    assert all(
        item.status in {GoogleSyncStatus.SUCCEEDED, GoogleSyncStatus.EMPTY}
        for item in third.attempts
    )

    calls_after_completion = len(transport.health_calls())
    exact_rerun = backfill.run(
        start="2099-01-02",
        end="2099-01-03",
        streams=["heart_rate"],
        chunk_days=1,
    )
    assert exact_rerun.status is GoogleSyncStatus.SUCCEEDED
    assert exact_rerun.request_count == 0
    assert all(item.skipped for item in exact_rerun.attempts)
    assert len(transport.health_calls()) == calls_after_completion

    engine, factory = _session(settings)
    try:
        with factory() as session:
            record_count = session.scalar(select(func.count()).select_from(GoogleSourceRecord))
            identity_count = session.scalar(
                select(func.count(func.distinct(GoogleSourceRecord.record_identity_key)))
            )
            assert record_count == dense_page_count
            assert identity_count == dense_page_count
    finally:
        engine.dispose()


def test_historical_backfill_failed_then_success_is_not_success(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", 400)
    settings, _service = _sync(tmp_path, transport)
    report = GoogleHistoricalBackfill(
        settings,
        transport=transport,
        auth_result=_auth_result(),
        access_token=SYNTHETIC_ACCESS,
        granted_scopes=ALLOWED_SCOPES,
    ).run(
        start="2099-01-01",
        end="2099-01-02",
        streams=["heart_rate"],
        chunk_days=1,
    )
    assert report.status is GoogleSyncStatus.PARTIAL
    statuses = {item.status for item in report.attempts}
    assert GoogleSyncStatus.FAILED in statuses
    assert GoogleSyncStatus.EMPTY in statuses or GoogleSyncStatus.SUCCEEDED in statuses


def test_invalid_json_terminal_body_is_retained_locally(tmp_path) -> None:
    marker = b"<<<not-json-terminal-body>>>"
    transport = FakeGoogleHealthTransport()
    transport.queue_raw("heart-rate", marker, status=200)
    settings, service = _sync(tmp_path, transport)
    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert report.status is GoogleSyncStatus.FAILED
    assert report.attempts[0].coverage_status == "failed"
    dumped = report.to_json()
    assert "not-json-terminal-body" not in dumped
    engine, factory = _session(settings)
    try:
        with factory() as session:
            bodies = _artifact_bodies(settings, session)
            assert marker in bodies
            coverage = list(session.scalars(select(CoverageInterval)))
            assert all(row.status != "present" for row in coverage)
            assert all(row.status != "confirmed_empty" for row in coverage)
    finally:
        engine.dispose()


def test_provider_error_body_is_retained_locally(tmp_path) -> None:
    marker = b'{"error":"terminal-provider-body"}'
    transport = FakeGoogleHealthTransport()
    transport.queue_raw("heart-rate", marker, status=400)
    settings, service = _sync(tmp_path, transport)
    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert report.status is GoogleSyncStatus.FAILED
    assert report.attempts[0].error == GoogleSafeError("provider", "provider_error", 400)
    dumped = report.to_json()
    assert "terminal-provider-body" not in dumped
    engine, factory = _session(settings)
    try:
        with factory() as session:
            bodies = _artifact_bodies(settings, session)
            assert marker in bodies
            coverage = list(session.scalars(select(CoverageInterval)))
            assert all(row.status not in {"present", "confirmed_empty"} for row in coverage)
    finally:
        engine.dispose()


@pytest.mark.parametrize("host_tz", ["UTC0", "EST5EDT,M3.2.0,M11.1.0", "JST-9"])
@pytest.mark.parametrize("start,end,exclusive", [
    ("2024-01-15", "2024-01-15", "2024-01-16"),
    ("2024-01-31", "2024-01-31", "2024-02-01"),
    ("2024-12-31", "2024-12-31", "2025-01-01"),
    ("2024-02-28", "2024-02-29", "2024-03-01"),
    ("2023-02-28", "2023-02-28", "2023-03-01"),
    ("2024-03-09", "2024-03-11", "2024-03-12"),
    ("2024-11-02", "2024-11-04", "2024-11-05"),
    ("2024-02-20", "2024-03-04", "2024-03-05"),  # Exactly 14 civil days.
])
def test_daily_rollup_exact_civil_request(tmp_path, monkeypatch, host_tz, start, end, exclusive):
    # tzset applies real process-local TZ changes on Linux CI; Windows has no tzset.
    with monkeypatch.context() as context:
        context.setenv("TZ", host_tz)
        if hasattr(time, "tzset"):
            time.tzset()
        try:
            transport = FakeGoogleHealthTransport()
            _settings, service = _sync(tmp_path, transport)
            report = service.run(start=start, end=end, streams=["heart_rate"],
                                 query_mode="dailyRollUp",
                                 data_source_family=FAMILY_GOOGLE_WEARABLES)
        finally:
            context.undo()
            if hasattr(time, "tzset"):
                time.tzset()
    assert report.status is GoogleSyncStatus.SUCCEEDED
    assert report.window_end_exclusive == exclusive
    call, = transport.health_calls()
    start_date, end_date = date.fromisoformat(start), date.fromisoformat(exclusive)
    assert call["method"] == "POST"
    assert call["url"] == (
        "https://health.googleapis.com/v4/users/me/dataTypes/heart-rate/dataPoints:dailyRollUp"
    )
    assert call["json_body"] == {
        "range": {
            "start": {"date": {"year": start_date.year, "month": start_date.month,
                               "day": start_date.day}},
            "end": {"date": {"year": end_date.year, "month": end_date.month, "day": end_date.day}},
        },
        "pageSize": 500,
        "dataSourceFamily": FAMILY_GOOGLE_WEARABLES,
    }


def test_daily_rollup_default_one_day_and_exclusive_entrypoint(tmp_path):
    transport = FakeGoogleHealthTransport()
    _settings, service = _sync(tmp_path / "default", transport)
    report = service.run(as_of="2024-02-29", streams=["heart_rate"], query_mode="dailyRollUp")
    assert report.status is GoogleSyncStatus.SUCCEEDED
    expected = {
        "range": {"start": {"date": {"year": 2024, "month": 2, "day": 29}},
                  "end": {"date": {"year": 2024, "month": 3, "day": 1}}},
        "pageSize": 500,
    }
    assert transport.health_calls()[0]["json_body"] == expected
    direct_transport = FakeGoogleHealthTransport()
    _settings, direct = _sync(tmp_path / "exclusive", direct_transport)
    report = direct.run_window(start=date(2024, 2, 29), end_exclusive=date(2024, 3, 1),
                               streams=["heart_rate"], query_mode="dailyRollUp")
    assert report.status is GoogleSyncStatus.SUCCEEDED
    assert direct_transport.health_calls()[0]["json_body"] == expected


@pytest.mark.parametrize("mode", ["dailyRollUp", "rollUp"])
def test_hr_rollup_over14_days_rejected_before_auth_or_transport(tmp_path, monkeypatch, mode):
    transport = FakeGoogleHealthTransport()
    _settings, service = _sync(tmp_path, transport)

    def forbidden_auth():
        pytest.fail("oversized rollup must fail before auth")

    monkeypatch.setattr(service, "_resolve_auth", forbidden_auth)
    with pytest.raises(ValueError, match="windows must be <= 14 days"):
        service.run(start="2024-02-20", end="2024-03-05", streams=["heart_rate"], query_mode=mode)
    assert transport.calls == []


def test_daily_rollup_two_pages_change_only_page_token(tmp_path):
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", {"rollupDataPoints": [], "nextPageToken": "synthetic-page-2"},
                    operation="dailyRollUp")
    transport.queue("heart-rate", {"rollupDataPoints": []}, operation="dailyRollUp",
                    page_token="synthetic-page-2")
    settings, service = _sync(tmp_path, transport)
    report = service.run(start="2024-12-31", end="2024-12-31", streams=["heart_rate"],
                         query_mode="dailyRollUp", data_source_family=FAMILY_GOOGLE_WEARABLES)
    assert report.status is GoogleSyncStatus.SUCCEEDED
    assert report.attempts[0].page_count == 2 and report.request_count == 2
    first, second = transport.health_calls()
    assert second == {**first, "has_page_token": True,
                      "json_body": {**first["json_body"], "pageToken": "synthetic-page-2"}}
    assert first["json_body"]["range"]["end"] == {"date": {"year": 2025, "month": 1, "day": 1}}
    engine, factory = _session(settings)
    try:
        with factory() as session:
            state = session.scalar(select(SyncStreamState))
            assert ":dailyRollUp:google-wearables" in state.stream_code
            assert state.watermark is not None
    finally:
        engine.dispose()


@pytest.mark.parametrize("status", [400, 401, 403, 503])
def test_daily_rollup_later_error_never_completes_window(tmp_path, status):
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", {"rollupDataPoints": [], "nextPageToken": "synthetic-page-2"},
                    operation="dailyRollUp")
    for _ in range(MAX_RETRY_ATTEMPTS if status == 503 else 1):
        transport.queue("heart-rate", status, operation="dailyRollUp",
                        page_token="synthetic-page-2")
    settings, service = _sync(tmp_path, transport, sleeper=lambda _delay: None)
    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"], query_mode="dailyRollUp")
    assert report.status is not GoogleSyncStatus.SUCCEEDED
    attempt = report.attempts[0]
    assert attempt.page_count == 1 and attempt.error.http_status == status
    assert attempt.coverage_status != "confirmed_empty"
    engine, factory = _session(settings)
    try:
        with factory() as session:
            state = session.scalar(select(SyncStreamState))
            assert state.watermark is None
            assert json.loads(state.cursor)["page_token"] == "synthetic-page-2"
            coverage = list(session.scalars(select(CoverageInterval)))
            assert coverage and all(row.status not in {"present", "confirmed_empty"}
                                    for row in coverage)
    finally:
        engine.dispose()


@pytest.mark.parametrize("mode", ["rollUp", "list", "reconcile"])
def test_physical_rollup_list_reconcile_requests_unchanged(tmp_path, mode):
    transport = FakeGoogleHealthTransport()
    _settings, service = _sync(tmp_path, transport)
    report = service.run(start="2024-12-31", end="2024-12-31", streams=["heart_rate"],
                         query_mode=mode, data_source_family=FAMILY_GOOGLE_WEARABLES)
    assert report.status is GoogleSyncStatus.SUCCEEDED
    call, = transport.health_calls()
    root = "https://health.googleapis.com/v4/users/me/dataTypes/heart-rate/dataPoints"
    if mode == "rollUp":
        assert call["method"] == "POST" and call["url"] == root + ":rollUp"
        assert call["json_body"] == {
            "range": {"startTime": "2024-12-31T00:00:00Z", "endTime": "2025-01-01T00:00:00Z"},
            "windowSize": "60s", "pageSize": 500, "dataSourceFamily": FAMILY_GOOGLE_WEARABLES,
        }
    else:
        assert call["method"] == "GET" and call["json_body"] is None
        parsed = urlparse(call["url"])
        assert parsed.scheme + "://" + parsed.netloc + parsed.path == (
            root + (":reconcile" if mode == "reconcile" else "")
        )
        assert parse_qs(parsed.query) == {
            "filter": ['heart_rate.sample_time.civil_time >= "2024-12-31" AND '
                       'heart_rate.sample_time.civil_time < "2025-01-01"'],
            "pageSize": ["500"], "dataSourceFamily": [FAMILY_GOOGLE_WEARABLES],
        }
