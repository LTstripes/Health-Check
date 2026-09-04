"""Content-addressed webhook payload storage outside Git."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from healthcheck.ingestion.openscale.errors import OpenScaleIngestError

MAX_PAYLOAD_BYTES = 1 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class StoredPayload:
    content_hash: str
    relative_storage_path: str
    created: bool
    byte_size: int


class ContentAddressedPayloadStore:
    """Store immutable webhook bytes under ``artifacts/payloads/<aa>/<hash>.json``."""

    def __init__(self, artifacts_root: Path):
        self.artifacts_root = artifacts_root

    def put(self, content: bytes, *, media_type: str = "application/json") -> StoredPayload:
        if len(content) > MAX_PAYLOAD_BYTES:
            raise OpenScaleIngestError(
                "payload_too_large",
                "webhook payload exceeds the configured size limit",
                status_code=413,
            )
        digest = hashlib.sha256(content).hexdigest()
        extension = ".json" if "json" in media_type.lower() else ".bin"
        relative = f"payloads/{digest[:2]}/{digest}{extension}"
        _validate_relative_storage_path(relative)
        absolute = self._resolve(relative)
        absolute.parent.mkdir(parents=True, exist_ok=True)
        created = False
        if not absolute.exists():
            temporary = absolute.with_name(absolute.name + ".tmp")
            temporary.write_bytes(content)
            temporary.replace(absolute)
            created = True
        return StoredPayload(
            content_hash=digest,
            relative_storage_path=relative,
            created=created,
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
            raise OpenScaleIngestError(
                "invalid_storage_path",
                "payload storage path escaped the artifact directory",
            ) from exc
        return absolute


def _validate_relative_storage_path(value: str) -> str:
    raw = value.strip().replace("\\", "/")
    posix_path = Path(raw)
    windows_path = PureWindowsPath(raw)
    if (
        not raw
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or raw.startswith(("/", "\\"))
    ):
        raise OpenScaleIngestError("invalid_storage_path", "payload storage path must be relative")
    if ".." in posix_path.parts or ".." in windows_path.parts:
        raise OpenScaleIngestError(
            "invalid_storage_path", "payload storage path must not escape its directory"
        )
    return raw


__all__ = ["ContentAddressedPayloadStore", "MAX_PAYLOAD_BYTES", "StoredPayload"]
