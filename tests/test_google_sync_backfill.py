"""Synthetic Google Health sync/backfill/refresh regressions for issue #88."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from sqlalchemy import func, select

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
from healthcheck.google.auth import (
    ALLOWED_SCOPES,
    DEFAULT_SCOPE_ORDER,
    SCOPE_METRICS,
    GoogleAuthResult,
    GoogleAuthService,
    GoogleAuthStatus,
    GoogleClientCredentials,
    GoogleHttpResponse,
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
from healthcheck.google.protection import GoogleLocalKeyFileProtection
from healthcheck.google.sync import (
    MAX_SYNC_PROVIDER_REQUESTS,
    RETRY_BACKOFF_SECONDS,
    SLEEP_PAGE_SIZE,
    UNATTRIBUTED_SOURCE_INSTANCE,
    GoogleHealthSync,
    GoogleRunKind,
    GoogleSyncStatus,
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
    hour: int = 8,
    data_source: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "dataSource": dict(data_source) if data_source is not None else _data_source(),
        "heartRate": {"sampleTime": _sample_time(hour=hour), "beatsPerMinute": bpm},
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
        self._queues: dict[tuple[str, str, str], list[GoogleHttpResponse]] = {}
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
            return queue.pop(0)
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
    assert first.attempts[0].resume_cursor_present is False
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
            assert raw_after > raw_before
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


def test_historical_backfill_failed_then_success_is_not_success(tmp_path) -> None:
    transport = FakeGoogleHealthTransport()
    transport.queue("heart-rate", 500)
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
    transport.queue_raw("heart-rate", marker, status=500)
    settings, service = _sync(tmp_path, transport)
    report = service.run(start=AS_OF, end=AS_OF, streams=["heart_rate"])
    assert report.status is GoogleSyncStatus.FAILED
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
