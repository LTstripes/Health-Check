"""Only synthetic sessions, fake HTTP, and external temporary databases."""

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select

from healthcheck import cli
from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine
from healthcheck.db.models import (
    CoverageInterval,
    GoogleNormalizationAttempt,
    GooglePayloadObservation,
    GoogleRecordMetric,
    GoogleSourceRecord,
    SyncRun,
    SyncStreamState,
)
from healthcheck.external_runtime_lock import EXTERNAL_RUNTIME_LOCK_FILENAME
from healthcheck.google import auth, steps
from healthcheck.google.auth import (
    DEFAULT_SCOPE_ORDER,
    SCOPE_ACTIVITY,
    STEPS_SCOPE_ORDER,
    GoogleAuthResult,
    GoogleAuthService,
    GoogleAuthStatus,
    GoogleClientCredentials,
    GoogleHttpResponse,
    GoogleTokenSet,
    UrllibGoogleHttpTransport,
)
from healthcheck.google.contracts import FAMILY_GOOGLE_WEARABLES, decode_count_sum_metric
from healthcheck.google.persistence import google_persistence_for
from healthcheck.google.replay import replay_google_observations
from healthcheck.google.steps import StepsPlan, acquire_steps, normalize_acquired_steps
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.runtime import resolve_runtime_paths

DAY = "2099-03-29"
SECRET = "synthetic-secret-never-display"


class Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _existing_settings(path):
    # Real cached grants already have profile ancestors. Fakes provide that parent
    # explicitly so acquisition never has to bootstrap a profile to take its lock.
    path.mkdir(parents=True, exist_ok=True)
    return Settings(data_dir=path)


def tokens(scopes=DEFAULT_SCOPE_ORDER):
    return GoogleTokenSet(SECRET, SECRET, "Bearer", 3600, " ".join(scopes))


def service(
    tmp_path, *, scopes=DEFAULT_SCOPE_ORDER, include_steps=False, response=None, denied=False
):
    transport = Transport(response) if response else Transport()
    browser = []
    saved = [tokens(scopes)]

    class Callback:
        def start(self):
            pass

        def wait(self):
            return SimpleNamespace(
                error_code="consent_denied" if denied else None,
                code="synthetic-code",
                state=svc._pending_state,
            )

    svc = GoogleAuthService(
        Settings(data_dir=tmp_path / "synthetic-auth-profile"),
        include_steps=include_steps,
        transport=transport,
        protector=SimpleNamespace(kind="synthetic"),
        browser_opener=browser.append,
        callback_factory=lambda _uri: Callback(),
        client_credentials=GoogleClientCredentials("synthetic-client", SECRET),
    )
    svc.token_path = SimpleNamespace(exists=lambda: bool(saved))
    svc._read_tokens = lambda: saved[-1]
    svc._write_tokens = saved.append
    svc.clear_tokens = lambda: pytest.fail("Steps opt-in must preserve the old session")
    return svc, saved, browser, transport


def oauth_response(scopes=STEPS_SCOPE_ORDER, *, missing_scope=False):
    body = {
        "access_token": "synthetic-new",
        "refresh_token": "synthetic-new-refresh",
        "token_type": "Bearer",
        "scope": " ".join(scopes),
    }
    if missing_scope:
        del body["scope"]
    return GoogleHttpResponse(200, json.dumps(body).encode())


def plan(day=DAY):
    return StepsPlan.build(day, "google-wearables")


def payload(count="0", *, body_plan=None):
    bounds = (body_plan or plan()).body()["range"]
    return {
        "rollupDataPoints": [
            {
                "civilStartTime": bounds["start"],
                "civilEndTime": bounds["end"],
                "steps": {"countSum": count},
            }
        ]
    }


def response(raw):
    return GoogleHttpResponse(200, raw if isinstance(raw, bytes) else json.dumps(raw).encode())


def granted():
    return SimpleNamespace(
        load_steps_access_token=lambda **kwargs: (
            SECRET,
            GoogleAuthResult(status=GoogleAuthStatus.AUTHENTICATED),
        )
    )


def test_defaults_unchanged_and_steps_requires_explicit_scope_set(tmp_path):
    for include, expected in [(False, DEFAULT_SCOPE_ORDER), (True, STEPS_SCOPE_ORDER)]:
        svc, _, _, _ = service(tmp_path, include_steps=include)
        query = parse_qs(urlparse(svc.authorization_url(force_reauth=True)).query)
        assert query["scope"] == [" ".join(expected)]
        assert query["include_granted_scopes"] == ["false"]
    assert auth.ALLOWED_SCOPES == frozenset(DEFAULT_SCOPE_ORDER)
    for scope_set in [
        (SCOPE_ACTIVITY,),
        (*STEPS_SCOPE_ORDER, SCOPE_ACTIVITY),
        (*DEFAULT_SCOPE_ORDER, auth.SCOPE_SETTINGS),
        (*DEFAULT_SCOPE_ORDER, SCOPE_ACTIVITY.replace("readonly", "writeonly")),
    ]:
        with pytest.raises(ValueError):
            auth.build_authorization_url(
                client_id="synthetic",
                state="synthetic",
                redirect_uri=auth.DEFAULT_GOOGLE_OAUTH_REDIRECT_URI,
                scopes=scope_set,
            )


@pytest.mark.parametrize("scopes", [DEFAULT_SCOPE_ORDER, (auth.SCOPE_SLEEP,), ()])
def test_cached_missing_steps_never_refreshes_bootstraps_or_writes(tmp_path, scopes):
    svc, saved, browser, transport = service(tmp_path, scopes=scopes, include_steps=True)
    assert not svc.bootstrap().ok
    assert not svc.load_access_token()[1].ok
    assert svc.load_steps_access_token()[0] == ""
    assert svc.load_steps_access_token(refresh_if_needed=True)[0] == ""
    assert len(saved) == 1 and not browser and not transport.calls


def test_complete_cached_steps_inspection_and_bootstrap_do_not_refresh(tmp_path):
    svc, saved, browser, transport = service(tmp_path, scopes=STEPS_SCOPE_ORDER, include_steps=True)
    assert svc.bootstrap().ok
    token, result = svc.load_steps_access_token()
    assert token == SECRET and result.ok and not result.refresh_attempted
    assert len(saved) == 1 and not browser and not transport.calls


@pytest.mark.parametrize("omit", [False, True])
def test_steps_apply_refreshes_one_snapshot_and_uses_fresh_access(tmp_path, omit):
    body = json.loads(oauth_response(missing_scope=omit).body)
    if omit:
        del body["refresh_token"]
    svc, saved, browser, oauth = service(
        tmp_path, scopes=STEPS_SCOPE_ORDER, include_steps=True, response=response(body)
    )
    original = saved[0]
    original.expires_in = 0  # Synthetic cached access must never be used for the data POST.
    reads = []

    def read_once():
        reads.append(True)
        return original

    svc._read_tokens = read_once
    data = Transport(response(payload()))
    report = acquire_steps(
        _existing_settings(tmp_path / "synthetic-runtime"), plan(), auth_service=svc, transport=data
    )
    assert report["status"] == "observed" and report["request_count"] == 1
    assert report["auth_refresh_attempted"] and report["auth_refresh_succeeded"]
    assert report["auth_error"] is None and len(reads) == 2 and len(oauth.calls) == 1
    assert oauth.calls[0][0:2] == ("POST", auth.GOOGLE_TOKEN_ENDPOINT)
    assert oauth.calls[0][2]["form"]["grant_type"] == "refresh_token"
    assert data.calls[0][2]["headers"]["Authorization"] == "Bearer synthetic-new"
    assert len(saved) == 2 and saved[-1].granted_scopes() == frozenset(STEPS_SCOPE_ORDER)
    assert saved[-1].refresh_token == (SECRET if omit else "synthetic-new-refresh")
    assert original.access_token == SECRET and not browser


@pytest.mark.parametrize("missing", STEPS_SCOPE_ORDER)
def test_steps_apply_requires_each_cached_scope_before_oauth(tmp_path, monkeypatch, missing):
    svc, saved, browser, oauth = service(
        tmp_path, scopes=tuple(s for s in STEPS_SCOPE_ORDER if s != missing), include_steps=True
    )
    monkeypatch.setattr(steps, "_google_execution_resources", lambda *a: pytest.fail("runtime"))
    data = Transport()
    report = acquire_steps(
        Settings(data_dir=tmp_path / "none"), plan(), auth_service=svc, transport=data
    )
    assert report["reason"] == "steps_grant_required" and report["request_count"] == 0
    assert not report["auth_refresh_attempted"] and not report["auth_refresh_succeeded"]
    assert len(saved) == 1 and not browser and not oauth.calls and not data.calls


@pytest.mark.parametrize(
    "failure",
    [
        "invalid_grant", "denied_401", "denied_403", "server", "transport", "malformed",
        "partial", "extra", "write_scope", "empty_scope", "scope_type", "bad_type",
        "empty_access", "missing_refresh", "storage", "protection",
    ],
)
def test_steps_refresh_failure_preserves_session_and_blocks_data(tmp_path, monkeypatch, failure):
    body = json.loads(oauth_response().body)
    if failure == "partial":
        body["scope"] = " ".join(DEFAULT_SCOPE_ORDER)
    elif failure in {"extra", "write_scope"}:
        body["scope"] += " " + (
            auth.SCOPE_SETTINGS if failure == "extra"
            else SCOPE_ACTIVITY.replace("readonly", "writeonly")
        )
    elif failure == "empty_scope":
        body["scope"] = ""
    elif failure == "scope_type":
        body["scope"] = [SCOPE_ACTIVITY]
    elif failure == "bad_type":
        body["token_type"] = "Basic"
    elif failure == "empty_access":
        body["access_token"] = ""
    reply = response(body)
    if failure == "invalid_grant":
        reply = GoogleHttpResponse(400, b'{"error":"invalid_grant"}')
    elif failure.startswith("denied_"):
        reply = GoogleHttpResponse(int(failure[-3:]), b'{}')
    elif failure == "server":
        reply = GoogleHttpResponse(503, SECRET.encode())
    elif failure == "transport":
        reply = OSError(SECRET)
    elif failure == "malformed":
        reply = response(b"{")
    svc, saved, browser, oauth = service(
        tmp_path, scopes=STEPS_SCOPE_ORDER, include_steps=True, response=reply
    )
    original = saved[0].as_storage_dict()
    if failure == "missing_refresh":
        saved[0].refresh_token = None
        original = saved[0].as_storage_dict()
    if failure in {"storage", "protection"}:

        def fail_write(_tokens):
            if failure == "protection":
                raise auth.GoogleCredentialProtectionUnavailable(SECRET)
            raise OSError(SECRET)

        svc._write_tokens = fail_write
    monkeypatch.setattr(steps, "_google_execution_resources", lambda *a: pytest.fail("runtime"))
    data = Transport()
    report = acquire_steps(
        _existing_settings(tmp_path / "none"), plan(), auth_service=svc, transport=data
    )
    assert report["reason"] == "steps_auth_failed" and report["request_count"] == 0
    assert report["auth_refresh_attempted"] and not report["auth_refresh_succeeded"]
    assert report["auth_error"] is not None and SECRET not in json.dumps(report)
    assert len(saved) == 1 and saved[0].as_storage_dict() == original
    assert len(oauth.calls) == (0 if failure == "missing_refresh" else 1)
    assert not browser and not data.calls
    assert {p.name for p in (tmp_path / "none").iterdir()} == {EXTERNAL_RUNTIME_LOCK_FILENAME}


def test_unexpected_cached_scope_stops_before_refresh(tmp_path):
    svc, saved, browser, oauth = service(
        tmp_path, scopes=(*STEPS_SCOPE_ORDER, auth.SCOPE_SETTINGS), include_steps=True
    )
    token, result = svc.load_steps_access_token(refresh_if_needed=True)
    assert not token and not result.ok and not result.refresh_attempted
    assert result.error.error_code == "scope_unexpected"
    assert len(saved) == 1 and not browser and not oauth.calls


@pytest.mark.parametrize("failure", ["partial", "protection", "replace"])
def test_steps_staged_refresh_preserves_previous_file_bytes(tmp_path, monkeypatch, failure):
    svc, _, browser, oauth = service(
        tmp_path, scopes=STEPS_SCOPE_ORDER, include_steps=True,
        response=oauth_response(DEFAULT_SCOPE_ORDER if failure == "partial" else STEPS_SCOPE_ORDER),
    )
    token_path = tmp_path / "synthetic-token-envelope.enc"
    original = b"synthetic-old-envelope"
    token_path.write_bytes(original)
    svc.token_path = token_path
    protected = []

    def protect(text, *, purpose):
        protected.append(purpose)
        if failure == "protection":
            raise auth.GoogleCredentialProtectionUnavailable(SECRET)
        return "synthetic-new-envelope"

    svc.protector = SimpleNamespace(kind="synthetic", protect=protect)
    svc._write_tokens = GoogleAuthService._write_tokens.__get__(svc)
    if failure == "replace":

        def fail_replace(_source, _target):
            raise OSError(SECRET)

        monkeypatch.setattr(Path, "replace", fail_replace)
    token, result = svc.load_steps_access_token(refresh_if_needed=True)
    assert not token and not result.ok and result.refresh_attempted
    assert token_path.read_bytes() == original and not list(tmp_path.glob(".*.tmp"))
    assert protected == ([] if failure == "partial" else ["google-tokens"])
    assert len(oauth.calls) == 1 and not browser


@pytest.mark.parametrize("status", [401, 403])
def test_steps_rejection_after_startup_refresh_never_refreshes_or_reposts(
    tmp_path, monkeypatch, status
):
    svc, saved, browser, oauth = service(
        tmp_path, scopes=STEPS_SCOPE_ORDER, include_steps=True, response=oauth_response()
    )
    data = Transport(GoogleHttpResponse(status, SECRET.encode()))
    monkeypatch.setattr(steps, "_google_execution_resources", lambda *a: pytest.fail("runtime"))
    report = acquire_steps(
        _existing_settings(tmp_path / "none"), plan(), auth_service=svc, transport=data
    )
    assert report["reason"] == "provider_rejected" and report["http_status"] == status
    assert report["auth_refresh_succeeded"] and report["request_count"] == 1
    assert len(oauth.calls) == len(data.calls) == 1 and len(saved) == 2 and not browser
    assert SECRET not in json.dumps(report)


@pytest.mark.parametrize(
    "kind", ["denied", "partial", "omitted_scope", "exchange_error", "storage"]
)
def test_steps_consent_stages_grant_preserving_previous_session(tmp_path, kind):
    reply = (
        GoogleHttpResponse(400, b'{"error":"invalid_grant"}')
        if kind == "exchange_error"
        else oauth_response(
            DEFAULT_SCOPE_ORDER if kind == "partial" else STEPS_SCOPE_ORDER,
            missing_scope=kind == "omitted_scope",
        )
    )
    svc, saved, browser, transport = service(
        tmp_path, include_steps=True, response=reply, denied=kind == "denied"
    )
    original = saved[0]
    if kind == "storage":

        def fail_write(_tokens):
            raise OSError(SECRET)

        svc._write_tokens = fail_write
    result = svc.bootstrap(force_reauth=True)
    assert not result.ok and saved == [original] and len(browser) == 1
    assert len(transport.calls) == (0 if kind == "denied" else 1)
    assert SECRET not in json.dumps(result.as_dict())


def test_successful_explicit_consent_replaces_only_after_full_grant(tmp_path):
    svc, saved, _, _ = service(tmp_path, include_steps=True, response=oauth_response())
    assert svc.bootstrap(force_reauth=True).ok
    assert len(saved) == 2 and saved[-1].granted_scopes() == frozenset(STEPS_SCOPE_ORDER)


def test_legacy_credential_without_scope_does_not_imply_activity():
    old = auth._parse_token_payload({"access_token": SECRET})
    assert old.granted_scopes() == frozenset(DEFAULT_SCOPE_ORDER)
    assert SCOPE_ACTIVITY not in old.granted_scopes()


def test_cli_dry_run_has_no_auth_runtime_or_network(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "GoogleAuthService", lambda *a, **k: pytest.fail("auth created"))
    monkeypatch.setattr(steps, "_google_execution_resources", lambda *a: pytest.fail("runtime"))
    profile = tmp_path / "must-not-exist"
    assert (
        cli.main(
            [
                "google-steps",
                "--date",
                DAY,
                "--family",
                "google-wearables",
                "--dry-run",
                "--data-dir",
                str(profile),
            ]
        )
        == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "planned" and out["coverage"] == out["pagination"] == "unknown"
    assert DAY not in json.dumps(out) and not profile.exists()


def test_documented_manual_consent_command_forwards_only_explicit_opt_in(tmp_path, monkeypatch):
    calls = []

    def fake_service(settings, **kwargs):
        calls.append((settings.data_dir, kwargs))

        def bootstrap(**options):
            calls.append(options)
            return GoogleAuthResult(
                status=GoogleAuthStatus.AUTHENTICATED, granted_scope_count=3, missing_scope_count=0
            )

        return SimpleNamespace(bootstrap=bootstrap)

    monkeypatch.setattr(cli, "GoogleAuthService", fake_service)
    profile = tmp_path / "owner-selected-synthetic-profile"
    assert (
        cli.main(["google-auth", "--include-steps", "--force-reauth", "--data-dir", str(profile)])
        == 0
    )
    assert calls == [(profile, {"include_steps": True}), {"force_reauth": True}]
    assert not profile.exists()


def test_documented_apply_command_with_missing_grant_stops_before_runtime(tmp_path, monkeypatch):
    svc, saved, browser, transport = service(tmp_path)
    def auth_factory(_settings, **kwargs):
        assert kwargs == {"include_steps": True}
        return svc

    monkeypatch.setattr(cli, "GoogleAuthService", auth_factory)
    monkeypatch.setattr(steps, "_google_execution_resources", lambda *a: pytest.fail("runtime"))
    profile = tmp_path / "owner-selected-synthetic-profile"
    assert (
        cli.main(
            [
                "google-steps",
                "--date",
                DAY,
                "--family",
                "google-wearables",
                "--apply",
                "--data-dir",
                str(profile),
            ]
        )
        == 1
    )
    assert not profile.exists() and not browser and not transport.calls and len(saved) == 1


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--apply", "--dry-run"],
        ["--apply"],
        ["--dry-run", "--family", "all-sources"],
        ["--dry-run", "--include-steps"],
    ],
)
def test_cli_invalid_steps_requests_fail_before_auth(monkeypatch, flags):
    monkeypatch.setattr(cli, "GoogleAuthService", lambda *a, **k: pytest.fail("auth created"))
    assert cli.main(["google-steps", "--date", DAY, *flags]) == 2


@pytest.mark.parametrize("day", ["2026-03-29", "2026-10-25", "2024-02-29"])
def test_civil_day_request_does_not_invent_zone_or_duration(day):
    body = plan(day).body()
    assert set(body["range"]["start"]) == {"date"}
    assert body["windowSizeDays"] == body["pageSize"] == 1
    assert body["dataSourceFamily"] == FAMILY_GOOGLE_WEARABLES
    raw = json.dumps(body)
    assert "timeZone" not in raw and "utcOffset" not in raw and "startTime" not in raw


def test_missing_grant_blocks_before_any_runtime_or_http(tmp_path, monkeypatch):
    svc, saved, _, transport = service(tmp_path)
    monkeypatch.setattr(steps, "_google_execution_resources", lambda *a: pytest.fail("runtime"))
    report = acquire_steps(
        Settings(data_dir=tmp_path / "no-create"), plan(), auth_service=svc, transport=transport
    )
    assert report["status"] == "blocked" and report["request_count"] == 0
    assert len(saved) == 1 and not transport.calls and not (tmp_path / "no-create").exists()


@pytest.mark.parametrize("code,requests", [(401, 1), (403, 1), (400, 1), (429, 3), (503, 3)])
def test_rejection_retry_budget_no_auth_recovery_or_runtime(tmp_path, monkeypatch, code, requests):
    transport = Transport(*(GoogleHttpResponse(code, SECRET.encode()) for _ in range(requests)))
    waits = []
    monkeypatch.setattr(steps, "_google_execution_resources", lambda *a: pytest.fail("runtime"))
    report = acquire_steps(
        _existing_settings(tmp_path / "none"),
        plan(),
        auth_service=granted(),
        transport=transport,
        sleeper=waits.append,
    )
    assert report["request_count"] == len(transport.calls) == requests
    assert waits == ([0.25, 0.5] if requests == 3 else [])
    assert SECRET not in json.dumps(report)


@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        {},
        {"rollupDataPoints": None},
        {"rollupDataPoints": [], "nextPageToken": "synthetic"},
        {"rollupDataPoints": [], "nextPageToken": None},
        {"rollupDataPoints": [], "nextPageToken": ""},
        {"rollupDataPoints": [], "unknown": True},
        b'{"rollupDataPoints":[],"rollupDataPoints":[]}',
    ],
)
def test_unknown_shape_or_pagination_never_creates_projection(raw):
    normalized = normalize_acquired_steps(response(raw).body, context=plan().context(1))
    assert normalized.status.value == "invalid" and not normalized.records


@pytest.mark.parametrize("kind", ["wrong_day", "partial_end", "multiple"])
def test_rejected_boundary_or_bucket_response_stays_rejected_after_replay(tmp_path, kind):
    raw = payload()
    if kind == "wrong_day":
        raw = payload(body_plan=plan("2099-03-30"))
    elif kind == "partial_end":
        raw["rollupDataPoints"][0]["civilEndTime"] = {
            "date": plan().body()["range"]["start"]["date"],
            "time": {"hours": 23, "minutes": 59, "seconds": 59},
        }
    else:
        raw["rollupDataPoints"] *= 2
    settings = _existing_settings(tmp_path / "synthetic-runtime")
    report = acquire_steps(
        settings, plan(), auth_service=granted(), transport=Transport(response(raw))
    )
    assert report["status"] == "rejected"
    paths = resolve_runtime_paths(settings)
    engine = create_sqlite_engine(paths)
    with create_session_factory(engine)() as session:
        observation = session.scalar(select(GooglePayloadObservation))
        assert observation.source_contract_version == steps.ACQUISITION_CONTRACT
        assert not session.scalar(select(func.count()).select_from(GoogleSourceRecord))
        replayed = replay_google_observations(
            session,
            payload_store=ContentAddressedGooglePayloadStore(paths.root / "artifacts"),
            observation_ids=[observation.id],
            normalization_contract_version="synthetic-replay-v2",
        )
        assert not replayed[0].records
        assert not session.scalar(select(func.count()).select_from(GoogleSourceRecord))
        assert steps.replay_context(replayed[0].observation.diagnostics_json) == plan().context(1)
    engine.dispose()


@pytest.mark.parametrize(
    "value,state",
    [
        ("0", "value"),
        (str(2**53 + 1), "value"),
        (str(2**63 - 1), "value"),
        (None, "null"),
        ("-1", "invalid"),
        (True, "invalid"),
    ],
)
def test_acquisition_exact_readback_and_immutable_request_provenance(tmp_path, value, state):
    settings = _existing_settings(tmp_path / "synthetic-runtime")
    transport = Transport(response(payload(value)))
    report = acquire_steps(settings, plan(), auth_service=granted(), transport=transport)
    assert report["coverage"] == report["pagination"] == "unknown"
    assert report["metric_states"] == {state: 1}
    method, url, request = transport.calls[0]
    assert method == "POST" and url == steps.STEPS_URL and request["json_body"] == plan().body()
    assert request["timeout"] == 30.0
    paths = resolve_runtime_paths(settings)
    engine = create_sqlite_engine(paths)
    with create_session_factory(engine)() as session:
        metric = session.scalar(select(GoogleRecordMetric))
        exact = decode_count_sum_metric(metric)
        assert exact.value == (int(value) if state == "value" else None)
        observation = session.scalar(select(GooglePayloadObservation))
        assert steps.replay_context(observation.diagnostics_json) == plan().context(1)
        run = session.get(SyncRun, observation.sync_run_id)
        assert run.stream_code == steps.ACQUISITION_CONTRACT
        assert (
            run.requested_start is run.requested_end is run.actual_start is run.actual_end is None
        )
        assert not session.scalar(select(func.count()).select_from(CoverageInterval))
        assert not session.scalar(select(func.count()).select_from(SyncStreamState))
        assert session.scalar(select(func.count()).select_from(GoogleNormalizationAttempt)) == 1
    engine.dispose()
    assert str(value) not in json.dumps(report) if state == "value" and value != "0" else True
    assert DAY not in json.dumps(report) and SECRET not in json.dumps(report)


@pytest.mark.parametrize(
    "bad", [None, [], [{"code": steps.CONTEXT_CODE}], [plan().context(1), plan().context(1)]]
)
def test_acquired_replay_context_missing_or_malformed_fails_closed(bad):
    with pytest.raises(ValueError):
        steps.replay_context(json.dumps(bad))


def test_response_oversize_never_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(steps, "_google_execution_resources", lambda *a: pytest.fail("runtime"))
    report = acquire_steps(
        _existing_settings(tmp_path / "none"),
        plan(),
        auth_service=granted(),
        transport=Transport(response(b"x" * (steps.MAX_RESPONSE_BYTES + 1))),
    )
    assert report["reason"] == "response_limit"


@pytest.mark.parametrize("error", [False, True])
def test_live_transport_read_cap_applies_to_success_and_http_error(monkeypatch, error):
    reads = []

    class Body(io.BytesIO):
        status = 200
        headers = {}

        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    body = Body(b"x" * 100)

    def fake_open(*a, **k):
        if error:
            raise HTTPError("https://synthetic.invalid", 500, "synthetic", {}, body)
        return body

    monkeypatch.setattr(auth, "urlopen", fake_open)
    reply = UrllibGoogleHttpTransport(max_response_bytes=10).request(
        "GET", "https://synthetic.invalid"
    )
    assert len(reply.body) == 11 and reads == [11]


def test_production_registries_do_not_enable_steps():
    from healthcheck.google.contracts import GOOGLE_STREAMS
    from healthcheck.google.sync import PRODUCTION_SYNC_SURFACES, parse_google_streams

    assert "steps" not in GOOGLE_STREAMS
    assert all(surface.code != "steps" for surface in PRODUCTION_SYNC_SURFACES)
    with pytest.raises(ValueError):
        parse_google_streams(["steps"])


def test_retry_success_uses_same_request_and_still_has_unknown_coverage(tmp_path):
    transport = Transport(
        OSError(SECRET),
        GoogleHttpResponse(429, SECRET.encode()),
        response({"rollupDataPoints": []}),
    )
    waits = []
    settings = _existing_settings(tmp_path / "synthetic-runtime")
    report = acquire_steps(
        settings, plan(), auth_service=granted(), transport=transport, sleeper=waits.append
    )
    assert report["status"] == "observed" and report["record_count"] == 0
    assert report["coverage"] == report["pagination"] == "unknown"
    assert report["request_count"] == 3 and waits == [0.25, 0.5]
    assert all(call[2]["json_body"] == plan().body() for call in transport.calls)
    paths = resolve_runtime_paths(settings)
    engine = create_sqlite_engine(paths)
    with create_session_factory(engine)() as session:
        observation = session.scalar(select(GooglePayloadObservation))
        assert steps.replay_context(observation.diagnostics_json) == plan().context(3)
        assert observation.parse_status == "empty"
        assert not session.scalar(select(func.count()).select_from(GoogleSourceRecord))
        assert not session.scalar(select(func.count()).select_from(CoverageInterval))
    engine.dispose()


def test_transport_unavailability_is_bounded_and_sanitized(tmp_path, monkeypatch):
    monkeypatch.setattr(steps, "_google_execution_resources", lambda *a: pytest.fail("runtime"))
    transport = Transport(*(OSError(SECRET) for _ in range(3)))
    report = acquire_steps(
        _existing_settings(tmp_path / "none"),
        plan(),
        auth_service=granted(),
        transport=transport,
        sleeper=lambda _: None,
    )
    assert report["reason"] == "provider_unavailable" and len(transport.calls) == 3
    assert SECRET not in json.dumps(report)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "malformed", "unknown_version"])
def test_recognized_acquired_observation_cannot_replay_without_valid_context(tmp_path, mutation):
    settings = _existing_settings(tmp_path / "synthetic-runtime")
    raw = response(payload()).body
    result = normalize_acquired_steps(raw, context=plan().context(1))
    contexts = () if mutation == "missing" else (plan().context(1),)
    if mutation == "duplicate":
        contexts *= 2
    elif mutation == "malformed":
        contexts = ({**plan().context(1), "coverage": "complete"},)
    elif mutation == "unknown_version":
        from dataclasses import replace

        result = replace(result, source_contract_version="google-steps-acquisition-v999")
    with steps._google_execution_resources(settings) as resources, resources.factory() as session:
        repo = google_persistence_for(session, payload_store=resources.store)
        outcome = repo.persist_result(result, payload=raw, observation_diagnostics=contexts)
        session.commit()
        count = session.scalar(select(func.count()).select_from(GoogleNormalizationAttempt))
        with pytest.raises(ValueError):
            replay_google_observations(
                session, payload_store=resources.store, observation_ids=[outcome.observation.id]
            )
        assert session.scalar(select(func.count()).select_from(GoogleNormalizationAttempt)) == count


@pytest.mark.parametrize("value", [True, 1.0])
def test_request_context_rejects_bool_and_float_integer_lookalikes(value):
    context = plan().context(1)
    context["request"]["windowSizeDays"] = value
    with pytest.raises(ValueError):
        steps.validate_context(context)


def test_later_acquired_correction_missing_and_stale_replay_preserve_history(tmp_path):
    settings = _existing_settings(tmp_path / "synthetic-runtime")
    start = datetime(2099, 4, 1, tzinfo=UTC)
    raws = [payload("9"), payload("2"), payload()]
    raws[-1]["rollupDataPoints"][0]["steps"] = {}
    for index, raw in enumerate(raws):
        report = acquire_steps(
            settings,
            plan(),
            auth_service=granted(),
            transport=Transport(response(raw)),
            clock=lambda i=index: start + timedelta(hours=i),
        )
        assert report["status"] == "observed"
    paths = resolve_runtime_paths(settings)
    engine = create_sqlite_engine(paths)
    with create_session_factory(engine)() as session:
        assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 1
        metric = session.scalar(select(GoogleRecordMetric))
        assert decode_count_sum_metric(metric).state.value == "missing"
        observations = list(
            session.scalars(
                select(GooglePayloadObservation).order_by(GooglePayloadObservation.received_at)
            )
        )
        assert len(observations) == 3
        replay_google_observations(
            session,
            payload_store=ContentAddressedGooglePayloadStore(paths.root / "artifacts"),
            observation_ids=[observations[0].id],
            normalization_contract_version="synthetic-stale-replay-v2",
        )
        session.expire_all()
        assert decode_count_sum_metric(session.scalar(select(GoogleRecordMetric))).value is None
        assert session.scalar(select(func.count()).select_from(GoogleNormalizationAttempt)) == 4
    engine.dispose()


def test_equal_epoch_acquired_conflict_does_not_publish_a_count(tmp_path):
    settings = _existing_settings(tmp_path / "synthetic-runtime")
    for count in ["1", "2"]:
        acquire_steps(
            settings,
            plan(),
            auth_service=granted(),
            transport=Transport(response(payload(count))),
            clock=lambda: datetime(2099, 4, 1, tzinfo=UTC),
        )
    engine = create_sqlite_engine(resolve_runtime_paths(settings))
    with create_session_factory(engine)() as session:
        record = session.scalar(select(GoogleSourceRecord))
        assert record.record_status == "invalid"
        repo = google_persistence_for(session)
        with pytest.raises(ValueError, match="conflicted"):
            repo.records.count_sum_for(record.id)
    engine.dispose()
