"""Synthetic tests for the bounded owner Garmin + dual-Google refresh command."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

from healthcheck import cli
from healthcheck.config import Settings
from healthcheck.db.engine import migrate_database
from healthcheck.garmin.auth import GarminAuthResult, GarminAuthStatus
from healthcheck.garmin.sync import (
    GarminSyncReport,
    GarminSyncStatus,
    compute_sync_window,
)
from healthcheck.google.auth import GoogleAuthResult, GoogleAuthStatus, GoogleSafeError
from healthcheck.google.sync import (
    GoogleRunKind,
    GoogleSyncAttempt,
    GoogleSyncReport,
    GoogleSyncStatus,
)
from healthcheck.owner_refresh import (
    OWNER_REFRESH_GOOGLE_HEART_RATE_CONTINUATION_ROUNDS,
    OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_FAMILY,
    OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_QUERY_MODE,
    OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_STREAMS,
    OwnerRefreshBusyError,
    OwnerRefreshLock,
    OwnerRefreshRuntimeError,
    OwnerRefreshStatus,
    _combined_status,
    run_owner_refresh,
)
from healthcheck.runtime import prepare_runtime, resolve_runtime_paths
from healthcheck.source_freshness import Facts


class _FakeGarminAuth:
    def __init__(self, settings, *, is_cn=False):
        self.is_cn = is_cn

    def load_existing(self):
        return object(), SimpleNamespace()


class _FakeGarminSync:
    def __init__(self, settings, *, client, auth_result):
        self.client = client

    def run(self, *, as_of, trailing_window_days):
        return SimpleNamespace(status=GarminSyncStatus.SUCCEEDED, as_of=as_of)


class _FakeGarminTrainingSync:
    def __init__(self, settings, *, client, auth_result):
        self.client = client
        self.auth_result = auth_result

    def run(self, *, start, end):
        return {
            "contract_version": "garmin-training-evidence-v1",
            "status": "succeeded",
            "request_count": 4,
            "readiness_requested_days": 3,
            "status_historical_backfill": False,
            "inserted_count": 2,
            "updated_count": 0,
            "raw_values_emitted": False,
            "private_identifiers_emitted": False,
        }


class _FakeGoogleAuth:
    def __init__(self, settings):
        pass


def _report(status):
    return GoogleSyncReport(
        auth=GoogleAuthResult(status=GoogleAuthStatus.AUTHENTICATED),
        status=status,
        kind=GoogleRunKind.REFRESH,
        window_start="2099-01-04",
        window_end_exclusive="2099-01-11",
        request_count=0,
        query_mode="list",
        data_source_family=None,
        streams=(),
        attempts=(),
    )


def _google_attempt(
    stream: str,
    status: GoogleSyncStatus,
    *,
    page_count: int,
    request_count: int,
    resume_cursor_present: bool = False,
    error: GoogleSafeError | None = None,
    window_start: str = "2099-01-04",
    window_end_exclusive: str = "2099-01-11",
) -> GoogleSyncAttempt:
    return GoogleSyncAttempt(
        stream=stream,
        data_type="heart-rate" if stream == "heart_rate" else stream,
        query_mode="list",
        data_source_family=None,
        window_start=window_start,
        window_end_exclusive=window_end_exclusive,
        status=status,
        coverage_status="present" if status is GoogleSyncStatus.SUCCEEDED else "unknown",
        page_count=page_count,
        request_count=request_count,
        resume_cursor_present=resume_cursor_present,
        error=error,
    )


def _google_report(
    *attempts: GoogleSyncAttempt,
    status: GoogleSyncStatus,
    request_count: int,
    window_start: str | None = None,
    window_end_exclusive: str | None = None,
) -> GoogleSyncReport:
    first = attempts[0] if attempts else None
    return GoogleSyncReport(
        auth=GoogleAuthResult(status=GoogleAuthStatus.AUTHENTICATED),
        status=status,
        kind=GoogleRunKind.REFRESH,
        window_start=window_start or (first.window_start if first else "2099-01-04"),
        window_end_exclusive=window_end_exclusive
        or (first.window_end_exclusive if first else "2099-01-11"),
        request_count=request_count,
        query_mode="list",
        data_source_family=None,
        streams=tuple(item.stream for item in attempts),
        attempts=tuple(attempts),
    )


def _hr_page_ceiling(
    *,
    final: bool = False,
    window_start: str = "2099-01-04",
    window_end_exclusive: str = "2099-01-11",
) -> GoogleSyncAttempt:
    return _google_attempt(
        "heart_rate",
        GoogleSyncStatus.SUCCEEDED if final else GoogleSyncStatus.PARTIAL,
        page_count=4 if final else 40,
        request_count=4 if final else 80,
        resume_cursor_present=not final,
        error=None
        if final
        else GoogleSafeError("budget", "page_ceiling"),
        window_start=window_start,
        window_end_exclusive=window_end_exclusive,
    )


def _established_settings(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    return settings


def _patch_providers(monkeypatch, owner_refresh, *, garmin_cls=_FakeGarminSync, google_fn=None):
    monkeypatch.setattr(owner_refresh, "GarminAuthService", _FakeGarminAuth)
    monkeypatch.setattr(owner_refresh, "GarminIncrementalSync", garmin_cls)
    monkeypatch.setattr(owner_refresh, "GarminTrainingSync", _FakeGarminTrainingSync)
    monkeypatch.setattr(owner_refresh, "GoogleAuthService", _FakeGoogleAuth)
    if google_fn is not None:
        monkeypatch.setattr(owner_refresh, "run_google_refresh", google_fn)


def test_owner_refresh_runs_garmin_and_both_google_layers(monkeypatch, tmp_path):
    import healthcheck.owner_refresh as owner_refresh

    google_calls = []

    def fake_google(settings, **kwargs):
        google_calls.append(kwargs)
        return _report(GoogleSyncStatus.SUCCEEDED)

    _patch_providers(monkeypatch, owner_refresh, google_fn=fake_google)

    report = run_owner_refresh(
        _established_settings(tmp_path),
        as_of="2099-01-10",
        trailing_window_days=7,
        is_cn=True,
        streams=["sleep"],
        query_mode="reconcile",
        data_source_family="any",
    )

    expected_start, expected_end = compute_sync_window(date(2099, 1, 10), 7)
    assert report.status is OwnerRefreshStatus.SUCCEEDED
    assert report.garmin_training["status"] == "succeeded"
    assert report.garmin_training["request_count"] == 4
    assert len(google_calls) == 2

    normal = google_calls[0]
    assert normal["start"] == expected_start
    assert normal["end"] == expected_end
    assert normal["streams"] == ["sleep"]
    assert normal["query_mode"] == "reconcile"
    assert normal["data_source_family"] == "any"

    wearables_sleep = google_calls[1]
    assert wearables_sleep["start"] == expected_start
    assert wearables_sleep["end"] == expected_end
    assert wearables_sleep["streams"] == list(OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_STREAMS)
    assert wearables_sleep["query_mode"] == OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_QUERY_MODE
    assert wearables_sleep["data_source_family"] == OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_FAMILY


@pytest.mark.parametrize("required_sleep_overdue", [True, False])
def test_owner_refresh_projects_freshness_after_layers_without_changing_status(
    monkeypatch, tmp_path, required_sleep_overdue
):
    import healthcheck.owner_refresh as owner_refresh
    import healthcheck.source_freshness_consumer as freshness_consumer

    now = datetime(2099, 1, 10, 12, tzinfo=UTC)
    events = []

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is UTC
            return now

    class OrderedGarmin(_FakeGarminSync):
        def run(self, *, as_of, trailing_window_days):
            events.append("garmin")
            window_start, window_end = compute_sync_window(as_of, trailing_window_days)
            return GarminSyncReport(
                auth=GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED),
                status=GarminSyncStatus.SUCCEEDED,
                as_of=as_of.isoformat(),
                window_start=window_start.isoformat(),
                window_end=window_end.isoformat(),
                trailing_window_days=trailing_window_days,
                request_count=0,
            )

    class OrderedTraining(_FakeGarminTrainingSync):
        def run(self, *, start, end):
            events.append("training")
            return super().run(start=start, end=end)

    def fake_google(settings, **kwargs):
        events.append("google")
        return _report(GoogleSyncStatus.SUCCEEDED)

    def fake_read_facts(_session, scope, **kwargs):
        events.append("freshness")
        assert kwargs["evaluation_local_date"] == date(2099, 1, 10)
        recent = now - timedelta(hours=1)
        if scope.key == "garmin:sleep" and required_sleep_overdue:
            successful = now - timedelta(hours=49)
            return Facts(
                last_attempt_at_utc=successful,
                last_success_at_utc=successful,
                evidence_at_utc=now - timedelta(hours=73),
                observed_once=True,
            )
        if scope.family == "weight":
            return Facts(confirmed_weight=True, observed_once=True)
        if scope.family == "activity":
            return Facts(
                last_attempt_at_utc=recent,
                last_success_at_utc=recent,
                coverage="complete",
                activity_count=0,
            )
        return Facts(
            last_attempt_at_utc=recent,
            last_success_at_utc=recent,
            evidence_at_utc=recent,
            observed_once=True,
        )

    monkeypatch.setattr(owner_refresh, "datetime", FrozenDateTime)
    monkeypatch.setattr(freshness_consumer, "read_facts", fake_read_facts)
    _patch_providers(monkeypatch, owner_refresh, garmin_cls=OrderedGarmin, google_fn=fake_google)
    monkeypatch.setattr(owner_refresh, "GarminTrainingSync", OrderedTraining)

    report = run_owner_refresh(
        _established_settings(tmp_path),
        as_of="2099-01-10",
        trailing_window_days=7,
        streams=["sleep"],
    )

    assert report.status is OwnerRefreshStatus.SUCCEEDED
    assert events[:4] == ["garmin", "training", "google", "google"]
    assert all(event == "freshness" for event in events[4:]), events
    if required_sleep_overdue:
        assert report.freshness["owner"]["actionable_items"] == [
            {
                "scope_key": "garmin:sleep",
                "state": "stale",
                "reason_code": "refresh_overdue",
            }
        ]
        assert report.freshness["owner"]["state"] == "stale"
    else:
        assert report.freshness["owner"]["state"] == "fresh"
        assert report.freshness["owner"]["actionable_items"] == []
    payload = report.to_json()
    assert now.isoformat() not in payload
    assert report.as_dict()["privacy"]["health_timestamps_emitted"] is False


@pytest.mark.parametrize(
    ("garmin_status", "google_status", "expected_status"),
    [
        (
            GarminSyncStatus.SUCCEEDED,
            GoogleSyncStatus.SUCCEEDED,
            OwnerRefreshStatus.SUCCEEDED,
        ),
        (
            GarminSyncStatus.PARTIAL,
            GoogleSyncStatus.SUCCEEDED,
            OwnerRefreshStatus.PARTIAL,
        ),
        (
            GarminSyncStatus.SUCCEEDED,
            GoogleSyncStatus.REAUTH_REQUIRED,
            OwnerRefreshStatus.REAUTH_REQUIRED,
        ),
    ],
)
def test_owner_refresh_freshness_failure_preserves_operational_status(
    monkeypatch, tmp_path, garmin_status, google_status, expected_status
):
    import healthcheck.owner_refresh as owner_refresh

    events = []

    class StatusGarmin(_FakeGarminSync):
        def run(self, *, as_of, trailing_window_days):
            events.append("garmin")
            window_start, window_end = compute_sync_window(as_of, trailing_window_days)
            return GarminSyncReport(
                auth=GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED),
                status=garmin_status,
                as_of=as_of.isoformat(),
                window_start=window_start.isoformat(),
                window_end=window_end.isoformat(),
                trailing_window_days=trailing_window_days,
                request_count=0,
            )

    class OrderedTraining(_FakeGarminTrainingSync):
        def run(self, *, start, end):
            events.append("training")
            return super().run(start=start, end=end)

    def fake_google(settings, **kwargs):
        events.append("google")
        return _report(google_status)

    def fail_freshness_read(*args, **kwargs):
        events.append("freshness")
        raise SQLAlchemyError("SELECT private-marker-193 from C:\\private\\health.db value=123kg")

    _patch_providers(monkeypatch, owner_refresh, garmin_cls=StatusGarmin, google_fn=fake_google)
    monkeypatch.setattr(owner_refresh, "GarminTrainingSync", OrderedTraining)
    monkeypatch.setattr(
        owner_refresh,
        "read_consumer_freshness_projection_from_database",
        fail_freshness_read,
    )

    report = run_owner_refresh(
        _established_settings(tmp_path),
        as_of="2099-01-10",
        trailing_window_days=7,
        streams=["sleep"],
    )

    expected_freshness = {
        "policy_version": "source-freshness-v1",
        "state": "unavailable",
        "reason_code": "freshness_evaluation_failed",
    }
    assert events == ["garmin", "training", "google", "google", "freshness"]
    assert report.status is expected_status
    assert report.freshness == expected_freshness
    payload = report.to_json()
    assert all(
        secret not in payload
        for secret in ("private-marker-193", "C:\\private\\health.db", "123kg", "SELECT")
    )


def test_cli_owner_refresh_keeps_success_report_when_freshness_fails(
    monkeypatch, tmp_path, capsys
):
    import healthcheck.owner_refresh as owner_refresh

    class SerializableGarmin(_FakeGarminSync):
        def run(self, *, as_of, trailing_window_days):
            window_start, window_end = compute_sync_window(as_of, trailing_window_days)
            return GarminSyncReport(
                auth=GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED),
                status=GarminSyncStatus.SUCCEEDED,
                as_of=as_of.isoformat(),
                window_start=window_start.isoformat(),
                window_end=window_end.isoformat(),
                trailing_window_days=trailing_window_days,
                request_count=0,
            )

    def fake_google(settings, **kwargs):
        return _report(GoogleSyncStatus.SUCCEEDED)

    def fail_freshness_read(*args, **kwargs):
        raise SQLAlchemyError("private-marker-193 C:\\private\\health.db SELECT 123kg")

    settings = _established_settings(tmp_path)
    _patch_providers(
        monkeypatch, owner_refresh, garmin_cls=SerializableGarmin, google_fn=fake_google
    )
    monkeypatch.setattr(
        owner_refresh,
        "read_consumer_freshness_projection_from_database",
        fail_freshness_read,
    )

    code = cli.main(
        [
            "owner-refresh",
            "--data-dir",
            str(settings.data_dir),
            "--date",
            "2099-01-10",
            "--trailing-window-days",
            "7",
        ]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert code == 0
    assert payload["refresh"]["status"] == "succeeded"
    assert payload["freshness"] == {
        "policy_version": "source-freshness-v1",
        "state": "unavailable",
        "reason_code": "freshness_evaluation_failed",
    }
    assert "error" not in payload
    assert all(
        secret not in output
        for secret in ("private-marker-193", "C:\\private\\health.db", "123kg", "SELECT")
    )


def test_owner_refresh_reuses_garmin_auth_and_training_uses_exact_window_and_order(
    monkeypatch, tmp_path
):
    import healthcheck.owner_refresh as owner_refresh

    events = []
    expected_auth_result = object()
    expected_client = object()

    class CountingAuth:
        def __init__(self, settings, *, is_cn=False):
            pass

        def load_existing(self):
            events.append("auth")
            return expected_client, expected_auth_result

    class CountingGarmin(_FakeGarminSync):
        def __init__(self, settings, *, client, auth_result):
            super().__init__(settings, client=client, auth_result=auth_result)

        def run(self, *, as_of, trailing_window_days):
            events.append("garmin")
            return SimpleNamespace(status=GarminSyncStatus.SUCCEEDED, as_of=as_of)

    class CountingTraining:
        def __init__(self, settings, *, client: object, auth_result: object):
            assert client is expected_client
            assert auth_result is expected_auth_result

        def run(self, *, start, end):
            events.append(("training", start, end))
            return _FakeGarminTrainingSync(
                None, client=expected_client, auth_result=expected_auth_result
            ).run(
                start=start, end=end
            )

    def fake_google(settings, **kwargs):
        events.append("google")
        return _report(GoogleSyncStatus.SUCCEEDED)

    monkeypatch.setattr(owner_refresh, "GarminAuthService", CountingAuth)
    monkeypatch.setattr(owner_refresh, "GarminIncrementalSync", CountingGarmin)
    monkeypatch.setattr(owner_refresh, "GarminTrainingSync", CountingTraining)
    monkeypatch.setattr(owner_refresh, "GoogleAuthService", _FakeGoogleAuth)
    monkeypatch.setattr(owner_refresh, "run_google_refresh", fake_google)

    report = run_owner_refresh(
        _established_settings(tmp_path),
        as_of="2099-01-10",
        trailing_window_days=7,
        streams=["sleep"],
    )

    expected_start, expected_end = compute_sync_window(date(2099, 1, 10), 7)
    assert events == [
        "auth",
        "garmin",
        ("training", expected_start, expected_end),
        "google",
        "google",
    ]
    assert report.garmin_training["status"] == "succeeded"


def test_owner_refresh_surfaces_training_partial_and_filters_report(monkeypatch, tmp_path):
    import healthcheck.owner_refresh as owner_refresh

    class PartialTraining:
        def __init__(self, settings, *, client, auth_result):
            pass

        def run(self, *, start, end):
            return {
                "status": "partial",
                "request_count": 3,
                "inserted_count": 1,
                "raw_payload": "private-provider-payload",
                "provider_id": "private-provider-id",
            }

    _patch_providers(monkeypatch, owner_refresh)
    monkeypatch.setattr(owner_refresh, "GarminTrainingSync", PartialTraining)
    monkeypatch.setattr(
        owner_refresh,
        "run_google_refresh",
        lambda settings, **kwargs: _report(GoogleSyncStatus.SUCCEEDED),
    )

    report = run_owner_refresh(
        _established_settings(tmp_path), as_of="2099-01-10", trailing_window_days=7
    )

    assert report.status is OwnerRefreshStatus.PARTIAL
    assert report.garmin_training["status"] == "partial"
    assert report.garmin_training["request_count"] == 3
    assert "raw_payload" not in report.garmin_training
    assert "provider_id" not in report.garmin_training
    assert "private-provider" not in json.dumps(report.garmin_training)


def test_owner_refresh_combines_training_failure_and_reauth_without_hiding_them():
    assert (
        _combined_status(
            GarminSyncStatus.SUCCEEDED,
            "partial",
            GoogleSyncStatus.SUCCEEDED,
            GoogleSyncStatus.SUCCEEDED,
        )
        is OwnerRefreshStatus.PARTIAL
    )
    assert (
        _combined_status(
            GarminSyncStatus.SUCCEEDED,
            "reauth_required",
            GoogleSyncStatus.SUCCEEDED,
            GoogleSyncStatus.SUCCEEDED,
        )
        is OwnerRefreshStatus.REAUTH_REQUIRED
    )
    assert (
        _combined_status(
            GarminSyncStatus.FAILED,
            "failed",
            GoogleSyncStatus.FAILED,
            GoogleSyncStatus.FAILED,
        )
        is OwnerRefreshStatus.FAILED
    )


def test_owner_refresh_selection_runs_fixed_wearables_sleep_without_cli_family(
    monkeypatch, tmp_path
):
    import healthcheck.owner_refresh as owner_refresh

    google_calls = []

    def fake_google(settings, **kwargs):
        google_calls.append(kwargs)
        return _report(GoogleSyncStatus.EMPTY)

    _patch_providers(monkeypatch, owner_refresh, google_fn=fake_google)

    report = run_owner_refresh(
        _established_settings(tmp_path), as_of="2099-01-10", streams=["sleep"]
    )
    assert report.status is OwnerRefreshStatus.SUCCEEDED
    assert len(google_calls) == 2
    assert google_calls[0]["query_mode"] is None
    assert google_calls[0]["data_source_family"] is None
    assert google_calls[0]["streams"] == ["sleep"]
    assert google_calls[1]["streams"] == ["sleep"]
    assert google_calls[1]["query_mode"] == "reconcile"
    assert google_calls[1]["data_source_family"] == "google-wearables"


def test_owner_refresh_does_not_partition_non_list_heart_rate(monkeypatch, tmp_path):
    import healthcheck.owner_refresh as owner_refresh

    google_calls = []

    def fake_google(settings, **kwargs):
        google_calls.append(kwargs)
        return _report(GoogleSyncStatus.SUCCEEDED)

    _patch_providers(monkeypatch, owner_refresh, google_fn=fake_google)
    report = run_owner_refresh(
        _established_settings(tmp_path),
        as_of="2099-01-10",
        trailing_window_days=3,
        streams=["heart_rate"],
        query_mode="reconcile",
    )

    assert report.status is OwnerRefreshStatus.SUCCEEDED
    assert len(google_calls) == 2
    normal = google_calls[0]
    assert normal["streams"] == ["heart_rate"]
    assert normal["query_mode"] == "reconcile"
    assert "checkpoint_partition" not in normal


def test_owner_refresh_converges_dense_hr_without_repeating_unrelated_layers(
    monkeypatch, tmp_path
):
    import healthcheck.owner_refresh as owner_refresh

    calls = []
    garmin_calls = []

    class CountingGarmin(_FakeGarminSync):
        def run(self, *, as_of, trailing_window_days):
            garmin_calls.append((as_of, trailing_window_days))
            return super().run(as_of=as_of, trailing_window_days=trailing_window_days)

    day_calls: dict[str, int] = {}

    def fake_google(settings, **kwargs):
        calls.append(kwargs)
        if kwargs.get("data_source_family") == OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_FAMILY:
            return _report(GoogleSyncStatus.EMPTY)
        partition = kwargs.get("checkpoint_partition")
        if partition is None:
            attempts = tuple(
                _google_attempt(
                    stream,
                    GoogleSyncStatus.SUCCEEDED,
                    page_count=1,
                    request_count=1,
                )
                for stream in kwargs["streams"]
            )
            return _google_report(
                *attempts,
                status=GoogleSyncStatus.SUCCEEDED,
                request_count=len(attempts),
            )
        day_calls[partition] = day_calls.get(partition, 0) + 1
        end_exclusive = date.fromisoformat(partition) + timedelta(days=1)
        needs_resume = partition == "2099-01-10" and day_calls[partition] == 1
        attempt = _hr_page_ceiling(
            final=not needs_resume,
            window_start=partition,
            window_end_exclusive=end_exclusive.isoformat(),
        )
        return _google_report(
            attempt,
            status=(
                GoogleSyncStatus.PARTIAL
                if needs_resume
                else GoogleSyncStatus.SUCCEEDED
            ),
            request_count=80 if needs_resume else 4,
        )

    _patch_providers(
        monkeypatch,
        owner_refresh,
        garmin_cls=CountingGarmin,
        google_fn=fake_google,
    )
    report = run_owner_refresh(
        _established_settings(tmp_path),
        as_of="2099-01-10",
        trailing_window_days=3,
    )

    assert report.status is OwnerRefreshStatus.SUCCEEDED
    assert len(garmin_calls) == 1
    assert len(calls) == 6
    assert calls[0]["streams"] == [
        "sleep",
        "hrv",
        "daily_hrv",
        "daily_resting_hr",
        "spo2",
        "daily_spo2",
        "respiratory_rate_sleep",
        "daily_respiratory_rate",
    ]
    heart_rate_calls = [item for item in calls if item["streams"] == ["heart_rate"]]
    assert [item["checkpoint_partition"] for item in heart_rate_calls] == [
        "2099-01-10",
        "2099-01-10",
        "2099-01-09",
        "2099-01-08",
    ]
    assert all(item["start"] == item["end"] for item in heart_rate_calls)
    assert all(item["query_mode"] is None for item in heart_rate_calls)
    assert all(item["data_source_family"] is None for item in heart_rate_calls)
    assert calls[-1]["streams"] == list(OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_STREAMS)
    assert report.google.status is GoogleSyncStatus.SUCCEEDED
    hr_attempts = [item for item in report.google.attempts if item.stream == "heart_rate"]
    assert [item.window_start for item in hr_attempts] == [
        "2099-01-10",
        "2099-01-09",
        "2099-01-08",
    ]
    assert all(item.status is GoogleSyncStatus.SUCCEEDED for item in hr_attempts)


def test_owner_refresh_dense_hr_stops_at_fixed_continuation_bound(monkeypatch, tmp_path):
    import healthcheck.owner_refresh as owner_refresh

    calls = []

    def fake_google(settings, **kwargs):
        calls.append(kwargs)
        if kwargs.get("data_source_family") == OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_FAMILY:
            return _report(GoogleSyncStatus.EMPTY)
        attempt = _hr_page_ceiling(
            window_start="2099-01-10", window_end_exclusive="2099-01-11"
        )
        return _google_report(
            attempt, status=GoogleSyncStatus.PARTIAL, request_count=80
        )

    _patch_providers(monkeypatch, owner_refresh, google_fn=fake_google)
    report = run_owner_refresh(
        _established_settings(tmp_path),
        as_of="2099-01-10",
        trailing_window_days=3,
        streams=["heart_rate"],
    )

    assert report.status is OwnerRefreshStatus.PARTIAL
    assert len(calls) == OWNER_REFRESH_GOOGLE_HEART_RATE_CONTINUATION_ROUNDS + 2
    assert {item.get("checkpoint_partition") for item in calls[:-1]} == {"2099-01-10"}
    assert calls[-1]["streams"] == list(OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_STREAMS)
    assert report.google.status is GoogleSyncStatus.PARTIAL
    assert report.google.request_count == 240
    assert report.google.attempts[0].resume_cursor_present is True
    assert [item.status for item in report.google.attempts[1:]] == [
        GoogleSyncStatus.NOT_RUN,
        GoogleSyncStatus.NOT_RUN,
    ]
    assert all(
        item.coverage_status is None and item.not_run_reason == "previous_day_incomplete"
        for item in report.google.attempts[1:]
    )


def test_owner_refresh_propagates_continuation_reauth_with_no_attempt(monkeypatch, tmp_path):
    import healthcheck.owner_refresh as owner_refresh

    calls = []
    reports = [
        _google_report(
            _hr_page_ceiling(
                window_start="2099-01-10", window_end_exclusive="2099-01-11"
            ),
            status=GoogleSyncStatus.PARTIAL,
            request_count=80,
        ),
        GoogleSyncReport(
            auth=GoogleAuthResult(status=GoogleAuthStatus.REAUTH_REQUIRED),
            status=GoogleSyncStatus.REAUTH_REQUIRED,
            kind=GoogleRunKind.REFRESH,
            window_start="2099-01-10",
            window_end_exclusive="2099-01-11",
            request_count=0,
            query_mode="list",
            data_source_family=None,
            streams=("heart_rate",),
            abort_reason="reauth_required",
        ),
        _report(GoogleSyncStatus.EMPTY),
    ]

    def fake_google(settings, **kwargs):
        calls.append(kwargs)
        return reports.pop(0)

    _patch_providers(monkeypatch, owner_refresh, google_fn=fake_google)
    report = run_owner_refresh(
        _established_settings(tmp_path),
        as_of="2099-01-10",
        trailing_window_days=2,
        streams=["heart_rate"],
    )

    assert report.status is OwnerRefreshStatus.REAUTH_REQUIRED
    assert report.google.status is GoogleSyncStatus.REAUTH_REQUIRED
    assert report.google.request_count == 80
    assert report.google.abort_reason == "reauth_required"
    assert len(calls) == 3
    assert calls[1]["streams"] == ["heart_rate"]
    assert calls[2]["streams"] == list(OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_STREAMS)


def test_owner_refresh_exact_rerun_repeats_only_bounded_google_layers(monkeypatch, tmp_path):
    import healthcheck.owner_refresh as owner_refresh

    calls = []

    def fake_google(settings, **kwargs):
        calls.append(kwargs)
        if kwargs.get("data_source_family") == OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_FAMILY:
            return _report(GoogleSyncStatus.EMPTY)
        if kwargs.get("streams") == ["heart_rate"]:
            is_final = sum(item.get("streams") == ["heart_rate"] for item in calls) % 2 == 0
            partition = kwargs["checkpoint_partition"]
            end_exclusive = date.fromisoformat(partition) + timedelta(days=1)
            return _google_report(
                _hr_page_ceiling(
                    final=is_final,
                    window_start=partition,
                    window_end_exclusive=end_exclusive.isoformat(),
                ),
                status=GoogleSyncStatus.SUCCEEDED if is_final else GoogleSyncStatus.PARTIAL,
                request_count=4 if is_final else 80,
            )
        raise AssertionError("unexpected normal Google refresh call")

    _patch_providers(monkeypatch, owner_refresh, google_fn=fake_google)
    settings = _established_settings(tmp_path)
    first = run_owner_refresh(
        settings, as_of="2099-01-10", trailing_window_days=1, streams=["heart_rate"]
    )
    second = run_owner_refresh(
        settings, as_of="2099-01-10", trailing_window_days=1, streams=["heart_rate"]
    )

    assert first.status is OwnerRefreshStatus.SUCCEEDED
    assert second.status is OwnerRefreshStatus.SUCCEEDED
    assert first.google.request_count == second.google.request_count == 84
    assert len(first.google.attempts) == len(second.google.attempts) == 1
    assert len(calls) == 6
    assert all("chunk_days" not in call and "reprocess" not in call for call in calls)


def test_owner_refresh_is_partial_when_one_provider_is_partial(monkeypatch, tmp_path):
    import healthcheck.owner_refresh as owner_refresh

    class PartialGarmin(_FakeGarminSync):
        def run(self, *, as_of, trailing_window_days):
            return SimpleNamespace(status=GarminSyncStatus.PARTIAL)

    _patch_providers(
        monkeypatch,
        owner_refresh,
        garmin_cls=PartialGarmin,
        google_fn=lambda settings, **kwargs: _report(GoogleSyncStatus.SUCCEEDED),
    )

    report = run_owner_refresh(
        _established_settings(tmp_path), as_of="2099-01-10", streams=["sleep"]
    )
    assert report.status is OwnerRefreshStatus.PARTIAL


@pytest.mark.parametrize(
    ("garmin", "google", "wearables_sleep", "expected"),
    [
        (
            GarminSyncStatus.EMPTY,
            GoogleSyncStatus.EMPTY,
            GoogleSyncStatus.EMPTY,
            OwnerRefreshStatus.SUCCEEDED,
        ),
        (
            GarminSyncStatus.SUCCEEDED,
            GoogleSyncStatus.SUCCEEDED,
            GoogleSyncStatus.SUCCEEDED,
            OwnerRefreshStatus.SUCCEEDED,
        ),
        (
            GarminSyncStatus.FAILED,
            GoogleSyncStatus.SUCCEEDED,
            GoogleSyncStatus.SUCCEEDED,
            OwnerRefreshStatus.PARTIAL,
        ),
        (
            GarminSyncStatus.SUCCEEDED,
            GoogleSyncStatus.FAILED,
            GoogleSyncStatus.SUCCEEDED,
            OwnerRefreshStatus.PARTIAL,
        ),
        (
            GarminSyncStatus.SUCCEEDED,
            GoogleSyncStatus.SUCCEEDED,
            GoogleSyncStatus.FAILED,
            OwnerRefreshStatus.PARTIAL,
        ),
        (
            GarminSyncStatus.FAILED,
            GoogleSyncStatus.FAILED,
            GoogleSyncStatus.FAILED,
            OwnerRefreshStatus.FAILED,
        ),
        (
            GarminSyncStatus.REAUTH_REQUIRED,
            GoogleSyncStatus.SUCCEEDED,
            GoogleSyncStatus.SUCCEEDED,
            OwnerRefreshStatus.REAUTH_REQUIRED,
        ),
        (
            GarminSyncStatus.SUCCEEDED,
            GoogleSyncStatus.REAUTH_REQUIRED,
            GoogleSyncStatus.SUCCEEDED,
            OwnerRefreshStatus.REAUTH_REQUIRED,
        ),
        (
            GarminSyncStatus.SUCCEEDED,
            GoogleSyncStatus.SUCCEEDED,
            GoogleSyncStatus.REAUTH_REQUIRED,
            OwnerRefreshStatus.REAUTH_REQUIRED,
        ),
        (
            GarminSyncStatus.REAUTH_REQUIRED,
            GoogleSyncStatus.FAILED,
            GoogleSyncStatus.EMPTY,
            OwnerRefreshStatus.REAUTH_REQUIRED,
        ),
    ],
)
def test_owner_refresh_combines_empty_failed_and_reauth_outcomes(
    garmin, google, wearables_sleep, expected
):
    assert _combined_status(garmin, google, wearables_sleep) is expected


def test_owner_refresh_one_google_layer_failure_is_honest_partial(monkeypatch, tmp_path):
    import healthcheck.owner_refresh as owner_refresh

    def fake_google(settings, **kwargs):
        if kwargs.get("data_source_family") == OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_FAMILY:
            return _report(GoogleSyncStatus.FAILED)
        return _report(GoogleSyncStatus.SUCCEEDED)

    _patch_providers(monkeypatch, owner_refresh, google_fn=fake_google)

    report = run_owner_refresh(
        _established_settings(tmp_path), as_of="2099-01-10", streams=["sleep"]
    )
    assert report.status is OwnerRefreshStatus.PARTIAL
    assert report.google.status is GoogleSyncStatus.SUCCEEDED
    assert report.google_wearables_sleep.status is GoogleSyncStatus.FAILED


def test_owner_refresh_exact_rerun_converges_when_layers_report_empty(monkeypatch, tmp_path):
    import healthcheck.owner_refresh as owner_refresh

    call_counts = {"google": 0}

    def fake_google(settings, **kwargs):
        call_counts["google"] += 1
        return _report(GoogleSyncStatus.EMPTY)

    class EmptyGarmin(_FakeGarminSync):
        def run(self, *, as_of, trailing_window_days):
            return SimpleNamespace(status=GarminSyncStatus.EMPTY, as_of=as_of)

    _patch_providers(monkeypatch, owner_refresh, garmin_cls=EmptyGarmin, google_fn=fake_google)
    settings = _established_settings(tmp_path)

    first = run_owner_refresh(
        settings, as_of="2099-01-10", trailing_window_days=7, streams=["sleep"]
    )
    second = run_owner_refresh(
        settings, as_of="2099-01-10", trailing_window_days=7, streams=["sleep"]
    )

    assert first.status is OwnerRefreshStatus.SUCCEEDED
    assert second.status is OwnerRefreshStatus.SUCCEEDED
    assert call_counts["google"] == 4
    assert first.window_start == second.window_start
    assert first.window_end == second.window_end


def test_owner_refresh_empty_report_is_privacy_safe():
    garmin = GarminSyncReport(
        auth=GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED),
        status=GarminSyncStatus.EMPTY,
        as_of="2099-01-10",
        window_start="2099-01-04",
        window_end="2099-01-10",
        trailing_window_days=7,
        request_count=0,
    )
    google = GoogleSyncReport(
        auth=GoogleAuthResult(status=GoogleAuthStatus.AUTHENTICATED),
        status=GoogleSyncStatus.EMPTY,
        kind=GoogleRunKind.REFRESH,
        window_start="2099-01-04",
        window_end_exclusive="2099-01-11",
        request_count=0,
        query_mode="list",
        data_source_family=None,
        streams=("sleep",),
    )
    wearables_sleep = GoogleSyncReport(
        auth=GoogleAuthResult(status=GoogleAuthStatus.AUTHENTICATED),
        status=GoogleSyncStatus.EMPTY,
        kind=GoogleRunKind.REFRESH,
        window_start="2099-01-04",
        window_end_exclusive="2099-01-11",
        request_count=0,
        query_mode="reconcile",
        data_source_family="users/me/dataSourceFamilies/google-wearables",
        streams=("sleep",),
    )
    from healthcheck.owner_refresh import OwnerRefreshReport

    payload = OwnerRefreshReport(
        status=OwnerRefreshStatus.SUCCEEDED,
        as_of="2099-01-10",
        window_start="2099-01-04",
        window_end="2099-01-10",
        trailing_window_days=7,
        garmin=garmin,
        garmin_training={
            "contract_version": "garmin-training-evidence-v1",
            "status": "succeeded",
            "raw_values_emitted": False,
            "private_identifiers_emitted": False,
        },
        google=google,
        google_wearables_sleep=wearables_sleep,
        freshness={
            "policy_version": "source-freshness-v1",
            "owner": {"state": "not_requested", "actionable_items": []},
            "providers": {
                "garmin": {"state": "not_requested"},
                "google": {"state": "not_requested"},
            },
            "optional_details": [],
        },
    ).to_json()
    decoded = json.loads(payload)
    assert decoded["refresh"]["status"] == "succeeded"
    assert decoded["garmin"]["sync"]["status"] == "empty"
    assert decoded["garmin_training"]["status"] == "succeeded"
    assert decoded["garmin_training"]["raw_values_emitted"] is False
    assert decoded["google"]["sync"]["status"] == "empty"
    assert decoded["google_wearables_sleep"]["sync"]["status"] == "empty"
    assert decoded["google_wearables_sleep"]["sync"]["query_mode"] == "reconcile"
    assert decoded["privacy"]["raw_values_emitted"] is False
    assert decoded["privacy"]["private_identifiers_emitted"] is False
    assert all(
        secret not in payload for secret in ("access_token", "refresh_token", "secret-token")
    )


def test_owner_refresh_fails_closed_for_missing_runtime(tmp_path):
    runtime = tmp_path / "typo-runtime"

    with pytest.raises(OwnerRefreshRuntimeError) as exc_info:
        run_owner_refresh(Settings(data_dir=runtime), as_of="2099-01-10")

    assert exc_info.value.error_code == "runtime_missing"
    assert not runtime.exists()


def test_owner_refresh_fails_closed_for_unestablished_runtime(tmp_path):
    runtime = tmp_path / "unestablished-runtime"
    runtime.mkdir()

    with pytest.raises(OwnerRefreshRuntimeError) as exc_info:
        run_owner_refresh(Settings(data_dir=runtime), as_of="2099-01-10")

    assert exc_info.value.error_code == "runtime_not_established"
    assert not (runtime / "healthcheck.db").exists()
    assert not (runtime / "config.toml").exists()


def test_owner_refresh_rejects_same_profile_overlap(monkeypatch, tmp_path):
    import healthcheck.owner_refresh as owner_refresh

    settings = _established_settings(tmp_path)
    paths = resolve_runtime_paths(settings)
    monkeypatch.setattr(owner_refresh, "GarminAuthService", _FakeGarminAuth)

    with OwnerRefreshLock(paths):
        with pytest.raises(OwnerRefreshBusyError):
            run_owner_refresh(settings, as_of="2099-01-10")


def test_cli_owner_refresh_reports_missing_runtime_without_bootstrap(tmp_path, capsys):
    runtime = tmp_path / "missing-runtime"
    code = cli.main(
        [
            "owner-refresh",
            "--data-dir",
            str(runtime),
            "--date",
            "2099-01-10",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["error"] == {
        "error_class": "runtime",
        "error_code": "runtime_missing",
        "http_status": None,
    }
    assert payload["privacy"]["tokens_emitted"] is False
    assert not runtime.exists()


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--start", "2099-01-01", "--end", "2099-01-02"],
        ["--dry-run"],
        ["--reprocess"],
        ["--max-observations", "1"],
        ["--chunk-days", "1"],
    ],
)
def test_cli_owner_refresh_never_routes_to_backfill_or_reprocess(
    monkeypatch, tmp_path, capsys, extra_args
):
    monkeypatch.setattr(
        cli,
        "run_owner_refresh",
        lambda *args, **kwargs: pytest.fail("bounded owner-refresh runner was invoked"),
    )
    code = cli.main(
        [
            "owner-refresh",
            "--data-dir",
            str(tmp_path / "runtime"),
            *extra_args,
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["error"]["error_code"] == "invalid_refresh_request"


def test_cli_owner_refresh_rejects_unbounded_google_window(tmp_path, capsys):
    code = cli.main(
        [
            "owner-refresh",
            "--data-dir",
            str(tmp_path / "runtime"),
            "--start",
            "2099-01-01",
            "--end",
            "2099-01-02",
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    payload = json.loads(captured.out)
    assert payload["error"]["error_code"] == "invalid_refresh_request"
    assert payload["privacy"]["tokens_emitted"] is False


@pytest.mark.parametrize("days", [0, 15])
def test_cli_owner_refresh_rejects_out_of_bound_window(tmp_path, capsys, days):
    settings = _established_settings(tmp_path)
    code = cli.main(
        [
            "owner-refresh",
            "--data-dir",
            str(settings.data_dir),
            "--date",
            "2099-01-10",
            "--trailing-window-days",
            str(days),
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    payload = json.loads(captured.out)
    assert payload["error"]["error_code"] == "invalid_refresh_request"
