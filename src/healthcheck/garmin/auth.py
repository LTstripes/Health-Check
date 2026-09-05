"""Owner-assisted Garmin authentication with an external token boundary.

The implementation-agent and CI path never supplies or receives owner
credentials.  The command-line entry point prompts the owner with hidden
input, delegates the actual sign-in/MFA flow to the pinned
``python-garminconnect`` client, and reports only a small safe status object.
Reusable session material is always passed to the client as a file below the
external Health-Check runtime directory; this module never reads or prints
the token file contents.
"""

from __future__ import annotations

import getpass
import logging
import secrets
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from healthcheck.config import Settings
from healthcheck.runtime import resolve_runtime_paths

AUTH_CONTRACT_VERSION = "r02-garmin-auth-spike-v1"
GARMIN_AUTH_STORAGE = "external_runtime"
GARMIN_TOKENSTORE_FILENAME = "garmin_tokens.json"


class GarminAuthStatus(StrEnum):
    """Safe high-level result states exposed by the owner command."""

    AUTHENTICATED = "authenticated"
    REAUTH_REQUIRED = "reauth_required"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class GarminSafeError:
    """A fixed-vocabulary error without provider text or private data."""

    error_class: str
    error_code: str
    http_status: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_class": self.error_class,
            "error_code": self.error_code,
            "http_status": self.http_status,
        }


@dataclass(frozen=True, slots=True)
class GarminAuthResult:
    """Sanitized auth outcome; no username, token path, or exception text."""

    status: GarminAuthStatus
    session_reused: bool = False
    mfa: str = "not_attempted"
    storage: str = GARMIN_AUTH_STORAGE
    error: GarminSafeError | None = None

    @property
    def ok(self) -> bool:
        return self.status == GarminAuthStatus.AUTHENTICATED

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": AUTH_CONTRACT_VERSION,
            "status": self.status.value,
            "session_reused": self.session_reused,
            "mfa": self.mfa,
            "storage": self.storage,
            "error": self.error.as_dict() if self.error else None,
        }


ClientFactory = Callable[..., Any]
Prompt = Callable[[str], str]


def _repository_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError("Health-Check checkout root could not be determined")


def validate_external_tokenstore(path: str | Path) -> Path:
    """Resolve an auth file and reject checkout-local or symlinked targets.

    The provider library performs its own final symlink-safe open.  This
    earlier check prevents a caller from selecting a relative path or a path
    below the checkout in the first place, including paths reached through an
    existing symlinked parent.
    """

    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raise ValueError("Garmin auth storage path must be absolute")
    for candidate in (raw, *raw.parents):
        try:
            if candidate.is_symlink():
                raise ValueError("Garmin auth storage path must not use symlinks")
        except OSError as exc:
            raise ValueError("Garmin auth storage path cannot be checked") from exc
    if raw.exists() and not raw.is_file():
        raise ValueError("Garmin auth storage path must be a regular file")
    try:
        resolved = raw.resolve()
        resolved.relative_to(_repository_root())
    except ValueError:
        return resolved
    except OSError as exc:
        raise ValueError("Garmin auth storage path cannot be resolved") from exc
    raise ValueError("Garmin auth storage must be outside the checkout")


def resolve_garmin_tokenstore(settings: Settings) -> Path:
    """Return the fixed external runtime token path without creating it."""

    runtime_root = resolve_runtime_paths(settings).root
    return validate_external_tokenstore(
        runtime_root / "garmin" / "auth" / GARMIN_TOKENSTORE_FILENAME
    )


def _safe_http_status(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    return status if isinstance(status, int) and 400 <= status <= 599 else None


def classify_garmin_error(exc: BaseException) -> GarminSafeError:
    """Map provider/runtime exceptions to safe, stable class/code pairs."""

    name = type(exc).__name__.casefold()
    status = _safe_http_status(exc)
    if status in {401, 403}:
        return GarminSafeError("authentication", "authentication_failed", status)
    if status == 404:
        return GarminSafeError("provider", "unsupported_or_not_found", status)
    if status == 429:
        return GarminSafeError("provider", "rate_limited", status)
    if status is not None and status >= 500:
        return GarminSafeError("provider", "provider_unavailable", status)
    if isinstance(exc, FileNotFoundError) or "filenotfound" in name:
        return GarminSafeError("storage", "session_missing")
    if isinstance(exc, PermissionError) or "permission" in name:
        return GarminSafeError("storage", "storage_permission")
    if isinstance(exc, ImportError) or "modulenotfound" in name:
        return GarminSafeError("runtime", "dependency_missing")
    if "expired" in name or "sessionexpired" in name:
        return GarminSafeError("authentication", "session_expired_or_unusable", status)
    if "toomanyrequests" in name or "ratelimit" in name:
        return GarminSafeError("provider", "rate_limited")
    if "notfound" in name:
        return GarminSafeError("provider", "unsupported_or_not_found")
    if "mfa" in name:
        return GarminSafeError("authentication", "mfa_failed")
    if "authentication" in name or "unauthor" in name or "credential" in name:
        return GarminSafeError("authentication", "authentication_failed")
    if (
        "connection" in name
        or "timeout" in name
        or "request" in name
        or isinstance(exc, (ConnectionError, TimeoutError))
    ):
        return GarminSafeError("provider", "provider_unavailable")
    if isinstance(exc, ValueError) or name.endswith("valueerror"):
        return GarminSafeError("input", "invalid_input")
    return GarminSafeError("provider", "provider_error")


@contextmanager
def _silence_provider_logging():
    """Prevent provider debug/error text from reaching stdout or log files."""

    names = ("garminconnect", "garminconnect.client", "garminconnect.__init__")
    saved: list[tuple[logging.Logger, bool, int, bool, list[logging.Handler]]] = []
    for name in names:
        logger = logging.getLogger(name)
        saved.append((logger, logger.disabled, logger.level, logger.propagate, logger.handlers[:]))
        logger.disabled = True
        logger.propagate = False
    try:
        yield
    finally:
        for logger, disabled, level, propagate, handlers in saved:
            logger.disabled = disabled
            logger.setLevel(level)
            logger.propagate = propagate
            logger.handlers[:] = handlers


def _default_client_factory(**kwargs: Any) -> Any:
    """Import the pinned provider only when an owner command actually runs."""

    from garminconnect import Garmin

    return Garmin(**kwargs)


class GarminAuthService:
    """Bootstrap or load one owner-local Garmin session.

    ``client_factory`` and prompts are injectable solely for synthetic tests;
    production callers use the lazy pinned library factory and hidden
    ``getpass`` prompts.  No method other than the provider's authentication
    entry points is called here.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        is_cn: bool = False,
        client_factory: ClientFactory | None = None,
        credential_prompt: Prompt | None = None,
        mfa_prompt: Prompt | None = None,
    ) -> None:
        self.tokenstore = resolve_garmin_tokenstore(settings)
        self.is_cn = is_cn
        self.client_factory = client_factory or _default_client_factory
        self.credential_prompt = credential_prompt or getpass.getpass
        self.mfa_prompt = mfa_prompt or getpass.getpass

    def bootstrap(self, *, force_reauth: bool = False) -> GarminAuthResult:
        """Reuse a valid external session, then fall back to hidden re-auth."""

        if not force_reauth and self.tokenstore.exists():
            client, cached_result = self.load_existing()
            if client is not None:
                return cached_result
            if cached_result.status is GarminAuthStatus.FAILED:
                return cached_result

        try:
            email = self.credential_prompt("Garmin email (hidden; not stored): ")
            password = self.credential_prompt("Garmin password (hidden; not stored): ")
        except (EOFError, KeyboardInterrupt):
            return GarminAuthResult(
                status=GarminAuthStatus.FAILED,
                error=GarminSafeError("interaction", "cancelled"),
            )
        except Exception:
            return GarminAuthResult(
                status=GarminAuthStatus.FAILED,
                error=GarminSafeError("interaction", "prompt_failed"),
            )
        if not isinstance(email, str) or not isinstance(password, str):
            return GarminAuthResult(
                status=GarminAuthStatus.FAILED,
                error=GarminSafeError("interaction", "credentials_missing"),
            )
        email = email.strip()
        if not email or not password:
            return GarminAuthResult(
                status=GarminAuthStatus.FAILED,
                error=GarminSafeError("interaction", "credentials_missing"),
            )
        return self._login_with_credentials(email, password, force_reauth=force_reauth)

    def load_existing(self) -> tuple[Any | None, GarminAuthResult]:
        """Load the external session without prompting or making credentials."""

        if not self.tokenstore.exists():
            return None, GarminAuthResult(
                status=GarminAuthStatus.REAUTH_REQUIRED,
                error=GarminSafeError("storage", "session_missing"),
            )
        if not self.tokenstore.is_file():
            return None, GarminAuthResult(
                status=GarminAuthStatus.FAILED,
                error=GarminSafeError("storage", "unsafe_storage_path"),
            )
        try:
            client = self._new_client()
            with _silence_provider_logging():
                client.login(tokenstore=str(self.tokenstore))
            self._forget_credentials(client)
        except Exception as exc:
            error = classify_garmin_error(exc)
            if error.error_class != "authentication" and error.error_code != "session_missing":
                return None, GarminAuthResult(
                    status=GarminAuthStatus.FAILED,
                    session_reused=True,
                    error=error,
                )
            return None, GarminAuthResult(
                status=GarminAuthStatus.REAUTH_REQUIRED,
                session_reused=True,
                error=GarminSafeError(
                    "authentication",
                    "session_expired_or_unusable",
                    _safe_http_status(exc),
                ),
            )
        return client, GarminAuthResult(
            status=GarminAuthStatus.AUTHENTICATED,
            session_reused=True,
        )

    def _new_client(
        self,
        *,
        email: str | None = None,
        password: str | None = None,
        prompt_mfa: Callable[[], str] | None = None,
    ) -> Any:
        with _silence_provider_logging():
            return self.client_factory(
                email=email,
                password=password,
                is_cn=self.is_cn,
                prompt_mfa=prompt_mfa,
                return_on_mfa=False,
                verify_login=True,
            )

    def _login_with_credentials(
        self,
        email: str,
        password: str,
        *,
        force_reauth: bool,
    ) -> GarminAuthResult:
        mfa_used = False
        login_tokenstore = self.tokenstore
        temporary_tokenstore: Path | None = None

        def prompt_mfa() -> str:
            nonlocal mfa_used
            mfa_used = True
            try:
                code = self.mfa_prompt("Garmin MFA code (hidden; not stored): ")
            except (EOFError, KeyboardInterrupt) as exc:
                raise GarminAuthInteractionError from exc
            except Exception as exc:
                raise GarminAuthInteractionError from exc
            if not isinstance(code, str) or not code.strip():
                raise GarminAuthInteractionError
            return code.strip()

        client: Any | None = None
        try:
            if force_reauth:
                temporary_tokenstore = validate_external_tokenstore(
                    self.tokenstore.with_name(
                        f".{self.tokenstore.stem}.{secrets.token_hex(16)}.json"
                    )
                )
                login_tokenstore = temporary_tokenstore
            client = self._new_client(
                email=email,
                password=password,
                prompt_mfa=prompt_mfa,
            )
            with _silence_provider_logging():
                login_result = client.login(tokenstore=str(login_tokenstore))
                if (
                    isinstance(login_result, tuple)
                    and login_result
                    and login_result[0] == "needs_mfa"
                ):
                    mfa_used = True
                    client.resume_login(
                        login_result[1] if len(login_result) > 1 else None,
                        prompt_mfa(),
                    )
            if not login_tokenstore.is_file():
                provider_client = getattr(client, "client", None)
                dump = getattr(provider_client, "dump", None)
                if callable(dump):
                    with _silence_provider_logging():
                        dump(str(login_tokenstore))
            if not login_tokenstore.is_file():
                return GarminAuthResult(
                    status=GarminAuthStatus.FAILED,
                    mfa="completed" if mfa_used else "not_needed",
                    error=GarminSafeError("storage", "session_not_persisted"),
                )
            if temporary_tokenstore is not None:
                temporary_tokenstore.replace(self.tokenstore)
            self._forget_credentials(client)
            return GarminAuthResult(
                status=GarminAuthStatus.AUTHENTICATED,
                mfa="completed" if mfa_used else "not_needed",
            )
        except GarminAuthInteractionError:
            return GarminAuthResult(
                status=GarminAuthStatus.FAILED,
                mfa="required" if mfa_used else "not_attempted",
                error=GarminSafeError("interaction", "cancelled"),
            )
        except Exception as exc:
            error = classify_garmin_error(exc)
            return GarminAuthResult(
                status=GarminAuthStatus.FAILED,
                mfa="completed" if mfa_used else "not_attempted",
                error=error,
            )
        finally:
            if client is not None:
                self._forget_credentials(client)
            if temporary_tokenstore is not None and temporary_tokenstore.exists():
                try:
                    temporary_tokenstore.unlink()
                except OSError:
                    pass
            email = ""
            password = ""

    @staticmethod
    def _forget_credentials(client: Any) -> None:
        """Reduce the in-memory credential lifetime after each provider call."""

        for attribute in ("email", "password", "username"):
            if hasattr(client, attribute):
                try:
                    setattr(client, attribute, None)
                except Exception:
                    pass


class GarminAuthInteractionError(Exception):
    """Internal non-sensitive marker for cancelled/empty hidden prompts."""


__all__ = [
    "AUTH_CONTRACT_VERSION",
    "GARMIN_AUTH_STORAGE",
    "GARMIN_TOKENSTORE_FILENAME",
    "GarminAuthResult",
    "GarminAuthService",
    "GarminAuthStatus",
    "GarminSafeError",
    "classify_garmin_error",
    "resolve_garmin_tokenstore",
    "validate_external_tokenstore",
]
