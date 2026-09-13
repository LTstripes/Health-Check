"""Google credential protection envelopes (Windows DPAPI + non-Windows local key).

Security outcome is analogous to Garmin DPAPI: secrets are never stored as
plaintext under the runtime data directory, and secret/token paths that resolve
inside the checkout fail closed before any write.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import os
import secrets
import sys
from collections.abc import Mapping
from ctypes import wintypes
from pathlib import Path
from typing import Any, Protocol

_MAX_PLAINTEXT = 64 * 1024
_DPAPI_ENVELOPE_FORMAT = "healthcheck-google-dpapi-v1"
_LOCAL_ENVELOPE_FORMAT = "healthcheck-google-local-key-v1"
GOOGLE_SESSION_PROTECTION_WINDOWS = "windows_user_dpapi_google"
GOOGLE_SESSION_PROTECTION_LOCAL = "local_keyfile_google"


class GoogleCredentialCorruptError(ValueError):
    """Protected Google credential material cannot be safely used."""


class GoogleCredentialProtectionUnavailable(RuntimeError):
    """Required user-scoped protection API or local key material is unavailable."""


class GoogleCredentialProtection(Protocol):
    """Injectable protect/unprotect boundary for synthetic tests."""

    @property
    def kind(self) -> str:
        """Stable protection-kind label for sanitized diagnostics."""

    def protect(self, plaintext: str) -> str:
        """Return a Google-specific protected envelope."""

    def unprotect(self, envelope: str) -> str:
        """Return plaintext or raise a safe local error."""


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
        raise GoogleCredentialProtectionUnavailable("Windows protection is required")
    try:
        return ctypes.WinDLL(name, use_last_error=True)
    except OSError as exc:
        raise GoogleCredentialProtectionUnavailable(
            "Windows protection API unavailable"
        ) from exc


def _local_free(kernel32: Any, pointer: Any) -> None:
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.LocalFree(ctypes.cast(pointer, ctypes.c_void_p))


def _blob_from_bytes(value: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(value)
    blob = _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


def _current_windows_user_sid() -> str:
    if sys.platform != "win32":
        raise GoogleCredentialProtectionUnavailable("Windows user protection is required")
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
        raise GoogleCredentialProtectionUnavailable("Windows owner token unavailable")
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
            raise GoogleCredentialProtectionUnavailable("Windows owner SID unavailable")
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token,
            1,
            ctypes.cast(buffer, wintypes.LPVOID),
            size,
            ctypes.byref(size),
        ):
            raise GoogleCredentialProtectionUnavailable("Windows owner SID unavailable")
        user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
        if not user.User.Sid:
            raise GoogleCredentialProtectionUnavailable("Windows owner SID unavailable")
        advapi32.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
        sid_text = ctypes.c_wchar_p()
        if not advapi32.ConvertSidToStringSidW(user.User.Sid, ctypes.byref(sid_text)):
            raise GoogleCredentialProtectionUnavailable("Windows owner SID unavailable")
        try:
            if not sid_text.value:
                raise GoogleCredentialProtectionUnavailable("Windows owner SID unavailable")
            return sid_text.value
        finally:
            _local_free(kernel32, sid_text)
    finally:
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(token)


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
        raise GoogleCredentialProtectionUnavailable("Windows Google credential protection failed")
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
        raise GoogleCredentialCorruptError("Windows Google credential ciphertext is invalid")
    del input_buffer
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        _local_free(kernel32, output_blob.pbData)
        if description:
            _local_free(kernel32, description)


class GoogleWindowsUserScopedProtection:
    """Protect Google secrets with the current Windows user's DPAPI key."""

    kind = GOOGLE_SESSION_PROTECTION_WINDOWS

    def protect(self, plaintext: str) -> str:
        if not isinstance(plaintext, str) or not plaintext or len(plaintext) > _MAX_PLAINTEXT:
            raise GoogleCredentialCorruptError("Google credential snapshot is invalid")
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
        if not isinstance(envelope, str) or not envelope or len(envelope) > _MAX_PLAINTEXT:
            raise GoogleCredentialCorruptError("protected Google envelope is invalid")
        try:
            value = json.loads(envelope)
        except (TypeError, ValueError) as exc:
            raise GoogleCredentialCorruptError("protected Google envelope is invalid") from exc
        if not isinstance(value, Mapping) or set(value) != {"format", "user_sid", "ciphertext"}:
            raise GoogleCredentialCorruptError("protected Google envelope is invalid")
        if value.get("format") != _DPAPI_ENVELOPE_FORMAT:
            raise GoogleCredentialCorruptError("protected Google format is unsupported")
        owner_sid = value.get("user_sid")
        if not isinstance(owner_sid, str) or owner_sid != _current_windows_user_sid():
            raise GoogleCredentialCorruptError("protected Google owner mismatch")
        ciphertext_text = value.get("ciphertext")
        if not isinstance(ciphertext_text, str):
            raise GoogleCredentialCorruptError("protected Google ciphertext is invalid")
        try:
            ciphertext = base64.b64decode(ciphertext_text.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError) as exc:
            raise GoogleCredentialCorruptError("protected Google ciphertext is invalid") from exc
        if not ciphertext:
            raise GoogleCredentialCorruptError("protected Google ciphertext is empty")
        plaintext = _dpapi_unprotect(ciphertext)
        try:
            result = plaintext.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GoogleCredentialCorruptError("protected Google text is invalid") from exc
        if not result or len(result) > _MAX_PLAINTEXT:
            raise GoogleCredentialCorruptError("protected Google text is invalid")
        return result


def _xor_keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    blocks: list[bytes] = []
    counter = 0
    while sum(len(block) for block in blocks) < length:
        counter_bytes = counter.to_bytes(8, "big")
        blocks.append(hmac.new(key, nonce + counter_bytes, hashlib.sha256).digest())
        counter += 1
    return b"".join(blocks)[:length]


class GoogleLocalKeyFileProtection:
    """Non-Windows protected-store equivalent using a 0600 key file outside checkout.

    Ciphertext is HMAC-SHA256 keystream XOR (stdlib-only). The key file must live
    under the same validated external auth directory as the secret envelopes.
    """

    kind = GOOGLE_SESSION_PROTECTION_LOCAL

    def __init__(self, key_path: Path) -> None:
        self.key_path = Path(key_path)

    def _load_or_create_key(self) -> bytes:
        path = self.key_path
        if path.exists():
            try:
                raw = path.read_bytes()
            except OSError as exc:
                raise GoogleCredentialProtectionUnavailable(
                    "Google local protection key unavailable"
                ) from exc
            if len(raw) != 32:
                raise GoogleCredentialCorruptError("Google local protection key is invalid")
            return raw
        key = secrets.token_bytes(32)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            fd = os.open(path, flags, 0o600)
            try:
                os.write(fd, key)
                os.fsync(fd)
            finally:
                os.close(fd)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except OSError as exc:
            raise GoogleCredentialProtectionUnavailable(
                "Google local protection key cannot be created"
            ) from exc
        return key

    def protect(self, plaintext: str) -> str:
        if not isinstance(plaintext, str) or not plaintext or len(plaintext) > _MAX_PLAINTEXT:
            raise GoogleCredentialCorruptError("Google credential snapshot is invalid")
        key = self._load_or_create_key()
        nonce = secrets.token_bytes(16)
        raw = plaintext.encode("utf-8")
        stream = _xor_keystream(key, nonce, len(raw))
        cipher = bytes(a ^ b for a, b in zip(raw, stream, strict=True))
        mac = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
        return json.dumps(
            {
                "format": _LOCAL_ENVELOPE_FORMAT,
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(cipher).decode("ascii"),
                "mac": base64.b64encode(mac).decode("ascii"),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def unprotect(self, envelope: str) -> str:
        if not isinstance(envelope, str) or not envelope or len(envelope) > _MAX_PLAINTEXT:
            raise GoogleCredentialCorruptError("protected Google envelope is invalid")
        try:
            value = json.loads(envelope)
        except (TypeError, ValueError) as exc:
            raise GoogleCredentialCorruptError("protected Google envelope is invalid") from exc
        if not isinstance(value, Mapping) or set(value) != {"format", "nonce", "ciphertext", "mac"}:
            raise GoogleCredentialCorruptError("protected Google envelope is invalid")
        if value.get("format") != _LOCAL_ENVELOPE_FORMAT:
            raise GoogleCredentialCorruptError("protected Google format is unsupported")
        try:
            nonce = base64.b64decode(str(value["nonce"]).encode("ascii"), validate=True)
            cipher = base64.b64decode(str(value["ciphertext"]).encode("ascii"), validate=True)
            mac = base64.b64decode(str(value["mac"]).encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError, KeyError) as exc:
            raise GoogleCredentialCorruptError("protected Google ciphertext is invalid") from exc
        if not nonce or not cipher or not mac:
            raise GoogleCredentialCorruptError("protected Google ciphertext is empty")
        key = self._load_or_create_key()
        expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected):
            raise GoogleCredentialCorruptError("protected Google envelope mac mismatch")
        raw = bytes(
            a ^ b for a, b in zip(cipher, _xor_keystream(key, nonce, len(cipher)), strict=True)
        )
        try:
            result = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GoogleCredentialCorruptError("protected Google text is invalid") from exc
        if not result or len(result) > _MAX_PLAINTEXT:
            raise GoogleCredentialCorruptError("protected Google text is invalid")
        return result


def default_google_protection(auth_dir: Path) -> GoogleCredentialProtection:
    """Windows DPAPI by default; local key-file protection elsewhere (CI-safe)."""

    if sys.platform == "win32":
        return GoogleWindowsUserScopedProtection()
    return GoogleLocalKeyFileProtection(Path(auth_dir) / ".google_protection_key")


__all__ = [
    "GOOGLE_SESSION_PROTECTION_LOCAL",
    "GOOGLE_SESSION_PROTECTION_WINDOWS",
    "GoogleCredentialCorruptError",
    "GoogleCredentialProtection",
    "GoogleCredentialProtectionUnavailable",
    "GoogleLocalKeyFileProtection",
    "GoogleWindowsUserScopedProtection",
    "default_google_protection",
]
