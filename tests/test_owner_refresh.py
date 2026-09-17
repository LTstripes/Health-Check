"""Synthetic tests for the bounded owner Garmin + Google refresh command."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from healthcheck import cli
from healthcheck.config import Settings
from healthcheck.db.engine import migrate_database
from healthcheck.garmin.auth import GarminAuthResult, GarminAuthStatus
from healthcheck.garmin.sync import (
    GarminSyncReport,
    GarminSyncStatus,
    compute_sync_window,
)
from healthcheck.google.auth import GoogleAuthResult, GoogleAuthStatus
from healthcheck.google.sync import GoogleRunKind, GoogleSyncReport, GoogleSyncStatus
from healthcheck.owner_refresh import (
    OwnerRefreshBusyError,
    OwnerRefreshLock,
    OwnerRefreshRuntimeError,
    OwnerRefreshStatus,
    _combined_status,
    run_owner_refresh,
)
from healthcheck.runtime import prepare_runtime, resolve_runtime_paths


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


class _FakeGoogleAuth:
    def __init__(self, settings):
        pass


def _report(status):
    return SimpleNamespace(
        status=status,
        as_dict=lambda: {"sync": {"status": status.value}},
    )


def _established_settings(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    return settings


def test_owner_refresh_uses_one_bounded_window_for_both_providers(monkeypatch, tmp_path):
    import healthcheck.owner_refresh as owner_refresh

    google_call = {}

    def fake_google(settings, **kwargs):
        google_call.update(kwargs)
        return _report(GoogleSyncStatus.SUCCEEDED)

    monkeypatch.setattr(owner_refresh, "GarminAuthService", _FakeGarminAuth)
    monkeypatch.setattr(owner_refresh, "GarminIncrementalSync", _FakeGarminSync)
    monkeypatch.setattr(owner_refresh, "GoogleAuthService", _FakeGoogleAuth)
    monkeypatch.setattr(owner_refresh, "run_google_refresh", fake_google)

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
    assert google_call["start"] == expected_start
    assert google_call["end"] == expected_end
    assert google_call["streams"] == ["sleep"]
    assert google_call["query_mode"] == "reconcile"
    assert google_call["data_source_family"] == "any"


def test_owner_refresh_is_partial_when_one_provider_is_partial(monkeypatch, tmp_path):
    import healthcheck.owner_refresh as owner_refresh

    class PartialGarmin(_FakeGarminSync):
        def run(self, *, as_of, trailing_window_days):
            return SimpleNamespace(status=GarminSyncStatus.PARTIAL)

    monkeypatch.setattr(owner_refresh, "GarminAuthService", _FakeGarminAuth)
    monkeypatch.setattr(owner_refresh, "GarminIncrementalSync", PartialGarmin)
    monkeypatch.setattr(owner_refresh, "GoogleAuthService", _FakeGoogleAuth)
    monkeypatch.setattr(
        owner_refresh,
        "run_google_refresh",
        lambda settings, **kwargs: _report(GoogleSyncStatus.SUCCEEDED),
    )

    report = run_owner_refresh(_established_settings(tmp_path), as_of="2099-01-10")
    assert report.status is OwnerRefreshStatus.PARTIAL


@pytest.mark.parametrize(
    ("garmin", "google", "expected"),
    [
        (GarminSyncStatus.EMPTY, GoogleSyncStatus.EMPTY, OwnerRefreshStatus.SUCCEEDED),
        (GarminSyncStatus.FAILED, GoogleSyncStatus.SUCCEEDED, OwnerRefreshStatus.PARTIAL),
        (GarminSyncStatus.SUCCEEDED, GoogleSyncStatus.FAILED, OwnerRefreshStatus.PARTIAL),
        (GarminSyncStatus.FAILED, GoogleSyncStatus.FAILED, OwnerRefreshStatus.FAILED),
        (
            GarminSyncStatus.REAUTH_REQUIRED,
            GoogleSyncStatus.SUCCEEDED,
            OwnerRefreshStatus.REAUTH_REQUIRED,
        ),
        (
            GarminSyncStatus.SUCCEEDED,
            GoogleSyncStatus.REAUTH_REQUIRED,
            OwnerRefreshStatus.REAUTH_REQUIRED,
        ),
        (
            GarminSyncStatus.REAUTH_REQUIRED,
            GoogleSyncStatus.FAILED,
            OwnerRefreshStatus.REAUTH_REQUIRED,
        ),
    ],
)
def test_owner_refresh_combines_empty_failed_and_reauth_outcomes(garmin, google, expected):
    assert _combined_status(garmin, google) is expected


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
    from healthcheck.owner_refresh import OwnerRefreshReport

    payload = OwnerRefreshReport(
        status=OwnerRefreshStatus.SUCCEEDED,
        as_of="2099-01-10",
        window_start="2099-01-04",
        window_end="2099-01-10",
        trailing_window_days=7,
        garmin=garmin,
        google=google,
    ).to_json()
    decoded = json.loads(payload)
    assert decoded["refresh"]["status"] == "succeeded"
    assert decoded["garmin"]["sync"]["status"] == "empty"
    assert decoded["google"]["sync"]["status"] == "empty"
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
