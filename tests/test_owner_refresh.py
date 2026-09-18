"""Synthetic tests for the bounded owner Garmin + dual-Google refresh command."""

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
        attempts=(),
        as_dict=lambda: {"sync": {"status": status.value}},
    )


def _google_attempt(
    stream: str,
    status: GoogleSyncStatus,
    *,
    page_count: int,
    request_count: int,
    resume_cursor_present: bool = False,
    error: GoogleSafeError | None = None,
) -> GoogleSyncAttempt:
    return GoogleSyncAttempt(
        stream=stream,
        data_type="heart-rate" if stream == "heart_rate" else stream,
        query_mode="list",
        data_source_family=None,
        window_start="2099-01-04",
        window_end_exclusive="2099-01-11",
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
) -> GoogleSyncReport:
    return GoogleSyncReport(
        auth=GoogleAuthResult(status=GoogleAuthStatus.AUTHENTICATED),
        status=status,
        kind=GoogleRunKind.REFRESH,
        window_start="2099-01-04",
        window_end_exclusive="2099-01-11",
        request_count=request_count,
        query_mode="list",
        data_source_family=None,
        streams=tuple(item.stream for item in attempts),
        attempts=tuple(attempts),
    )


def _hr_page_ceiling(*, final: bool = False) -> GoogleSyncAttempt:
    return _google_attempt(
        "heart_rate",
        GoogleSyncStatus.SUCCEEDED if final else GoogleSyncStatus.PARTIAL,
        page_count=4 if final else 40,
        request_count=4 if final else 80,
        resume_cursor_present=not final,
        error=None
        if final
        else GoogleSafeError("budget", "page_ceiling"),
    )


def _established_settings(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    return settings


def _patch_providers(monkeypatch, owner_refresh, *, garmin_cls=_FakeGarminSync, google_fn=None):
    monkeypatch.setattr(owner_refresh, "GarminAuthService", _FakeGarminAuth)
    monkeypatch.setattr(owner_refresh, "GarminIncrementalSync", garmin_cls)
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


def test_owner_refresh_default_runs_fixed_wearables_sleep_without_cli_family(monkeypatch, tmp_path):
    import healthcheck.owner_refresh as owner_refresh

    google_calls = []

    def fake_google(settings, **kwargs):
        google_calls.append(kwargs)
        return _report(GoogleSyncStatus.EMPTY)

    _patch_providers(monkeypatch, owner_refresh, google_fn=fake_google)

    report = run_owner_refresh(_established_settings(tmp_path), as_of="2099-01-10")
    assert report.status is OwnerRefreshStatus.SUCCEEDED
    assert len(google_calls) == 2
    assert google_calls[0]["query_mode"] is None
    assert google_calls[0]["data_source_family"] is None
    assert google_calls[0]["streams"] is None
    assert google_calls[1]["streams"] == ["sleep"]
    assert google_calls[1]["query_mode"] == "reconcile"
    assert google_calls[1]["data_source_family"] == "google-wearables"


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

    sleep_attempt = _google_attempt(
        "sleep", GoogleSyncStatus.SUCCEEDED, page_count=1, request_count=1
    )
    reports = [
        _google_report(
            _hr_page_ceiling(),
            sleep_attempt,
            status=GoogleSyncStatus.PARTIAL,
            request_count=81,
        ),
        _google_report(
            _hr_page_ceiling(), status=GoogleSyncStatus.PARTIAL, request_count=80
        ),
        _google_report(
            _hr_page_ceiling(final=True),
            status=GoogleSyncStatus.SUCCEEDED,
            request_count=4,
        ),
        _report(GoogleSyncStatus.EMPTY),
    ]

    def fake_google(settings, **kwargs):
        calls.append(kwargs)
        return reports.pop(0)

    _patch_providers(
        monkeypatch,
        owner_refresh,
        garmin_cls=CountingGarmin,
        google_fn=fake_google,
    )
    report = run_owner_refresh(
        _established_settings(tmp_path),
        as_of="2099-01-10",
        trailing_window_days=7,
    )

    assert report.status is OwnerRefreshStatus.SUCCEEDED
    assert len(garmin_calls) == 1
    assert len(calls) == 1 + OWNER_REFRESH_GOOGLE_HEART_RATE_CONTINUATION_ROUNDS + 1
    assert calls[1]["streams"] == ["heart_rate"]
    assert calls[2]["streams"] == ["heart_rate"]
    assert calls[1]["query_mode"] == calls[0]["query_mode"] is None
    assert calls[1]["data_source_family"] == calls[0]["data_source_family"] is None
    assert calls[3]["streams"] == list(OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_STREAMS)
    assert report.google.status is GoogleSyncStatus.SUCCEEDED
    assert report.google.request_count == 81 + 80 + 4
    assert [item.stream for item in report.google.attempts] == ["heart_rate", "sleep"]
    assert report.google.attempts[0].status is GoogleSyncStatus.SUCCEEDED
    assert report.google.attempts[0].page_count == 4
    assert report.google.attempts[0].request_count == 4
    assert report.google.attempts[1] == sleep_attempt


def test_owner_refresh_dense_hr_stops_at_fixed_continuation_bound(monkeypatch, tmp_path):
    import healthcheck.owner_refresh as owner_refresh

    calls = []
    reports = [
        _google_report(_hr_page_ceiling(), status=GoogleSyncStatus.PARTIAL, request_count=80),
        _google_report(_hr_page_ceiling(), status=GoogleSyncStatus.PARTIAL, request_count=80),
        _google_report(_hr_page_ceiling(), status=GoogleSyncStatus.PARTIAL, request_count=80),
        _report(GoogleSyncStatus.EMPTY),
    ]

    def fake_google(settings, **kwargs):
        calls.append(kwargs)
        return reports.pop(0)

    _patch_providers(monkeypatch, owner_refresh, google_fn=fake_google)
    report = run_owner_refresh(_established_settings(tmp_path), as_of="2099-01-10")

    assert report.status is OwnerRefreshStatus.PARTIAL
    assert len(calls) == OWNER_REFRESH_GOOGLE_HEART_RATE_CONTINUATION_ROUNDS + 2
    assert calls[-1]["streams"] == list(OWNER_REFRESH_GOOGLE_WEARABLES_SLEEP_STREAMS)
    assert report.google.status is GoogleSyncStatus.PARTIAL
    assert report.google.request_count == 240
    assert report.google.attempts[0].resume_cursor_present is True


def test_owner_refresh_propagates_continuation_reauth_with_no_attempt(monkeypatch, tmp_path):
    import healthcheck.owner_refresh as owner_refresh

    calls = []
    reports = [
        _google_report(_hr_page_ceiling(), status=GoogleSyncStatus.PARTIAL, request_count=80),
        GoogleSyncReport(
            auth=GoogleAuthResult(status=GoogleAuthStatus.REAUTH_REQUIRED),
            status=GoogleSyncStatus.REAUTH_REQUIRED,
            kind=GoogleRunKind.REFRESH,
            window_start="2099-01-04",
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
    report = run_owner_refresh(_established_settings(tmp_path), as_of="2099-01-10")

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
            return _google_report(
                _hr_page_ceiling(final=is_final),
                status=GoogleSyncStatus.SUCCEEDED if is_final else GoogleSyncStatus.PARTIAL,
                request_count=4 if is_final else 80,
            )
        return _google_report(_hr_page_ceiling(), status=GoogleSyncStatus.PARTIAL, request_count=80)

    _patch_providers(monkeypatch, owner_refresh, google_fn=fake_google)
    settings = _established_settings(tmp_path)
    first = run_owner_refresh(settings, as_of="2099-01-10")
    second = run_owner_refresh(settings, as_of="2099-01-10")

    assert first.status is OwnerRefreshStatus.SUCCEEDED
    assert second.status is OwnerRefreshStatus.SUCCEEDED
    assert first.google.request_count == second.google.request_count == 164
    assert len(first.google.attempts) == len(second.google.attempts) == 1
    assert len(calls) == 2 * (OWNER_REFRESH_GOOGLE_HEART_RATE_CONTINUATION_ROUNDS + 2)
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

    report = run_owner_refresh(_established_settings(tmp_path), as_of="2099-01-10")
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

    report = run_owner_refresh(_established_settings(tmp_path), as_of="2099-01-10")
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

    first = run_owner_refresh(settings, as_of="2099-01-10", trailing_window_days=7)
    second = run_owner_refresh(settings, as_of="2099-01-10", trailing_window_days=7)

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
        google=google,
        google_wearables_sleep=wearables_sleep,
    ).to_json()
    decoded = json.loads(payload)
    assert decoded["refresh"]["status"] == "succeeded"
    assert decoded["garmin"]["sync"]["status"] == "empty"
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
