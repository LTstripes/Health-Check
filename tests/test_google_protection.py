"""Synthetic frozen #247 envelope, migration and read-side-effect regressions."""

from __future__ import annotations

import base64
import builtins
import hashlib
import hmac
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from healthcheck.config import Settings
from healthcheck.google import protection as module
from healthcheck.google.auth import GoogleAuthService
from healthcheck.google.protection import (
    GoogleCredentialCorruptError,
    GoogleCredentialProtectionUnavailable,
    GoogleLocalKeyFileProtection,
    GoogleWindowsUserScopedProtection,
)

KEY = bytes(range(32))
V1 = "healthcheck-google-local-key-v1"
V2 = "healthcheck-google-local-key-v2"
TOKENS = "google-tokens"
CLIENT = "google-client-credentials"
# Fixed known answers from the pre-#247 HMAC/XOR algorithm, not the candidate writer.
LEGACY = {
    "format": V1,
    "nonce": "AAECAwQFBgcICQoLDA0ODw==",
    "ciphertext": "aFM7wxZkwoQtW+7q/hRtnSw7BwFfiXdDq7Ks",
    "mac": "aOiGP+DhG9ziAs10D3dGmCojK033RWnYPI2xR44tPh4=",
}
LEGACY_CLIENT = {
    **LEGACY,
    "ciphertext": (
        "YAg22xdk2JkREuato1d9nWIsHQFPhXoaob+pyuq8T0COw+S6Zj7tzkrkmfCQb4CiwTIZrFfwW+VljXQ5iZAQ2qLJUw=="
    ),
    "mac": "Yn8VcCE594QhGHy2qMjncXNjlNXLNExTee8+Cbb7xgk=",
}
LEGACY_TOKENS = {
    **LEGACY,
    "ciphertext": (
        "YAg01B1kxZ4RD+3k/Bss3i4rDApPhHxDq7DtzuerCB/fgqTxcTX/41zykt2BdMn9jWNa4FDhUOVkiy0jj94Q2rCZS8b7r9MzmpMwJ6oXU4KJjP5RinlZzSKErT2yEjAPcpX9pIPBcOc3RkRGz4F9P7MPvNPgCpfvmWQ="
    ),
    "mac": "9kW5aaef0qUpaCBkjcDWgZLqWc1SmDyYWpKhM/SQOg8=",
}


def encoded(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def legacy_envelope(raw: bytes) -> str:
    """Test-only legacy producer for size/UTF-8 boundaries; fixed answers anchor it."""
    nonce = bytes(range(16))
    stream = b"".join(
        hmac.new(KEY, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest()
        for i in range((len(raw) + 31) // 32)
    )
    cipher = bytes(a ^ b for a, b in zip(raw, stream))
    return json.dumps(
        {
            "format": V1,
            "nonce": encoded(nonce),
            "ciphertext": encoded(cipher),
            "mac": encoded(hmac.new(KEY, nonce + cipher, hashlib.sha256).digest()),
        }
    )


def independent_v2(raw: bytes, *, aad: bytes | None = None) -> str:
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=V2.encode(), info=b"aes-256-gcm").derive(
        KEY
    )
    nonce = bytes(range(12))
    cipher = AESGCM(key).encrypt(
        nonce, raw, aad if aad is not None else V2.encode() + b"\0" + TOKENS.encode()
    )
    return json.dumps(
        {"format": V2, "purpose": TOKENS, "nonce": encoded(nonce), "ciphertext": encoded(cipher)}
    )


@pytest.fixture
def protector(tmp_path: Path) -> GoogleLocalKeyFileProtection:
    path = tmp_path / "key"
    path.write_bytes(KEY)
    return GoogleLocalKeyFileProtection(path)


@pytest.mark.parametrize("purpose", [TOKENS, CLIENT])
def test_legacy_known_answer_read_is_unchanged_and_unbound(protector, purpose) -> None:
    assert json.loads(legacy_envelope(b"synthetic legacy credential")) == LEGACY
    assert protector.unprotect(json.dumps(LEGACY), purpose=purpose) == "synthetic legacy credential"
    assert protector.key_path.read_bytes() == KEY


@pytest.mark.parametrize(
    "plaintext", ["x", "x" * 65536, "я" * 32768], ids=["min", "max-ascii", "max-utf8"]
)
@pytest.mark.parametrize("purpose", [TOKENS, CLIENT])
def test_v2_roundtrip_limits_canonical_format_and_unique_nonce(
    protector, plaintext, purpose
) -> None:
    first = protector.protect(plaintext, purpose=purpose)
    second = protector.protect(plaintext, purpose=purpose)
    value = json.loads(first)
    assert set(value) == {"format", "purpose", "nonce", "ciphertext"}
    assert value["format"] == V2 and value["purpose"] == purpose
    assert len(base64.b64decode(value["nonce"])) == 12
    assert len(base64.b64decode(value["ciphertext"])) == len(plaintext.encode()) + 16
    assert first == json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    assert len(first.encode()) <= 96 * 1024
    assert value["nonce"] != json.loads(second)["nonce"]
    assert protector.unprotect(first, purpose=purpose) == plaintext


def test_frozen_hkdf_and_aad_interoperate_with_independent_aesgcm(protector) -> None:
    assert (
        protector.unprotect(independent_v2(b"synthetic text"), purpose=TOKENS) == "synthetic text"
    )
    value = json.loads(protector.protect("synthetic text", purpose=TOKENS))
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=V2.encode(), info=b"aes-256-gcm").derive(
        KEY
    )
    assert (
        AESGCM(key).decrypt(
            base64.b64decode(value["nonce"]),
            base64.b64decode(value["ciphertext"]),
            V2.encode() + b"\0" + TOKENS.encode(),
        )
        == b"synthetic text"
    )


@pytest.mark.parametrize(
    "aad", [b"wrong-version\0google-tokens", V2.encode() + b"\0" + CLIENT.encode(), b""]
)
def test_authenticated_aad_is_expected_version_and_role(protector, aad) -> None:
    with pytest.raises(GoogleCredentialCorruptError):
        protector.unprotect(independent_v2(b"synthetic", aad=aad), purpose=TOKENS)


@pytest.mark.parametrize("field,offset", [("nonce", 0), ("ciphertext", 0), ("ciphertext", -1)])
@pytest.mark.parametrize("version", [V1, V2])
def test_nonce_ciphertext_and_tag_tampering_fails(protector, field, offset, version) -> None:
    value = (
        dict(LEGACY)
        if version == V1
        else json.loads(protector.protect("synthetic", purpose=TOKENS))
    )
    raw = bytearray(base64.b64decode(value[field]))
    raw[offset] ^= 1
    value[field] = encoded(raw)
    with pytest.raises(GoogleCredentialCorruptError):
        protector.unprotect(json.dumps(value), purpose=TOKENS)


def test_legacy_mac_tampering_fails(protector) -> None:
    value = {**LEGACY, "mac": encoded(b"x" * 32)}
    with pytest.raises(GoogleCredentialCorruptError):
        protector.unprotect(json.dumps(value), purpose=TOKENS)


@pytest.mark.parametrize("purpose,other", [(TOKENS, CLIENT), (CLIENT, TOKENS)])
def test_role_transplant_rejects_even_relabelled_envelope(protector, purpose, other) -> None:
    envelope = protector.protect("synthetic", purpose=purpose)
    with pytest.raises(GoogleCredentialCorruptError):
        protector.unprotect(envelope, purpose=other)
    value = json.loads(envelope)
    value["purpose"] = other
    with pytest.raises(GoogleCredentialCorruptError):
        protector.unprotect(json.dumps(value), purpose=other)


@pytest.mark.parametrize("version", [V1, V2])
def test_wrong_missing_unreadable_and_malformed_key_never_replaced(
    protector, monkeypatch, version
) -> None:
    envelope = (
        json.dumps(LEGACY) if version == V1 else protector.protect("synthetic", purpose=TOKENS)
    )
    for bad in [b"x" * 32, b"", b"x" * 31, b"x" * 33]:
        protector.key_path.write_bytes(bad)
        with pytest.raises(GoogleCredentialCorruptError):
            protector.unprotect(envelope, purpose=TOKENS)
        assert protector.key_path.read_bytes() == bad
    protector.key_path.unlink()
    with pytest.raises(GoogleCredentialProtectionUnavailable):
        protector.unprotect(envelope, purpose=TOKENS)
    assert not protector.key_path.exists()
    protector.key_path.write_bytes(KEY)
    original = Path.open

    def denied(path, *args, **kwargs):
        if path == protector.key_path:
            raise PermissionError("synthetic denial")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", denied)
        with pytest.raises(GoogleCredentialProtectionUnavailable):
            protector.unprotect(envelope, purpose=TOKENS)
    assert protector.key_path.read_bytes() == KEY


@pytest.mark.parametrize(
    "plaintext",
    ["", "x" * 65537, "я" * 32769, "\ud800", None],
    ids=["empty", "oversize-ascii", "oversize-utf8", "surrogate", "non-string"],
)
def test_invalid_plaintext_creates_no_key(tmp_path, plaintext) -> None:
    protection = GoogleLocalKeyFileProtection(tmp_path / "missing" / "key")
    with pytest.raises(GoogleCredentialCorruptError):
        protection.protect(plaintext, purpose=TOKENS)
    assert not protection.key_path.parent.exists()


@pytest.mark.parametrize("purpose", ["", "A", "bad_role", "я", "x" * 65, "abc\n", None, 1])
def test_invalid_expected_purpose_fails_before_key_creation(tmp_path, purpose) -> None:
    protection = GoogleLocalKeyFileProtection(tmp_path / "missing" / "key")
    with pytest.raises(GoogleCredentialCorruptError):
        protection.protect("synthetic", purpose=purpose)
    with pytest.raises(GoogleCredentialCorruptError):
        protection.unprotect(json.dumps(LEGACY), purpose=purpose)
    assert not protection.key_path.parent.exists()


@pytest.mark.parametrize("purpose", ["a", "a" * 64])
def test_valid_purpose_limits(protector, purpose) -> None:
    envelope = protector.protect("synthetic", purpose=purpose)
    assert protector.unprotect(envelope, purpose=purpose) == "synthetic"


@pytest.mark.parametrize(
    "envelope",
    [
        "",
        "{",
        "null",
        "[]",
        '"text"',
        "1",
        "[" * 2000 + "]" * 2000,
        "x" * (96 * 1024 + 1),
        "я" * (48 * 1024 + 1),
        "\ud800",
        None,
        '{"format":"a","format":"b"}',
    ],
    ids=[
        "empty",
        "truncated",
        "null",
        "array",
        "string",
        "number",
        "deep",
        "oversize-ascii",
        "oversize-utf8",
        "surrogate",
        "non-string",
        "duplicate",
    ],
)
def test_json_parser_and_envelope_limits_fail_closed_without_key(tmp_path, envelope) -> None:
    protection = GoogleLocalKeyFileProtection(tmp_path / "missing" / "key")
    with pytest.raises(GoogleCredentialCorruptError):
        protection.unprotect(envelope, purpose=TOKENS)
    assert not protection.key_path.parent.exists()


@pytest.mark.parametrize("version", [V1, V2])
@pytest.mark.parametrize("change", ["extra", "missing", "format", "object-format", "duplicate"])
def test_exact_fields_and_format(protector, version, change) -> None:
    value = (
        dict(LEGACY)
        if version == V1
        else json.loads(protector.protect("synthetic", purpose=TOKENS))
    )
    if change == "extra":
        value["extra"] = "bad"
    elif change == "missing":
        del value["nonce"]
    elif change == "format":
        value["format"] = "healthcheck-google-local-key-v3"
    elif change == "object-format":
        value["format"] = {}
    envelope = json.dumps(value)
    if change == "duplicate":
        envelope = envelope[:-1] + ',"nonce":"AA=="}'
    with pytest.raises(GoogleCredentialCorruptError):
        protector.unprotect(envelope, purpose=TOKENS)


@pytest.mark.parametrize("field", ["nonce", "ciphertext", "mac"])
@pytest.mark.parametrize("bad", ["!", "AA==\n", "я", None, 123, [], {}])
def test_strict_v1_base64_types(protector, field, bad) -> None:
    with pytest.raises(GoogleCredentialCorruptError):
        protector.unprotect(json.dumps({**LEGACY, field: bad}), purpose=TOKENS)


@pytest.mark.parametrize("field", ["nonce", "ciphertext"])
@pytest.mark.parametrize("bad", ["!", "AA==\n", "я", None, 123, [], {}])
def test_strict_v2_base64_types(protector, field, bad) -> None:
    value = json.loads(protector.protect("synthetic", purpose=TOKENS))
    value[field] = bad
    with pytest.raises(GoogleCredentialCorruptError):
        protector.unprotect(json.dumps(value), purpose=TOKENS)


@pytest.mark.parametrize(
    "field,length",
    [
        ("nonce", 0),
        ("nonce", 15),
        ("nonce", 17),
        ("mac", 0),
        ("mac", 31),
        ("mac", 33),
        ("ciphertext", 0),
        ("ciphertext", 65537),
    ],
)
def test_v1_strict_decoded_lengths(protector, field, length) -> None:
    with pytest.raises(GoogleCredentialCorruptError):
        protector.unprotect(json.dumps({**LEGACY, field: encoded(b"x" * length)}), purpose=TOKENS)


@pytest.mark.parametrize(
    "field,length",
    [
        ("nonce", 0),
        ("nonce", 11),
        ("nonce", 13),
        ("ciphertext", 0),
        ("ciphertext", 16),
        ("ciphertext", 65553),
    ],
)
def test_v2_strict_decoded_lengths(protector, field, length) -> None:
    value = json.loads(protector.protect("synthetic", purpose=TOKENS))
    value[field] = encoded(b"x" * length)
    with pytest.raises(GoogleCredentialCorruptError):
        protector.unprotect(json.dumps(value), purpose=TOKENS)


@pytest.mark.parametrize("bad", ["", "INVALID", "я", "x" * 65, None, []])
def test_v2_bad_envelope_purpose(protector, bad) -> None:
    value = json.loads(protector.protect("synthetic", purpose=TOKENS))
    value["purpose"] = bad
    with pytest.raises(GoogleCredentialCorruptError):
        protector.unprotect(json.dumps(value), purpose=TOKENS)


@pytest.mark.parametrize("length", [1, 65536])
def test_legacy_plaintext_size_limits(protector, length) -> None:
    assert protector.unprotect(legacy_envelope(b"x" * length), purpose=TOKENS) == "x" * length


@pytest.mark.parametrize("envelope", [legacy_envelope(b"\xff"), independent_v2(b"\xff")])
def test_authenticated_invalid_utf8_fails_closed(protector, envelope) -> None:
    with pytest.raises(GoogleCredentialCorruptError):
        protector.unprotect(envelope, purpose=TOKENS)


def test_normal_store_writes_migrate_both_roles_only_on_write(tmp_path, caplog) -> None:
    runtime = tmp_path / "runtime"
    key_path = runtime / "google" / "auth" / ".google_protection_key"
    key_path.parent.mkdir(parents=True)
    key_path.write_bytes(KEY)
    service = GoogleAuthService(
        Settings(data_dir=runtime), protector=GoogleLocalKeyFileProtection(key_path)
    )
    service.client_path.write_text(json.dumps(LEGACY_CLIENT), encoding="utf-8")
    service.token_path.write_text(json.dumps(LEGACY_TOKENS), encoding="utf-8")
    paths = [service.client_path, service.token_path, key_path]
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
    client = service.load_client_credentials()
    tokens = service._read_tokens()
    assert client.client_secret == "synthetic-secret" and tokens.access_token == "synthetic-access"
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths] == before
    service.store_client_credentials(client)
    assert service.token_path.read_bytes() == before[1][0]
    service._write_tokens(tokens)
    assert key_path.read_bytes() == KEY
    for path, purpose in [(service.client_path, CLIENT), (service.token_path, TOKENS)]:
        value = json.loads(path.read_text())
        assert value["format"] == V2 and value["purpose"] == purpose
        assert (
            "synthetic-secret" not in path.read_text()
            and "synthetic-access" not in path.read_text()
        )
    assert service.load_client_credentials() == client
    assert service._read_tokens() == tokens
    assert "synthetic-secret" not in caplog.text and "synthetic-access" not in caplog.text
    client_bytes = service.client_path.read_bytes()
    token_bytes = service.token_path.read_bytes()
    service.client_path.write_bytes(token_bytes)
    service.token_path.write_bytes(client_bytes)
    with pytest.raises(GoogleCredentialCorruptError):
        service.load_client_credentials()
    with pytest.raises(GoogleCredentialCorruptError):
        service._read_tokens()
    key_path.unlink()
    service.client_path.write_bytes(client_bytes)
    service.token_path.write_bytes(token_bytes)
    for load in [service.load_client_credentials, service._read_tokens]:
        with pytest.raises(GoogleCredentialProtectionUnavailable):
            load()
        assert not key_path.exists()
    assert service.client_path.read_bytes() == client_bytes
    assert service.token_path.read_bytes() == token_bytes


def test_v2_pure_read_performs_no_filesystem_write(protector, monkeypatch) -> None:
    envelope = protector.protect("synthetic", purpose=TOKENS)
    original = Path.open

    def read_only(path, mode="r", *args, **kwargs):
        assert mode == "rb"
        return original(path, mode, *args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("pure read attempted filesystem mutation")

    monkeypatch.setattr(Path, "open", read_only)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(module.os, "open", forbidden)
    monkeypatch.setattr(module.os, "write", forbidden)
    assert protector.unprotect(envelope, purpose=TOKENS) == "synthetic"


def test_new_write_creates_only_one_32_byte_key(tmp_path) -> None:
    protection = GoogleLocalKeyFileProtection(tmp_path / "auth" / "key")
    first = protection.protect("synthetic", purpose=TOKENS)
    key = protection.key_path.read_bytes()
    second = protection.protect("synthetic", purpose=CLIENT)
    assert len(key) == 32 and protection.key_path.read_bytes() == key
    assert list(protection.key_path.parent.iterdir()) == [protection.key_path]
    assert protection.unprotect(first, purpose=TOKENS) == "synthetic"
    assert protection.unprotect(second, purpose=CLIENT) == "synthetic"


def test_windows_dpapi_envelope_and_purpose_ignored_without_crypto(monkeypatch) -> None:
    original_import = builtins.__import__

    def without_crypto(name, *args, **kwargs):
        assert not name.startswith("cryptography")
        return original_import(name, *args, **kwargs)

    protected = []
    monkeypatch.setattr(builtins, "__import__", without_crypto)
    monkeypatch.setattr(module, "_current_windows_user_sid", lambda: "synthetic-sid")
    monkeypatch.setattr(module, "_dpapi_protect", lambda raw: protected.append(raw) or b"cipher")
    monkeypatch.setattr(
        module, "_dpapi_unprotect", lambda raw: b"synthetic" if raw == b"cipher" else b""
    )
    protection = GoogleWindowsUserScopedProtection()
    envelope = protection.protect("synthetic", purpose="ignored invalid purpose!")
    assert protected == [b"synthetic"]
    assert envelope == (
        '{"ciphertext":"Y2lwaGVy","format":"healthcheck-google-dpapi-v1",'
        '"user_sid":"synthetic-sid"}'
    )
    assert protection.unprotect(envelope, purpose="also ignored") == "synthetic"
    with pytest.raises(GoogleCredentialCorruptError):
        protection.unprotect(envelope.replace("synthetic-sid", "different-sid"), purpose=TOKENS)
