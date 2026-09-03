"""Content-addressed photo storage outside Git."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from healthcheck.ingestion.photo.errors import PhotoImportError

_MEDIA_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


@dataclass(frozen=True, slots=True)
class StoredPhoto:
    content_hash: str
    relative_storage_path: str
    created: bool


class ContentAddressedPhotoStore:
    """Store immutable image bytes under ``artifacts/photos/<aa>/<hash>.<ext>``."""

    def __init__(self, artifacts_root: Path):
        self.artifacts_root = artifacts_root

    def put(self, content: bytes, media_type: str) -> StoredPhoto:
        digest = hashlib.sha256(content).hexdigest()
        extension = _MEDIA_EXTENSIONS.get(media_type)
        if extension is None:
            raise PhotoImportError("unsupported_media_type", "unsupported photo media type")
        relative = f"photos/{digest[:2]}/{digest}{extension}"
        _validate_relative_storage_path(relative)
        absolute = self._resolve(relative)
        absolute.parent.mkdir(parents=True, exist_ok=True)
        created = False
        if not absolute.exists():
            temporary = absolute.with_name(absolute.name + ".tmp")
            temporary.write_bytes(content)
            temporary.replace(absolute)
            created = True
        return StoredPhoto(content_hash=digest, relative_storage_path=relative, created=created)

    def read(self, relative_storage_path: str) -> bytes:
        return self._resolve(relative_storage_path).read_bytes()

    def _resolve(self, relative_storage_path: str) -> Path:
        relative = _validate_relative_storage_path(relative_storage_path)
        absolute = (self.artifacts_root / relative).resolve()
        try:
            absolute.relative_to(self.artifacts_root.resolve())
        except ValueError as exc:
            raise PhotoImportError(
                "invalid_storage_path", "photo storage path escaped the artifact directory"
            ) from exc
        return absolute


def detect_media_type(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    raise PhotoImportError("unsupported_media_type", "only png, jpeg and webp photos are accepted")


def safe_filename(filename: str | None) -> str | None:
    if filename is None:
        return None
    raw = filename.strip()
    if not raw:
        return None
    posix_path = Path(raw)
    windows_path = PureWindowsPath(raw)
    if posix_path.is_absolute() or windows_path.is_absolute() or raw.startswith(("/", "\\")):
        raise PhotoImportError("invalid_filename", "source_filename must not be an absolute path")
    name = posix_path.name or windows_path.name
    if not name or name in {".", ".."}:
        return None
    return name[:255]


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
        raise PhotoImportError("invalid_storage_path", "photo storage path must be relative")
    if ".." in posix_path.parts or ".." in windows_path.parts:
        raise PhotoImportError(
            "invalid_storage_path", "photo storage path must not escape its directory"
        )
    return raw
