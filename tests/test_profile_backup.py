from __future__ import annotations

import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import pytest

from healthcheck.cli import main
from healthcheck.config import Settings
from healthcheck.demo import seed_demo
from healthcheck.profile_backup import (
    ProfileBackupError,
    create_backup,
    restore_profile,
    verify_backup,
)
from healthcheck.runtime import prepare_runtime


@pytest.fixture
def external_tmp_path():
    with tempfile.TemporaryDirectory(prefix="healthcheck-profile-") as root:
        yield Path(root)


def _synthetic_profile(tmp_path: Path) -> Path:
    profile = tmp_path / "source"
    seed_demo(Settings(data_dir=profile))
    (profile / "artifacts" / "provenance.txt").write_text("synthetic provenance", encoding="utf-8")
    (profile / "logs").mkdir(exist_ok=True)
    (profile / "logs" / "transient.log").write_text("not archived", encoding="utf-8")
    return profile


def test_backup_verify_restore_round_trip_and_unknown_file_is_preserved_on_refusal(
    external_tmp_path: Path,
) -> None:
    tmp_path = external_tmp_path
    source = _synthetic_profile(tmp_path)
    archive = tmp_path / "backups" / "profile.zip"
    archive.parent.mkdir()

    created = create_backup(source, archive)
    verified = verify_backup(archive)

    target = tmp_path / "restored"
    target.mkdir()
    unknown = target / "owner-note.txt"
    unknown.write_text("keep this", encoding="utf-8")
    with pytest.raises(ProfileBackupError, match="non-empty"):
        restore_profile(archive, target)

    empty_target = tmp_path / "empty-restored"
    empty_target.mkdir()
    restored = restore_profile(archive, empty_target)

    assert created.classification == verified.classification == "synthetic"
    assert restored.file_count == created.file_count
    assert (empty_target / "healthcheck.db").is_file()
    assert (empty_target / "artifacts" / "provenance.txt").read_text(encoding="utf-8") == (
        "synthetic provenance"
    )
    assert not (empty_target / "logs").exists()


def test_wal_backup_contains_committed_uncheckpointed_data(external_tmp_path: Path) -> None:
    tmp_path = external_tmp_path
    source = prepare_runtime(Settings(data_dir=tmp_path / "wal-source"))
    connection = sqlite3.connect(source.database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE synthetic_wal_marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO synthetic_wal_marker VALUES ('synthetic-only')")
        connection.commit()
        assert Path(f"{source.database}-wal").is_file()
    finally:
        connection.close()

    archive = tmp_path / "wal.zip"
    create_backup(source.root, archive)
    with zipfile.ZipFile(archive) as handle:
        assert "profile/healthcheck.db" in handle.namelist()
        assert "profile/healthcheck.db-wal" not in handle.namelist()
    target = tmp_path / "wal-restored"
    restore_profile(archive, target)
    restored = sqlite3.connect(target / "healthcheck.db")
    try:
        assert restored.execute("SELECT value FROM synthetic_wal_marker").fetchone() == (
            "synthetic-only",
        )
    finally:
        restored.close()


def test_checksum_corruption_and_traversal_are_rejected_before_replace(
    external_tmp_path: Path,
) -> None:
    tmp_path = external_tmp_path
    source = _synthetic_profile(tmp_path)
    archive = tmp_path / "profile.zip"
    create_backup(source, archive)
    target = tmp_path / "private-looking"
    target.mkdir()
    sentinel = target / "private-looking.txt"
    sentinel.write_text("must remain", encoding="utf-8")

    corrupt = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(archive) as original, zipfile.ZipFile(corrupt, "w") as changed:
        for info in original.infolist():
            payload = original.read(info.filename)
            if info.filename == "profile/artifacts/provenance.txt":
                payload = b"tampered"
            changed.writestr(info, payload)
    with pytest.raises(ProfileBackupError, match="checksum"):
        restore_profile(corrupt, target, replace=True)
    assert sentinel.read_text(encoding="utf-8") == "must remain"

    traversal = tmp_path / "traversal.zip"
    manifest = {
        "format_version": 1,
        "created_at": "2026-09-04T00:00:00Z",
        "app": {"name": "health-check", "version": "0.1.0"},
        "schema": {"migration_revision": None},
        "profile": {"classification": "unknown"},
        "database": {
            "path": "healthcheck.db",
            "journal_mode": "wal",
            "backup_method": "sqlite_online_backup",
        },
        "files": [],
    }
    with zipfile.ZipFile(traversal, "w") as handle:
        handle.writestr("manifest.json", json.dumps(manifest))
        handle.writestr("profile/../escape.txt", b"unsafe")
    with pytest.raises(ProfileBackupError):
        verify_backup(traversal)


def test_replace_is_explicit_and_checkout_is_refused(external_tmp_path: Path) -> None:
    tmp_path = external_tmp_path
    source = _synthetic_profile(tmp_path)
    archive = tmp_path / "profile.zip"
    create_backup(source, archive)
    target = tmp_path / "target"
    target.mkdir()
    (target / "unknown.txt").write_text("old", encoding="utf-8")
    with pytest.raises(ProfileBackupError, match="non-empty"):
        restore_profile(archive, target)

    result = restore_profile(archive, target, replace=True)
    assert result.replaced is True
    assert not (target / "unknown.txt").exists()
    assert (target / "healthcheck.db").is_file()

    with pytest.raises(ProfileBackupError, match="outside the checkout"):
        restore_profile(archive, Path(__file__).resolve().parents[1])


def test_replace_over_existing_healthcheck_profile_with_database_and_artifacts(
    external_tmp_path: Path,
) -> None:
    source = _synthetic_profile(external_tmp_path)
    archive = external_tmp_path / "profile.zip"
    create_backup(source, archive)

    target = external_tmp_path / "existing-profile"
    paths = prepare_runtime(Settings(data_dir=target))
    connection = sqlite3.connect(paths.database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE existing_profile_marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO existing_profile_marker VALUES ('old')")
        connection.commit()
    finally:
        connection.close()
    old_artifact = target / "artifacts" / "photos" / "old.png"
    old_artifact.write_bytes(b"old artifact")

    result = restore_profile(archive, target, replace=True)

    assert result.replaced is True
    assert (target / "healthcheck.db").is_file()
    assert (target / "artifacts" / "provenance.txt").read_text(encoding="utf-8") == (
        "synthetic provenance"
    )
    assert not old_artifact.exists()
    restored_db = sqlite3.connect(target / "healthcheck.db")
    try:
        assert restored_db.execute(
            "SELECT name FROM sqlite_master WHERE name = 'existing_profile_marker'"
        ).fetchone() is None
    finally:
        restored_db.close()


def test_archive_symlink_entry_and_cli_output_do_not_expose_content(
    external_tmp_path: Path, capsys
) -> None:
    tmp_path = external_tmp_path
    source = _synthetic_profile(tmp_path)
    archive = tmp_path / "profile.zip"
    create_backup(source, archive)
    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as handle:
        info = zipfile.ZipInfo("profile/link")
        info.external_attr = (0o120777 << 16) | 0xA0000000
        handle.writestr("manifest.json", b"{}")
        handle.writestr(info, b"secret health 80.1")
    with pytest.raises(ProfileBackupError, match="special"):
        verify_backup(unsafe)

    secret = "secret health 80.1"
    assert main(["verify-backup", "--backup", str(archive)]) == 0
    assert secret not in capsys.readouterr().out
