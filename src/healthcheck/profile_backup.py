"""Safe backup, verification and restore for a local Health-Check profile."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from healthcheck.runtime import _repository_root

FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
PROFILE_PREFIX = "profile/"
DATABASE_NAME = "healthcheck.db"
LOGS_DIRECTORY = "logs"
MAX_ARCHIVE_MEMBER_BYTES = 1_073_741_824
MAX_ARCHIVE_TOTAL_BYTES = 2_147_483_648
MAX_MANIFEST_BYTES = 1_048_576


class ProfileBackupError(ValueError):
    """Raised when a profile or backup cannot be handled safely."""


@dataclass(frozen=True, slots=True)
class BackupResult:
    archive: Path
    file_count: int
    classification: str
    migration_revision: str | None


@dataclass(frozen=True, slots=True)
class BackupVerification:
    archive: Path
    file_count: int
    classification: str
    migration_revision: str | None


@dataclass(frozen=True, slots=True)
class RestoreResult:
    target: Path
    file_count: int
    classification: str
    replaced: bool


@dataclass(frozen=True, slots=True)
class _ArchivePlan:
    manifest: dict[str, Any]
    files: tuple[dict[str, Any], ...]
    archive: Path


def create_backup(profile: Path, archive: Path) -> BackupResult:
    """Create an atomic, SQLite-consistent ZIP backup of *profile*."""

    profile_root = _safe_profile_root(profile, must_exist=True)
    archive_path = _safe_output_path(archive)
    if _is_within(archive_path.parent, profile_root):
        raise ProfileBackupError("backup archive must be outside the profile")
    if archive_path.exists():
        raise ProfileBackupError("backup archive already exists")

    database = profile_root / DATABASE_NAME
    _require_regular_file(database, "profile database")
    files = tuple(_profile_files(profile_root))

    with tempfile.TemporaryDirectory(prefix=".healthcheck-backup-") as temporary:
        stage = Path(temporary) / "profile"
        stage.mkdir()
        staged_database = stage / DATABASE_NAME
        journal_mode = _online_backup(database, staged_database)

        staged_files: list[dict[str, Any]] = []
        for source in files:
            relative = source.relative_to(profile_root).as_posix()
            destination = stage / Path(*PurePosixPath(relative).parts)
            if relative == DATABASE_NAME:
                candidate = staged_database
            else:
                candidate = destination
                candidate.parent.mkdir(parents=True, exist_ok=True)
                _copy_stable_file(source, candidate)
            staged_files.append(
                {
                    "path": relative,
                    "size": candidate.stat().st_size,
                    "sha256": _sha256(candidate),
                    "kind": "database" if relative == DATABASE_NAME else "profile_file",
                }
            )

        if {path.relative_to(profile_root) for path in _profile_files(profile_root)} != {
            path.relative_to(profile_root) for path in files
        }:
            raise ProfileBackupError("profile file list changed while backup was being created")

        migration_revision = _migration_revision(staged_database)
        manifest = _build_manifest(
            staged_files,
            classification=_classify_profile(profile_root),
            migration_revision=migration_revision,
            journal_mode=journal_mode,
        )
        _write_archive(archive_path, stage, manifest, staged_files)

    verification = verify_backup(archive_path)
    return BackupResult(
        archive=verification.archive,
        file_count=verification.file_count,
        classification=verification.classification,
        migration_revision=verification.migration_revision,
    )


def verify_backup(archive: Path) -> BackupVerification:
    """Validate the complete archive, including every checksum and the DB."""

    plan = _validate_archive(archive)
    return BackupVerification(
        archive=plan.archive,
        file_count=len(plan.files),
        classification=str(plan.manifest["profile"]["classification"]),
        migration_revision=plan.manifest["schema"].get("migration_revision"),
    )


def restore_profile(archive: Path, target: Path, *, replace: bool = False) -> RestoreResult:
    """Restore a verified archive without mutating the target during preflight."""

    plan = _validate_archive(archive)
    target_root = _safe_target_root(target)
    target_exists = target_root.exists()
    if target_exists and target_root.is_dir() and any(target_root.iterdir()):
        if not replace:
            raise ProfileBackupError(
                "restore target is non-empty; choose a new/empty target or use --replace"
            )

    parent = _safe_existing_directory(target_root.parent, "restore target parent")
    if _is_within(target_root, _repository_root().resolve()):
        raise ProfileBackupError("restore target must be outside the checkout")
    if target_exists:
        _validate_directory_tree(target_root)
        _validate_restore_conflicts(target_root, plan.files)

    with tempfile.TemporaryDirectory(prefix=".healthcheck-restore-", dir=str(parent)) as temporary:
        staged_root = Path(temporary) / "profile"
        _extract_archive(plan, staged_root)
        _validate_directory_tree(staged_root)
        if target_exists and replace:
            _replace_target(target_root, staged_root, parent)
        elif target_exists:
            _copy_into_existing_target(staged_root, target_root, plan.files)
        else:
            os.replace(staged_root, target_root)

    return RestoreResult(
        target=target_root,
        file_count=len(plan.files),
        classification=str(plan.manifest["profile"]["classification"]),
        replaced=bool(replace and target_exists),
    )


# Explicit aliases keep the service vocabulary convenient for callers.
backup_profile = create_backup
restore_backup = restore_profile


def _safe_profile_root(value: Path, *, must_exist: bool) -> Path:
    root = _absolute_path(value)
    _reject_symlink_ancestors(root)
    if root.parent == root:
        raise ProfileBackupError("profile must not be a filesystem root")
    if _overlaps_checkout(root):
        raise ProfileBackupError("profile must be outside the checkout")
    if must_exist:
        _safe_existing_directory(root, "profile")
    return root


def _safe_target_root(value: Path) -> Path:
    root = _absolute_path(value)
    _reject_symlink_ancestors(root)
    if root.exists() and _is_link_or_reparse(root):
        raise ProfileBackupError("restore target must not be a symlink")
    if root.exists() and not root.is_dir():
        raise ProfileBackupError("restore target must be a real directory")
    if root.parent == root:
        raise ProfileBackupError("restore target must not be a filesystem root")
    if _overlaps_checkout(root):
        raise ProfileBackupError("restore target must be outside the checkout")
    return root


def _safe_output_path(value: Path) -> Path:
    output = _absolute_path(value)
    _reject_symlink_ancestors(output)
    _safe_existing_directory(output.parent, "backup destination parent")
    if output.exists() and (_is_link_or_reparse(output) or not output.is_file()):
        raise ProfileBackupError("backup destination is not a regular file")
    if _is_within(output, _repository_root().resolve()):
        raise ProfileBackupError("backup archive must be outside the checkout")
    return output


def _absolute_path(value: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(Path(value).expanduser())))


def _reject_symlink_ancestors(path: Path) -> None:
    current = path
    while True:
        if current.exists() and _is_link_or_reparse(current):
            raise ProfileBackupError("path contains a symlink")
        parent = current.parent
        if parent == current:
            return
        current = parent


def _safe_existing_directory(path: Path, label: str) -> Path:
    if not path.exists() or _is_link_or_reparse(path) or not path.is_dir():
        raise ProfileBackupError(f"{label} must be an existing real directory")
    return path


def _require_regular_file(path: Path, label: str) -> None:
    if _is_link_or_reparse(path) or not path.is_file():
        raise ProfileBackupError(f"{label} must be a regular file")


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _overlaps_checkout(path: Path) -> bool:
    checkout = _repository_root().resolve()
    return _is_within(path, checkout) or _is_within(checkout, path)


def _is_link_or_reparse(path: Path) -> bool:
    """Treat Windows junctions/reparse points like symlinks for profile IO."""

    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    try:
        attributes = os.lstat(path).st_file_attributes
    except (AttributeError, FileNotFoundError, OSError):
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _profile_files(root: Path) -> Iterator[Path]:
    discovered: list[Path] = []
    _walk_directory(root, root, discovered, include_logs=False)
    database = root / DATABASE_NAME
    if database not in discovered:
        raise ProfileBackupError("profile database is missing")
    for path in sorted(discovered, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if relative in {f"{DATABASE_NAME}-wal", f"{DATABASE_NAME}-shm"}:
            continue
        yield path


def _walk_directory(root: Path, current: Path, files: list[Path], *, include_logs: bool) -> None:
    try:
        entries = sorted(current.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise ProfileBackupError("profile tree could not be read") from exc
    for entry in entries:
        if _is_link_or_reparse(entry):
            raise ProfileBackupError("profile tree contains a symlink")
        relative = entry.relative_to(root).as_posix()
        if entry.is_dir():
            _walk_directory(
                root,
                entry,
                files,
                include_logs=include_logs or relative == LOGS_DIRECTORY,
            )
        elif entry.is_file():
            if include_logs or relative.startswith(f"{LOGS_DIRECTORY}/"):
                continue
            files.append(entry)
        else:
            raise ProfileBackupError("profile tree contains a special file")


def _copy_stable_file(source: Path, destination: Path) -> None:
    before = source.stat()
    with source.open("rb") as source_handle, destination.open("wb") as destination_handle:
        shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
        destination_handle.flush()
        os.fsync(destination_handle.fileno())
    after = source.stat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ino != after.st_ino
    ):
        raise ProfileBackupError("profile changed while backup was being created")


def _online_backup(source_path: Path, destination_path: Path) -> str:
    try:
        source = sqlite3.connect(str(source_path), timeout=5, isolation_level=None)
        source.execute("PRAGMA busy_timeout=5000")
        journal_mode = str(source.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if journal_mode != "wal":
            source.close()
            raise ProfileBackupError("profile database is not using SQLite WAL mode")
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            source.close()
            raise ProfileBackupError("profile database failed SQLite integrity check")
        destination = sqlite3.connect(str(destination_path), timeout=5)
        try:
            source.backup(destination, pages=100, sleep=0.05)
            destination.execute("PRAGMA journal_mode=WAL")
            destination.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ProfileBackupError("backup database failed SQLite integrity check")
        finally:
            destination.close()
            source.close()
    except sqlite3.Error as exc:
        raise ProfileBackupError("SQLite backup could not be completed") from exc
    return journal_mode


def _migration_revision(database: Path) -> str | None:
    try:
        connection = sqlite3.connect(str(database), uri=False)
        try:
            row = connection.execute(
                "SELECT version_num FROM alembic_version LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        if "no such table: alembic_version" not in str(exc).lower():
            raise ProfileBackupError("database migration identity could not be read") from exc
        return None
    return None if row is None else str(row[0])


def _classify_profile(root: Path) -> str:
    marker = root / ".healthcheck-synthetic-demo.json"
    if _is_link_or_reparse(marker):
        raise ProfileBackupError("synthetic profile marker must be a regular file")
    if not marker.exists():
        return "normal"
    if not marker.is_file():
        raise ProfileBackupError("synthetic profile marker must be a regular file")
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ProfileBackupError("synthetic profile marker is invalid") from exc
    if isinstance(value, dict) and value.get("label") == "synthetic demo data":
        return "synthetic"
    return "unknown"


def _build_manifest(
    files: list[dict[str, Any]],
    *,
    classification: str,
    migration_revision: str | None,
    journal_mode: str,
) -> dict[str, Any]:
    try:
        app_version = importlib.metadata.version("health-check")
    except importlib.metadata.PackageNotFoundError:
        app_version = "0.1.0"
    return {
        "format_version": FORMAT_VERSION,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        ),
        "app": {"name": "health-check", "version": app_version},
        "schema": {"migration_revision": migration_revision},
        "profile": {"classification": classification},
        "database": {
            "path": DATABASE_NAME,
            "journal_mode": journal_mode,
            "backup_method": "sqlite_online_backup",
        },
        "files": files,
    }


def _write_archive(
    archive: Path, stage: Path, manifest: dict[str, Any], files: list[dict[str, Any]]
) -> None:
    temporary = archive.with_name(f".{archive.name}.{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            strict_timestamps=False,
        ) as handle:
            handle.writestr(
                MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            )
            for item in files:
                source = stage / Path(*PurePosixPath(item["path"]).parts)
                handle.write(source, f"{PROFILE_PREFIX}{item['path']}")
        os.replace(temporary, archive)
    except (OSError, zipfile.BadZipFile) as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ProfileBackupError("backup archive could not be written") from exc


def _validate_archive(archive: Path) -> _ArchivePlan:
    archive_path = _absolute_path(archive)
    _reject_symlink_ancestors(archive_path)
    _require_regular_file(archive_path, "backup archive")
    try:
        handle = zipfile.ZipFile(archive_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ProfileBackupError("backup archive is not a valid ZIP") from exc
    with handle:
        infos = handle.infolist()
        _validate_zip_members(infos)
        if handle.getinfo(MANIFEST_NAME).file_size > MAX_MANIFEST_BYTES:
            raise ProfileBackupError("backup manifest is too large")
        try:
            raw_manifest = handle.read(MANIFEST_NAME)
            manifest = _strict_json(raw_manifest)
        except (KeyError, OSError, UnicodeError, ValueError, zipfile.BadZipFile) as exc:
            raise ProfileBackupError("backup manifest is invalid") from exc
        files = _validate_manifest(manifest, infos)
        expected_names = {MANIFEST_NAME} | {
            f"{PROFILE_PREFIX}{item['path']}" for item in files
        }
        actual_names = {info.filename for info in infos}
        if actual_names != expected_names:
            raise ProfileBackupError("backup archive file list does not match its manifest")
        total = 0
        for item in files:
            info = handle.getinfo(f"{PROFILE_PREFIX}{item['path']}")
            if info.file_size != item["size"]:
                raise ProfileBackupError("backup checksum/size validation failed")
            total += info.file_size
            if total > MAX_ARCHIVE_TOTAL_BYTES:
                raise ProfileBackupError("backup archive is too large")
            digest = hashlib.sha256()
            try:
                with handle.open(info, "r") as source:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
            except (OSError, zipfile.BadZipFile) as exc:
                raise ProfileBackupError("backup archive contains an unreadable file") from exc
            if digest.hexdigest() != item["sha256"]:
                raise ProfileBackupError("backup checksum validation failed")

        database_item = next((item for item in files if item["kind"] == "database"), None)
        if database_item is None or database_item["path"] != DATABASE_NAME:
            raise ProfileBackupError("backup database entry is missing")
        _validate_archive_database(handle, database_item, manifest)
    return _ArchivePlan(manifest=manifest, files=tuple(files), archive=archive_path)


def _validate_zip_members(infos: list[zipfile.ZipInfo]) -> None:
    names: set[str] = set()
    for info in infos:
        if info.filename in names:
            raise ProfileBackupError("backup archive contains duplicate entries")
        names.add(info.filename)
        if info.filename == MANIFEST_NAME:
            pass
        elif info.filename.startswith(PROFILE_PREFIX):
            _validate_relative_path(info.filename[len(PROFILE_PREFIX) :])
        else:
            raise ProfileBackupError("backup archive contains an unexpected path")
        if info.is_dir() or info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
            raise ProfileBackupError("backup archive contains an oversized or directory entry")
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
            raise ProfileBackupError("backup archive contains a special file")
    if MANIFEST_NAME not in names:
        raise ProfileBackupError("backup manifest is missing")


def _validate_relative_path(value: str) -> None:
    if not value or "\\" in value or "\x00" in value:
        raise ProfileBackupError("backup contains an unsafe path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ProfileBackupError("backup contains a traversal path")
    if any(":" in part for part in path.parts):
        raise ProfileBackupError("backup contains an unsafe path")


def _strict_json(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )
    if not isinstance(value, dict):
        raise ValueError("manifest must be an object")
    return value


def _validate_manifest(
    manifest: dict[str, Any], infos: list[zipfile.ZipInfo]
) -> list[dict[str, Any]]:
    if set(manifest) != {
        "format_version",
        "created_at",
        "app",
        "schema",
        "profile",
        "database",
        "files",
    }:
        raise ProfileBackupError("backup manifest structure is invalid")
    if manifest.get("format_version") != FORMAT_VERSION:
        raise ProfileBackupError("unsupported backup format")
    if not isinstance(manifest.get("created_at"), str):
        raise ProfileBackupError("backup creation time is invalid")
    app = manifest.get("app")
    schema = manifest.get("schema")
    profile = manifest.get("profile")
    database = manifest.get("database")
    files = manifest.get("files")
    if not all(isinstance(value, dict) for value in (app, schema, profile, database)):
        raise ProfileBackupError("backup manifest metadata is invalid")
    if set(app) != {"name", "version"}:
        raise ProfileBackupError("backup application identity is invalid")
    if set(schema) != {"migration_revision"}:
        raise ProfileBackupError("backup schema identity is invalid")
    if set(profile) != {"classification"}:
        raise ProfileBackupError("backup profile classification is invalid")
    if set(database) != {"path", "journal_mode", "backup_method"}:
        raise ProfileBackupError("backup database identity is invalid")
    if app.get("name") != "health-check" or not isinstance(app.get("version"), str):
        raise ProfileBackupError("backup application identity is invalid")
    if not isinstance(schema.get("migration_revision"), (str, type(None))):
        raise ProfileBackupError("backup schema identity is invalid")
    if profile.get("classification") not in {"synthetic", "normal", "unknown"}:
        raise ProfileBackupError("backup profile classification is invalid")
    if database.get("path") != DATABASE_NAME:
        raise ProfileBackupError("backup database identity is invalid")
    if (
        database.get("journal_mode") != "wal"
        or database.get("backup_method") != "sqlite_online_backup"
    ):
        raise ProfileBackupError("backup database consistency metadata is invalid")
    if not isinstance(files, list) or not files:
        raise ProfileBackupError("backup file manifest is empty or invalid")

    known_names = {info.filename for info in infos}
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise ProfileBackupError("backup file manifest entry is invalid")
        if set(item) != {"path", "size", "sha256", "kind"}:
            raise ProfileBackupError("backup file manifest entry is invalid")
        path = item.get("path")
        size = item.get("size")
        checksum = item.get("sha256")
        kind = item.get("kind")
        if (
            not isinstance(path, str)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(checksum, str)
            or len(checksum) != 64
            or any(character not in "0123456789abcdef" for character in checksum)
            or kind not in {"database", "profile_file"}
        ):
            raise ProfileBackupError("backup file manifest entry is invalid")
        _validate_relative_path(path)
        if path in seen or f"{PROFILE_PREFIX}{path}" not in known_names:
            raise ProfileBackupError("backup file manifest has duplicate or missing entries")
        if path == DATABASE_NAME and kind != "database":
            raise ProfileBackupError("backup database manifest entry is invalid")
        if path != DATABASE_NAME and kind == "database":
            raise ProfileBackupError("backup database manifest entry is invalid")
        seen.add(path)
        result.append(item)
    return result


def _validate_archive_database(
    handle: zipfile.ZipFile, item: dict[str, Any], manifest: dict[str, Any]
) -> None:
    with tempfile.TemporaryDirectory(prefix=".healthcheck-verify-") as temporary:
        database = Path(temporary) / DATABASE_NAME
        with handle.open(f"{PROFILE_PREFIX}{DATABASE_NAME}", "r") as source, database.open(
            "wb"
        ) as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
        try:
            connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
            try:
                if str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower() != "wal":
                    raise ProfileBackupError("backup database is not in WAL mode")
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ProfileBackupError("backup database failed SQLite integrity check")
                revision = _migration_revision(database)
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise ProfileBackupError("backup database is unreadable") from exc
        if revision != manifest["schema"].get("migration_revision"):
            raise ProfileBackupError("backup database migration identity does not match manifest")


def _extract_archive(plan: _ArchivePlan, destination: Path) -> None:
    destination.mkdir(parents=True)
    with zipfile.ZipFile(plan.archive, "r") as handle:
        for item in plan.files:
            relative = PurePosixPath(item["path"])
            target = destination / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with handle.open(f"{PROFILE_PREFIX}{item['path']}", "r") as source, target.open(
                "wb"
            ) as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            if target.stat().st_size != item["size"] or _sha256(target) != item["sha256"]:
                raise ProfileBackupError("backup changed while restore was being prepared")


def _validate_directory_tree(root: Path) -> None:
    if _is_link_or_reparse(root) or not root.is_dir():
        raise ProfileBackupError("profile tree must contain only real directories and files")
    for entry in root.iterdir():
        if _is_link_or_reparse(entry):
            raise ProfileBackupError("profile tree contains a symlink")
        if entry.is_dir():
            _validate_directory_tree(entry)
        elif not entry.is_file():
            raise ProfileBackupError("profile tree contains a special file")


def _validate_restore_conflicts(target: Path, files: tuple[dict[str, Any], ...]) -> None:
    for item in files:
        destination = target / Path(*PurePosixPath(item["path"]).parts)
        current = destination
        while current != target:
            if current.exists() and (_is_link_or_reparse(current) or not current.is_dir()):
                raise ProfileBackupError("restore conflicts with an unsafe target entry")
            current = current.parent
        if destination.exists() and (
            _is_link_or_reparse(destination) or not destination.is_file()
        ):
            raise ProfileBackupError("restore conflicts with an unsafe target entry")


def _copy_into_existing_target(
    staged_root: Path, target: Path, files: tuple[dict[str, Any], ...]
) -> None:
    for item in files:
        source = staged_root / Path(*PurePosixPath(item["path"]).parts)
        destination = target / Path(*PurePosixPath(item["path"]).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)


def _replace_target(target: Path, staged_root: Path, parent: Path) -> None:
    quarantine = parent / f".{target.name}.healthcheck-old-{uuid.uuid4().hex}"
    try:
        os.replace(target, quarantine)
        try:
            os.replace(staged_root, target)
        except OSError:
            os.replace(quarantine, target)
            raise
        _validate_directory_tree(quarantine)
        shutil.rmtree(quarantine)
    except OSError as exc:
        raise ProfileBackupError("destructive profile replacement could not be completed") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
