"""Synthetic owner-assisted Garmin authentication tests."""

from __future__ import annotations

import base64
import json
import logging
import sys
from pathlib import Path

import pytest
from garminconnect import Garmin
from garminconnect.client import token_file_path

from healthcheck import cli
from healthcheck.cli import build_parser
from healthcheck.config import Settings
from healthcheck.garmin.auth import (
    GarminAuthResult,
    GarminAuthService,
    GarminAuthStatus,
    GarminSessionCorruptError,
    GarminSessionProtectionUnavailable,
    WindowsUserScopedTokenProtection,
    _silence_provider_logging,
    validate_external_tokenstore,
)


class ExpiredSessionError(Exception):
    pass


class AuthenticationError(Exception):
    pass


class SyntheticTokenProtection:
    """Opaque reversible boundary used only by synthetic auth tests."""

    def protect(self, plaintext: str) -> str:
        return json.dumps({"ciphertext": base64.b64encode(plaintext.encode()).decode()})

    def unprotect(self, envelope: str) -> str:
        try:
            value = json.loads(envelope)
            return base64.b64decode(value["ciphertext"], validate=True).decode()
        except Exception as exc:
            raise GarminSessionCorruptError from exc


class FakeGarminClient:
    def __init__(self, behavior: str, **kwargs: object) -> None:
        self.behavior = behavior
        self.email = kwargs.get("email")
        self.username = self.email
        self.password = kwargs.get("password")
        self.prompt_mfa = kwargs.get("prompt_mfa")
        self.login_paths: list[str | None] = []
        self.mfa_code: str | None = None

    def login(self, *, tokenstore: str | None = None) -> tuple[str | None, object | None]:
        self.login_paths.append(tokenstore)
        if self.behavior == "expired":
            raise ExpiredSessionError("synthetic expired session with fake credential material")
        if self.behavior == "failure":
            raise AuthenticationError("synthetic authentication failure; never echo this")
        if self.behavior == "mfa_callback":
            assert callable(self.prompt_mfa)
            self.mfa_code = self.prompt_mfa()
        if self.behavior == "mfa_resume":
            return "needs_mfa", {"synthetic_state": True}
        return None, None

    def resume_login(self, state: object, code: str) -> tuple[None, None]:
        assert state == {"synthetic_state": True}
        self.mfa_code = code
        return None, None

    def dumps(self) -> str:
        return json.dumps(
            {
                "di_token": "synthetic-di-token",
                "di_refresh_token": "synthetic-refresh-token",
                "di_client_id": "synthetic-client-id",
            }
        )


class FakeFactory:
    def __init__(self, *behaviors: str) -> None:
        self.behaviors = list(behaviors)
        self.clients: list[FakeGarminClient] = []

    def __call__(self, **kwargs: object) -> FakeGarminClient:
        behavior = self.behaviors.pop(0) if self.behaviors else "success"
        client = FakeGarminClient(behavior, **kwargs)
        self.clients.append(client)
        return client


def service(
    tmp_path: Path,
    factory: FakeFactory,
    *,
    credential_values: tuple[str, str] = ("owner@example.invalid", "synthetic-password"),
    mfa_value: str = "000000",
) -> GarminAuthService:
    values = iter(credential_values)
    return GarminAuthService(
        Settings(data_dir=tmp_path / "runtime"),
        client_factory=factory,
        credential_prompt=lambda _prompt: next(values),
        mfa_prompt=lambda _prompt: mfa_value,
        session_protector=SyntheticTokenProtection(),
    )


def seed_session(auth_service: GarminAuthService, *, token: str = "synthetic-old-token") -> None:
    auth_service.tokenstore.parent.mkdir(parents=True)
    auth_service._write_protected_session(
        json.dumps({"di_token": token, "di_refresh_token": "synthetic-old-refresh"})
    )


def test_synthetic_auth_success_never_returns_credentials(tmp_path: Path) -> None:
    factory = FakeFactory("success")
    auth_service = service(tmp_path, factory)

    result = auth_service.bootstrap()

    assert result.status is GarminAuthStatus.AUTHENTICATED
    assert result.mfa == "not_needed"
    assert auth_service.tokenstore.is_file()
    assert factory.clients[0].email is None
    assert factory.clients[0].password is None
    serialized = json.dumps(result.as_dict(), sort_keys=True)
    assert "owner@example.invalid" not in serialized
    assert "synthetic-password" not in serialized
    assert "synthetic-session-only" not in serialized


def test_synthetic_mfa_callback_is_hidden_and_not_reported(tmp_path: Path) -> None:
    factory = FakeFactory("mfa_callback")
    auth_service = service(tmp_path, factory, mfa_value="synthetic-otp")

    result = auth_service.bootstrap()

    assert result.status is GarminAuthStatus.AUTHENTICATED
    assert result.mfa == "completed"
    assert factory.clients[0].mfa_code == "synthetic-otp"
    serialized = json.dumps(result.as_dict(), sort_keys=True)
    assert "synthetic-otp" not in serialized


def test_synthetic_mfa_resume_path_is_supported(tmp_path: Path) -> None:
    factory = FakeFactory("mfa_resume")
    auth_service = service(tmp_path, factory, mfa_value="synthetic-otp")

    result = auth_service.bootstrap()

    assert result.status is GarminAuthStatus.AUTHENTICATED
    assert result.mfa == "completed"
    assert factory.clients[0].mfa_code == "synthetic-otp"


def test_auth_failure_is_fixed_vocabulary_and_does_not_echo_error(tmp_path: Path) -> None:
    factory = FakeFactory("failure")
    auth_service = service(tmp_path, factory)

    result = auth_service.bootstrap()

    assert result.status is GarminAuthStatus.FAILED
    assert result.error is not None
    assert result.error.error_code == "authentication_failed"
    serialized = json.dumps(result.as_dict(), sort_keys=True)
    assert "owner@example.invalid" not in serialized
    assert "synthetic-password" not in serialized
    assert "never echo this" not in serialized


def test_expired_cached_session_falls_back_to_owner_reauth(tmp_path: Path) -> None:
    factory = FakeFactory("expired", "success")
    auth_service = service(tmp_path, factory)
    seed_session(auth_service)

    result = auth_service.bootstrap()

    assert result.status is GarminAuthStatus.AUTHENTICATED
    assert len(factory.clients) == 2
    assert factory.clients[0].email is None
    assert factory.clients[0].login_paths[0].startswith("{")
    assert factory.clients[1].login_paths == [None]
    assert auth_service.tokenstore.read_text(encoding="utf-8") != "synthetic-old-session"


def test_corrupt_cached_session_has_deterministic_owner_recovery_path(tmp_path: Path) -> None:
    factory = FakeFactory("success")
    auth_service = service(tmp_path, factory)
    auth_service.tokenstore.parent.mkdir(parents=True)
    auth_service.tokenstore.write_text("synthetic-poisoned-session", encoding="utf-8")

    client, load_result = auth_service.load_existing()

    assert client is None
    assert load_result.status is GarminAuthStatus.REAUTH_REQUIRED
    assert load_result.error is not None
    assert load_result.error.error_code == "session_corrupt"
    result = auth_service.bootstrap()
    assert result.status is GarminAuthStatus.AUTHENTICATED
    assert factory.clients[0].login_paths == [None]


def test_force_reauth_uses_external_temporary_store_and_replaces_only_on_success(
    tmp_path: Path,
) -> None:
    factory = FakeFactory("success")
    auth_service = service(tmp_path, factory)
    seed_session(auth_service)
    old_session = auth_service.tokenstore.read_text(encoding="utf-8")

    result = auth_service.bootstrap(force_reauth=True)

    assert result.status is GarminAuthStatus.AUTHENTICATED
    assert factory.clients[0].login_paths == [None]
    assert auth_service.tokenstore.read_text(encoding="utf-8") != old_session
    assert not list(auth_service.tokenstore.parent.glob(".garmin_tokens.json.*.json"))


def test_force_reauth_failure_preserves_previous_session(tmp_path: Path) -> None:
    factory = FakeFactory("failure")
    auth_service = service(tmp_path, factory)
    seed_session(auth_service)
    old_session = auth_service.tokenstore.read_text(encoding="utf-8")

    result = auth_service.bootstrap(force_reauth=True)

    assert result.status is GarminAuthStatus.FAILED
    assert auth_service.tokenstore.read_text(encoding="utf-8") == old_session
    assert factory.clients[0].login_paths == [None]
    assert not list(auth_service.tokenstore.parent.glob(".garmin_tokens.json.*.json"))


def test_force_reauth_uses_pinned_provider_file_semantics_and_replaces_session(
    tmp_path: Path,
) -> None:
    captured_tokenstores: list[str | None] = []

    def provider_factory(**kwargs: object) -> Garmin:
        provider = Garmin(**kwargs)
        provider.client.di_token = "synthetic-di-token"
        provider.client.di_refresh_token = "synthetic-refresh-token"
        provider.client.di_client_id = "synthetic-client-id"

        def local_login(*, tokenstore: str | None = None) -> tuple[None, None]:
            captured_tokenstores.append(tokenstore)
            return None, None

        provider.login = local_login
        return provider

    auth_service = GarminAuthService(
        Settings(data_dir=tmp_path / "runtime"),
        client_factory=provider_factory,
        credential_prompt=lambda prompt: (
            "synthetic-owner-value" if "email" in prompt else "synthetic-password"
        ),
        session_protector=SyntheticTokenProtection(),
    )
    seed_session(auth_service)
    old_session = auth_service.tokenstore.read_text(encoding="utf-8")

    result = auth_service.bootstrap(force_reauth=True)

    assert result.status is GarminAuthStatus.AUTHENTICATED
    assert captured_tokenstores == [None]
    non_json_path = auth_service.tokenstore.with_suffix(".tmp")
    assert token_file_path(str(non_json_path)) == non_json_path / "garmin_tokens.json"
    assert auth_service.tokenstore.is_file()
    assert auth_service.tokenstore.read_text(encoding="utf-8") != old_session
    assert not list(auth_service.tokenstore.parent.glob(".garmin_tokens.json.*.json"))


def test_force_reauth_with_pinned_provider_failure_keeps_old_session(tmp_path: Path) -> None:
    captured_tokenstores: list[str | None] = []

    def provider_factory(**kwargs: object) -> Garmin:
        provider = Garmin(**kwargs)

        def local_login(*, tokenstore: str | None = None) -> tuple[None, None]:
            captured_tokenstores.append(tokenstore)
            raise AuthenticationError("synthetic pinned-provider failure")

        provider.login = local_login
        return provider

    auth_service = GarminAuthService(
        Settings(data_dir=tmp_path / "runtime"),
        client_factory=provider_factory,
        credential_prompt=lambda _prompt: "synthetic-credential",
        session_protector=SyntheticTokenProtection(),
    )
    seed_session(auth_service)
    old_session = auth_service.tokenstore.read_text(encoding="utf-8")

    result = auth_service.bootstrap(force_reauth=True)

    assert result.status is GarminAuthStatus.FAILED
    assert auth_service.tokenstore.read_text(encoding="utf-8") == old_session
    assert captured_tokenstores == [None]
    assert not list(auth_service.tokenstore.parent.glob(".garmin_tokens.json.*.json"))


def test_pinned_provider_accepts_inline_session_without_path_semantics() -> None:
    provider = Garmin()
    provider._load_profile_and_settings = lambda: None
    provider.client._token_expires_soon = lambda: False

    result = provider.login(
        tokenstore=json.dumps(
            {
                "di_token": "synthetic-di-token",
                "di_refresh_token": "synthetic-refresh-token",
                "di_client_id": "synthetic-client-id",
            }
        )
    )

    assert result == (None, None)
    assert provider.client.di_token == "synthetic-di-token"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI regression")
def test_windows_user_scoped_protection_round_trips_and_rejects_owner_tampering() -> None:
    protection = WindowsUserScopedTokenProtection()
    plaintext = '{"di_token":"synthetic-dpapi-token"}'

    try:
        envelope = protection.protect(plaintext)
    except GarminSessionProtectionUnavailable:
        pytest.skip("Windows user DPAPI profile is unavailable in this test host")

    assert "synthetic-dpapi-token" not in envelope
    assert protection.unprotect(envelope) == plaintext
    tampered = json.loads(envelope)
    tampered["user_sid"] = f"{tampered['user_sid']}-tampered"
    with pytest.raises(GarminSessionCorruptError):
        protection.unprotect(json.dumps(tampered))


def test_provider_logging_is_silenced_and_logger_state_is_restored(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logger = logging.getLogger("garminconnect")
    original = (logger.disabled, logger.level, logger.propagate, logger.handlers[:])

    with _silence_provider_logging():
        logger.error("synthetic-token-and-private-payload")

    captured = capsys.readouterr()
    assert "synthetic-token-and-private-payload" not in captured.out + captured.err
    assert (logger.disabled, logger.level, logger.propagate, logger.handlers[:]) == original


def test_owner_cli_auth_bypasses_runtime_preparation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeAuthService:
        def __init__(self, settings: Settings, *, is_cn: bool = False) -> None:
            assert settings.data_dir == tmp_path / "runtime"
            assert is_cn is False

        def bootstrap(self, *, force_reauth: bool = False) -> GarminAuthResult:
            assert force_reauth is False
            return GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED)

    monkeypatch.setattr(cli, "GarminAuthService", FakeAuthService)
    monkeypatch.setattr(
        cli,
        "prepare_runtime",
        lambda _settings: pytest.fail("owner auth must not prepare a database runtime"),
    )

    assert cli.main(["garmin-auth", "--data-dir", str(tmp_path / "runtime")]) == 0
    assert "authenticated" in capsys.readouterr().out


def test_owner_cli_probe_without_session_is_sanitized_and_offline_from_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeAuthService:
        def __init__(self, settings: Settings, *, is_cn: bool = False) -> None:
            assert settings.data_dir == tmp_path / "runtime"
            assert is_cn is False

        def load_existing(self) -> tuple[None, GarminAuthResult]:
            return None, GarminAuthResult(status=GarminAuthStatus.REAUTH_REQUIRED)

    monkeypatch.setattr(cli, "GarminAuthService", FakeAuthService)
    monkeypatch.setattr(
        cli,
        "prepare_runtime",
        lambda _settings: pytest.fail("owner probe must not prepare a database runtime"),
    )

    result = cli.main(
        [
            "garmin-capabilities",
            "--data-dir",
            str(tmp_path / "runtime"),
            "--date",
            "2026-09-05",
        ]
    )

    assert result == 1
    output = capsys.readouterr().out
    assert '"status": "reauth_required"' in output
    assert "healthcheck.db" not in output


def test_runtime_rejects_checkout_local_auth_path(tmp_path: Path) -> None:
    checkout = Path(__file__).resolve().parents[1]

    with pytest.raises(ValueError, match="outside the checkout"):
        validate_external_tokenstore(checkout / "local-session.json")
    with pytest.raises(ValueError, match="outside the checkout"):
        GarminAuthService(Settings(data_dir=checkout / "runtime"))

    assert not (checkout / "local-session.json").exists()
    assert tmp_path.exists()


def test_cli_has_no_credential_arguments() -> None:
    parser = build_parser()
    parsed = parser.parse_args(["garmin-auth"])

    assert not hasattr(parsed, "email")
    assert not hasattr(parsed, "password")
    with pytest.raises(SystemExit):
        parser.parse_args(["garmin-auth", "--password", "synthetic-password"])
