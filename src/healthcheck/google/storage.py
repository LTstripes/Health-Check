"""Content-addressed storage for offline Google Health source payloads."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from uuid import uuid4

_FORBIDDEN_KEY_FRAGMENTS = (
    "access_token",
    "refresh_token",
    "client_secret",
    "id_token",
    "authorization",
    "password",
    "bind_key",
    "private_key",
)


@dataclass(frozen=True, slots=True)
class StoredGooglePayload:
    """Result of writing one immutable Google payload artifact."""

    content_hash: str
    relative_storage_path: str
    created: bool
    byte_size: int


class ContentAddressedGooglePayloadStore:
    """Store JSON/binary bytes below an external ``artifacts`` directory."""

    def __init__(self, artifacts_root: Path):
        self.artifacts_root = Path(artifacts_root)

    def put(
        self,
        content: bytes,
        *,
        media_type: str = "application/json",
        payload_format: str | None = None,
    ) -> StoredGooglePayload:
        if not isinstance(content, bytes):
            raise TypeError("Google payload content must be bytes")
        digest = hashlib.sha256(content).hexdigest()
        normalized_format = (
            (payload_format or _payload_format_for_media_type(media_type)).strip().lower()
        )
        extension = {"json": ".json", "binary": ".bin"}.get(normalized_format)
        if extension is None:
            raise ValueError("Google payload format must be json or binary")
        relative = f"google/payloads/{digest[:2]}/{digest}{extension}"
        _validate_relative_storage_path(relative)
        absolute = self._resolve(relative)
        absolute.parent.mkdir(parents=True, exist_ok=True)
        if absolute.exists():
            if (
                not absolute.is_file()
                or hashlib.sha256(absolute.read_bytes()).hexdigest() != digest
            ):
                raise ValueError(
                    "content-addressed Google payload artifact does not match its hash"
                )
            return StoredGooglePayload(
                content_hash=digest,
                relative_storage_path=relative,
                created=False,
                byte_size=len(content),
            )

        temporary = absolute.with_name(f".{absolute.name}.{uuid4().hex}.tmp")
        temporary.write_bytes(content)
        temporary.replace(absolute)
        return StoredGooglePayload(
            content_hash=digest,
            relative_storage_path=relative,
            created=True,
            byte_size=len(content),
        )

    def read(self, relative_storage_path: str) -> bytes:
        return self._resolve(relative_storage_path).read_bytes()

    def _resolve(self, relative_storage_path: str) -> Path:
        relative = _validate_relative_storage_path(relative_storage_path)
        absolute = (self.artifacts_root / relative).resolve()
        try:
            absolute.relative_to(self.artifacts_root.resolve())
        except ValueError as exc:
            raise ValueError("Google payload storage path escaped the artifact directory") from exc
        return absolute


def serialize_google_payload(value: bytes | bytearray | Mapping[str, object]) -> bytes:
    """Serialize synthetic mappings without changing presence semantics."""

    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, bytes):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("Google payload must be bytes or a mapping")
    _reject_private_keys(value)
    try:
        return json.dumps(
            _json_value(value),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Google payload mapping is not JSON serializable") from exc


def _payload_format_for_media_type(media_type: str) -> str:
    normalized = media_type.split(";", 1)[0].strip().lower()
    if "json" in normalized:
        return "json"
    return "binary"


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(nested) for key, nested in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(nested) for nested in value]
    return value


def _reject_private_keys(value: object, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                raise ValueError("private or credential-shaped payload key is not accepted")
            _reject_private_keys(nested, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            _reject_private_keys(nested, f"{path}[{index}]")


def _validate_relative_storage_path(value: str) -> str:
    raw = str(value).strip().replace("\\", "/")
    posix_path = Path(raw)
    windows_path = PureWindowsPath(raw)
    if (
        not raw
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or raw.startswith(("/", "\\"))
        or ".." in posix_path.parts
        or ".." in windows_path.parts
    ):
        raise ValueError("Google payload storage path must be relative and non-escaping")
    return raw


__all__ = [
    "ContentAddressedGooglePayloadStore",
    "StoredGooglePayload",
    "serialize_google_payload",
]
