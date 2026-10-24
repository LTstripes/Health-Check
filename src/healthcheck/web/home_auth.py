"""Single-owner direct-HTTPS UI boundary; no provider auth or persistent sessions."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import ssl
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from ipaddress import IPv4Address
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from cryptography import x509
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from healthcheck.config import Settings
from healthcheck.logging import log_event
from healthcheck.runtime import _repository_root, resolve_runtime_paths
from healthcheck.web.ui_guard import UNSAFE_METHODS, _raw_counts, _raw_values

COOKIE = "__Host-healthcheck"
IDLE_SECONDS = 30 * 60
ABSOLUTE_SECONDS = 12 * 60 * 60
MAX_SESSIONS = 16
MAX_LOGIN_BYTES = 4096
LOGIN_READ_SECONDS = 10
SCRYPT_N = 2**17
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "frame-ancestors 'none'; form-action 'self'; base-uri 'self'",
}


class HomeServerError(ValueError):
    """A deliberately nonsensitive configuration/setup failure."""


def access_file(path: Path | None, settings: Settings) -> Path:
    if path is None or not path.is_absolute():
        raise HomeServerError("home_server_access_file_required")
    resolved = path.resolve()
    if resolved.is_relative_to(_repository_root()) or resolved.is_relative_to(
        resolve_runtime_paths(settings).root
    ):
        raise HomeServerError("home_server_access_file_must_be_outside_code_and_profile")
    # Never follow an explicitly supplied link or a linked parent into access state.
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise HomeServerError("home_server_access_file_must_not_be_linked")
    return resolved


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=8, p=1,
        dklen=32, maxmem=256 * 1024 * 1024,
    )


def password_record(password: str) -> dict[str, str | int]:
    if not 12 <= len(password) or len(password.encode("utf-8")) > 1024:
        raise HomeServerError("password_requires_12_characters_and_at_most_1024_bytes")
    salt = secrets.token_bytes(16)
    return {"format": 1, "salt": salt.hex(), "digest": _derive(password, salt).hex()}


def write_password(path: Path, settings: Settings, password: str, *, replace: bool = False) -> None:
    target = access_file(path, settings)
    if not resolve_runtime_paths(settings).database.is_file():
        raise HomeServerError("ui_password_requires_an_existing_profile")
    record = password_record(password)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Exclusive creation is the default. Replacement is explicit and atomic.
    if not replace:
        try:
            with target.open("x", encoding="utf-8") as stream:
                os.chmod(target, 0o600)
                json.dump(record, stream)
        except FileExistsError:
            raise HomeServerError("ui_password_already_configured") from None
        return
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         delete=False, prefix=".ui-password-") as stream:
            temporary = stream.name
            os.chmod(temporary, 0o600)
            json.dump(record, stream)
        os.replace(temporary, target)
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()


def read_password(path: Path) -> tuple[bytes, bytes]:
    try:
        if path.stat().st_size > 2048 or not path.is_file():
            raise ValueError
        value = json.loads(path.read_text(encoding="utf-8"))
        if set(value) != {"format", "salt", "digest"} or value["format"] != 1:
            raise ValueError
        salt, digest = bytes.fromhex(value["salt"]), bytes.fromhex(value["digest"])
        if len(salt) != 16 or len(digest) != 32:
            raise ValueError
        return salt, digest
    except (OSError, ValueError, TypeError, KeyError):
        raise HomeServerError("home_server_password_unavailable") from None


def validate_tls(settings: Settings) -> None:
    try:
        cert, key = settings.ui_tls_certfile, settings.ui_tls_keyfile
        if cert is None or key is None:
            raise ValueError
        for path in (cert, key):
            access_file(path, settings)
            if not path.is_file() or path.stat().st_size > 512 * 1024:
                raise ValueError
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert, key)
        leaf = x509.load_pem_x509_certificate(cert.read_bytes())
        names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        now = datetime.now(UTC)
        if IPv4Address(settings.ui_host) not in names.get_values_for_type(x509.IPAddress):
            raise ValueError
        if not leaf.not_valid_before_utc <= now < leaf.not_valid_after_utc:
            raise ValueError
    except (OSError, ValueError, TypeError, x509.ExtensionNotFound):
        raise HomeServerError("home_server_tls_unavailable_or_wrong_ip") from None


@dataclass
class HomeAuth:
    auth_file: Path
    salt: bytes = field(repr=False)
    digest: bytes = field(repr=False)
    sessions: dict[bytes, tuple[float, float]] = field(default_factory=dict, repr=False)
    attempts: deque[float] = field(default_factory=deque, repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def configure(cls, settings: Settings) -> HomeAuth:
        validate_tls(settings)
        path = access_file(settings.ui_auth_file, settings)
        verifier = read_password(path)
        if not resolve_runtime_paths(settings).database.is_file():
            raise HomeServerError("home_server_requires_existing_profile")
        return cls(path, *verifier)

    def current_verifier(self) -> bool:
        # Replacement invalidates this process immediately; restart loads the new verifier.
        try:
            salt, digest = read_password(self.auth_file)
            return hmac.compare_digest(salt, self.salt) and hmac.compare_digest(digest, self.digest)
        except HomeServerError:
            return False

    def may_attempt(self) -> bool:
        now = time.monotonic()
        with self.lock:
            while self.attempts and self.attempts[0] <= now - 60:
                self.attempts.popleft()
            if len(self.attempts) >= 5:
                return False
            self.attempts.append(now)
            return True

    def verify(self, password: str) -> bool:
        if not 12 <= len(password) or len(password.encode("utf-8")) > 1024:
            return False
        return hmac.compare_digest(_derive(password, self.salt), self.digest)

    def issue(self) -> str:
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self.lock:
            self._expire(now)
            while len(self.sessions) >= MAX_SESSIONS:
                self.sessions.pop(next(iter(self.sessions)))
            self.sessions[hashlib.sha256(token.encode()).digest()] = (now, now)
        return token

    def _expire(self, now: float) -> None:
        for key, (created, seen) in list(self.sessions.items()):
            if now - created >= ABSOLUTE_SECONDS or now - seen >= IDLE_SECONDS:
                del self.sessions[key]

    def session(self, token: str | None, *, revoke: bool = False) -> bool:
        if token is None or len(token) > 128:
            return False
        key = hashlib.sha256(token.encode()).digest()
        now = time.monotonic()
        with self.lock:
            self._expire(now)
            if key not in self.sessions:
                return False
            if revoke:
                del self.sessions[key]
            else:
                self.sessions[key] = (self.sessions[key][0], now)
        return True


def _response(code: str, status: int) -> Response:
    return JSONResponse({"code": code, "message": "request failed"}, status_code=status)


def _same_origin(value: str, expected: str, *, referer: bool = False) -> bool:
    try:
        parsed = urlsplit(value)
        if parsed.username or parsed.password or parsed.scheme != "https":
            return False
        if any(c.isspace() for c in value) or "," in value:
            return False
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return origin == expected and (
            referer or not (parsed.path or parsed.query or parsed.fragment)
        )
    except ValueError:
        return False


async def _login(request: Request, auth: HomeAuth) -> Response:
    if request.method == "GET":
        return _login_page(request)
    if request.method != "POST":
        return _response("method_not_allowed", 405)
    if not auth.may_attempt():
        response = _login_page(request, 429, "Слишком много попыток. Попробуйте через минуту.")
        response.headers["Retry-After"] = "60"
        return response
    if request.headers.get("content-type", "").split(";", 1)[0] != (
        "application/x-www-form-urlencoded"
    ):
        return _response("login_failed", 400)
    body = bytearray()
    try:
        async with asyncio.timeout(LOGIN_READ_SECONDS):
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_LOGIN_BYTES:
                    return _response("login_failed", 413)
                body.extend(chunk)
    except TimeoutError:
        return _response("login_failed", 408)
    try:
        fields = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=2)
        if set(fields) != {"password"} or len(fields["password"]) != 1:
            raise ValueError
        password = fields["password"][0]
    except (UnicodeError, ValueError):
        return _response("login_failed", 400)
    if not await run_in_threadpool(auth.verify, password):
        return _login_page(request, 401, "Не удалось войти. Проверьте пароль.")
    response = RedirectResponse("/brief", status_code=303)
    # Discard an existing browser session before issuing a fresh one.
    auth.session(request.cookies.get(COOKIE), revoke=True)
    response.set_cookie(COOKIE, auth.issue(), secure=True, httponly=True, samesite="strict",
                        path="/", max_age=ABSOLUTE_SECONDS)
    return response


def _login_page(request: Request, status: int = 200, error: str | None = None) -> Response:
    # Self-contained public form: no private navigation or unauthenticated assets.
    from healthcheck.web.pages import templates

    return templates.TemplateResponse(request=request, name="login.html",
                                      context={"error": error}, status_code=status)


async def home_guard(request: Request, call_next) -> Response:
    try:
        response = await _home_request(request, call_next)
    except Exception as exc:
        log_event("home_request_failed", operation="request", status="error",
                  reason=type(exc).__name__)
        response = _response("internal_error", 500)
    response.headers.update(SECURITY_HEADERS)
    return response


async def _home_request(request: Request, call_next) -> Response:
    settings = request.app.state.settings
    expected_host = settings.ui_host
    if settings.ui_port != 443:
        expected_host += f":{settings.ui_port}"
    expected_origin = f"https://{expected_host}"
    raw = list(request.scope.get("headers", []))
    counts = _raw_counts(raw)
    if request.scope.get("scheme") != "https":
        return _response("https_required", 403)
    if counts.get("host") != 1 or _raw_values(raw, "host")[0] != expected_host:
        return _response("host_forbidden", 403)
    # Headers are never used to derive trust or origin; direct TLS only.
    if counts.get("cookie", 0) > 1:
        return _response("session_invalid", 403)
    cookie_parts = request.headers.get("cookie", "").split(";")
    if sum(part.strip().split("=", 1)[0] == COOKIE for part in cookie_parts) > 1:
        return _response("session_invalid", 403)
    if request.method not in {"GET", "HEAD", "OPTIONS", *UNSAFE_METHODS}:
        return _response("method_not_allowed", 405)
    if request.method in UNSAFE_METHODS:
        if counts.get("origin") != 1 or not _same_origin(
            _raw_values(raw, "origin")[0], expected_origin
        ):
            return _response("origin_forbidden", 403)
        if counts.get("sec-fetch-site", 0) > 1 or counts.get("referer", 0) > 1:
            return _response("origin_forbidden", 403)
        if counts.get("sec-fetch-site") and request.headers["sec-fetch-site"] != "same-origin":
            return _response("origin_forbidden", 403)
        if counts.get("referer") and not _same_origin(
            request.headers["referer"], expected_origin, referer=True
        ):
            return _response("origin_forbidden", 403)
    auth = request.app.state.home_auth
    if not auth.current_verifier():
        with auth.lock:
            auth.sessions.clear()
        return _response("home_server_restart_required", 503)
    if request.url.path == "/login":
        if request.url.query:
            return _response("login_query_forbidden", 400)
        return await _login(request, auth)
    if request.url.path == "/healthz" and request.method in {"GET", "HEAD"}:
        return await call_next(request)
    token = request.cookies.get(COOKIE)
    if not auth.session(token):
        if request.method == "GET" and not request.url.path.startswith("/api/"):
            return RedirectResponse("/login", status_code=303)
        return _response("login_required", 401)
    request.state.home_server = True
    if request.url.path == "/logout":
        if request.method != "POST":
            return _response("method_not_allowed", 405)
        auth.session(token, revoke=True)
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
        return response
    return await call_next(request)
