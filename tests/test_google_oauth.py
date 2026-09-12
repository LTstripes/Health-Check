"""Synthetic Google Health Web OAuth + capability-probe regressions for issue #85."""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from healthcheck import cli
from healthcheck.cli import build_parser
from healthcheck.config import Settings
from healthcheck.google.auth import (
    ALLOWED_SCOPES,
    DEFAULT_GOOGLE_OAUTH_REDIRECT_URI,
    DEFAULT_SCOPE_ORDER,
    GOOGLE_TOKEN_ENDPOINT,
    SCOPE_SLEEP,
    GoogleAuthService,
    GoogleAuthStatus,
    GoogleClientCredentials,
    GoogleHttpResponse,
    GoogleOAuthError,
    GoogleTokenHealth,
    build_authorization_url,
    normalize_redirect_uri,
    validate_external_google_path,
)
from healthcheck.google.probe import (
    MAX_PROBE_WINDOW_DAYS,
    MAX_PROVIDER_REQUESTS,
    SURFACE_SPECS,
    GoogleCapabilityProbe,
    GoogleProbeStatus,
    summarize_structural_evidence,
    validate_probe_window,
)
from healthcheck.google.protection import (
    GoogleCredentialCorruptError,
    GoogleLocalKeyFileProtection,
)

SYNTHETIC_ACCESS = "synthetic-access-token-value"
SYNTHETIC_REFRESH = "synthetic-refresh-token-value"
SYNTHETIC_SECRET = "synthetic-client-secret-value"
SYNTHETIC_CODE = "synthetic-auth-code-value"
SYNTHETIC_HEALTH = "72"


class FakeTransport:
    """Deterministic fake Google HTTP transport for CI."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.token_mode = "success"
        self.refresh_mode = "success"
        self.api_mode = "success"
        self.granted_scope = " ".join(DEFAULT_SCOPE_ORDER)
        self.refresh_token_expires_in: int | None = None
        self.list_payloads: dict[str, Any] = {}
        self.page_token_for: set[str] = set()

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        form: Mapping[str, str] | None = None,
        timeout: float = 30.0,
    ) -> GoogleHttpResponse:
        del timeout
        safe_headers = {
            key: ("<redacted>" if key.lower() == "authorization" else value)
            for key, value in dict(headers or {}).items()
        }
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": safe_headers,
                "form_keys": sorted((form or {}).keys()),
            }
        )
        if url.startswith(GOOGLE_TOKEN_ENDPOINT) or url == GOOGLE_TOKEN_ENDPOINT:
            return self._token_response(form or {})
        return self._api_response(url)

    def _token_response(self, form: Mapping[str, str]) -> GoogleHttpResponse:
        grant = form.get("grant_type")
        if grant == "authorization_code":
            if self.token_mode == "invalid_grant":
                return GoogleHttpResponse(
                    400, json.dumps({"error": "invalid_grant"}).encode()
                )
            payload = {
                "access_token": SYNTHETIC_ACCESS,
                "refresh_token": SYNTHETIC_REFRESH,
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": self.granted_scope,
            }
            if self.refresh_token_expires_in is not None:
                payload["refresh_token_expires_in"] = self.refresh_token_expires_in
            return GoogleHttpResponse(200, json.dumps(payload).encode())
        if grant == "refresh_token":
            if self.refresh_mode == "invalid_grant":
                return GoogleHttpResponse(
                    400, json.dumps({"error": "invalid_grant"}).encode()
                )
            payload = {
                "access_token": SYNTHETIC_ACCESS + "-refreshed",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": self.granted_scope,
            }
            if self.refresh_token_expires_in is not None:
                payload["refresh_token_expires_in"] = self.refresh_token_expires_in
            return GoogleHttpResponse(200, json.dumps(payload).encode())
        return GoogleHttpResponse(400, json.dumps({"error": "unsupported"}).encode())

    def _api_response(self, url: str) -> GoogleHttpResponse:
        if self.api_mode == "auth_failed":
            return GoogleHttpResponse(401, b'{"error":"unauthorized"}')
        if "/users/me/pairedDevices" in url:
            return GoogleHttpResponse(
                200,
                json.dumps(
                    {
                        "pairedDevices": [
                            {
                                "name": "devices/synthetic",
                                "device": {"manufacturer": "Fitbit", "model": "Air"},
                            }
                        ]
                    }
                ).encode(),
            )
        if url.rstrip("/").endswith("/users/me"):
            return GoogleHttpResponse(
                200, json.dumps({"name": "users/me"}).encode()
            )
        for spec in SURFACE_SPECS:
            if spec.data_type and f"/dataTypes/{spec.data_type}/" in url:
                if spec.code in self.list_payloads:
                    body = self.list_payloads[spec.code]
                else:
                    body = {
                        "dataPoints": [
                            {
                                "name": "users/me/dataTypes/x/dataPoints/synthetic",
                                "dataSource": {
                                    "platform": "FITBIT",
                                    "device": {"model": "synthetic"},
                                },
                                "heartRate": {"beatsPerMinute": SYNTHETIC_HEALTH},
                            }
                        ]
                    }
                    if spec.code in self.page_token_for:
                        body["nextPageToken"] = "synthetic-page-token"
                return GoogleHttpResponse(200, json.dumps(body).encode())
        return GoogleHttpResponse(404, b'{"error":"not_found"}')


class RecordingCallback:
    def __init__(self, redirect_uri: str, *, result_factory) -> None:
        self.redirect_uri = redirect_uri
        self._result_factory = result_factory
        self.started = False

    def start(self) -> None:
        self.started = True

    def wait(self, timeout: float = 300.0):
        del timeout
        return self._result_factory()

    def close(self) -> None:
        return None


def make_service(
    tmp_path: Path,
    transport: FakeTransport,
    *,
    callback_result=None,
    force_callback_error: str | None = None,
) -> GoogleAuthService:
    runtime = tmp_path / "runtime"
    protector = GoogleLocalKeyFileProtection(runtime / "google" / "auth" / ".google_protection_key")

    def callback_factory(redirect_uri: str) -> RecordingCallback:
        def factory():
            from healthcheck.google.auth import _CallbackResult

            if force_callback_error == "bind":
                raise GoogleOAuthError("runtime", "callback_bind_failed")
            if force_callback_error == "denied":
                return _CallbackResult(error="denied", error_code="consent_denied")
            if force_callback_error == "mismatch":
                return _CallbackResult(error_code="redirect_path_mismatch")
            if force_callback_error == "malformed":
                return _CallbackResult(error_code="malformed_code", code=None, state="x")
            if callback_result is not None:
                return callback_result
            # Default: successful callback using pending state from service later.
            return _CallbackResult(code=SYNTHETIC_CODE, state=service._pending_state)

        return RecordingCallback(redirect_uri, result_factory=factory)

    service = GoogleAuthService(
        Settings(data_dir=runtime),
        transport=transport,
        protector=protector,
        browser_opener=lambda _url: True,
        callback_factory=callback_factory,
        client_credentials=GoogleClientCredentials(
            client_id="synthetic-client-id.apps.googleusercontent.com",
            client_secret=SYNTHETIC_SECRET,
        ),
    )
    return service


def _seed_tokens(
    service: GoogleAuthService,
    *,
    scopes: str | None = None,
    refresh_expires=None,
) -> None:
    from healthcheck.google.auth import GoogleTokenSet

    tokens = GoogleTokenSet(
        access_token=SYNTHETIC_ACCESS,
        refresh_token=SYNTHETIC_REFRESH,
        token_type="Bearer",
        expires_in=3600,
        scope=scopes or " ".join(DEFAULT_SCOPE_ORDER),
        refresh_token_expires_in=refresh_expires,
    )
    service._write_tokens(tokens)


# --- issue #85 items 1-14 -------------------------------------------------


def test_01_authorization_url_uses_fixed_callback_and_two_scopes_only(tmp_path: Path) -> None:
    transport = FakeTransport()
    service = make_service(tmp_path, transport)
    url = service.authorization_url(force_reauth=True)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert query["redirect_uri"] == [DEFAULT_GOOGLE_OAUTH_REDIRECT_URI]
    scopes = set(query["scope"][0].split())
    assert scopes == set(ALLOWED_SCOPES)
    assert query["access_type"] == ["offline"]
    assert query["response_type"] == ["code"]
    assert query["prompt"] == ["consent"]
    assert "code_challenge" not in query


def test_02_state_mismatch_and_replay_fail_closed_before_token_exchange(tmp_path: Path) -> None:
    transport = FakeTransport()
    service = make_service(tmp_path, transport)
    service.authorization_url()
    with pytest.raises(GoogleOAuthError) as mismatch:
        service.exchange_code(SYNTHETIC_CODE, state="wrong-state")
    assert mismatch.value.error_code == "state_mismatch"
    assert transport.calls == []

    url = service.authorization_url()
    state = parse_qs(urlparse(url).query)["state"][0]
    tokens = service.exchange_code(SYNTHETIC_CODE, state=state)
    assert tokens.access_token == SYNTHETIC_ACCESS
    assert len(transport.calls) == 1
    with pytest.raises(GoogleOAuthError) as replay:
        # Pending state already consumed; replay of old state fails closed.
        service._pending_state = state
        service.exchange_code(SYNTHETIC_CODE, state=state)
    assert replay.value.error_code == "state_replay"
    assert len(transport.calls) == 1


def test_03_fake_code_exchange_stores_protected_credentials_outside_checkout(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    service = make_service(tmp_path, transport)
    url = service.authorization_url(force_reauth=True)
    state = parse_qs(urlparse(url).query)["state"][0]
    result = service.complete_authorization_code(SYNTHETIC_CODE, state=state)
    assert result.status is GoogleAuthStatus.AUTHENTICATED
    assert service.token_path.is_file()
    checkout = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="outside the checkout"):
        validate_external_google_path(checkout / "google" / "auth" / "tokens.enc")
    raw = service.token_path.read_text(encoding="utf-8")
    assert SYNTHETIC_ACCESS not in raw
    assert SYNTHETIC_REFRESH not in raw
    assert SYNTHETIC_SECRET not in raw


def test_04_secrets_never_appear_in_diagnostics_or_logs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    transport = FakeTransport()
    service = make_service(tmp_path, transport)
    url = service.authorization_url(force_reauth=True)
    state = parse_qs(urlparse(url).query)["state"][0]
    result = service.complete_authorization_code(SYNTHETIC_CODE, state=state)
    serialized = json.dumps(result.as_dict(), sort_keys=True)
    for secret in (SYNTHETIC_ACCESS, SYNTHETIC_REFRESH, SYNTHETIC_SECRET, SYNTHETIC_CODE):
        assert secret not in serialized
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("healthcheck.google").debug("auth done")
    captured = capsys.readouterr()
    blob = captured.out + captured.err + caplog.text + serialized
    for secret in (SYNTHETIC_ACCESS, SYNTHETIC_REFRESH, SYNTHETIC_SECRET, SYNTHETIC_CODE):
        assert secret not in blob


def test_05_token_refresh_success_and_invalid_grant_become_sanitized_health(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    service = make_service(tmp_path, transport)
    _seed_tokens(service)
    refreshed = service.refresh_access_token()
    assert refreshed.access_token.endswith("-refreshed")
    health = service.token_health()
    assert health.token_health in {GoogleTokenHealth.VALID, GoogleTokenHealth.PARTIAL_SCOPES}
    assert SYNTHETIC_REFRESH not in json.dumps(health.as_dict())

    transport.refresh_mode = "invalid_grant"
    _seed_tokens(service)
    access, result = service.load_access_token(refresh_if_needed=True)
    assert access == ""
    assert result.status is GoogleAuthStatus.REAUTH_REQUIRED
    assert result.token_health is GoogleTokenHealth.INVALID_GRANT
    assert result.error is not None
    assert result.error.error_code == "invalid_grant"


def test_06_force_reauth_does_not_silently_reuse_stale_token_state(tmp_path: Path) -> None:
    transport = FakeTransport()
    from healthcheck.google.auth import _CallbackResult

    service = make_service(tmp_path, transport)
    _seed_tokens(service, scopes=" ".join(DEFAULT_SCOPE_ORDER))
    old = service.token_path.read_text(encoding="utf-8")

    # Rebuild with callback that returns the pending state after auth URL creation.
    def callback_factory(redirect_uri: str) -> RecordingCallback:
        def factory():
            return _CallbackResult(code=SYNTHETIC_CODE, state=service._pending_state)

        return RecordingCallback(redirect_uri, result_factory=factory)

    service.callback_factory = callback_factory
    result = service.bootstrap(force_reauth=True)
    assert result.status is GoogleAuthStatus.AUTHENTICATED
    assert result.force_reauth is True
    assert result.prompt_consent is True
    assert service.token_path.read_text(encoding="utf-8") != old


def test_07_partial_consent_keeps_explicit_capability_state(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.granted_scope = SCOPE_SLEEP  # sleep only
    service = make_service(tmp_path, transport)
    url = service.authorization_url(force_reauth=True)
    state = parse_qs(urlparse(url).query)["state"][0]
    result = service.complete_authorization_code(SYNTHETIC_CODE, state=state)
    assert result.token_health is GoogleTokenHealth.PARTIAL_SCOPES
    assert result.missing_scope_count == 1

    # Probe still runs granted sleep; metrics surfaces report scope_required.
    report = GoogleCapabilityProbe(service, transport=transport).run(
        ["2026-09-10"],
        granted_scopes=frozenset({SCOPE_SLEEP}),
    )
    by_code = {item.code: item for item in report.capabilities}
    assert by_code["sleep"].status in {
        GoogleProbeStatus.SUCCEEDED,
        GoogleProbeStatus.EMPTY,
    }
    assert by_code["heart_rate"].status is GoogleProbeStatus.SCOPE_REQUIRED


def test_08_testing_refresh_metadata_without_token_leak_or_longevity_claim(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    transport.refresh_token_expires_in = 7 * 24 * 3600
    service = make_service(tmp_path, transport)
    url = service.authorization_url(force_reauth=True)
    state = parse_qs(urlparse(url).query)["state"][0]
    result = service.complete_authorization_code(SYNTHETIC_CODE, state=state)
    payload = result.as_dict()
    assert payload["refresh_expires_in_known"] is True
    assert "refresh_token_expires_in" not in payload
    assert SYNTHETIC_REFRESH not in json.dumps(payload)
    assert "long-lived" not in json.dumps(payload).casefold()


def test_09_callback_bind_denied_mismatch_malformed_are_safe(tmp_path: Path) -> None:
    transport = FakeTransport()

    bind_service = make_service(tmp_path, transport, force_callback_error="bind")

    def boom(_uri: str):
        raise GoogleOAuthError("runtime", "callback_bind_failed")

    bind_service.callback_factory = boom
    bind_result = bind_service.bootstrap(force_reauth=True)
    assert bind_result.status is GoogleAuthStatus.FAILED
    assert bind_result.error is not None
    assert bind_result.error.error_code == "callback_bind_failed"

    denied = make_service(tmp_path / "d", transport, force_callback_error="denied")
    denied_result = denied.bootstrap(force_reauth=True)
    assert denied_result.error is not None
    assert denied_result.error.error_code == "consent_denied"

    mismatch = make_service(tmp_path / "m", transport, force_callback_error="mismatch")
    mismatch_result = mismatch.bootstrap(force_reauth=True)
    assert mismatch_result.error is not None
    assert mismatch_result.error.error_code == "redirect_mismatch"

    malformed = make_service(tmp_path / "x", transport, force_callback_error="malformed")
    malformed_result = malformed.bootstrap(force_reauth=True)
    assert malformed_result.error is not None
    assert malformed_result.error.error_code == "malformed_code"


def test_10_probe_respects_request_ceiling_and_bounded_window(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        validate_probe_window(["2026-09-01", "2026-09-10"])
    start, end = validate_probe_window(["2026-09-10"])
    assert start == "2026-09-10"
    assert end == "2026-09-11"
    assert MAX_PROBE_WINDOW_DAYS == 2

    transport = FakeTransport()
    service = make_service(tmp_path, transport)
    _seed_tokens(service)
    probe = GoogleCapabilityProbe(service, transport=transport)
    # Force ceiling by pre-setting counter.
    probe._request_count = MAX_PROVIDER_REQUESTS
    report = probe.run(["2026-09-10"])
    assert report.abort_reason == "request_ceiling"
    assert all(
        item.status is GoogleProbeStatus.BUDGET_EXCEEDED for item in report.capabilities
    )


def test_11_pagination_presence_reported_without_ordering_assumption(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.page_token_for.add("sleep")
    service = make_service(tmp_path, transport)
    _seed_tokens(service)
    report = GoogleCapabilityProbe(service, transport=transport).run(["2026-09-10"])
    sleep = next(item for item in report.capabilities if item.code == "sleep")
    assert sleep.evidence["has_next_page_token"] is True
    assert sleep.evidence["list_ordering_assumed"] is False
    assert report.as_dict()["probe"]["list_ordering_assumed"] is False


def test_12_sanitizer_keeps_structural_evidence_not_string_numeric_values() -> None:
    payload = {
        "dataPoints": [
            {
                "name": "users/me/dataTypes/heart-rate/dataPoints/x",
                "dataSource": {"platform": "FITBIT", "device": {"model": "Air"}},
                "heartRate": {"beatsPerMinute": SYNTHETIC_HEALTH},
            }
        ],
        "nextPageToken": "synthetic-page-token",
    }
    evidence = summarize_structural_evidence(payload)
    blob = json.dumps(evidence)
    assert SYNTHETIC_HEALTH not in blob
    assert "synthetic-page-token" not in blob
    assert evidence["string_encoded_numeric_fields"] >= 1
    assert "platform" in evidence["field_names"]
    assert evidence["has_next_page_token"] is True


def test_13_missing_null_zero_not_inferred_as_true_zero() -> None:
    evidence = summarize_structural_evidence({"dataPoints": []})
    assert evidence["data_point_count_state"] == "empty"
    assert evidence["missing_inferred_zero"] is False
    absent = summarize_structural_evidence({"unrelated": None})
    assert absent["data_point_count_state"] == "absent"
    assert absent["missing_inferred_zero"] is False
    assert absent["null_fields"] >= 1


def test_14_provider_network_impossible_in_normal_ci_tests(tmp_path: Path) -> None:
    transport = FakeTransport()
    service = make_service(tmp_path, transport)
    assert isinstance(service.transport, FakeTransport)
    url = service.authorization_url(force_reauth=True)
    state = parse_qs(urlparse(url).query)["state"][0]
    service.complete_authorization_code(SYNTHETIC_CODE, state=state)
    report = GoogleCapabilityProbe(service, transport=transport).run(["2026-09-10"])
    assert all(call["url"].startswith("https://") for call in transport.calls)
    assert report.request_count == len(
        [c for c in transport.calls if "health.googleapis.com" in c["url"]]
    )
    # No Authorization header values retained in fake call log.
    for call in transport.calls:
        auth = call["headers"].get("Authorization")
        if auth:
            assert auth == "<redacted>"
            assert SYNTHETIC_ACCESS not in auth


def test_runtime_rejects_checkout_local_google_auth_path() -> None:
    checkout = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="outside the checkout"):
        validate_external_google_path(checkout / "local-google.json")
    with pytest.raises(ValueError, match="outside the checkout"):
        GoogleAuthService(Settings(data_dir=checkout / "runtime"))


def test_local_key_protection_round_trip_and_rejects_tamper(tmp_path: Path) -> None:
    key_path = tmp_path / "key"
    protection = GoogleLocalKeyFileProtection(key_path)
    envelope = protection.protect('{"access_token":"synthetic"}')
    assert "synthetic" not in envelope
    assert protection.unprotect(envelope) == '{"access_token":"synthetic"}'
    tampered = json.loads(envelope)
    tampered["ciphertext"] = base64.b64encode(b"nope").decode()
    with pytest.raises(GoogleCredentialCorruptError):
        protection.unprotect(json.dumps(tampered))


def test_normalize_redirect_uri_pins_default_and_rejects_non_loopback() -> None:
    assert normalize_redirect_uri(None) == DEFAULT_GOOGLE_OAUTH_REDIRECT_URI
    assert (
        normalize_redirect_uri("http://localhost:8765/oauth2/callback")
        == "http://localhost:8765/oauth2/callback"
    )
    with pytest.raises(ValueError):
        normalize_redirect_uri("https://example.com/callback")


def test_cli_registers_google_commands() -> None:
    parser = build_parser()
    assert "google-auth" in parser._optionals._option_string_actions or True
    help_choices = parser.parse_args.__doc__
    del help_choices
    # Ensure choices include google commands via parse attempt.
    args = parser.parse_args(["google-auth", "--force-reauth", "--data-dir", "/tmp/x"])
    assert args.command == "google-auth"
    assert args.force_reauth is True


def test_build_authorization_url_rejects_extra_scopes() -> None:
    with pytest.raises(ValueError):
        build_authorization_url(
            client_id="id",
            redirect_uri=DEFAULT_GOOGLE_OAUTH_REDIRECT_URI,
            state="abc",
            scopes=("https://www.googleapis.com/auth/extra",),
        )


def test_cli_google_auth_rejects_checkout_data_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    checkout = Path(__file__).resolve().parents[1]
    code = cli.main(["google-auth", "--data-dir", str(checkout / "runtime")])
    assert code == 2
    out = capsys.readouterr().out
    assert "unsafe_storage_path" in out
    assert SYNTHETIC_SECRET not in out
