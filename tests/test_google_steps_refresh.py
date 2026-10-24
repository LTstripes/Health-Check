"""Bounded missed-day reliability using synthetic profiles, receipts and HTTP only."""

import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from healthcheck import cli, owner_refresh
from healthcheck.collection_policy import set_collection_policy
from healthcheck.db.engine import create_session_factory, create_sqlite_engine
from healthcheck.db.models import (
    GooglePayloadObservation,
    GoogleSourceRecord,
    SyncRun,
    SyncStreamState,
)
from healthcheck.google import steps, steps_refresh
from healthcheck.google.auth import GoogleAuthResult, GoogleAuthStatus, GoogleHttpResponse
from healthcheck.google.steps_refresh import (
    STEPS_REFRESH_STATE_CODE,
    StepsRefreshStateError,
    activate_steps_refresh,
)
from healthcheck.google.sync import GoogleSyncStatus
from healthcheck.owner_refresh import OwnerRefreshRuntimeError, run_owner_refresh
from healthcheck.runtime import resolve_runtime_paths
from test_google_steps_acquisition import Transport, granted, payload, response
from test_owner_refresh import _established_settings, _patch_providers, _report


@pytest.fixture
def synthetic(monkeypatch, tmp_path):
    settings = _established_settings(tmp_path)
    _patch_providers(
        monkeypatch,
        owner_refresh,
        google_fn=lambda *a, **k: _report(GoogleSyncStatus.SUCCEEDED),
    )
    monkeypatch.setattr(
        owner_refresh, "read_consumer_freshness_projection_from_database", lambda *a, **k: {}
    )
    monkeypatch.setattr(owner_refresh, "GoogleAuthService", lambda *a, **k: granted())
    set_clock(monkeypatch, date(2099, 3, 30))
    return settings


def set_clock(monkeypatch, day):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(day.year, day.month, day.day, 12, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(owner_refresh, "datetime", Clock)


def raw(day, count="9"):
    result = payload(count)
    bounds = steps.StepsPlan(day).body()["range"]
    result["rollupDataPoints"][0].update(civilStartTime=bounds["start"], civilEndTime=bounds["end"])
    return result


def acquire_with(monkeypatch, content=None, responses=None, auth=None):
    calls = []
    auth_calls = []

    def acquire(settings, plan, **kwargs):
        calls.append(plan.day)
        if responses is not None:
            http = responses
        else:
            value = content(plan.day) if content else raw(plan.day)
            http = Transport(response(value))
        if auth is not None:
            kwargs["auth_service"] = auth
        result = steps.acquire_steps(
            settings, plan, **kwargs, transport=http, sleeper=lambda _: None
        )
        auth_calls.append(result.get("auth_refresh_attempted", False))
        return result

    monkeypatch.setattr(owner_refresh, "acquire_steps", acquire)
    return calls, auth_calls


def run(settings):
    return run_owner_refresh(settings, include_google_steps=True, google_steps_catchup=True)


def state(settings):
    engine = create_sqlite_engine(resolve_runtime_paths(settings))
    try:
        with create_session_factory(engine)() as session:
            row = session.scalar(
                select(SyncStreamState).where(
                    SyncStreamState.stream_code == STEPS_REFRESH_STATE_CODE
                )
            )
            return json.loads(row.cursor) if row else None
    finally:
        engine.dispose()


def mutate(settings, fn):
    engine = create_sqlite_engine(resolve_runtime_paths(settings))
    try:
        with create_session_factory(engine)() as session:
            fn(session)
            session.commit()
    finally:
        engine.dispose()


def test_first_activation_has_explicit_source_no_history_adoption_and_v3(monkeypatch, synthetic):
    calls, _ = acquire_with(monkeypatch)
    report = run(synthetic)
    assert calls == [date(2099, 3, 29)]
    output = report.as_dict()
    assert output["contract_version"] == "healthcheck-owner-refresh-v3"
    assert output["google_steps"]["activation_floor"] == "2099-03-29"
    assert output["google_steps"]["pending_date_count"] == 0
    assert output["google_steps"]["coverage"] == "unknown"
    cursor = state(synthetic)
    assert cursor["binding"]["source_instance"] == steps.IDENTITY.source_instance_id
    assert cursor["binding"]["source_kind"] == "family_aggregate"
    assert cursor["next_date"] == "2099-03-30"
    assert cursor["receipt"]["day"] == "2099-03-29"
    assert cursor["source_id"] not in report.to_json()
    assert cursor["receipt"]["observation_id"] not in report.to_json()


@pytest.mark.parametrize("gap,first_count,pending", [(1, 1, 0), (7, 7, 0), (11, 7, 4)])
def test_offline_gap_oldest_first_and_finite_resume(
    monkeypatch, synthetic, gap, first_count, pending
):
    activate_steps_refresh(synthetic, as_of=date(2099, 3, 30))
    set_clock(monkeypatch, date(2099, 3, 29) + timedelta(days=gap))
    calls, _ = acquire_with(monkeypatch)
    report = run(synthetic).google_steps
    assert calls == [date(2099, 3, 29) + timedelta(days=i) for i in range(first_count)]
    assert report["pending_date_count"] == pending
    assert report["status"] == ("partial" if pending else "succeeded")
    if pending:
        calls.clear()
        second = run(synthetic).google_steps
        assert calls == [date(2099, 4, 5) + timedelta(days=i) for i in range(pending)]
        assert second["pending_date_count"] == 0
        assert state(synthetic)["activation_floor"] == "2099-03-29"


def test_activation_commits_before_any_provider_and_survives_failure(monkeypatch, synthetic):
    def fail(*a, **k):
        assert state(synthetic)["activation_floor"] == "2099-03-29"
        raise RuntimeError("synthetic provider interrupted")

    monkeypatch.setattr(owner_refresh, "GarminAuthService", fail)
    with pytest.raises(RuntimeError, match="synthetic provider"):
        run(synthetic)
    progress = activate_steps_refresh(synthetic, as_of=date(2099, 4, 2))
    assert progress.activation_floor == progress.next_date == date(2099, 3, 29)


def test_missing_grant_keeps_floor_and_stops_later_dates(monkeypatch, synthetic):
    activate_steps_refresh(synthetic, as_of=date(2099, 3, 30))
    set_clock(monkeypatch, date(2099, 4, 2))
    auth = SimpleNamespace(
        load_steps_access_token=lambda **k: ("", GoogleAuthResult(GoogleAuthStatus.REAUTH_REQUIRED))
    )
    calls, _ = acquire_with(monkeypatch, auth=auth, responses=Transport())
    report = run(synthetic).google_steps
    assert calls == [date(2099, 3, 29)]
    assert report["request_count"] == 0 and report["pending_date_count"] == 4
    assert [item["status"] for item in report["attempts"]] == [
        "failed",
        "not_run",
        "not_run",
        "not_run",
    ]
    assert state(synthetic)["receipt"] is None


def test_caught_up_reacquires_yesterday_once_and_persists_correction(monkeypatch, synthetic):
    calls, _ = acquire_with(monkeypatch)
    run(synthetic)
    acquire_with(monkeypatch, content=lambda day: raw(day, "0"))
    second = run(synthetic).google_steps
    assert second["selected_dates"] == ["2099-03-29"]
    assert second["attempted_date_count"] == 1
    assert second["attempts"][0]["acquisition"]["metric_states"] == {"value": 1}
    assert state(synthetic)["next_date"] == "2099-03-30"
    assert calls == [date(2099, 3, 29)]


@pytest.mark.parametrize("kind", ["empty", "missing", "null", "zero", "int64"])
def test_valid_nonvalue_and_exact_integer_receipts_advance(monkeypatch, synthetic, kind):
    def content(day):
        if kind == "empty":
            return {"rollupDataPoints": []}
        value = raw(day, "9223372036854775807" if kind == "int64" else "0")
        if kind == "missing":
            value["rollupDataPoints"][0]["steps"] = {}
        if kind == "null":
            value["rollupDataPoints"][0]["steps"] = {"countSum": None}
        return value

    acquire_with(monkeypatch, content=content)
    report = run(synthetic).google_steps
    assert report["status"] == "succeeded"
    assert state(synthetic)["next_date"] == "2099-03-30"
    assert activate_steps_refresh(synthetic, as_of=date(2099, 3, 30)).next_date == date(2099, 3, 30)


def test_partial_failure_commits_earlier_day_and_stops_rest(monkeypatch, synthetic):
    activate_steps_refresh(synthetic, as_of=date(2099, 3, 30))
    set_clock(monkeypatch, date(2099, 4, 2))
    http = Transport(response(raw(date(2099, 3, 29))), response({"unexpected": []}))
    calls, _ = acquire_with(monkeypatch, responses=http)
    report = run(synthetic).google_steps
    assert calls == [date(2099, 3, 29), date(2099, 3, 30)]
    assert report["pending_date_count"] == 3
    assert report["attempts"][1]["status"] == "partial"
    assert report["attempts"][2]["status"] == "not_run"
    assert state(synthetic)["next_date"] == "2099-03-30"
    acquire_with(monkeypatch)
    assert run(synthetic).google_steps["selected_dates"][0] == "2099-03-30"


def test_progress_failure_rolls_back_successful_acquisition_atomically(monkeypatch, synthetic):
    original = steps_refresh.advance_steps_refresh

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise ValueError("synthetic commit interruption")

    monkeypatch.setattr(steps_refresh, "advance_steps_refresh", fail)
    acquire_with(monkeypatch)
    report = run(synthetic).google_steps
    assert report["status"] == "failed"
    assert state(synthetic)["receipt"] is None
    assert state(synthetic)["next_date"] == "2099-03-29"

    def check(session):
        for model in (SyncRun, GooglePayloadObservation, GoogleSourceRecord):
            assert session.scalar(select(func.count()).select_from(model)) == 0

    mutate(synthetic, check)
    monkeypatch.setattr(steps_refresh, "advance_steps_refresh", original)
    assert run(synthetic).google_steps["status"] == "succeeded"


@pytest.mark.parametrize(
    "target",
    [
        "family",
        "query",
        "contract",
        "day",
        "source",
        "run",
        "observation",
        "context",
        "duplicate_context",
        "no_receipt",
        "observation_family",
        "observation_query",
        "observation_contract",
        "observation_day",
        "run_link",
        "unfinished_run",
    ],
)
def test_resume_rejects_invalid_exact_receipt_before_auth(monkeypatch, synthetic, target):
    acquire_with(monkeypatch)
    run(synthetic)

    def damage(session):
        row = session.scalar(
            select(SyncStreamState).where(SyncStreamState.stream_code == STEPS_REFRESH_STATE_CODE)
        )
        cursor = json.loads(row.cursor)
        observation = session.get(GooglePayloadObservation, cursor["receipt"]["observation_id"])
        malformed_observation = target in {
            "observation",
            "context",
            "duplicate_context",
            "observation_family",
            "observation_query",
            "observation_contract",
            "observation_day",
            "run_link",
        }
        if malformed_observation:
            # Preserve the real append-only observation. Insert independent
            # synthetic malformed evidence rather than bypassing its DB trigger.
            observation = GooglePayloadObservation(
                **{
                    column.name: getattr(observation, column.name)
                    for column in GooglePayloadObservation.__table__.columns
                    if column.name not in {"id", "observation_key"}
                },
                id=str(uuid4()),
                observation_key="synthetic-malformed-receipt:" + uuid4().hex,
            )
            session.add(observation)
            cursor["receipt"]["observation_id"] = observation.id
        if target in {"family", "query", "contract"}:
            key = {"family": "family", "query": "query_mode", "contract": "acquisition_contract"}[
                target
            ]
            cursor["binding"][key] = "different"
        elif target == "day":
            cursor["receipt"]["day"] = "2099-03-28"
        elif target == "source":
            cursor["source_id"] = "different"
        elif target == "run":
            session.get(SyncRun, cursor["receipt"]["run_id"]).status = "failed"
        elif target == "observation":
            observation.parse_status = "partial"
        elif target == "observation_family":
            observation.data_source_family = "users/me/dataSourceFamilies/different"
        elif target == "observation_query":
            observation.query_mode = "reconcile"
        elif target == "observation_contract":
            observation.source_contract_version = "google-steps-acquisition-v999"
        elif target == "observation_day":
            observation.diagnostics_json = json.dumps(
                [steps.StepsPlan(date(2099, 3, 28)).context(1)]
            )
        elif target == "run_link":
            observation.sync_run_id = None
        elif target == "unfinished_run":
            session.get(SyncRun, cursor["receipt"]["run_id"]).completed_at = None
        elif target == "context":
            observation.diagnostics_json = "[]"
        elif target == "duplicate_context":
            context = steps.StepsPlan(date(2099, 3, 29)).context(1)
            observation.diagnostics_json = json.dumps([context, context])
        else:
            cursor["receipt"] = None
        row.cursor = json.dumps(cursor)

    mutate(synthetic, damage)
    for name in ("GarminAuthService", "GoogleAuthService"):
        monkeypatch.setattr(owner_refresh, name, lambda *a, **k: pytest.fail("auth before receipt"))
    with pytest.raises(OwnerRefreshRuntimeError, match="steps_catchup_state_invalid"):
        run(synthetic)


def test_policy_off_has_no_steps_auth_or_progress(monkeypatch, synthetic):
    set_collection_policy(synthetic, stream="google:steps", state="off")
    for name in ("GarminAuthService", "GoogleAuthService", "activate_steps_refresh"):
        monkeypatch.setattr(owner_refresh, name, lambda *a, **k: pytest.fail("OFF work"))
    with pytest.raises(owner_refresh.OwnerRefreshPolicyError):
        run(synthetic)
    assert state(synthetic) is None


def test_no_flag_does_not_create_progress(monkeypatch, synthetic):
    monkeypatch.setattr(owner_refresh, "activate_steps_refresh", lambda *a, **k: pytest.fail("OFF"))
    report = run_owner_refresh(synthetic)
    assert report.as_dict()["contract_version"] == "healthcheck-owner-refresh-v1"
    assert state(synthetic) is None


@pytest.mark.parametrize("flags", [[], ["--include-google-steps", "--date", "2000-01-01"]])
def test_catchup_bad_arguments_precede_provider_work(monkeypatch, synthetic, capsys, flags):
    monkeypatch.setattr(owner_refresh, "GarminAuthService", lambda *a, **k: pytest.fail("auth"))
    assert (
        cli.main(
            [
                "owner-refresh",
                "--google-steps-catchup",
                "--data-dir",
                str(synthetic.data_dir),
                *flags,
            ]
        )
        == 2
    )
    if flags:
        assert (
            json.loads(capsys.readouterr().out)["contract_version"]
            == "healthcheck-owner-refresh-v3"
        )
    assert state(synthetic) is None


def test_missing_runtime_catchup_error_is_v3(tmp_path, capsys):
    assert (
        cli.main(
            [
                "owner-refresh",
                "--include-google-steps",
                "--google-steps-catchup",
                "--data-dir",
                str(tmp_path / "absent"),
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["contract_version"] == "healthcheck-owner-refresh-v3"


def test_backwards_clock_and_corrupt_cursor_fail_closed(synthetic):
    activate_steps_refresh(synthetic, as_of=date(2099, 3, 30))
    with pytest.raises(StepsRefreshStateError):
        activate_steps_refresh(synthetic, as_of=date(2099, 3, 29))

    def damage(session):
        row = session.scalar(
            select(SyncStreamState).where(SyncStreamState.stream_code == STEPS_REFRESH_STATE_CODE)
        )
        row.cursor = '{"contract":1,"contract":2}'

    mutate(synthetic, damage)
    with pytest.raises(StepsRefreshStateError):
        activate_steps_refresh(synthetic, as_of=date(2099, 3, 30))


def test_seven_dates_cap_includes_retries_and_startup_refreshes(monkeypatch, synthetic):
    activate_steps_refresh(synthetic, as_of=date(2099, 3, 30))
    set_clock(monkeypatch, date(2099, 4, 9))
    responses = []
    for index in range(7):
        day = date(2099, 3, 29) + timedelta(days=index)
        responses.extend(
            [
                GoogleHttpResponse(429, b"synthetic"),
                GoogleHttpResponse(503, b"synthetic"),
                response(raw(day)),
            ]
        )
    http = Transport(*responses)
    refreshes = []

    def token(**kwargs):
        refresh = kwargs.get("refresh_if_needed", False)
        refreshes.append(refresh)
        return "synthetic", GoogleAuthResult(
            GoogleAuthStatus.AUTHENTICATED,
            refresh_attempted=refresh,
            refresh_succeeded=refresh,
        )

    calls, _ = acquire_with(
        monkeypatch, responses=http, auth=SimpleNamespace(load_steps_access_token=token)
    )
    report = run(synthetic).google_steps
    assert len(calls) == len(set(calls)) == 7
    assert len(http.calls) == report["request_count"] == 21
    assert sum(refreshes) == report["startup_refresh_count"] == 7
    assert len(http.calls) + sum(refreshes) == report["limits"]["max_steps_http_requests"] == 28
    assert report["pending_date_count"] == 4


def test_retry_exhaustion_stops_with_original_failure_and_pending_dates(monkeypatch, synthetic):
    activate_steps_refresh(synthetic, as_of=date(2099, 3, 30))
    set_clock(monkeypatch, date(2099, 4, 2))
    http = Transport(*[GoogleHttpResponse(429, b"synthetic") for _ in range(3)])
    calls, _ = acquire_with(monkeypatch, responses=http)
    report = run(synthetic).google_steps
    assert calls == [date(2099, 3, 29)] and report["request_count"] == 3
    assert report["attempts"][0]["acquisition"]["reason"] == "retry_exhausted"
    assert report["pending_date_count"] == 4
    assert [item["status"] for item in report["attempts"]][1:] == ["not_run"] * 3


def test_existing_acquired_presence_does_not_seed_activation_or_skip(monkeypatch, synthetic):
    for day in (date(2090, 1, 1), date(2099, 3, 29)):
        assert (
            steps.acquire_steps(
                synthetic,
                steps.StepsPlan(day),
                auth_service=granted(),
                transport=Transport(response(raw(day))),
            )["status"]
            == "observed"
        )
    calls, _ = acquire_with(monkeypatch)
    report = run(synthetic).google_steps
    assert calls == [date(2099, 3, 29)]
    assert report["activation_floor"] == "2099-03-29"


@pytest.mark.parametrize(
    "instant,expected",
    [
        (datetime(2099, 3, 29, 20, 59, tzinfo=UTC), date(2099, 3, 28)),
        (datetime(2099, 3, 29, 21, 0, tzinfo=UTC), date(2099, 3, 29)),
    ],
)
def test_catchup_activation_uses_moscow_midnight(monkeypatch, synthetic, instant, expected):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)

    monkeypatch.setattr(owner_refresh, "datetime", Clock)
    calls, _ = acquire_with(monkeypatch)
    run(synthetic)
    assert calls == [expected]
    assert state(synthetic)["activation_floor"] == expected.isoformat()


def test_cli_catchup_success_emits_v3(monkeypatch, synthetic, capsys):
    acquire_with(monkeypatch)
    assert (
        cli.main(
            [
                "owner-refresh",
                "--include-google-steps",
                "--google-steps-catchup",
                "--data-dir",
                str(synthetic.data_dir),
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["contract_version"] == "healthcheck-owner-refresh-v3"
    assert output["google_steps"]["selected_dates"] == ["2099-03-29"]


def test_interrupted_after_commit_resumes_next_date(monkeypatch, synthetic):
    activate_steps_refresh(synthetic, as_of=date(2099, 3, 30))
    set_clock(monkeypatch, date(2099, 4, 2))
    calls = []

    def interrupted(settings, plan, **kwargs):
        calls.append(plan.day)
        result = steps.acquire_steps(
            settings, plan, **kwargs, transport=Transport(response(raw(plan.day)))
        )
        assert result["status"] == "observed"
        raise RuntimeError("synthetic process interruption after commit")

    monkeypatch.setattr(owner_refresh, "acquire_steps", interrupted)
    with pytest.raises(RuntimeError, match="after commit"):
        run(synthetic)
    assert state(synthetic)["next_date"] == "2099-03-30"
    resumed, _ = acquire_with(monkeypatch)
    assert run(synthetic).google_steps["status"] == "succeeded"
    assert resumed == [date(2099, 3, 30), date(2099, 3, 31), date(2099, 4, 1)]


def test_catchup_acquisition_keeps_owner_profile_lock(monkeypatch, synthetic):
    from healthcheck.external_runtime_lock import (
        ExternalRuntimeOperationBusyError,
        ExternalRuntimeOperationLock,
    )

    def acquire(settings, plan, **kwargs):
        with pytest.raises(ExternalRuntimeOperationBusyError):
            with ExternalRuntimeOperationLock(
                resolve_runtime_paths(settings), allow_reentrant=False
            ):
                pass
        return steps.acquire_steps(
            settings, plan, **kwargs, transport=Transport(response(raw(plan.day)))
        )

    monkeypatch.setattr(owner_refresh, "acquire_steps", acquire)
    assert run(synthetic).google_steps["status"] == "succeeded"


def test_flag_omission_preserves_floor_and_later_catchup(monkeypatch, synthetic):
    activate_steps_refresh(synthetic, as_of=date(2099, 3, 30))
    original = state(synthetic)
    run_owner_refresh(synthetic)
    assert state(synthetic) == original
    set_clock(monkeypatch, date(2099, 4, 2))
    calls, _ = acquire_with(monkeypatch)
    run(synthetic)
    assert calls[0] == date(2099, 3, 29)
    assert state(synthetic)["activation_floor"] == "2099-03-29"


@pytest.mark.parametrize("count", ["9.5", "9223372036854775808"])
def test_invalid_count_never_advances_acquisition_progress(monkeypatch, synthetic, count):
    acquire_with(monkeypatch, content=lambda day: raw(day, count))
    report = run(synthetic).google_steps
    assert report["status"] == "partial"
    assert report["attempts"][0]["acquisition"]["status"] == "rejected"
    assert state(synthetic)["next_date"] == "2099-03-29"
    assert state(synthetic)["receipt"] is None
