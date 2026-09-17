"""Synthetic tests for the bounded owner Garmin + Google refresh command."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from healthcheck import cli
from healthcheck.config import Settings
from healthcheck.garmin.sync import (
    GarminSyncStatus,
    compute_sync_window,
)
from healthcheck.google.sync import GoogleSyncStatus
from healthcheck.owner_refresh import OwnerRefreshStatus, run_owner_refresh


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


def test_owner_refresh_uses_one_bounded_window_for_both_providers(monkeypatch):
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
        Settings(data_dir="synthetic-runtime"),
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


def test_owner_refresh_is_partial_when_one_provider_is_partial(monkeypatch):
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

    report = run_owner_refresh(Settings(data_dir="synthetic-runtime"), as_of="2099-01-10")
    assert report.status is OwnerRefreshStatus.PARTIAL


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
    code = cli.main(
        [
            "owner-refresh",
            "--data-dir",
            str(tmp_path / "runtime"),
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
