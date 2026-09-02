"""External runtime directory layout and safety checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from healthcheck.config import Settings


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """Resolved paths for state that must not live in the repository."""

    root: Path
    config: Path
    database: Path
    photos: Path
    payloads: Path
    logs: Path


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_runtime_paths(settings: Settings) -> RuntimePaths:
    root = settings.data_dir.resolve()
    repository = _repository_root()
    try:
        root.relative_to(repository)
    except ValueError:
        pass
    else:
        raise ValueError(f"HEALTHCHECK_DATA_DIR must be outside the checkout: {root}")

    artifacts = root / "artifacts"
    return RuntimePaths(
        root=root,
        config=root / "config.toml",
        database=root / "healthcheck.db",
        photos=artifacts / "photos",
        payloads=artifacts / "payloads",
        logs=root / "logs",
    )


def prepare_runtime(settings: Settings) -> RuntimePaths:
    """Create only the external runtime directories needed by the bootstrap."""

    paths = resolve_runtime_paths(settings)
    paths.photos.mkdir(parents=True, exist_ok=True)
    paths.payloads.mkdir(parents=True, exist_ok=True)
    paths.logs.mkdir(parents=True, exist_ok=True)
    paths.config.touch(exist_ok=True)
    return paths
