"""Synthetic owner-assisted Garmin authentication tests."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from healthcheck import cli
from healthcheck.cli import build_parser
from healthcheck.config import Settings
from healthcheck.garmin.auth import (
    GarminAuthResult,
    GarminAuthService,
    GarminAuthStatus,
    _silence_provider_logging,
    validate_external_tokenstore,
)


class ExpiredSessionError(Exception):
    pass


class AuthenticationError(Exception):
    pass


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
        self._write_session(tokenstore)
        return None, None

    def resume_login(self, state: object, code: str) -> tuple[None, None]:
        assert state == {"synthetic_state": True}
        self.mfa_code = code
        self._write_session(self.login_paths[-1])
        return None, None

    @staticmethod
    def _write_session(tokenstore: str | None) -> None:
        assert tokenstore is not None
        path = Path(tokenstore)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic-session-only", encoding="utf-8")


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
    auth_service.tokenstore.parent.mkdir(parents=True)
    auth_service.tokenstore.write_text("synthetic-old-session", encoding="utf-8")

    result = auth_service.bootstrap()

    assert result.status is GarminAuthStatus.AUTHENTICATED
    assert len(factory.clients) == 2
    assert factory.clients[0].email is None
    assert auth_service.tokenstore.read_text(encoding="utf-8") == "synthetic-session-only"


def test_force_reauth_uses_external_temporary_store_and_replaces_only_on_success(
    tmp_path: Path,
) -> None:
    factory = FakeFactory("success")
    auth_service = service(tmp_path, factory)
    auth_service.tokenstore.parent.mkdir(parents=True)
    auth_service.tokenstore.write_text("synthetic-old-session", encoding="utf-8")

    result = auth_service.bootstrap(force_reauth=True)

    assert result.status is GarminAuthStatus.AUTHENTICATED
    assert Path(factory.clients[0].login_paths[0]) != auth_service.tokenstore
    assert auth_service.tokenstore.read_text(encoding="utf-8") == "synthetic-session-only"
    assert not list(auth_service.tokenstore.parent.glob("*.tmp"))


def test_force_reauth_failure_preserves_previous_session(tmp_path: Path) -> None:
    factory = FakeFactory("failure")
    auth_service = service(tmp_path, factory)
    auth_service.tokenstore.parent.mkdir(parents=True)
    auth_service.tokenstore.write_text("synthetic-old-session", encoding="utf-8")

    result = auth_service.bootstrap(force_reauth=True)

    assert result.status is GarminAuthStatus.FAILED
    assert auth_service.tokenstore.read_text(encoding="utf-8") == "synthetic-old-session"
    assert not list(auth_service.tokenstore.parent.glob("*.tmp"))


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
