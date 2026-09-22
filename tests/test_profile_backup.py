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
        assert (
            restored_db.execute(
                "SELECT name FROM sqlite_master WHERE name = 'existing_profile_marker'"
            ).fetchone()
            is None
        )
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


def test_archive_size_caps_cover_observed_multi_gib_owner_db() -> None:
    from healthcheck.profile_backup import MAX_ARCHIVE_MEMBER_BYTES, MAX_ARCHIVE_TOTAL_BYTES

    # Current Stable archive: 5.341 GiB DB, 5.598 GiB total expanded.
    observed_database_bytes = 5_734_481_920
    observed_total_bytes = 6_010_738_699
    assert MAX_ARCHIVE_MEMBER_BYTES == 6 * 1024 * 1024 * 1024
    assert MAX_ARCHIVE_TOTAL_BYTES == 8 * 1024 * 1024 * 1024
    assert MAX_ARCHIVE_MEMBER_BYTES > observed_database_bytes
    assert MAX_ARCHIVE_TOTAL_BYTES > observed_total_bytes
    assert MAX_ARCHIVE_TOTAL_BYTES > MAX_ARCHIVE_MEMBER_BYTES


def test_member_over_hard_max_fails_closed_against_production_cap() -> None:
    from healthcheck.profile_backup import MAX_ARCHIVE_MEMBER_BYTES, _validate_zip_members

    manifest = zipfile.ZipInfo("manifest.json")
    manifest.file_size = 12
    manifest.external_attr = 0o100644 << 16

    oversized = zipfile.ZipInfo("profile/healthcheck.db")
    oversized.file_size = MAX_ARCHIVE_MEMBER_BYTES + 1
    oversized.external_attr = 0o100644 << 16
    with pytest.raises(ProfileBackupError, match="oversized"):
        _validate_zip_members([manifest, oversized])

    accepted = zipfile.ZipInfo("profile/healthcheck.db")
    accepted.file_size = MAX_ARCHIVE_MEMBER_BYTES
    accepted.external_attr = 0o100644 << 16
    _validate_zip_members([manifest, accepted])


def test_total_over_hard_max_fails_closed_against_production_cap() -> None:
    from healthcheck.profile_backup import MAX_ARCHIVE_TOTAL_BYTES, _validate_total_expanded_size

    _validate_total_expanded_size(MAX_ARCHIVE_TOTAL_BYTES)
    with pytest.raises(ProfileBackupError, match="too large"):
        _validate_total_expanded_size(MAX_ARCHIVE_TOTAL_BYTES + 1)


def test_total_expanded_size_cap_enforced_during_verify(
    external_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import healthcheck.profile_backup as profile_backup

    source = _synthetic_profile(external_tmp_path)
    archive = external_tmp_path / "profile.zip"
    create_backup(source, archive)

    monkeypatch.setattr(profile_backup, "MAX_ARCHIVE_TOTAL_BYTES", 1)
    with pytest.raises(ProfileBackupError, match="too large"):
        verify_backup(archive)


def test_oversized_member_cap_enforced_during_verify(
    external_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import healthcheck.profile_backup as profile_backup

    source = _synthetic_profile(external_tmp_path)
    archive = external_tmp_path / "profile.zip"
    create_backup(source, archive)

    monkeypatch.setattr(profile_backup, "MAX_ARCHIVE_MEMBER_BYTES", 1)
    with pytest.raises(ProfileBackupError, match="oversized"):
        verify_backup(archive)


def test_zip64_round_trip_when_zip64_limit_is_forced(
    external_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Force ZIP64 for modest payloads so CI proves large-file ZIP support without GiB fixtures.
    monkeypatch.setattr(zipfile, "ZIP64_LIMIT", 64)

    source = _synthetic_profile(external_tmp_path)
    archive = external_tmp_path / "zip64-profile.zip"
    created = create_backup(source, archive)
    verified = verify_backup(archive)
    target = external_tmp_path / "zip64-restored"
    restored = restore_profile(archive, target)

    assert created.file_count == verified.file_count == restored.file_count
    assert (target / "healthcheck.db").is_file()
    with zipfile.ZipFile(archive) as handle:
        assert any(info.file_size > 64 for info in handle.infolist())


def test_truncated_archive_fails_verify_and_cannot_replace_target(
    external_tmp_path: Path,
) -> None:
    source = _synthetic_profile(external_tmp_path)
    archive = external_tmp_path / "profile.zip"
    create_backup(source, archive)

    truncated = external_tmp_path / "truncated.zip"
    payload = archive.read_bytes()
    truncated.write_bytes(payload[: max(64, len(payload) // 3)])

    target = external_tmp_path / "protected-target"
    target.mkdir()
    sentinel = target / "keep-me.txt"
    sentinel.write_text("must remain", encoding="utf-8")

    with pytest.raises(ProfileBackupError):
        verify_backup(truncated)
    with pytest.raises(ProfileBackupError):
        restore_profile(truncated, target, replace=True)
    assert sentinel.read_text(encoding="utf-8") == "must remain"


def test_large_sparse_profile_above_one_gib_backup_verify_restore(
    external_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove DB >1 GiB can backup/verify/restore under the raised caps.

    Uses SQLite zeroblob growth (highly compressible / sparse-friendly) and a
    sleep-free online-backup wrapper so CI does not spend minutes sleeping.
    """
    import healthcheck.profile_backup as profile_backup

    original_online_backup = profile_backup._online_backup

    def _fast_online_backup(source_path: Path, destination_path: Path) -> str:
        try:
            source = sqlite3.connect(str(source_path), timeout=5, isolation_level=None)
            source.execute("PRAGMA busy_timeout=5000")
            journal_mode = str(source.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            if journal_mode != "wal":
                source.close()
                raise profile_backup.ProfileBackupError(
                    "profile database is not using SQLite WAL mode"
                )
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                source.close()
                raise profile_backup.ProfileBackupError(
                    "profile database failed SQLite integrity check"
                )
            destination = sqlite3.connect(str(destination_path), timeout=5)
            try:
                source.backup(destination, pages=0, sleep=0)
                destination.execute("PRAGMA journal_mode=WAL")
                destination.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise profile_backup.ProfileBackupError(
                        "backup database failed SQLite integrity check"
                    )
            finally:
                destination.close()
                source.close()
        except sqlite3.Error as exc:
            raise profile_backup.ProfileBackupError("SQLite backup could not be completed") from exc
        return journal_mode

    # Keep production pacing unchanged; only accelerate this large synthetic proof.
    assert original_online_backup is profile_backup._online_backup
    monkeypatch.setattr(profile_backup, "_online_backup", _fast_online_backup)

    profile = external_tmp_path / "large-source"
    paths = prepare_runtime(Settings(data_dir=profile))
    marker_value = "large-profile-marker-v141"
    # SQLite default max length is 1e9; use several zeroblobs to exceed 1 GiB total.
    chunk_bytes = 400_000_000
    chunk_count = 3  # 1.2 GiB payload + schema overhead
    connection = sqlite3.connect(paths.database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
            "CREATE TABLE large_profile_marker ("
            "id INTEGER PRIMARY KEY, value TEXT NOT NULL, payload BLOB NOT NULL)"
        )
        for index in range(chunk_count):
            connection.execute(
                "INSERT INTO large_profile_marker(value, payload) VALUES (?, zeroblob(?))",
                (f"{marker_value}-{index}", chunk_bytes),
            )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()

    db_size = Path(paths.database).stat().st_size
    assert db_size > 1_073_741_824
    assert db_size < profile_backup.MAX_ARCHIVE_MEMBER_BYTES

    archive = external_tmp_path / "large-profile.zip"
    created = create_backup(profile, archive)
    verified = verify_backup(archive)
    target = external_tmp_path / "large-restored"
    restored = restore_profile(archive, target)

    assert created.classification == verified.classification == restored.classification
    assert (target / "healthcheck.db").stat().st_size > 1_073_741_824
    restored_db = sqlite3.connect(target / "healthcheck.db")
    try:
        rows = restored_db.execute(
            "SELECT value, length(payload) FROM large_profile_marker ORDER BY id"
        ).fetchall()
        assert rows == [(f"{marker_value}-{index}", chunk_bytes) for index in range(chunk_count)]
        assert restored_db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        restored_db.close()
