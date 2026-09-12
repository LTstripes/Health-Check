"""Google Health Web Application OAuth boundary (R04-02 / issue #85).

Implements authorization-code flow for a Web Application / Web Server client
with one fixed registered loopback callback. CI and workers use injectable fake
transports only; this module never prints tokens, secrets, codes, cookies, or
Authorization headers.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from webbrowser import open as open_browser

from healthcheck.config import Settings
from healthcheck.google.protection import (
    GOOGLE_SESSION_PROTECTION_LOCAL,
    GOOGLE_SESSION_PROTECTION_WINDOWS,
    GoogleCredentialCorruptError,
    GoogleCredentialProtection,
    GoogleCredentialProtectionUnavailable,
    default_google_protection,
)
from healthcheck.runtime import resolve_runtime_paths

AUTH_CONTRACT_VERSION = "r04-google-web-oauth-v1"
GOOGLE_AUTH_STORAGE = "external_runtime"
GOOGLE_CLIENT_FILENAME = "client_credentials.enc"
GOOGLE_TOKEN_FILENAME = "tokens.enc"
GOOGLE_PROTECTION_KEY_FILENAME = ".google_protection_key"

# Exact fixed registered localhost callback (R04-02 pin). Override only when the
# exact replacement URI is also registered in the Google Cloud Web client.
DEFAULT_GOOGLE_OAUTH_REDIRECT_URI = "http://127.0.0.1:8765/oauth2/callback"
DEFAULT_GOOGLE_OAUTH_CALLBACK_HOST = "127.0.0.1"
DEFAULT_GOOGLE_OAUTH_CALLBACK_PORT = 8765
DEFAULT_GOOGLE_OAUTH_CALLBACK_PATH = "/oauth2/callback"

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

SCOPE_SLEEP = "https://www.googleapis.com/auth/googlehealth.sleep.readonly"
SCOPE_METRICS = (
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly"
)
# Documented for pairedDevices.list only. R04 must NOT request/authorize this scope.
SCOPE_SETTINGS = "https://www.googleapis.com/auth/googlehealth.settings.readonly"
ALLOWED_SCOPES: frozenset[str] = frozenset({SCOPE_SLEEP, SCOPE_METRICS})
DEFAULT_SCOPE_ORDER: tuple[str, ...] = (SCOPE_SLEEP, SCOPE_METRICS)

_MAX_TEXT = 64 * 1024


class GoogleAuthStatus(StrEnum):
    """Safe high-level OAuth outcome states."""

    AUTHENTICATED = "authenticated"
    REAUTH_REQUIRED = "reauth_required"
    FAILED = "failed"


class GoogleTokenHealth(StrEnum):
    """Sanitized token-health vocabulary (no secret material)."""

    MISSING = "missing"
    VALID = "valid"
    REFRESHED = "refreshed"
    EXPIRED_OR_REVOKED = "expired_or_revoked"
    INVALID_GRANT = "invalid_grant"
    CORRUPT = "corrupt"
    PARTIAL_SCOPES = "partial_scopes"
    PROTECTION_UNAVAILABLE = "protection_unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class GoogleSafeError:
    """Fixed-vocabulary error without provider text or private data."""

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
class GoogleAuthResult:
    """Sanitized auth outcome; never includes tokens, secrets, or codes."""

    status: GoogleAuthStatus
    token_health: GoogleTokenHealth = GoogleTokenHealth.UNKNOWN
    session_reused: bool = False
    force_reauth: bool = False
    prompt_consent: bool = False
    granted_scope_count: int | None = None
    missing_scope_count: int | None = None
    refresh_expires_in_known: bool | None = None
    storage: str = GOOGLE_AUTH_STORAGE
    protection: str | None = None
    redirect_uri: str = DEFAULT_GOOGLE_OAUTH_REDIRECT_URI
    error: GoogleSafeError | None = None

    @property
    def ok(self) -> bool:
        return self.status == GoogleAuthStatus.AUTHENTICATED

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": AUTH_CONTRACT_VERSION,
            "status": self.status.value,
            "token_health": self.token_health.value,
            "session_reused": self.session_reused,
            "force_reauth": self.force_reauth,
            "prompt_consent": self.prompt_consent,
            "granted_scope_count": self.granted_scope_count,
            "missing_scope_count": self.missing_scope_count,
            "refresh_expires_in_known": self.refresh_expires_in_known,
            "storage": self.storage,
            "protection": self.protection,
            "redirect_uri": self.redirect_uri,
            "client_type": "web_application",
            "access_type": "offline",
            "error": self.error.as_dict() if self.error else None,
        }


class GoogleHttpResponse:
    """Minimal HTTP response for injectable transports."""

    def __init__(
        self,
        status: int,
        body: bytes,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status = status
        self.body = body
        self.headers = {str(k).lower(): str(v) for k, v in dict(headers or {}).items()}

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


class GoogleHttpTransport(Protocol):
    """Injectable HTTP boundary so CI never performs live Google calls."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        form: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> GoogleHttpResponse:
        """Perform one HTTP request and return status/body."""


class UrllibGoogleHttpTransport:
    """Stdlib urllib transport used only for owner-invoked live runs."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        form: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> GoogleHttpResponse:
        if form is not None and json_body is not None:
            raise ValueError("Google HTTP transport cannot send form and JSON together")
        header_items = dict(headers or {})
        header_names = {key.lower() for key in header_items}
        if json_body is not None:
            data = json.dumps(dict(json_body), ensure_ascii=True, separators=(",", ":")).encode(
                "utf-8"
            )
        elif form is not None:
            data = urlencode(dict(form)).encode("utf-8")
        else:
            data = None
        request = Request(url, data=data, method=method.upper())
        for key, value in header_items.items():
            # Never log; set only for the outbound request object.
            request.add_header(key, value)
        if json_body is not None and "content-type" not in header_names:
            request.add_header("Content-Type", "application/json")
        elif form is not None and "content-type" not in header_names:
            request.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 — owner URL constants
                body = response.read()
                status = int(getattr(response, "status", 200))
                header_map = {k: v for k, v in response.headers.items()}
                return GoogleHttpResponse(status, body, headers=header_map)
        except HTTPError as exc:
            body = exc.read() if hasattr(exc, "read") else b""
            return GoogleHttpResponse(int(exc.code), body, headers=dict(exc.headers or {}))
        except URLError as exc:
            raise GoogleOAuthError("provider", "provider_unavailable") from exc


class GoogleOAuthError(Exception):
    """Internal non-sensitive OAuth failure carrying a safe class/code pair."""

    def __init__(self, error_class: str, error_code: str, http_status: int | None = None) -> None:
        super().__init__(error_code)
        self.error_class = error_class
        self.error_code = error_code
        self.http_status = http_status

    def as_safe(self) -> GoogleSafeError:
        return GoogleSafeError(self.error_class, self.error_code, self.http_status)


@dataclass(frozen=True, slots=True)
class GoogleClientCredentials:
    client_id: str
    client_secret: str

    def as_storage_dict(self) -> dict[str, str]:
        return {"client_id": self.client_id, "client_secret": self.client_secret}


@dataclass
class GoogleTokenSet:
    access_token: str
    refresh_token: str | None
    token_type: str
    expires_in: int | None
    scope: str
    refresh_token_expires_in: int | None = None

    def granted_scopes(self) -> frozenset[str]:
        parts = [item for item in self.scope.split() if item]
        return frozenset(parts)

    def as_storage_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
            "scope": self.scope,
        }
        if self.refresh_token_expires_in is not None:
            payload["refresh_token_expires_in"] = self.refresh_token_expires_in
        return payload


def _repository_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError("Health-Check checkout root could not be determined")


def validate_external_google_path(path: str | Path) -> Path:
    """Resolve an auth file/dir and reject checkout-local or symlinked targets."""

    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raise ValueError("Google auth storage path must be absolute")
    for candidate in (raw, *raw.parents):
        try:
            if candidate.is_symlink():
                raise ValueError("Google auth storage path must not use symlinks")
        except OSError as exc:
            raise ValueError("Google auth storage path cannot be checked") from exc
    try:
        resolved = raw.resolve()
        resolved.relative_to(_repository_root())
    except ValueError:
        return resolved
    except OSError as exc:
        raise ValueError("Google auth storage path cannot be resolved") from exc
    raise ValueError("Google auth storage must be outside the checkout")


def resolve_google_auth_dir(settings: Settings) -> Path:
    """Return `{data_dir}/google/auth` without creating it."""

    runtime_root = resolve_runtime_paths(settings).root
    return validate_external_google_path(runtime_root / "google" / "auth")


def resolve_google_token_path(settings: Settings) -> Path:
    return validate_external_google_path(resolve_google_auth_dir(settings) / GOOGLE_TOKEN_FILENAME)


def resolve_google_client_path(settings: Settings) -> Path:
    return validate_external_google_path(resolve_google_auth_dir(settings) / GOOGLE_CLIENT_FILENAME)


def normalize_redirect_uri(redirect_uri: str | None) -> str:
    """Pin the default callback; accept override only for exact registered loopback URIs."""

    if redirect_uri is None or not str(redirect_uri).strip():
        return DEFAULT_GOOGLE_OAUTH_REDIRECT_URI
    value = str(redirect_uri).strip()
    parsed = urlparse(value)
    if parsed.scheme != "http":
        raise ValueError("Google OAuth redirect URI must use http loopback")
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Google OAuth redirect URI must be a loopback host")
    if not parsed.path or parsed.path != parsed.path:
        raise ValueError("Google OAuth redirect URI path is invalid")
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError("Google OAuth redirect URI must not include query/fragment")
    if parsed.port is None or not (1 <= parsed.port <= 65535):
        raise ValueError("Google OAuth redirect URI must include an explicit port")
    return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}{parsed.path}"


def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: Sequence[str] = DEFAULT_SCOPE_ORDER,
    prompt_consent: bool = False,
) -> str:
    """Build the Web Application authorization URL (no PKCE by default)."""

    if not client_id or not isinstance(client_id, str):
        raise ValueError("client_id is required")
    if not state or not isinstance(state, str):
        raise ValueError("state is required")
    scope_list = tuple(scopes)
    if not scope_list or set(scope_list) - ALLOWED_SCOPES:
        raise ValueError("only the two accepted Google Health read scopes are allowed")
    if set(scope_list) != ALLOWED_SCOPES:
        raise ValueError("authorization must request both accepted Google Health read scopes")
    params: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": normalize_redirect_uri(redirect_uri),
        "response_type": "code",
        "scope": " ".join(DEFAULT_SCOPE_ORDER),
        "state": state,
        "access_type": "offline",
        "include_granted_scopes": "false",
    }
    if prompt_consent:
        params["prompt"] = "consent"
    return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"


def classify_google_oauth_error(exc: BaseException) -> GoogleSafeError:
    if isinstance(exc, GoogleOAuthError):
        return exc.as_safe()
    if isinstance(exc, GoogleCredentialCorruptError):
        return GoogleSafeError("storage", "credential_corrupt")
    if isinstance(exc, GoogleCredentialProtectionUnavailable):
        return GoogleSafeError("storage", "protection_unavailable")
    if isinstance(exc, FileNotFoundError):
        return GoogleSafeError("storage", "credential_missing")
    if isinstance(exc, PermissionError):
        return GoogleSafeError("storage", "storage_permission")
    if isinstance(exc, ValueError):
        return GoogleSafeError("input", "invalid_input")
    name = type(exc).__name__.casefold()
    if "timeout" in name or "connection" in name:
        return GoogleSafeError("provider", "provider_unavailable")
    return GoogleSafeError("provider", "provider_error")


def _atomic_write_text(path: Path, text: str) -> None:
    target = validate_external_google_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = validate_external_google_path(
        target.with_name(f".{target.name}.{secrets.token_hex(16)}.tmp")
    )
    try:
        with temporary.open("x", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def _parse_token_payload(payload: Mapping[str, Any]) -> GoogleTokenSet:
    access = payload.get("access_token")
    if not isinstance(access, str) or not access:
        raise GoogleOAuthError("authentication", "token_response_invalid")
    refresh = payload.get("refresh_token")
    if refresh is not None and (not isinstance(refresh, str) or not refresh):
        raise GoogleOAuthError("authentication", "token_response_invalid")
    token_type = payload.get("token_type", "Bearer")
    if not isinstance(token_type, str) or not token_type:
        token_type = "Bearer"
    scope = payload.get("scope", " ".join(DEFAULT_SCOPE_ORDER))
    if not isinstance(scope, str):
        raise GoogleOAuthError("authentication", "token_response_invalid")
    expires_in = payload.get("expires_in")
    if expires_in is not None and not isinstance(expires_in, int):
        try:
            expires_in = int(expires_in)
        except (TypeError, ValueError) as exc:
            raise GoogleOAuthError("authentication", "token_response_invalid") from exc
    refresh_expires = payload.get("refresh_token_expires_in")
    if refresh_expires is not None and not isinstance(refresh_expires, int):
        try:
            refresh_expires = int(refresh_expires)
        except (TypeError, ValueError) as exc:
            raise GoogleOAuthError("authentication", "token_response_invalid") from exc
    return GoogleTokenSet(
        access_token=access,
        refresh_token=refresh if isinstance(refresh, str) else None,
        token_type=token_type,
        expires_in=expires_in if isinstance(expires_in, int) else None,
        scope=scope,
        refresh_token_expires_in=refresh_expires if isinstance(refresh_expires, int) else None,
    )


@dataclass
class _CallbackResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None
    error_code: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    result: _CallbackResult
    expected_path: str
    lock: threading.Lock

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        # Never print query strings that may contain codes.
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != self.expected_path:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not found")
            with self.lock:
                if self.result.error_code is None:
                    self.result.error_code = "redirect_path_mismatch"
            return
        query = parse_qs(parsed.query, keep_blank_values=False)
        with self.lock:
            if "error" in query:
                self.result.error = "denied"
                self.result.error_code = "consent_denied"
            else:
                code_values = query.get("code", [])
                state_values = query.get("state", [])
                if not code_values or not code_values[0]:
                    self.result.error_code = "malformed_code"
                else:
                    self.result.code = code_values[0]
                self.result.state = state_values[0] if state_values else None
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Health-Check Google OAuth callback received. You can close this window.")


class LoopbackCallbackServer:
    """Bound a one-shot fixed-port loopback callback listener."""

    def __init__(self, redirect_uri: str = DEFAULT_GOOGLE_OAUTH_REDIRECT_URI) -> None:
        uri = normalize_redirect_uri(redirect_uri)
        parsed = urlparse(uri)
        assert parsed.hostname is not None and parsed.port is not None
        self.redirect_uri = uri
        self.host = parsed.hostname
        self.port = parsed.port
        self.path = parsed.path
        self._result = _CallbackResult()
        self._lock = threading.Lock()
        self._httpd: HTTPServer | None = None

    def start(self) -> None:
        result = self._result
        lock = self._lock
        path = self.path

        class Handler(_CallbackHandler):
            pass

        Handler.result = result
        Handler.expected_path = path
        Handler.lock = lock
        try:
            self._httpd = HTTPServer((self.host, self.port), Handler)
        except OSError as exc:
            raise GoogleOAuthError("runtime", "callback_bind_failed") from exc

    def wait(self, timeout: float = 300.0) -> _CallbackResult:
        if self._httpd is None:
            raise GoogleOAuthError("runtime", "callback_not_started")
        timer = threading.Timer(timeout, self._httpd.shutdown)
        timer.daemon = True
        timer.start()
        try:
            self._httpd.handle_request()
        finally:
            timer.cancel()
            self.close()
        return self._result

    def close(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.server_close()
            finally:
                self._httpd = None


BrowserOpener = Callable[[str], bool]
CallbackFactory = Callable[[str], LoopbackCallbackServer]


class GoogleAuthService:
    """Owner-assisted Google Health Web Application OAuth service."""

    def __init__(
        self,
        settings: Settings,
        *,
        redirect_uri: str | None = None,
        transport: GoogleHttpTransport | None = None,
        protector: GoogleCredentialProtection | None = None,
        browser_opener: BrowserOpener | None = None,
        callback_factory: CallbackFactory | None = None,
        client_credentials: GoogleClientCredentials | None = None,
    ) -> None:
        self.settings = settings
        self.auth_dir = resolve_google_auth_dir(settings)
        self.client_path = resolve_google_client_path(settings)
        self.token_path = resolve_google_token_path(settings)
        self.redirect_uri = normalize_redirect_uri(redirect_uri)
        self.transport = transport or UrllibGoogleHttpTransport()
        self.protector = protector or default_google_protection(self.auth_dir)
        self.browser_opener = browser_opener or open_browser
        self.callback_factory = callback_factory or LoopbackCallbackServer
        self._inline_client = client_credentials
        self._pending_state: str | None = None
        self._consumed_states: set[str] = set()

    @property
    def protection_kind(self) -> str:
        return getattr(self.protector, "kind", GOOGLE_SESSION_PROTECTION_LOCAL)

    def store_client_credentials(self, credentials: GoogleClientCredentials) -> None:
        """Persist protected Web client ID/secret under the external auth dir."""

        if not credentials.client_id or not credentials.client_secret:
            raise ValueError("client_id and client_secret are required")
        envelope = self.protector.protect(json.dumps(credentials.as_storage_dict(), sort_keys=True))
        _atomic_write_text(self.client_path, envelope)

    def load_client_credentials(self) -> GoogleClientCredentials:
        if self._inline_client is not None:
            return self._inline_client
        if not self.client_path.is_file():
            raise FileNotFoundError("Google client credentials are missing")
        try:
            envelope = self.client_path.read_text(encoding="utf-8")
            plaintext = self.protector.unprotect(envelope)
            payload = json.loads(plaintext)
        except GoogleCredentialCorruptError:
            raise
        except GoogleCredentialProtectionUnavailable:
            raise
        except Exception as exc:
            raise GoogleCredentialCorruptError("Google client credentials are corrupt") from exc
        client_id = payload.get("client_id")
        client_secret = payload.get("client_secret")
        if not isinstance(client_id, str) or not isinstance(client_secret, str):
            raise GoogleCredentialCorruptError("Google client credentials are corrupt")
        if not client_id or not client_secret:
            raise GoogleCredentialCorruptError("Google client credentials are corrupt")
        return GoogleClientCredentials(client_id=client_id, client_secret=client_secret)

    def _write_tokens(self, tokens: GoogleTokenSet) -> None:
        envelope = self.protector.protect(json.dumps(tokens.as_storage_dict(), sort_keys=True))
        _atomic_write_text(self.token_path, envelope)

    def _read_tokens(self) -> GoogleTokenSet:
        if not self.token_path.is_file():
            raise FileNotFoundError("Google token store is missing")
        try:
            envelope = self.token_path.read_text(encoding="utf-8")
            plaintext = self.protector.unprotect(envelope)
            payload = json.loads(plaintext)
            if not isinstance(payload, Mapping):
                raise GoogleCredentialCorruptError("Google token store is corrupt")
            return _parse_token_payload(payload)
        except (
            GoogleCredentialCorruptError,
            GoogleCredentialProtectionUnavailable,
            GoogleOAuthError,
        ):
            raise
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise GoogleCredentialCorruptError("Google token store is corrupt") from exc

    def clear_tokens(self) -> None:
        if self.token_path.exists():
            validate_external_google_path(self.token_path)
            try:
                self.token_path.unlink()
            except OSError as exc:
                raise GoogleOAuthError("storage", "storage_permission") from exc

    def authorization_url(
        self,
        *,
        force_reauth: bool = False,
        prompt_consent: bool | None = None,
    ) -> str:
        """Create a one-use state and return the authorization URL."""

        credentials = self.load_client_credentials()
        state = secrets.token_urlsafe(32)
        self._pending_state = state
        use_consent = bool(force_reauth) if prompt_consent is None else bool(prompt_consent)
        if prompt_consent is None:
            # prompt=consent only for initial RT acquisition / deliberate reauth.
            use_consent = force_reauth or not self.token_path.exists()
        return build_authorization_url(
            client_id=credentials.client_id,
            redirect_uri=self.redirect_uri,
            state=state,
            prompt_consent=use_consent,
        )

    def consume_state(self, state: str | None) -> None:
        """Validate CSRF state exactly once; mismatch/replay fail closed."""

        expected = self._pending_state
        self._pending_state = None
        if not isinstance(state, str) or not state:
            raise GoogleOAuthError("authentication", "state_missing")
        if expected is None or state != expected:
            raise GoogleOAuthError("authentication", "state_mismatch")
        if state in self._consumed_states:
            raise GoogleOAuthError("authentication", "state_replay")
        self._consumed_states.add(state)

    def exchange_code(self, code: str, *, state: str | None) -> GoogleTokenSet:
        """Validate state, then exchange the authorization code for tokens."""

        self.consume_state(state)
        if not isinstance(code, str) or not code.strip():
            raise GoogleOAuthError("authentication", "malformed_code")
        credentials = self.load_client_credentials()
        response = self.transport.request(
            "POST",
            GOOGLE_TOKEN_ENDPOINT,
            form={
                "code": code.strip(),
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        return self._tokens_from_response(response, require_refresh=True)

    def refresh_access_token(self, tokens: GoogleTokenSet | None = None) -> GoogleTokenSet:
        current = tokens or self._read_tokens()
        if not current.refresh_token:
            raise GoogleOAuthError("authentication", "refresh_token_missing")
        credentials = self.load_client_credentials()
        response = self.transport.request(
            "POST",
            GOOGLE_TOKEN_ENDPOINT,
            form={
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
                "refresh_token": current.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        refreshed = self._tokens_from_response(response, require_refresh=False)
        if refreshed.refresh_token is None:
            refreshed.refresh_token = current.refresh_token
        if not refreshed.scope:
            refreshed.scope = current.scope
        self._write_tokens(refreshed)
        return refreshed

    def _tokens_from_response(
        self,
        response: GoogleHttpResponse,
        *,
        require_refresh: bool,
    ) -> GoogleTokenSet:
        try:
            payload = response.json()
        except Exception as exc:
            raise GoogleOAuthError(
                "authentication",
                "token_response_invalid",
                response.status,
            ) from exc
        if not isinstance(payload, Mapping):
            raise GoogleOAuthError("authentication", "token_response_invalid", response.status)
        if response.status >= 400:
            error = str(payload.get("error", ""))
            if error == "invalid_grant":
                raise GoogleOAuthError("authentication", "invalid_grant", response.status)
            if response.status in {401, 403}:
                raise GoogleOAuthError("authentication", "authentication_failed", response.status)
            raise GoogleOAuthError("authentication", "token_exchange_failed", response.status)
        tokens = _parse_token_payload(payload)
        if require_refresh and not tokens.refresh_token:
            raise GoogleOAuthError("authentication", "refresh_token_missing", response.status)
        return tokens

    def token_health(self) -> GoogleAuthResult:
        """Return sanitized token-health without emitting secret material."""

        try:
            tokens = self._read_tokens()
        except FileNotFoundError:
            return GoogleAuthResult(
                status=GoogleAuthStatus.REAUTH_REQUIRED,
                token_health=GoogleTokenHealth.MISSING,
                protection=self.protection_kind,
                redirect_uri=self.redirect_uri,
                error=GoogleSafeError("storage", "credential_missing"),
            )
        except GoogleCredentialCorruptError:
            return GoogleAuthResult(
                status=GoogleAuthStatus.REAUTH_REQUIRED,
                token_health=GoogleTokenHealth.CORRUPT,
                protection=self.protection_kind,
                redirect_uri=self.redirect_uri,
                error=GoogleSafeError("storage", "credential_corrupt"),
            )
        except GoogleCredentialProtectionUnavailable:
            return GoogleAuthResult(
                status=GoogleAuthStatus.FAILED,
                token_health=GoogleTokenHealth.PROTECTION_UNAVAILABLE,
                protection=self.protection_kind,
                redirect_uri=self.redirect_uri,
                error=GoogleSafeError("storage", "protection_unavailable"),
            )
        granted = tokens.granted_scopes()
        missing = ALLOWED_SCOPES - granted
        health = GoogleTokenHealth.PARTIAL_SCOPES if missing else GoogleTokenHealth.VALID
        return GoogleAuthResult(
            status=GoogleAuthStatus.AUTHENTICATED,
            token_health=health,
            session_reused=True,
            granted_scope_count=len(granted & ALLOWED_SCOPES),
            missing_scope_count=len(missing),
            refresh_expires_in_known=tokens.refresh_token_expires_in is not None,
            protection=self.protection_kind,
            redirect_uri=self.redirect_uri,
        )

    def load_access_token(self, *, refresh_if_needed: bool = True) -> tuple[str, GoogleAuthResult]:
        """Load a usable access token and sanitized health (never logged by callers)."""

        try:
            tokens = self._read_tokens()
        except Exception as exc:
            error = classify_google_oauth_error(exc)
            status = (
                GoogleAuthStatus.REAUTH_REQUIRED
                if error.error_code in {"credential_missing", "credential_corrupt", "invalid_grant"}
                else GoogleAuthStatus.FAILED
            )
            health = {
                "credential_missing": GoogleTokenHealth.MISSING,
                "credential_corrupt": GoogleTokenHealth.CORRUPT,
                "invalid_grant": GoogleTokenHealth.INVALID_GRANT,
                "protection_unavailable": GoogleTokenHealth.PROTECTION_UNAVAILABLE,
            }.get(error.error_code, GoogleTokenHealth.UNKNOWN)
            return "", GoogleAuthResult(
                status=status,
                token_health=health,
                protection=self.protection_kind,
                redirect_uri=self.redirect_uri,
                error=error,
            )
        if refresh_if_needed:
            try:
                tokens = self.refresh_access_token(tokens)
                health = GoogleTokenHealth.REFRESHED
            except GoogleOAuthError as exc:
                if exc.error_code == "invalid_grant":
                    return "", GoogleAuthResult(
                        status=GoogleAuthStatus.REAUTH_REQUIRED,
                        token_health=GoogleTokenHealth.INVALID_GRANT,
                        session_reused=True,
                        protection=self.protection_kind,
                        redirect_uri=self.redirect_uri,
                        error=exc.as_safe(),
                    )
                # Keep existing access token if refresh failed for non-revocation reasons.
                health = GoogleTokenHealth.VALID
            else:
                granted = tokens.granted_scopes()
                missing = ALLOWED_SCOPES - granted
                result = GoogleAuthResult(
                    status=GoogleAuthStatus.AUTHENTICATED,
                    token_health=GoogleTokenHealth.PARTIAL_SCOPES if missing else health,
                    session_reused=True,
                    granted_scope_count=len(granted & ALLOWED_SCOPES),
                    missing_scope_count=len(missing),
                    refresh_expires_in_known=tokens.refresh_token_expires_in is not None,
                    protection=self.protection_kind,
                    redirect_uri=self.redirect_uri,
                )
                return tokens.access_token, result
        granted = tokens.granted_scopes()
        missing = ALLOWED_SCOPES - granted
        return tokens.access_token, GoogleAuthResult(
            status=GoogleAuthStatus.AUTHENTICATED,
            token_health=GoogleTokenHealth.PARTIAL_SCOPES if missing else GoogleTokenHealth.VALID,
            session_reused=True,
            granted_scope_count=len(granted & ALLOWED_SCOPES),
            missing_scope_count=len(missing),
            refresh_expires_in_known=tokens.refresh_token_expires_in is not None,
            protection=self.protection_kind,
            redirect_uri=self.redirect_uri,
        )

    def complete_authorization_code(
        self,
        code: str,
        *,
        state: str | None,
        force_reauth: bool = False,
    ) -> GoogleAuthResult:
        """Exchange a code after state validation and store protected tokens."""

        try:
            if force_reauth:
                # Do not silently reuse stale token state across deliberate reauth.
                self.clear_tokens()
            tokens = self.exchange_code(code, state=state)
            self._write_tokens(tokens)
            granted = tokens.granted_scopes()
            missing = ALLOWED_SCOPES - granted
            return GoogleAuthResult(
                status=GoogleAuthStatus.AUTHENTICATED,
                token_health=(
                    GoogleTokenHealth.PARTIAL_SCOPES if missing else GoogleTokenHealth.VALID
                ),
                force_reauth=force_reauth,
                prompt_consent=force_reauth or True,
                granted_scope_count=len(granted & ALLOWED_SCOPES),
                missing_scope_count=len(missing),
                refresh_expires_in_known=tokens.refresh_token_expires_in is not None,
                protection=self.protection_kind,
                redirect_uri=self.redirect_uri,
            )
        except Exception as exc:
            error = classify_google_oauth_error(exc)
            status = (
                GoogleAuthStatus.REAUTH_REQUIRED
                if error.error_code
                in {
                    "invalid_grant",
                    "state_mismatch",
                    "state_replay",
                    "state_missing",
                    "consent_denied",
                }
                else GoogleAuthStatus.FAILED
            )
            return GoogleAuthResult(
                status=status,
                token_health=GoogleTokenHealth.UNKNOWN,
                force_reauth=force_reauth,
                protection=self.protection_kind,
                redirect_uri=self.redirect_uri,
                error=error,
            )

    def bootstrap(self, *, force_reauth: bool = False) -> GoogleAuthResult:
        """Run system-browser authorization-code flow with fixed loopback callback."""

        if not force_reauth and self.token_path.exists():
            access, health = self.load_access_token(refresh_if_needed=True)
            if access and health.ok:
                return health

        try:
            url = self.authorization_url(force_reauth=force_reauth)
            prompt_consent = "prompt=consent" in url
        except Exception as exc:
            return GoogleAuthResult(
                status=GoogleAuthStatus.FAILED,
                token_health=GoogleTokenHealth.UNKNOWN,
                force_reauth=force_reauth,
                protection=self.protection_kind,
                redirect_uri=self.redirect_uri,
                error=classify_google_oauth_error(exc),
            )

        try:
            callback = self.callback_factory(self.redirect_uri)
            callback.start()
        except Exception as exc:
            return GoogleAuthResult(
                status=GoogleAuthStatus.FAILED,
                token_health=GoogleTokenHealth.UNKNOWN,
                force_reauth=force_reauth,
                prompt_consent=prompt_consent,
                protection=self.protection_kind,
                redirect_uri=self.redirect_uri,
                error=classify_google_oauth_error(exc),
            )

        try:
            self.browser_opener(url)
        except Exception:
            # Browser open failure is non-fatal if the owner pastes the URL manually;
            # still continue waiting for the callback.
            pass

        try:
            result = callback.wait()
        except Exception as exc:
            return GoogleAuthResult(
                status=GoogleAuthStatus.FAILED,
                token_health=GoogleTokenHealth.UNKNOWN,
                force_reauth=force_reauth,
                prompt_consent=prompt_consent,
                protection=self.protection_kind,
                redirect_uri=self.redirect_uri,
                error=classify_google_oauth_error(exc),
            )

        if result.error_code == "consent_denied":
            return GoogleAuthResult(
                status=GoogleAuthStatus.REAUTH_REQUIRED,
                token_health=GoogleTokenHealth.UNKNOWN,
                force_reauth=force_reauth,
                prompt_consent=prompt_consent,
                protection=self.protection_kind,
                redirect_uri=self.redirect_uri,
                error=GoogleSafeError("authentication", "consent_denied"),
            )
        if result.error_code == "redirect_path_mismatch":
            return GoogleAuthResult(
                status=GoogleAuthStatus.FAILED,
                token_health=GoogleTokenHealth.UNKNOWN,
                force_reauth=force_reauth,
                prompt_consent=prompt_consent,
                protection=self.protection_kind,
                redirect_uri=self.redirect_uri,
                error=GoogleSafeError("authentication", "redirect_mismatch"),
            )
        if result.error_code == "malformed_code" or not result.code:
            return GoogleAuthResult(
                status=GoogleAuthStatus.FAILED,
                token_health=GoogleTokenHealth.UNKNOWN,
                force_reauth=force_reauth,
                prompt_consent=prompt_consent,
                protection=self.protection_kind,
                redirect_uri=self.redirect_uri,
                error=GoogleSafeError("authentication", "malformed_code"),
            )

        outcome = self.complete_authorization_code(
            result.code,
            state=result.state,
            force_reauth=force_reauth,
        )
        # Preserve whether consent was requested on the authorization URL.
        return GoogleAuthResult(
            status=outcome.status,
            token_health=outcome.token_health,
            session_reused=False,
            force_reauth=force_reauth,
            prompt_consent=prompt_consent,
            granted_scope_count=outcome.granted_scope_count,
            missing_scope_count=outcome.missing_scope_count,
            refresh_expires_in_known=outcome.refresh_expires_in_known,
            storage=outcome.storage,
            protection=outcome.protection,
            redirect_uri=outcome.redirect_uri,
            error=outcome.error,
        )


__all__ = [
    "ALLOWED_SCOPES",
    "AUTH_CONTRACT_VERSION",
    "DEFAULT_GOOGLE_OAUTH_REDIRECT_URI",
    "DEFAULT_SCOPE_ORDER",
    "SCOPE_METRICS",
    "SCOPE_SETTINGS",
    "SCOPE_SLEEP",
    "GOOGLE_AUTH_STORAGE",
    "GOOGLE_CLIENT_FILENAME",
    "GOOGLE_TOKEN_FILENAME",
    "GOOGLE_SESSION_PROTECTION_LOCAL",
    "GOOGLE_SESSION_PROTECTION_WINDOWS",
    "GoogleAuthResult",
    "GoogleAuthService",
    "GoogleAuthStatus",
    "GoogleClientCredentials",
    "GoogleHttpResponse",
    "GoogleHttpTransport",
    "GoogleOAuthError",
    "GoogleSafeError",
    "GoogleTokenHealth",
    "GoogleTokenSet",
    "LoopbackCallbackServer",
    "UrllibGoogleHttpTransport",
    "build_authorization_url",
    "classify_google_oauth_error",
    "normalize_redirect_uri",
    "resolve_google_auth_dir",
    "resolve_google_client_path",
    "resolve_google_token_path",
    "validate_external_google_path",
]
