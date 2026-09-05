"""Owner-assisted Garmin authentication with protected external session state.

The implementation-agent and CI path never supplies or receives owner
credentials.  The command-line entry point prompts the owner with hidden
input, delegates the actual sign-in/MFA flow to the pinned
``python-garminconnect`` client, and reports only a small safe status object.

The provider accepts an inline JSON token snapshot, so plaintext token material
never has to be written to a temporary provider path.  The canonical session
file is a Windows-user-scoped DPAPI envelope stored outside the checkout.
"""

from __future__ import annotations

import base64
import ctypes
import getpass
import json
import logging
import os
import secrets
import sys
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from healthcheck.config import Settings
from healthcheck.runtime import resolve_runtime_paths

AUTH_CONTRACT_VERSION = "r02-garmin-auth-spike-v1"
GARMIN_AUTH_STORAGE = "external_runtime"
GARMIN_TOKENSTORE_FILENAME = "garmin_tokens.json"
GARMIN_SESSION_PROTECTION = "windows_user_dpapi"
_DPAPI_ENVELOPE_FORMAT = "healthcheck-garmin-dpapi-v1"
_MAX_SESSION_TEXT = 64 * 1024


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


class GarminSessionCorruptError(ValueError):
    """The owner-local protected session cannot be safely used."""


class GarminSessionProtectionUnavailable(RuntimeError):
    """The required Windows user-scoped protection API is unavailable."""


class GarminSessionProtection(Protocol):
    """Small injectable boundary for synthetic auth tests."""

    def protect(self, plaintext: str) -> str:
        """Return a protected envelope for one provider token snapshot."""

    def unprotect(self, envelope: str) -> str:
        """Return one provider token snapshot or raise a safe local error."""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [
        ("Sid", ctypes.c_void_p),
        ("Attributes", wintypes.DWORD),
    ]


class _TokenUser(ctypes.Structure):
    _fields_ = [("User", _SidAndAttributes)]


def _windows_library(name: str) -> Any:
    if sys.platform != "win32":
        raise GarminSessionProtectionUnavailable("Windows protection is required")
    try:
        return ctypes.WinDLL(name, use_last_error=True)
    except OSError as exc:
        raise GarminSessionProtectionUnavailable("Windows protection API unavailable") from exc


def _current_windows_user_sid() -> str:
    """Resolve the current process owner SID without using a username."""

    if sys.platform != "win32":
        raise GarminSessionProtectionUnavailable("Windows user protection is required")
    advapi32 = _windows_library("advapi32.dll")
    kernel32 = _windows_library("kernel32.dll")
    token = wintypes.HANDLE()
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise GarminSessionProtectionUnavailable("Windows owner token unavailable")
    try:
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        advapi32.GetTokenInformation.restype = wintypes.BOOL
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if size.value < ctypes.sizeof(_TokenUser):
            raise GarminSessionProtectionUnavailable("Windows owner SID unavailable")
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token,
            1,
            ctypes.cast(buffer, wintypes.LPVOID),
            size,
            ctypes.byref(size),
        ):
            raise GarminSessionProtectionUnavailable("Windows owner SID unavailable")
        user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
        if not user.User.Sid:
            raise GarminSessionProtectionUnavailable("Windows owner SID unavailable")
        advapi32.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
        sid_text = ctypes.c_wchar_p()
        if not advapi32.ConvertSidToStringSidW(user.User.Sid, ctypes.byref(sid_text)):
            raise GarminSessionProtectionUnavailable("Windows owner SID unavailable")
        try:
            if not sid_text.value:
                raise GarminSessionProtectionUnavailable("Windows owner SID unavailable")
            return sid_text.value
        finally:
            _local_free(kernel32, sid_text)
    finally:
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(token)


def _local_free(kernel32: Any, pointer: Any) -> None:
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.LocalFree(ctypes.cast(pointer, ctypes.c_void_p))


def _blob_from_bytes(value: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(value)
    blob = _DataBlob(
        len(value),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return blob, buffer


def _dpapi_protect(value: bytes) -> bytes:
    crypt32 = _windows_library("crypt32.dll")
    kernel32 = _windows_library("kernel32.dll")
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_wchar_p,
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    input_blob, input_buffer = _blob_from_bytes(value)
    output_blob = _DataBlob()
    if not crypt32.CryptProtectData(
        ctypes.byref(input_blob), None, None, None, None, 0x1, ctypes.byref(output_blob)
    ):
        del input_buffer
        raise GarminSessionProtectionUnavailable("Windows session protection failed")
    del input_buffer
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        _local_free(kernel32, output_blob.pbData)


def _dpapi_unprotect(value: bytes) -> bytes:
    crypt32 = _windows_library("crypt32.dll")
    kernel32 = _windows_library("kernel32.dll")
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    input_blob, input_buffer = _blob_from_bytes(value)
    output_blob = _DataBlob()
    description = ctypes.c_wchar_p()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        ctypes.byref(description),
        None,
        None,
        None,
        0x1,
        ctypes.byref(output_blob),
    ):
        del input_buffer
        raise GarminSessionCorruptError("Windows session ciphertext is invalid")
    del input_buffer
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        _local_free(kernel32, output_blob.pbData)
        if description:
            _local_free(kernel32, description)


class WindowsUserScopedTokenProtection:
    """Protect token snapshots with the current Windows user's DPAPI key."""

    def protect(self, plaintext: str) -> str:
        if not isinstance(plaintext, str) or not plaintext or len(plaintext) > _MAX_SESSION_TEXT:
            raise GarminSessionCorruptError("provider session snapshot is invalid")
        sid = _current_windows_user_sid()
        ciphertext = _dpapi_protect(plaintext.encode("utf-8"))
        return json.dumps(
            {
                "format": _DPAPI_ENVELOPE_FORMAT,
                "user_sid": sid,
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def unprotect(self, envelope: str) -> str:
        if not isinstance(envelope, str) or not envelope or len(envelope) > _MAX_SESSION_TEXT:
            raise GarminSessionCorruptError("protected session envelope is invalid")
        try:
            value = json.loads(envelope)
        except (TypeError, ValueError) as exc:
            raise GarminSessionCorruptError("protected session envelope is invalid") from exc
        if not isinstance(value, Mapping) or set(value) != {"format", "user_sid", "ciphertext"}:
            raise GarminSessionCorruptError("protected session envelope is invalid")
        if value.get("format") != _DPAPI_ENVELOPE_FORMAT:
            raise GarminSessionCorruptError("protected session format is unsupported")
        owner_sid = value.get("user_sid")
        if not isinstance(owner_sid, str) or owner_sid != _current_windows_user_sid():
            raise GarminSessionCorruptError("protected session owner mismatch")
        ciphertext_text = value.get("ciphertext")
        if not isinstance(ciphertext_text, str):
            raise GarminSessionCorruptError("protected session ciphertext is invalid")
        try:
            ciphertext = base64.b64decode(ciphertext_text.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError) as exc:
            raise GarminSessionCorruptError("protected session ciphertext is invalid") from exc
        if not ciphertext:
            raise GarminSessionCorruptError("protected session ciphertext is empty")
        plaintext = _dpapi_unprotect(ciphertext)
        try:
            result = plaintext.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GarminSessionCorruptError("protected session text is invalid") from exc
        if not result or len(result) > _MAX_SESSION_TEXT:
            raise GarminSessionCorruptError("protected session text is invalid")
        return result


ClientFactory = Callable[..., Any]
Prompt = Callable[[str], str]


def _repository_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError("Health-Check checkout root could not be determined")


def validate_external_tokenstore(path: str | Path) -> Path:
    """Resolve an auth file and reject checkout-local or symlinked targets."""

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

    if isinstance(exc, GarminSessionCorruptError):
        return GarminSafeError("storage", "session_corrupt")
    if isinstance(exc, GarminSessionProtectionUnavailable):
        return GarminSafeError("storage", "windows_protection_unavailable")
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


def _validate_provider_session(serialized: str) -> str:
    if not isinstance(serialized, str) or not serialized or len(serialized) > _MAX_SESSION_TEXT:
        raise GarminSessionCorruptError("provider session snapshot is invalid")
    try:
        value = json.loads(serialized)
    except (TypeError, ValueError) as exc:
        raise GarminSessionCorruptError("provider session snapshot is invalid") from exc
    if not isinstance(value, Mapping):
        raise GarminSessionCorruptError("provider session snapshot is invalid")
    token = value.get("di_token")
    if not isinstance(token, str) or not token.strip():
        raise GarminSessionCorruptError("provider session snapshot is invalid")
    return serialized


@contextmanager
def _ignore_provider_tokenstore_environment():
    """Prevent an ambient provider path from bypassing explicit owner reauth."""

    missing = object()
    previous = os.environ.pop("GARMINTOKENS", missing)
    try:
        yield
    finally:
        if previous is not missing:
            os.environ["GARMINTOKENS"] = previous


class GarminAuthService:
    """Bootstrap or load one owner-local Garmin session."""

    def __init__(
        self,
        settings: Settings,
        *,
        is_cn: bool = False,
        client_factory: ClientFactory | None = None,
        credential_prompt: Prompt | None = None,
        mfa_prompt: Prompt | None = None,
        session_protector: GarminSessionProtection | None = None,
    ) -> None:
        self.tokenstore = resolve_garmin_tokenstore(settings)
        self.is_cn = is_cn
        self.client_factory = client_factory or _default_client_factory
        self.credential_prompt = credential_prompt or getpass.getpass
        self.mfa_prompt = mfa_prompt or getpass.getpass
        self.session_protector = session_protector or WindowsUserScopedTokenProtection()

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
        """Load the protected external session without prompting."""

        if not self.tokenstore.exists():
            return None, GarminAuthResult(
                status=GarminAuthStatus.REAUTH_REQUIRED,
                error=GarminSafeError("storage", "session_missing"),
            )
        if not self.tokenstore.is_file():
            return None, GarminAuthResult(
                status=GarminAuthStatus.REAUTH_REQUIRED,
                error=GarminSafeError("storage", "session_corrupt"),
            )
        try:
            serialized = self._read_protected_session()
            client = self._new_client()
            with _silence_provider_logging():
                client.login(tokenstore=serialized)
            refreshed = self._serialize_client_session(client)
            self._write_protected_session(refreshed)
            self._forget_credentials(client)
        except GarminSessionProtectionUnavailable as exc:
            return None, GarminAuthResult(
                status=GarminAuthStatus.FAILED,
                session_reused=True,
                error=classify_garmin_error(exc),
            )
        except GarminSessionCorruptError as exc:
            return None, GarminAuthResult(
                status=GarminAuthStatus.REAUTH_REQUIRED,
                session_reused=True,
                error=classify_garmin_error(exc),
            )
        except Exception as exc:
            error = classify_garmin_error(exc)
            if error.error_class != "authentication":
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

    def _read_protected_session(self) -> str:
        try:
            if self.tokenstore.stat().st_size > _MAX_SESSION_TEXT:
                raise GarminSessionCorruptError("protected session envelope is too large")
            envelope = self.tokenstore.read_text(encoding="utf-8")
        except GarminSessionCorruptError:
            raise
        except (OSError, UnicodeError) as exc:
            raise GarminSessionCorruptError("protected session cannot be read") from exc
        return _validate_provider_session(self.session_protector.unprotect(envelope))

    def _serialize_client_session(self, client: Any) -> str:
        provider_client = getattr(client, "client", None)
        dump_text = getattr(provider_client, "dumps", None)
        if not callable(dump_text):
            dump_text = getattr(client, "dumps", None)
        if not callable(dump_text):
            raise GarminSessionCorruptError("provider session serializer unavailable")
        try:
            serialized = dump_text()
        except Exception as exc:
            raise GarminSessionCorruptError("provider session serializer failed") from exc
        return _validate_provider_session(serialized)

    def _write_protected_session(self, serialized: str) -> None:
        protected = self.session_protector.protect(_validate_provider_session(serialized))
        if not isinstance(protected, str) or not protected or len(protected) > _MAX_SESSION_TEXT:
            raise GarminSessionProtectionUnavailable("protected session envelope is invalid")
        target = validate_external_tokenstore(self.tokenstore)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = validate_external_tokenstore(
            target.with_name(f".{target.name}.{secrets.token_hex(16)}.json")
        )
        try:
            with temporary.open("x", encoding="utf-8", newline="") as handle:
                handle.write(protected)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(target)
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

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
        del force_reauth
        mfa_used = False

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
            client = self._new_client(
                email=email,
                password=password,
                prompt_mfa=prompt_mfa,
            )
            with _ignore_provider_tokenstore_environment():
                with _silence_provider_logging():
                    login_result = client.login(tokenstore=None)
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
            self._write_protected_session(self._serialize_client_session(client))
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
    "GARMIN_SESSION_PROTECTION",
    "GARMIN_TOKENSTORE_FILENAME",
    "GarminAuthResult",
    "GarminAuthService",
    "GarminAuthStatus",
    "GarminSafeError",
    "GarminSessionCorruptError",
    "GarminSessionProtectionUnavailable",
    "WindowsUserScopedTokenProtection",
    "classify_garmin_error",
    "resolve_garmin_tokenstore",
    "validate_external_tokenstore",
]
