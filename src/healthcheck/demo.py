"""Safe, synthetic-only R01 demo profile seeding."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from healthcheck.config import Settings
from healthcheck.db.engine import (
    create_sqlite_engine,
    migrate_database,
    session_scope,
)
from healthcheck.db.models import (
    AcquisitionSource,
    ImportCandidate,
    IngestBatch,
    IngestEvent,
    MeasurementSession,
    ScalarMeasurement,
)
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.ingestion.photo.service import PhotoImportService, PhotoUpload
from healthcheck.ingestion.photo.synthetic import (
    encode_synthetic_png,
    six_month_synthetic_batch,
)
from healthcheck.runtime import RuntimePaths, prepare_runtime, resolve_runtime_paths
from healthcheck.web.query import WeightQueryService

DEMO_SEED_ID = "r01-six-month-synthetic-v1"
DEMO_MARKER_NAME = ".healthcheck-synthetic-demo.json"
DEMO_SOURCE_APPLICATION = "Health-Check Synthetic Demo"


class DemoSeedError(ValueError):
    """Raised when the requested runtime is not a safe demo target."""


@dataclass(frozen=True, slots=True)
class DemoSeedResult:
    data_dir: Path
    created: bool
    reset: bool
    weigh_in_count: int
    candidate_count: int


def seed_demo(settings: Settings, *, reset: bool = False) -> DemoSeedResult:
    """Create or safely re-use a dedicated synthetic demo profile.

    A non-empty runtime without this tool's marker is never modified.  Reset is
    accepted only for a previously marked demo profile and removes only the
    known demo database/artifact state before reseeding it.
    """

    raw_target = Path(settings.data_dir).expanduser().absolute()
    if raw_target.is_symlink():
        raise DemoSeedError("demo target must not be a symlink")

    try:
        paths = resolve_runtime_paths(settings)
    except ValueError as exc:
        raise DemoSeedError(str(exc)) from None

    marker = paths.root / DEMO_MARKER_NAME
    had_marked_demo = False
    if paths.root.exists():
        if not paths.root.is_dir() or paths.root.is_symlink():
            raise DemoSeedError("demo target must be a real directory")
        if marker.exists():
            if marker.is_symlink() or not marker.is_file():
                raise DemoSeedError("demo marker is not a regular file")
            _read_and_validate_marker(marker)
            had_marked_demo = True
            if reset:
                _reset_marked_demo(paths, marker)
            else:
                _validate_seeded_demo(paths)
                marker_data = _read_and_validate_marker(marker)
                return DemoSeedResult(
                    data_dir=paths.root,
                    created=False,
                    reset=False,
                    weigh_in_count=int(marker_data["weigh_in_count"]),
                    candidate_count=int(marker_data["candidate_count"]),
                )
        elif any(paths.root.iterdir()):
            raise DemoSeedError(
                "demo target is non-empty and is not a Health-Check synthetic demo; "
                "choose a new dedicated HEALTHCHECK_DATA_DIR"
            )

    # A reset removes the marker after its safety check.  Any later failure is
    # intentionally fail-closed: the next invocation will not guess ownership.
    if had_marked_demo and marker.exists():
        marker.unlink()

    paths = prepare_runtime(settings)
    migrate_database(paths)
    uploads, expected_candidates = _synthetic_uploads()
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            service = PhotoImportService(
                session,
                paths,
                FakeImageMeasurementExtractor(version="synthetic-demo-v1"),
            )
            imported = service.import_photos(
                uploads,
                timezone="UTC",
                provider_code="xiaomi_home",
            )
            candidate_ids = [
                candidate_id for item in imported.items for candidate_id in item.candidate_ids
            ]
            if len(candidate_ids) != expected_candidates:
                raise DemoSeedError("synthetic import did not produce the expected candidate set")
            service.confirm(candidate_ids, actor="synthetic-demo")
    finally:
        engine.dispose()

    _write_marker(
        paths,
        weigh_in_count=len(uploads),
        candidate_count=expected_candidates,
    )
    _validate_seeded_demo(paths)
    return DemoSeedResult(
        data_dir=paths.root,
        created=True,
        reset=reset,
        weigh_in_count=len(uploads),
        candidate_count=expected_candidates,
    )


def _synthetic_uploads() -> tuple[list[PhotoUpload], int]:
    uploads: list[PhotoUpload] = []
    candidate_count = 0
    for filename, _image, payload in six_month_synthetic_batch():
        labelled_payload = dict(payload)
        labelled_payload["source_application"] = DEMO_SOURCE_APPLICATION
        image = encode_synthetic_png(labelled_payload)
        field_count = sum(len(group.get("fields") or []) for group in labelled_payload["groups"])
        candidate_count += field_count
        uploads.append(
            PhotoUpload(filename=filename, content=image, declared_media_type="image/png")
        )
    return uploads, candidate_count


def _marker_path(paths: RuntimePaths) -> Path:
    return paths.root / DEMO_MARKER_NAME


def _read_and_validate_marker(marker: Path) -> dict[str, Any]:
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DemoSeedError("demo marker is unreadable") from exc
    if not isinstance(value, dict) or value.get("seed_id") != DEMO_SEED_ID:
        raise DemoSeedError("demo marker is not owned by this synthetic seed")
    for key in ("weigh_in_count", "candidate_count"):
        if not isinstance(value.get(key), int) or value[key] <= 0:
            raise DemoSeedError("demo marker is invalid")
    return value


def _write_marker(paths: RuntimePaths, *, weigh_in_count: int, candidate_count: int) -> None:
    marker = _marker_path(paths)
    temporary = marker.with_name(f"{marker.name}.tmp")
    payload = {
        "format_version": 1,
        "seed_id": DEMO_SEED_ID,
        "label": "synthetic demo data",
        "weigh_in_count": weigh_in_count,
        "candidate_count": candidate_count,
    }
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, marker)


def _reset_marked_demo(paths: RuntimePaths, marker: Path) -> None:
    """Remove only state owned by a validated marker, leaving unknown files."""

    for database_path in (
        paths.database,
        Path(f"{paths.database}-wal"),
        Path(f"{paths.database}-shm"),
    ):
        if database_path.exists():
            if database_path.is_symlink() or not database_path.is_file():
                raise DemoSeedError("demo database state is not a regular file")
            database_path.unlink()
    artifacts = paths.root / "artifacts"
    if artifacts.exists():
        if artifacts.is_symlink() or not artifacts.is_dir():
            raise DemoSeedError("demo artifacts directory is not a regular directory")
        shutil.rmtree(artifacts)
    marker.touch(exist_ok=True)


def _validate_seeded_demo(paths: RuntimePaths) -> None:
    marker_data = _read_and_validate_marker(_marker_path(paths))
    if not paths.database.is_file():
        raise DemoSeedError("marked synthetic demo database is missing")
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            expected = {
                IngestBatch: 1,
                IngestEvent: marker_data["weigh_in_count"],
                ImportCandidate: marker_data["candidate_count"],
                MeasurementSession: marker_data["weigh_in_count"],
                ScalarMeasurement: marker_data["candidate_count"],
            }
            for model, count in expected.items():
                actual = session.scalar(select(func.count()).select_from(model))
                if actual != count:
                    raise DemoSeedError("marked synthetic demo does not match its seed manifest")
            source = session.scalar(
                select(AcquisitionSource).where(
                    AcquisitionSource.source_application == DEMO_SOURCE_APPLICATION
                )
            )
            if source is None or source.source_application != DEMO_SOURCE_APPLICATION:
                raise DemoSeedError("marked synthetic demo is not labelled as synthetic")
            payload = WeightQueryService(session, Settings(data_dir=paths.root)).dashboard()
            if len(payload["series"]["raw_points"]) != marker_data["weigh_in_count"]:
                raise DemoSeedError("marked synthetic demo has an unexpected weight series")
            if not payload["series"]["trend_points"]:
                raise DemoSeedError("marked synthetic demo has no trend data")
            if not payload["summary"]["latest_composition"]["available"]:
                raise DemoSeedError("marked synthetic demo has no composition summary")
            if not payload["series"]["composition_by_group"]:
                raise DemoSeedError("marked synthetic demo has no composition series")
            if payload["summary"]["coverage"] is None:
                raise DemoSeedError("marked synthetic demo has no coverage summary")
    finally:
        engine.dispose()
