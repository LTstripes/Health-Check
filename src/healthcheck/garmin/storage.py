"""Content-addressed storage for offline Garmin source payloads."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from uuid import uuid4

from healthcheck.garmin.contracts import GarminCapabilityFixture, is_forbidden_payload_key


@dataclass(frozen=True, slots=True)
class StoredGarminPayload:
    """Result of writing one immutable Garmin payload artifact."""

    content_hash: str
    relative_storage_path: str
    created: bool
    byte_size: int


class ContentAddressedGarminPayloadStore:
    """Store JSON/FIT bytes below an external ``artifacts`` directory.

    The storage path contains only a digest and a safe extension.  The store
    never writes inside the checkout and does not keep a second copy in the
    SQLite database.
    """

    def __init__(self, artifacts_root: Path):
        self.artifacts_root = Path(artifacts_root)

    def put(
        self,
        content: bytes,
        *,
        media_type: str = "application/json",
        payload_format: str | None = None,
    ) -> StoredGarminPayload:
        if not isinstance(content, bytes):
            raise TypeError("Garmin payload content must be bytes")
        digest = hashlib.sha256(content).hexdigest()
        if payload_format is not None and not isinstance(payload_format, str):
            raise TypeError("Garmin payload format must be text or null")
        normalized_format = (
            (payload_format or _payload_format_for_media_type(media_type)).strip().lower()
        )
        extension = {"json": ".json", "fit": ".fit", "binary": ".bin"}.get(normalized_format)
        if extension is None:
            raise ValueError("Garmin payload format must be json, fit, or binary")
        relative = f"payloads/{digest[:2]}/{digest}{extension}"
        _validate_relative_storage_path(relative)
        absolute = self._resolve(relative)
        absolute.parent.mkdir(parents=True, exist_ok=True)
        if absolute.exists():
            if (
                not absolute.is_file()
                or hashlib.sha256(absolute.read_bytes()).hexdigest() != digest
            ):
                raise ValueError(
                    "content-addressed Garmin payload artifact does not match its hash"
                )
            return StoredGarminPayload(
                content_hash=digest,
                relative_storage_path=relative,
                created=False,
                byte_size=len(content),
            )

        temporary = absolute.with_name(f".{absolute.name}.{uuid4().hex}.tmp")
        temporary.write_bytes(content)
        temporary.replace(absolute)
        return StoredGarminPayload(
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
            raise ValueError("Garmin payload storage path escaped the artifact directory") from exc
        return absolute


def serialize_garmin_payload(
    value: bytes | bytearray | Mapping[str, object] | GarminCapabilityFixture,
) -> bytes:
    """Serialize a synthetic mapping without changing presence semantics.

    Bytes are accepted verbatim so a caller can retain the exact provider
    response.  Mapping and fixture inputs are deterministic test conveniences;
    they are canonicalized only for content-addressed storage.
    """

    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, bytes):
        return value
    if isinstance(value, GarminCapabilityFixture):
        value = {
            "fixture_contract_version": value.contract_version,
            "fixture_id": value.fixture_id,
            "source_kind": "synthetic",
            "provider_code": value.provider_code,
            "stream_code": value.stream.value,
            "device": {
                "attributed": value.device_attributed,
                "code": value.device_code,
                "model": value.device_model,
            },
            "client_methods": list(value.client_methods),
            "payload_fields": dict(value.payload_fields),
            "payload": value.payload,
        }
    if not isinstance(value, Mapping):
        raise TypeError("Garmin payload must be bytes, a mapping, or a validated fixture")
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
        raise ValueError("Garmin payload mapping is not JSON serializable") from exc


def _payload_format_for_media_type(media_type: str) -> str:
    normalized = media_type.split(";", 1)[0].strip().lower()
    if "json" in normalized:
        return "json"
    if normalized in {"application/fit", "application/vnd.garmin.fit"} or "fit" in normalized:
        return "fit"
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
            if is_forbidden_payload_key(key):
                raise ValueError(
                    "private or credential-shaped payload key is not accepted"
                )
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
        raise ValueError("Garmin payload storage path must be relative and non-escaping")
    return raw


__all__ = [
    "ContentAddressedGarminPayloadStore",
    "StoredGarminPayload",
    "serialize_garmin_payload",
]
