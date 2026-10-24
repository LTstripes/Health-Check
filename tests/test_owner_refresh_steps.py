"""Synthetic opt-in boundary checks; reuse the existing provider and acquisition fixtures."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from healthcheck import cli, owner_refresh
from healthcheck.collection_policy import set_collection_policy
from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine
from healthcheck.db.models import GooglePayloadObservation, GoogleRecordMetric, GoogleSourceRecord
from healthcheck.external_runtime_lock import (
    ExternalRuntimeOperationBusyError,
    ExternalRuntimeOperationLock,
    ExternalRuntimeOperationLockError,
)
from healthcheck.google import steps
from healthcheck.google.auth import GoogleAuthResult, GoogleAuthStatus
from healthcheck.google.contracts import decode_count_sum_metric
from healthcheck.google.sync import GoogleSyncStatus, parse_google_streams
from healthcheck.owner_refresh import OwnerRefreshLock, OwnerRefreshPolicyError, run_owner_refresh
from healthcheck.runtime import resolve_runtime_paths
from test_google_steps_acquisition import Transport, granted, payload, plan, response
from test_owner_refresh import _established_settings, _patch_providers, _report


@pytest.fixture
def normal_refresh(monkeypatch, tmp_path):
    settings = _established_settings(tmp_path)
    calls = []

    def google(settings, **kwargs):
        calls.append(kwargs)
        return _report(GoogleSyncStatus.SUCCEEDED)

    _patch_providers(monkeypatch, owner_refresh, google_fn=google)
    monkeypatch.setattr(
        owner_refresh, "read_consumer_freshness_projection_from_database", lambda *a, **k: {}
    )
    return settings, calls


def test_default_and_steps_policy_off_preserve_legacy_selection(monkeypatch, normal_refresh):
    settings, calls = normal_refresh
    monkeypatch.setattr(owner_refresh, "acquire_steps", lambda *a, **k: pytest.fail("Steps"))
    before = run_owner_refresh(settings, as_of="2099-01-10")
    def selection(call):
        return {k: v for k, v in call.items() if k not in {"auth_service", "phase_timing"}}

    before_calls = [selection(call) for call in calls]
    calls.clear()
    set_collection_policy(settings, stream="google:steps", state="off")
    after = run_owner_refresh(settings, as_of="2099-01-10")
    assert [selection(call) for call in calls] == before_calls
    assert before.as_dict().keys() == after.as_dict().keys()
    assert after.as_dict()["contract_version"] == "healthcheck-owner-refresh-v1"
    assert "google_steps" not in after.as_dict()
    assert "google_steps" not in after.timing["phases"]
    assert "steps" not in {surface.code for surface in parse_google_streams(None)}
    with pytest.raises(ValueError):
        parse_google_streams(["steps"])


def test_explicit_opt_in_policy_conflict_precedes_all_providers(monkeypatch, tmp_path):
    settings = _established_settings(tmp_path)
    set_collection_policy(settings, stream="google:steps", state="off")
    for name in ("GarminAuthService", "GoogleAuthService", "acquire_steps"):
        monkeypatch.setattr(owner_refresh, name, lambda *a, **k: pytest.fail("provider work"))
    with pytest.raises(OwnerRefreshPolicyError, match="collection_policy_conflict"):
        run_owner_refresh(settings, as_of="2099-01-10", include_google_steps=True)


@pytest.mark.parametrize("basis,requested", [
    ("2100-01-01", "2099-12-31"), ("2099-03-01", "2099-02-28"),
    ("2096-03-01", "2096-02-29"),
])
def test_explicit_date_is_steps_basis_without_changing_normal_window(
    monkeypatch, normal_refresh, basis, requested,
):
    settings, calls = normal_refresh
    auth_calls = []
    monkeypatch.setattr(owner_refresh, "GoogleAuthService", lambda *a, **k: auth_calls.append(k))
    acquired = []
    acquisition = steps._report("observed", "observed_only", 1, metric_states={"missing": 1})

    def acquire(settings, steps_plan, **kwargs):
        acquired.append(steps_plan)
        return acquisition

    monkeypatch.setattr(owner_refresh, "acquire_steps", acquire)
    result = run_owner_refresh(settings, as_of=basis, include_google_steps=True)
    output = result.as_dict()
    assert acquired[0].day.isoformat() == requested
    assert output["contract_version"] == "healthcheck-owner-refresh-v2"
    assert output["google_steps"] == {
        "as_of": basis, "requested_date": requested, "selection_zone": "Europe/Moscow",
        "status": "succeeded", "acquisition": acquisition,
    }
    assert result.as_of == basis and result.window_end == basis
    assert {call["end"] for call in calls} == {
        date.fromisoformat(basis) - timedelta(days=i) for i in range(7)
    }
    assert calls[0]["start"] == date.fromisoformat(basis) - timedelta(days=6)
    assert calls[-1]["start"] == calls[0]["start"]
    assert auth_calls == [{}, {"include_steps": True}]


@pytest.mark.parametrize("instant,basis,requested", [
    (datetime(2099, 12, 31, 20, 59, tzinfo=UTC), "2099-12-31", "2099-12-30"),
    (datetime(2099, 12, 31, 21, 0, tzinfo=UTC), "2100-01-01", "2099-12-31"),
])
def test_default_steps_date_uses_moscow_midnight_only(
    monkeypatch, normal_refresh, instant, basis, requested,
):
    settings, calls = normal_refresh

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)

    monkeypatch.setattr(owner_refresh, "datetime", Clock)
    monkeypatch.setattr(owner_refresh, "validate_sync_date", lambda value: date(2099, 12, 31))
    monkeypatch.setattr(owner_refresh, "GoogleAuthService", lambda *a, **k: granted())
    monkeypatch.setattr(
        owner_refresh, "acquire_steps",
        lambda *a, **k: steps._report("observed", "observed_only", 1),
    )
    report = run_owner_refresh(settings, include_google_steps=True)
    assert report.as_of == "2099-12-31" and report.window_start == "2099-12-25"
    assert report.google_steps["as_of"] == basis
    assert report.google_steps["requested_date"] == requested
    assert {call["end"] for call in calls} == {
        date(2099, 12, 31) - timedelta(days=i) for i in range(7)
    }


def test_previous_day_underflow_is_rejected_before_providers(monkeypatch, tmp_path):
    settings = _established_settings(tmp_path)
    monkeypatch.setattr(
        owner_refresh, "GarminAuthService", lambda *a, **k: pytest.fail("provider")
    )
    with pytest.raises(ValueError, match="previous civil date"):
        run_owner_refresh(settings, as_of="0001-01-01", include_google_steps=True)


@pytest.mark.parametrize("status,error,operational,combined", [
    ("observed", None, "succeeded", "succeeded"),
    ("rejected", None, "partial", "partial"),
    ("failed", None, "failed", "partial"),
    ("blocked", None, "failed", "partial"),
    ("blocked", {"error_class": "authentication", "error_code": "scope_required"},
     "reauth_required", "reauth_required"),
    ("blocked", {"error_class": "authentication", "error_code": "scope_unexpected"},
     "reauth_required", "reauth_required"),
    ("blocked", {"error_class": "authentication", "error_code": "invalid_grant"},
     "reauth_required", "reauth_required"),
    ("blocked", {"error_class": "authentication", "error_code": "credential_corrupt"},
     "failed", "partial"),
    ("failed", {"error_class": "transport", "error_code": "invalid_grant"},
     "failed", "partial"),
])
def test_steps_status_and_original_report_are_preserved(
    monkeypatch, normal_refresh, status, error, operational, combined,
):
    settings, _ = normal_refresh
    acquisition = steps._report(status, "synthetic", 0, auth_error=error)
    monkeypatch.setattr(owner_refresh, "GoogleAuthService", lambda *a, **k: granted())
    monkeypatch.setattr(owner_refresh, "acquire_steps", lambda *a, **k: acquisition)
    report = run_owner_refresh(settings, as_of="2099-01-10", include_google_steps=True)
    assert report.status.value == combined
    assert report.google_steps["status"] == operational
    assert report.google_steps["acquisition"] is acquisition
    assert acquisition["coverage"] == acquisition["pagination"] == "unknown"


@pytest.mark.parametrize("command", ["google-sync", "google-auth", "google-steps", "garmin-sync"])
def test_cli_flag_guard_precedes_settings(monkeypatch, capsys, command):
    monkeypatch.setattr(cli, "_settings", lambda *a: pytest.fail("settings"))
    assert cli.main([command, "--include-google-steps"]) == 2
    assert "requires owner-refresh" in capsys.readouterr().err


@pytest.mark.parametrize("extra,code", [
    ([], "runtime_missing"), (["--dry-run"], "invalid_refresh_request"),
])
def test_cli_opt_in_errors_have_v2(tmp_path, capsys, extra, code):
    assert cli.main([
        "owner-refresh", "--include-google-steps", "--data-dir", str(tmp_path / "absent"), *extra,
    ]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["contract_version"] == "healthcheck-owner-refresh-v2"
    assert report["error"]["error_code"] == code


def test_standalone_lock_blocks_contender_before_refresh_and_http(tmp_path):
    settings = Settings(data_dir=tmp_path / "standalone")
    paths = resolve_runtime_paths(settings)
    paths.root.mkdir()
    inspected = []
    contender = SimpleNamespace(load_steps_access_token=lambda **k: (
        inspected.append(k) or "synthetic", GoogleAuthResult(GoogleAuthStatus.AUTHENTICATED)
    ))

    class CheckingTransport(Transport):
        def request(self, *args, **kwargs):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    steps.acquire_steps, settings, plan(), auth_service=contender,
                    transport=Transport(),
                )
                with pytest.raises(ExternalRuntimeOperationBusyError):
                    future.result(timeout=5)
            assert inspected == [{}]
            return super().request(*args, **kwargs)

    result = steps.acquire_steps(
        settings, plan(), auth_service=granted(), transport=CheckingTransport(response(payload()))
    )
    assert result["status"] == "observed"
    # Persistence really nested the same shared lock, and all levels released it.
    with ExternalRuntimeOperationLock(paths, allow_reentrant=False):
        pass


def test_owner_opt_in_real_acquisition_preserves_repeat_correction_zero_and_missing(
    monkeypatch, normal_refresh,
):
    settings, _ = normal_refresh
    monkeypatch.setattr(owner_refresh, "GoogleAuthService", lambda *a, **k: granted())
    raws = [payload("9"), payload("9"), payload("2"), payload("0"), payload()]
    raws[-1]["rollupDataPoints"][0]["steps"] = {}
    reports = []
    for index, raw in enumerate(raws):
        def acquire(settings, steps_plan, **kwargs):
            assert steps_plan == plan()
            # The owner lock is already held and the acquisition/persistence locks reenter it.
            with pytest.raises(ExternalRuntimeOperationBusyError):
                with ExternalRuntimeOperationLock(
                    resolve_runtime_paths(settings), allow_reentrant=False,
                ):
                    pass
            return steps.acquire_steps(
                settings, steps_plan, **kwargs, transport=Transport(response(raw)),
                clock=lambda: datetime(2099, 4, 1, index, tzinfo=UTC),
            )

        monkeypatch.setattr(owner_refresh, "acquire_steps", acquire)
        reports.append(run_owner_refresh(settings, as_of="2099-03-30", include_google_steps=True))
    assert [r.google_steps["acquisition"]["metric_states"] for r in reports] == [
        {"value": 1}, {"value": 1}, {"value": 1}, {"value": 1}, {"missing": 1},
    ]
    engine = create_sqlite_engine(resolve_runtime_paths(settings))
    with create_session_factory(engine)() as session:
        assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 1
        assert session.scalar(select(func.count()).select_from(GooglePayloadObservation)) == 5
        metric = decode_count_sum_metric(session.scalar(select(GoogleRecordMetric)))
        assert metric.state.value == "missing"
    engine.dispose()
    assert all(r.status.value == "succeeded" for r in reports)
    with OwnerRefreshLock(resolve_runtime_paths(settings)):
        pass


def test_eligible_missing_profile_parent_fails_before_refresh_or_http(tmp_path):
    settings = Settings(data_dir=tmp_path / "absent")
    inspected = []
    auth = SimpleNamespace(load_steps_access_token=lambda **k: (
        inspected.append(k) or "synthetic", GoogleAuthResult(GoogleAuthStatus.AUTHENTICATED)
    ))
    http = Transport()
    with pytest.raises(ExternalRuntimeOperationLockError):
        steps.acquire_steps(settings, plan(), auth_service=auth, transport=http)
    assert inspected == [{}] and not http.calls and not settings.data_dir.exists()


def test_cli_opt_in_dispatches_and_emits_original_acquisition(
    monkeypatch, normal_refresh, capsys,
):
    settings, _ = normal_refresh
    acquisition = steps._report("observed", "observed_only", 1)
    monkeypatch.setattr(owner_refresh, "GoogleAuthService", lambda *a, **k: granted())

    def acquire(settings, steps_plan, **kwargs):
        assert steps_plan.day == date(2099, 1, 9)
        return acquisition

    monkeypatch.setattr(owner_refresh, "acquire_steps", acquire)
    assert cli.main([
        "owner-refresh", "--include-google-steps", "--date", "2099-01-10",
        "--stream", "sleep", "--data-dir", str(settings.data_dir),
    ]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["contract_version"] == "healthcheck-owner-refresh-v2"
    assert report["google_steps"]["acquisition"] == acquisition
