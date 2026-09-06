"""Offline synthetic Garmin payload fixture contract.

The fixture envelope is intentionally not an ingestion or persistence model.
It provides a stable shape for contract tests while the real Garmin adapter
and owner-controlled live spike remain future work.  ``payload_fields`` only
records fields present in a synthetic payload; it never promotes a field to a
Vivoactive 5 capability.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from healthcheck.garmin.capabilities import (
    GARMIN_PROVIDER_CODE,
    VIVOACTIVE_5_DEVICE_CODE,
    VIVOACTIVE_5_MODEL,
    GarminStream,
    get_capability,
)

CAPABILITY_FIXTURE_CONTRACT_VERSION = "r02-garmin-capability-fixture-v1"
SYNTHETIC_SOURCE_KIND = "synthetic"
_MISSING = object()
_FORBIDDEN_KEY_PARTS = frozenset(
    {
        "access_token",
        "authorization",
        "bearer",
        "client_secret",
        "cookie",
        "credential",
        "email",
        "mfa",
        "otp",
        "password",
        "refresh_token",
        "secret",
        "token",
        "username",
    }
)
_SHORT_FORBIDDEN_TOKENS = frozenset(part for part in _FORBIDDEN_KEY_PARTS if len(part) <= 3)
_KEY_TOKEN_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


class GarminCapabilityFixtureError(ValueError):
    """Raised when an offline fixture violates the synthetic contract."""


@dataclass(frozen=True, slots=True)
class GarminCapabilityFixture:
    """Validated, immutable metadata for one synthetic provider-shaped payload."""

    fixture_id: str
    stream: GarminStream
    provider_code: str
    device_attributed: bool
    device_code: str | None
    device_model: str | None
    payload: Mapping[str, Any]
    payload_fields: Mapping[str, str]
    client_methods: Sequence[str] = ()
    contract_version: str = CAPABILITY_FIXTURE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        fixture_id = _required_text(self.fixture_id, "fixture_id")
        try:
            stream = GarminStream(self.stream)
        except (TypeError, ValueError) as exc:
            raise GarminCapabilityFixtureError("unsupported stream_code") from exc
        provider_code = _required_text(self.provider_code, "provider_code")
        if not isinstance(self.device_attributed, bool):
            raise GarminCapabilityFixtureError("device.attributed must be boolean")
        device_code = _optional_text(self.device_code)
        device_model = _optional_text(self.device_model)
        if not isinstance(self.payload, Mapping):
            raise GarminCapabilityFixtureError("payload must be an object")
        payload = _freeze_mapping(self.payload)
        if not isinstance(self.payload_fields, Mapping):
            raise GarminCapabilityFixtureError("payload_fields must be an object")
        normalized_fields: dict[str, str] = {}
        for capability_code, path in self.payload_fields.items():
            if not isinstance(capability_code, str):
                raise GarminCapabilityFixtureError("payload_fields capability codes must be text")
            try:
                capability = get_capability(capability_code)
            except (KeyError, TypeError) as exc:
                raise GarminCapabilityFixtureError(
                    f"unknown capability in payload_fields: {capability_code}"
                ) from exc
            if capability.stream != stream:
                raise GarminCapabilityFixtureError(
                    f"capability stream mismatch: {capability_code} is not {stream.value}"
                )
            normalized_path = _required_text(path, "payload field path")
            if any(part == "" for part in normalized_path.split(".")):
                raise GarminCapabilityFixtureError(
                    "payload field paths cannot contain empty segments"
                )
            if _read_path(payload, normalized_path) is _MISSING:
                raise GarminCapabilityFixtureError(
                    f"payload field path is absent: {capability_code} -> {normalized_path}"
                )
            if capability.code in normalized_fields:
                raise GarminCapabilityFixtureError(
                    f"duplicate capability in payload_fields: {capability.code}"
                )
            normalized_fields[capability.code] = normalized_path
        client_methods = _text_tuple(self.client_methods, "client_methods")
        contract_version = _required_text(self.contract_version, "contract_version")
        object.__setattr__(self, "fixture_id", fixture_id)
        object.__setattr__(self, "stream", stream)
        object.__setattr__(self, "provider_code", provider_code)
        object.__setattr__(self, "device_code", device_code)
        object.__setattr__(self, "device_model", device_model)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(
            self, "payload_fields", MappingProxyType(dict(sorted(normalized_fields.items())))
        )
        object.__setattr__(self, "client_methods", client_methods)
        object.__setattr__(self, "contract_version", contract_version)
        self.validate()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> GarminCapabilityFixture:
        """Build and validate a fixture from its JSON object."""

        if not isinstance(value, Mapping):
            raise GarminCapabilityFixtureError("fixture root must be an object")
        _reject_forbidden_keys(value)
        contract_version = value.get("fixture_contract_version")
        if contract_version != CAPABILITY_FIXTURE_CONTRACT_VERSION:
            raise GarminCapabilityFixtureError("unsupported fixture contract version")
        if value.get("source_kind") != SYNTHETIC_SOURCE_KIND:
            raise GarminCapabilityFixtureError("only synthetic fixtures are allowed")
        device = value.get("device")
        if not isinstance(device, Mapping):
            raise GarminCapabilityFixtureError("device metadata is required")
        return cls(
            fixture_id=value.get("fixture_id"),
            stream=value.get("stream_code"),
            provider_code=value.get("provider_code"),
            device_attributed=device.get("attributed"),
            device_code=device.get("code"),
            device_model=device.get("model"),
            payload=value.get("payload"),
            payload_fields=value.get("payload_fields", {}),
            client_methods=value.get("client_methods", ()),
            contract_version=contract_version,
        )

    def validate(self) -> GarminCapabilityFixture:
        """Recheck invariants and return ``self`` for fluent contract tests."""

        if not self.fixture_id.startswith("synthetic-"):
            raise GarminCapabilityFixtureError("fixture_id must identify synthetic data")
        if self.provider_code != GARMIN_PROVIDER_CODE:
            raise GarminCapabilityFixtureError("fixture provider must be garmin_connect")
        if self.contract_version != CAPABILITY_FIXTURE_CONTRACT_VERSION:
            raise GarminCapabilityFixtureError("unsupported fixture contract version")
        if self.device_attributed:
            if self.device_code != VIVOACTIVE_5_DEVICE_CODE:
                raise GarminCapabilityFixtureError(
                    "attributed fixture device must be synthetic Vivoactive 5"
                )
            if self.device_model != VIVOACTIVE_5_MODEL:
                raise GarminCapabilityFixtureError(
                    "attributed fixture model must be synthetic Vivoactive 5"
                )
        elif self.device_code is not None or self.device_model is not None:
            raise GarminCapabilityFixtureError(
                "unattributed fixture must not carry a device identity"
            )
        _reject_forbidden_keys(self.payload)
        return self

    def payload_field_present(self, capability_code: str) -> bool:
        """Return raw field presence, including an explicit JSON null."""

        path = self.payload_fields.get(capability_code.strip().lower())
        return path is not None and _read_path(self.payload, path) is not _MISSING

    def payload_value(self, capability_code: str) -> Any:
        """Return a raw field value; missing and explicit null remain distinct."""

        path = self.payload_fields.get(capability_code.strip().lower())
        if path is None:
            return _MISSING
        return _read_path(self.payload, path)

    def payload_has_value(self, capability_code: str) -> bool:
        """Return true only for a present, non-null raw field."""

        value = self.payload_value(capability_code)
        return value is not _MISSING and value is not None

    def as_dict(self) -> dict[str, Any]:
        """Return metadata only; raw fixture payloads are not copied to reports."""

        return {
            "fixture_id": self.fixture_id,
            "fixture_contract_version": self.contract_version,
            "source_kind": SYNTHETIC_SOURCE_KIND,
            "provider_code": self.provider_code,
            "stream_code": self.stream.value,
            "device": {
                "attributed": self.device_attributed,
                "code": self.device_code,
                "model": self.device_model,
            },
            "payload_fields": dict(self.payload_fields),
            "client_methods": list(self.client_methods),
        }


def load_synthetic_fixture(path: str | Path) -> GarminCapabilityFixture:
    """Load one checked-in synthetic JSON fixture without network or persistence."""

    fixture_path = Path(path)
    try:
        value = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GarminCapabilityFixtureError("synthetic fixture is not valid JSON") from exc
    return GarminCapabilityFixture.from_mapping(value)


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    # A shallow read-only view is sufficient for the envelope ownership
    # boundary; validation walks nested mappings recursively.
    return MappingProxyType(dict(value))


def _read_path(value: Any, path: str) -> Any:
    current = value
    for segment in path.split("."):
        if isinstance(current, Mapping):
            if segment not in current:
                return _MISSING
            current = current[segment]
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            try:
                current = current[int(segment)]
            except (IndexError, TypeError, ValueError):
                return _MISSING
        else:
            return _MISSING
    return current


def is_forbidden_payload_key(key: object) -> bool:
    """Return True when a mapping key is credential or token shaped.

    Short secret tokens such as ``mfa`` match only as whole key tokens after
    camelCase and separator splits. Longer fragments still match as
    substrings so keys like ``ownerEmail`` and ``refreshToken`` stay
    fail-closed.
    """

    key_text = str(key).strip()
    if not key_text:
        return False
    lowered = key_text.lower()
    tokens = _payload_key_tokens(key_text)
    for part in _FORBIDDEN_KEY_PARTS:
        if part in _SHORT_FORBIDDEN_TOKENS:
            if part == lowered or part in tokens:
                return True
        elif part in lowered:
            return True
    return False


def _payload_key_tokens(key_text: str) -> frozenset[str]:
    tokens: set[str] = set()
    for piece in re.split(r"[^A-Za-z0-9]+", key_text):
        if not piece:
            continue
        tokens.add(piece.lower())
        tokens.update(match.group(0).lower() for match in _KEY_TOKEN_RE.finditer(piece))
    return frozenset(tokens)


def _reject_forbidden_keys(value: Any, path: str = "fixture") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if is_forbidden_payload_key(key):
                raise GarminCapabilityFixtureError(
                    f"forbidden credential/private key in synthetic fixture: {path}.{key}"
                )
            _reject_forbidden_keys(nested, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            _reject_forbidden_keys(nested, f"{path}[{index}]")


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GarminCapabilityFixtureError(f"{name} is required")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GarminCapabilityFixtureError("optional device metadata must be text or null")
    normalized = value.strip()
    return normalized or None


def _text_tuple(values: Sequence[str], name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise GarminCapabilityFixtureError(f"{name} must be an array")
    try:
        result = tuple(_required_text(value, name) for value in values)
    except TypeError as exc:
        raise GarminCapabilityFixtureError(f"{name} must be an array") from exc
    if len(result) != len(set(result)):
        raise GarminCapabilityFixtureError(f"{name} must not contain duplicates")
    return result


__all__ = [
    "CAPABILITY_FIXTURE_CONTRACT_VERSION",
    "GarminCapabilityFixture",
    "GarminCapabilityFixtureError",
    "is_forbidden_payload_key",
    "load_synthetic_fixture",
]
