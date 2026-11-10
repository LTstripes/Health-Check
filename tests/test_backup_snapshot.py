from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

from healthcheck import profile_backup as native
from healthcheck.cli import main


@pytest.fixture
def prepared(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "synthetic"
    assert main(["seed-demo", "--data-dir", str(source)]) == 0
    projection = tmp_path / "projection"
    projection.mkdir()
    native.snapshot_database(source / native.DATABASE_NAME, projection / native.DATABASE_NAME)
    # Data-only selection happens before packaging: original config/auth files
    # never enter the projection. Keep the wrapper's empty config allowlist.
    (source / "provider.token").write_text("synthetic-secret")
    (projection / "config.toml").write_text("# Empty data-only config\n")
    (projection / "artifacts").mkdir()
    (projection / "artifacts" / "synthetic.json").write_text('{"weight": 75}')
    (projection / "logs").mkdir()
    (projection / "logs" / "secret.log").write_text("synthetic-secret-in-log")
    return source, projection


def test_snapshot_path_round_trip_matches_old_file_set_and_database(
    prepared, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    _, projection = prepared
    old = native.create_backup(projection, tmp_path / "old.zip", scratch=tmp_path)
    calls = []
    online_backup = native._online_backup

    def counted(*args, **kwargs):
        calls.append(args)
        return online_backup(*args, **kwargs)

    monkeypatch.setattr(native, "_online_backup", counted)
    # Start the complete new workflow from the synthetic live source, like the
    # Owner wrapper: one online snapshot, then package its closed DB directly.
    source, _ = prepared
    fresh = tmp_path / "fresh-projection"
    shutil.copytree(projection, fresh)
    snapshot = fresh / native.DATABASE_NAME
    snapshot.unlink()
    clock = native.BackupTimings()
    native.snapshot_database(source / native.DATABASE_NAME, snapshot, timings=clock)
    assert len(calls) == 1
    with caplog.at_level(logging.INFO, logger=native.__name__):
        new = native.create_backup(
            fresh, tmp_path / "new.zip", scratch=tmp_path,
            source_snapshot=snapshot, timings=clock,
        )
    assert len(calls) == 1, "packaging took a second online snapshot"
    for result in (old, new):
        verified = native.verify_backup(result.archive, scratch=tmp_path)
        assert verified.file_count == result.file_count
        native.restore_profile(result.archive, tmp_path / result.archive.stem, scratch=tmp_path)
    with zipfile.ZipFile(old.archive) as a, zipfile.ZipFile(new.archive) as b:
        before = json.loads(a.read(native.MANIFEST_NAME))
        after = json.loads(b.read(native.MANIFEST_NAME))
        assert before["files"] == after["files"]
        assert a.namelist() == b.namelist()
        assert "profile/provider.token" not in b.namelist()
        assert not any(name.startswith("profile/logs/") for name in b.namelist())
    assert native._sha256(tmp_path / "old" / native.DATABASE_NAME) == native._sha256(
        tmp_path / "new" / native.DATABASE_NAME
    )
    with closing(sqlite3.connect(tmp_path / "new" / native.DATABASE_NAME)) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    receipt = json.loads(new.receipt.read_text())
    assert receipt["status"] == "complete"
    assert receipt["sha256"] == native._sha256(new.archive)
    assert receipt["timings_seconds"] == new.timings_seconds
    assert set(new.timings_seconds) == set(native.STAGES)
    assert all(value >= 0 for value in new.timings_seconds.values())
    assert all(new.timings_seconds[stage] > 0 for stage in native.STAGES)
    assert "backup stage=deflate duration_seconds=" in caplog.text
    assert "synthetic-secret" not in caplog.text


def test_corrupt_closed_snapshot_is_rejected_before_publication(prepared, tmp_path: Path) -> None:
    _, projection = prepared
    snapshot = projection / native.DATABASE_NAME
    snapshot.write_bytes(b"not a SQLite database")
    archive = tmp_path / "corrupt.zip"
    with pytest.raises(native.ProfileBackupError):
        native.create_backup(projection, archive, source_snapshot=snapshot, scratch=tmp_path)
    assert not archive.exists()
    assert json.loads(archive.with_name(archive.name + ".receipt.json").read_text())["status"] == (
        "incomplete"
    )


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_snapshot_with_any_sidecar_is_refused(prepared, tmp_path: Path, suffix: str) -> None:
    _, projection = prepared
    snapshot = projection / native.DATABASE_NAME
    snapshot.with_name(snapshot.name + suffix).write_bytes(b"")
    with pytest.raises(native.ProfileBackupError, match="closed"):
        native.create_backup(projection, tmp_path / "open.zip", source_snapshot=snapshot)


def test_snapshot_must_be_projection_database(prepared, tmp_path: Path) -> None:
    source, projection = prepared
    with pytest.raises(native.ProfileBackupError, match="prepared profile database"):
        native.create_backup(
            projection, tmp_path / "wrong.zip", source_snapshot=source / native.DATABASE_NAME
        )


def test_snapshot_bytes_do_not_skip_archive_integrity(
    prepared, tmp_path: Path, monkeypatch
) -> None:
    _, projection = prepared
    real_connect = native.sqlite3.connect
    integrity_checks = []

    class Connection(sqlite3.Connection):
        def execute(self, statement, *args, **kwargs):
            if statement == "PRAGMA integrity_check":
                integrity_checks.append(statement)
            return super().execute(statement, *args, **kwargs)

    def connect(*args, **kwargs):
        return real_connect(*args, **kwargs, factory=Connection)

    monkeypatch.setattr(native.sqlite3, "connect", connect)
    native.create_backup(
        projection, tmp_path / "single-check.zip",
        source_snapshot=projection / native.DATABASE_NAME,
        scratch=tmp_path,
    )
    assert len(integrity_checks) == 1, "identical snapshot bytes were integrity-checked again"


@pytest.mark.parametrize("stage", ["deflate", "verify", "publish"])
def test_interrupted_creation_keeps_last_good(prepared, tmp_path: Path, monkeypatch, stage) -> None:
    _, projection = prepared
    good = native.create_backup(projection, tmp_path / "good.zip", scratch=tmp_path)
    latest = tmp_path / "latest-good.json"
    native.publish_backup(good, tmp_path / "published-good.zip", latest_good=latest)
    previous = latest.read_bytes()
    good_hash = native._sha256(tmp_path / "published-good.zip")

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt("synthetic interruption")

    entry = {"deflate": "_write_archive", "verify": "verify_backup", "publish": "_publish_new_file"}
    monkeypatch.setattr(native, entry[stage], interrupt)
    candidate = tmp_path / "interrupted.zip"
    with pytest.raises(KeyboardInterrupt):
        native.create_backup(
            projection, candidate, source_snapshot=projection / native.DATABASE_NAME,
            scratch=tmp_path,
        )
    assert not candidate.exists()
    assert latest.read_bytes() == previous
    assert native._sha256(tmp_path / "published-good.zip") == good_hash
    assert json.loads(candidate.with_name(candidate.name + ".receipt.json").read_text())[
        "status"
    ] == "incomplete"


@pytest.mark.parametrize("failure", ["copy", "hash", "receipt", "latest"])
def test_interrupted_publication_does_not_advance_latest(
    prepared, tmp_path: Path, monkeypatch, failure
) -> None:
    _, projection = prepared
    good = native.create_backup(projection, tmp_path / "local.zip", scratch=tmp_path)
    latest = tmp_path / "latest-good.json"
    native.publish_backup(good, tmp_path / "first.zip", latest_good=latest)
    previous = latest.read_bytes()
    destination = tmp_path / "interrupted.zip"

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt("synthetic power loss")

    if failure == "copy":
        monkeypatch.setattr(native, "_copy_stable_file", interrupt)
    elif failure == "hash":
        monkeypatch.setattr(native, "_sha256", lambda path: "0" * 64)
    else:
        save = native._save_receipt

        def fail_save(path, receipt):
            if (failure == "latest" and path == latest) or (
                failure == "receipt" and receipt["status"] == "complete"
            ):
                interrupt()
            save(path, receipt)

        monkeypatch.setattr(native, "_save_receipt", fail_save)
    with pytest.raises((KeyboardInterrupt, native.ProfileBackupError)):
        native.publish_backup(good, destination, latest_good=latest)
    assert latest.read_bytes() == previous
    assert json.loads(destination.with_name(destination.name + ".receipt.json").read_text())[
        "status"
    ] == "incomplete"
    if failure != "hash":
        assert native._sha256(tmp_path / "first.zip") == good.sha256


def test_successful_publication_receipt_and_source_tamper(prepared, tmp_path: Path) -> None:
    _, projection = prepared
    clock = native.BackupTimings()
    result = native.create_backup(
        projection, tmp_path / "local.zip", source_snapshot=projection / native.DATABASE_NAME,
        scratch=tmp_path, timings=clock,
    )
    # Keep the wrapper's trial restore in the complete workflow.
    native.restore_profile(
        result.archive, tmp_path / "trial", scratch=tmp_path, require_new=True, timings=clock
    )
    latest = tmp_path / "latest-good.json"
    receipt_path = native.publish_backup(
        result, tmp_path / "final.zip", latest_good=latest,
        metadata={"restore_rehearsal_this_run": True, "status": "bogus", "sha256": "bogus"},
        timings=clock,
    )
    receipt = json.loads(receipt_path.read_text())
    assert receipt == json.loads(latest.read_text())
    assert receipt["status"] == "complete"
    assert receipt["restore_rehearsal_this_run"] is True
    assert receipt["sha256"] == result.sha256
    assert receipt["timings_seconds"]["publish"] > result.timings_seconds["publish"]
    assert receipt["timings_seconds"]["integrity"] > result.timings_seconds["integrity"]
    previous = latest.read_bytes()
    result.archive.write_bytes(b"synthetic tampering after verification")
    with pytest.raises(native.ProfileBackupError, match="checksum"):
        native.publish_backup(result, tmp_path / "tampered.zip", latest_good=latest)
    assert not (tmp_path / "tampered.zip").exists()
    assert latest.read_bytes() == previous


def test_destination_race_never_overwrites_a_recovery_point(prepared, tmp_path: Path, monkeypatch):
    _, projection = prepared
    target = tmp_path / "race.zip"
    verify = native.verify_backup

    def race(*args, **kwargs):
        result = verify(*args, **kwargs)
        target.write_bytes(b"concurrent recovery point")
        return result

    monkeypatch.setattr(native, "verify_backup", race)
    with pytest.raises(FileExistsError):
        native.create_backup(projection, target, scratch=tmp_path)
    assert target.read_bytes() == b"concurrent recovery point"


def test_stage_durations_are_exclusive_and_log_completed_stages(monkeypatch) -> None:
    ticks = iter([0.0, 1.0, 3.0, 5.0])
    monkeypatch.setattr(native.time, "perf_counter", lambda: next(ticks))
    events = []
    clock = native.BackupTimings(on_stage=lambda stage, elapsed: events.append((stage, elapsed)))
    with clock.measure("verify"), clock.measure("integrity"):
        pass
    clock.log_totals()
    assert clock.seconds["integrity"] == 2.0
    assert clock.seconds["verify"] == 3.0
    assert dict(events) == clock.seconds


@pytest.mark.parametrize("phase", ["creation", "publication"])
def test_process_loss_leaves_incomplete_and_preserves_latest(
    prepared, tmp_path: Path, phase: str
) -> None:
    _, projection = prepared
    good = native.create_backup(projection, tmp_path / "local.zip", scratch=tmp_path)
    latest = tmp_path / "latest-good.json"
    native.publish_backup(good, tmp_path / "good.zip", latest_good=latest)
    previous = latest.read_bytes()
    candidate = tmp_path / "killed.zip"
    script = """
import os, sys
from pathlib import Path
from healthcheck import profile_backup as native
projection, archive, latest = map(Path, sys.argv[1:4])
if sys.argv[4] == 'creation':
    native._write_archive = lambda *args, **kwargs: os._exit(77)
    native.create_backup(projection, archive, source_snapshot=projection / native.DATABASE_NAME)
else:
    result = native.create_backup(projection, archive.with_suffix('.local.zip'),
                                  source_snapshot=projection / native.DATABASE_NAME)
    native._copy_stable_file = lambda *args, **kwargs: os._exit(77)
    native.publish_backup(result, archive, latest_good=latest)
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(projection), str(candidate), str(latest), phase],
        capture_output=True, text=True, timeout=60,
    )
    assert child.returncode == 77, child.stderr
    assert not candidate.exists()
    assert json.loads(candidate.with_name(candidate.name + ".receipt.json").read_text())[
        "status"
    ] == "incomplete"
    assert latest.read_bytes() == previous
    verified = native.verify_backup(tmp_path / "good.zip", scratch=tmp_path)
    assert verified.file_count == good.file_count
