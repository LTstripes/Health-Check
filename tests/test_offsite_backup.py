"""Synthetic IO/state-machine tests; the age process double is NOT cryptography.

Native Windows no-follow handles, no-overwrite rename and deletion remain real
on Windows. Linux uses explicit test doubles for Windows-only IO. No executable
is downloaded/discovered, and no Owner keys, data or provider calls are used.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from healthcheck import offsite_backup as offsite
from healthcheck import offsite_fs as fs
from healthcheck.cli import main
from healthcheck.config import Settings
from healthcheck.demo import seed_demo
from healthcheck.profile_backup import create_backup, restore_profile, verify_backup
from healthcheck.web.ui_app import create_ui_app

IDENTITY = "AGE-SECRET-KEY-1" + "Q" * 58
RECIPIENT = "age1" + "q" * 58
HEADER = (
    b"age-encryption.org/v1\n-> X25519 "
    + b"A" * 43
    + b"\n"
    + b"B" * 43
    + b"\n--- "
    + b"C" * 43
    + b"\n"
)


class AgeProcessDouble:
    """Opaque in-memory fixture lookup. No encryption/authentication implementation."""

    def __init__(self):
        self.files = {}
        self.calls = []
        self.version = b"v1.3.2\n"

    def __call__(self, arguments, output):
        self.calls.append(arguments)
        assert IDENTITY not in " ".join(arguments)
        if arguments[1] == "--version":
            output.write(self.version)
        elif arguments[1] == "--encrypt":
            payload = Path(arguments[-1]).read_bytes()
            cipher = HEADER + f"opaque-fixture-{len(self.files)}".encode()
            self.files[cipher] = payload
            output.write(cipher)
        else:
            assert arguments[1:3] == ["--decrypt", "--identity"]
            if Path(arguments[3]).read_text().strip() != IDENTITY:
                raise fs.OffsiteError("age_failed")
            payload = self.files.get(Path(arguments[-1]).read_bytes())
            if payload is None:
                raise fs.OffsiteError("age_failed")
            output.write(payload)


@pytest.fixture(scope="module")
def synthetic_source():
    with tempfile.TemporaryDirectory(prefix="hc148-seed-") as temporary:
        profile = Path(temporary) / "profile"
        seed_demo(Settings(data_dir=profile))
        (profile / "artifacts" / "canary.txt").write_text("synthetic-health-canary")
        (profile / "garmin" / "auth").mkdir(parents=True)
        (profile / "garmin" / "auth" / "garmin_tokens.json").write_text(
            "synthetic foreign DPAPI ciphertext"
        )
        yield profile


@pytest.fixture
def workflow(monkeypatch, synthetic_source):
    with tempfile.TemporaryDirectory(prefix="hc148-test-") as temporary:
        root = Path(temporary)
        profile = root / "profile"
        source_zip = root / "source.zip"
        create_backup(synthetic_source, source_zip)
        restore_profile(source_zip, profile)
        source_zip.unlink()
        destination, staging = root / "destination", root / "staging"
        destination.mkdir()
        staging.mkdir()
        executable, identity = root / "age.exe", root / "identity.txt"
        executable.write_bytes(b"synthetic executable placeholder, never executed")
        identity.write_text(IDENTITY)
        fake = AgeProcessDouble()
        monkeypatch.setattr(offsite, "_age_process", fake)
        monkeypatch.setattr(fs, "require_ntfs", lambda _: None)
        monkeypatch.setattr(fs, "require_private", lambda _: None)
        if os.name != "nt":

            def rename(source, target):
                # Atomic no-overwrite fixture helper, only for Linux state-machine tests.
                os.link(source, target)
                source.unlink()

            monkeypatch.setattr(offsite, "_rename_new", rename)
            monkeypatch.setattr(fs, "retire_file", lambda stream: Path(stream.name).unlink())
            # fdopen exposes a numeric .name; use /proc fixture identity for deletion.
            monkeypatch.setattr(
                fs,
                "retire_file",
                lambda stream: Path(os.readlink(f"/proc/self/fd/{stream.fileno()}")).unlink(),
            )
        config = offsite.OffsiteConfig(
            profile, destination, staging, executable, identity, RECIPIENT, True
        )
        yield config, root, fake


def published(workflow, *, rotate=False):
    config, _, _ = workflow
    result = offsite.publish_backup(config, rotate=rotate)
    assert result["status"] == "succeeded", result
    return result


def recover(workflow, point, target=None):
    config, root, _ = workflow
    return offsite.recover_backup(
        config.destination / point["archive"],
        target or root / "restored",
        config.staging,
        config.executable,
        config.identity,
        expected_uuid=point["uuid"],
        expected_sha256=point["sha256"],
        staging_nonsynced=True,
    )


def test_full_publish_clean_restore_and_supported_reads(workflow):
    config, root, fake = workflow
    point = published(workflow)
    archive = config.destination / point["archive"]
    before = archive.read_bytes()
    assert b"synthetic-health-canary" not in before  # opaque process double, not crypto proof
    receipt = json.loads((config.destination / (point["archive"] + ".json")).read_text())
    assert set(receipt) == offsite.RECEIPT_KEYS
    ledger = json.loads((config.profile / offsite.LEDGER_NAME).read_text())
    assert ledger["records"] == [receipt]
    assert [args[1] for args in fake.calls] == ["--version", "--encrypt", "--decrypt", "--decrypt"]
    assert not list(config.staging.iterdir())
    report = recover(workflow, point)
    assert report["data_recovery"] == "PASS"
    assert report["provider_authorization"] == "reauthorization_required"
    assert report["provider_refresh"] == "not_run"
    assert report["offsite_presence"] == "UNVERIFIED"
    assert report["readiness"]["domains"]["measurement_sessions"]["count"] > 0
    assert archive.read_bytes() == before
    assert (root / "restored" / "garmin" / "auth" / "garmin_tokens.json").exists()
    app, _ = create_ui_app(Settings(data_dir=root / "restored"))
    try:
        with TestClient(app) as client:
            assert client.get("/healthz").status_code == 200
            assert client.get("/").status_code == 200
    finally:
        if hasattr(app.state, "engine"):
            app.state.engine.dispose()


@pytest.mark.parametrize("mutation", ["truncate", "body", "header"])
def test_corrupt_ciphertext_never_mutates_target(workflow, mutation):
    config, root, _ = workflow
    point = published(workflow)
    archive = config.destination / point["archive"]
    payload = archive.read_bytes()
    changed = (
        payload[:-1]
        if mutation == "truncate"
        else payload.replace(b"fixture", b"BROKEN")
        if mutation == "body"
        else b"bad" + payload[3:]
    )
    archive.write_bytes(changed)
    point["sha256"] = offsite._hash_path(archive)  # trusted hash alone is not authentication
    result = recover(workflow, point)
    assert result["status"] == "failed"
    assert not (root / "restored").exists()


@pytest.mark.parametrize("key", ["wrong", "missing", "multiple", "passphrase"])
def test_identity_failures_before_target_mutation(workflow, key):
    config, root, _ = workflow
    point = published(workflow)
    if key == "missing":
        config.identity.unlink()
    else:
        value = (
            IDENTITY.replace("Q", "R")
            if key == "wrong"
            else (IDENTITY + "\n" + IDENTITY if key == "multiple" else "passphrase")
        )
        config.identity.write_text(value)
    result = recover(workflow, point)
    assert result["status"] == "failed"
    assert not (root / "restored").exists()


@pytest.mark.parametrize("field", ["uuid", "sha256"])
def test_independent_fingerprint_is_required(workflow, field):
    _, root, _ = workflow
    point = published(workflow)
    point[field] = "0" * (32 if field == "uuid" else 64)
    result = recover(workflow, point)
    assert result["status"] == "failed"
    assert not (root / "restored").exists()


def test_existing_target_and_archive_immutability(workflow):
    _, root, _ = workflow
    point = published(workflow)
    target = root / "target"
    target.mkdir()
    note = target / "unknown.txt"
    note.write_text("preserve")
    result = recover(workflow, point, target)
    assert result["status"] == "failed"
    assert note.read_text() == "preserve"
    assert recover(workflow, point, root / "absent")["data_recovery"] == "PASS"


@pytest.mark.parametrize("version", [b"v1.3.1\n", b"v1.3.2 EXTRA\n", b"\n"])
def test_exact_age_version_before_backup(workflow, version):
    config, _, fake = workflow
    fake.version = version
    result = offsite.publish_backup(config)
    assert result["created"] is False
    assert result["action_required"] == ["age_version_mismatch"]


@pytest.mark.parametrize("recipient", ["ssh-rsa unsafe", "age1pqBAD", "-flag", "password", "age1"])
def test_native_single_recipient_only(workflow, recipient):
    config, _, _ = workflow
    report = offsite.publish_backup(replace(config, recipient=recipient))
    assert report["created"] is False


def test_explicit_paths_and_staging_attestation(workflow):
    config, _, _ = workflow
    for changed in (
        replace(config, staging_nonsynced=False),
        replace(config, executable=Path("age.exe")),
        replace(config, staging=config.destination),
        replace(config, identity=config.profile / "identity.txt"),
    ):
        result = offsite.publish_backup(changed)
        assert result["created"] is False


def test_private_and_filesystem_uncertainty_fail_closed(workflow, monkeypatch):
    config, _, _ = workflow
    for guard in ("require_private", "require_ntfs"):
        with monkeypatch.context() as change:

            def deny(_):
                raise fs.OffsiteError("synthetic_guard_failure")

            change.setattr(fs, guard, deny)
            assert offsite.publish_backup(config)["created"] is False


@pytest.mark.parametrize("failure", ["encrypt", "copy", "rename", "readback", "receipt", "ledger"])
def test_failure_points_never_authorize_retention(workflow, monkeypatch, failure):
    config, _, fake = workflow
    good = published(workflow)
    old_archive = config.destination / good["archive"]
    old_content = old_archive.read_bytes()
    if failure == "encrypt":
        original = fake.__call__

        def process(args, output):
            if args[1] == "--encrypt":
                raise OSError("synthetic-health-canary secret path")
            original(args, output)

        monkeypatch.setattr(offsite, "_age_process", process)
    elif failure == "copy":
        monkeypatch.setattr(
            offsite.shutil,
            "copyfileobj",
            lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
        )
    elif failure == "rename":
        monkeypatch.setattr(
            offsite, "_rename_new", lambda *a: (_ for _ in ()).throw(OSError("disconnect"))
        )
    elif failure == "readback":
        original = offsite._rename_new

        def corrupt(source, target):
            original(source, target)
            if target.name.endswith(".zip.age"):
                target.write_bytes(b"corruption")

        monkeypatch.setattr(offsite, "_rename_new", corrupt)
    else:
        original = offsite._write_json

        def fail(path, value, **kwargs):
            if (failure == "ledger" and path.name == offsite.LEDGER_NAME) or (
                failure == "receipt" and path.parent == config.destination
            ):
                raise OSError("ACL failure")
            return original(path, value, **kwargs)

        monkeypatch.setattr(offsite, "_write_json", fail)
    report = offsite.publish_backup(config, rotate=True)
    assert report["status"] in {"failed", "publication_uncertain"}
    assert report["retention"] == "not_run"
    assert old_archive.read_bytes() == old_content
    assert "synthetic-health-canary" not in json.dumps(report)


def test_concurrent_destination_and_profile_lock(workflow):
    config, _, _ = workflow
    for directory, name in (
        (config.destination, ".hc148-operation.lock"),
        (config.profile, ".offsite-ledger.lock"),
    ):
        with offsite._operation_lock(directory, name):
            result = offsite.publish_backup(config)
            assert result["action_required"] == ["operation_busy"]
            assert not result["created"]


def test_keep_three_and_preserve_unknown_files(workflow):
    config, _, _ = workflow
    unknown = config.destination / "owner-note.txt"
    unknown.write_text("preserve")
    partial = config.destination / ".unknown.partial"
    partial.write_text("preserve")
    for _ in range(5):
        published(workflow, rotate=True)
    inventory = offsite.list_backups(config.profile, config.destination)
    assert len(inventory["verified"]) == 3
    assert len(list(config.destination.glob("*.zip.age"))) == 3
    assert inventory["would_delete"] == []
    assert unknown.read_text() == partial.read_text() == "preserve"
    # Prior trusted records are ordinary backup members.
    local = config.staging / "ledger.zip"
    create_backup(config.profile, local, scratch=config.staging)
    assert verify_backup(local, scratch=config.staging).file_count > 0


@pytest.mark.parametrize("problem", ["absent", "invalid", "receipt", "hash", "forged", "orphan"])
def test_retention_ambiguity_deletes_nothing(workflow, problem):
    config, _, _ = workflow
    points = [published(workflow) for _ in range(4)]
    point = points[0]
    ledger = config.profile / offsite.LEDGER_NAME
    if problem == "absent":
        ledger.unlink()
    elif problem == "invalid":
        ledger.write_text('{"contract":"broken","contract":"duplicate"}')
    elif problem == "receipt":
        (config.destination / (point["archive"] + ".json")).write_text("{}")
    elif problem == "hash":
        (config.destination / point["archive"]).write_bytes(b"corrupt")
    else:
        name = point["archive"].replace(point["uuid"], "0" * 32)
        (config.destination / (name + ".json")).write_text(json.dumps({}))
        if problem == "forged":
            (config.destination / name).write_bytes(b"fake")
    before = {p.name: p.read_bytes() for p in config.destination.iterdir()}
    inventory = offsite.list_backups(config.profile, config.destination)
    assert inventory["would_delete"] == []
    assert offsite._rotate(config.profile, config.destination) == "blocked_untrusted_inventory"
    assert before == {p.name: p.read_bytes() for p in config.destination.iterdir()}


def test_retention_failure_does_not_invalidate_new_point(workflow, monkeypatch):
    config, _, _ = workflow
    for _ in range(4):
        published(workflow)
    monkeypatch.setattr(offsite, "_delete_pair", lambda *a: (_ for _ in ()).throw(OSError("ACL")))
    point = published(workflow, rotate=True)
    assert point["destination_verified"] is True
    assert point["retention"] == "failed"
    assert len(list(config.destination.glob("*.zip.age"))) == 5


def test_lock_collision_hardlink_and_duplicate_json(workflow):
    config, root, _ = workflow
    source, target = root / "source", root / "target"
    source.write_text("new")
    target.write_text("preserve")
    with pytest.raises(FileExistsError):
        offsite._rename_new(source, target)
    assert target.read_text() == "preserve"
    os.link(config.identity, root / "linked-key")
    assert offsite.publish_backup(config)["created"] is False
    with pytest.raises(fs.OffsiteError):
        offsite._decode_json(b'{"a":1,"a":2}')


def test_inventory_is_bounded(workflow):
    config, _, _ = workflow
    published(workflow)
    for i in range(offsite.MAX_INVENTORY):
        (config.destination / f"unknown-{i}").touch()
    result = offsite.list_backups(config.profile, config.destination)
    assert result["ambiguous"]
    assert result["would_delete"] == []


def test_cli_status_and_privacy(workflow, capsys):
    config, _, _ = workflow
    args = [
        "offsite-backup",
        "--data-dir",
        str(config.profile),
        "--destination",
        str(config.destination),
        "--staging",
        str(config.staging),
        "--age-executable",
        str(config.executable),
        "--recovery-identity",
        str(config.identity),
        "--recipient",
        RECIPIENT,
        "--staging-nonsynced",
    ]
    assert main(args) == 0
    output = capsys.readouterr().out
    assert "synthetic-health-canary" not in output and IDENTITY not in output
    assert str(config.profile) not in output
    report = json.loads(output)
    assert report["destination_verified"] is True
    assert (
        main(
            [
                "offsite-backup-list",
                "--data-dir",
                str(config.profile),
                "--destination",
                str(config.destination),
                "--dry-run",
            ]
        )
        == 0
    )
    assert main(["offsite-recover", "--replace"]) == 2


def test_process_errors_are_sanitized(workflow, monkeypatch):
    config, _, _ = workflow
    monkeypatch.undo()  # direct production runner, no process double

    def run(*args, **kwargs):
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert not kwargs.get("shell", False)
        return SimpleNamespace(returncode=2)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(fs.OffsiteError, match="age_failed"):
        with tempfile.TemporaryFile() as stream:
            offsite._age_process([str(config.executable), "--version"], stream)


def test_native_platform_and_safe_ancestors(tmp_path):
    if os.name == "nt":
        fs.require_ntfs(tmp_path)
    else:
        with pytest.raises(fs.OffsiteError, match="unsupported_filesystem"):
            fs.require_ntfs(tmp_path)
    with pytest.raises(fs.OffsiteError):
        fs.absolute(Path("relative"))
    with pytest.raises(fs.OffsiteError):
        fs.absolute(Path("//server/share/file"))
    with fs.pin_directories(tmp_path):
        assert fs.identity(tmp_path, directory=True)

    # Simulated reparse lstat covers native cloud placeholders without real cloud IO.
    class Reparse:
        st_mode = 0
        st_file_attributes = 0x400

    original = Path.lstat
    try:
        Path.lstat = lambda *args: Reparse()
        with pytest.raises(fs.OffsiteError, match="unsafe_reparse"):
            fs.identity(tmp_path)
    finally:
        Path.lstat = original


def test_native_private_acl_and_handle_identity(tmp_path):
    if os.name != "nt":
        with pytest.raises(fs.OffsiteError):
            fs.require_private(tmp_path)
        return
    from healthcheck.google.protection import _current_windows_user_sid

    private = tmp_path / "private"
    private.mkdir()
    sid = _current_windows_user_sid()
    result = subprocess.run(
        ["icacls", str(private), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    fs.require_private(private)
    entry = private / "file"
    replacement = private / "replacement"
    entry.write_text("synthetic")
    replacement.write_text("replacement")
    with fs.read_file(entry):
        with pytest.raises(OSError):
            os.replace(replacement, entry)
    with fs.pin_directories(private):
        with pytest.raises(OSError):
            private.rename(tmp_path / "renamed")
    result = subprocess.run(
        ["icacls", str(private), "/grant", "*S-1-1-0:(R)"], capture_output=True, check=False
    )
    assert result.returncode == 0
    with pytest.raises(fs.OffsiteError, match="private_context_required"):
        fs.require_private(private)


def test_ledger_swap_after_read_is_not_overwritten(workflow, monkeypatch):
    config, _, fake = workflow
    published(workflow)
    ledger = config.profile / offsite.LEDGER_NAME
    original = fake.__call__

    def process(args, output):
        original(args, output)
        if args[1] == "--encrypt":
            ledger.write_text('{"changed":"synthetic"}')

    monkeypatch.setattr(offsite, "_age_process", process)
    report = offsite.publish_backup(config, rotate=True)
    assert report["status"] == "publication_uncertain"
    assert report["action_required"] == ["ledger_changed"]
    assert ledger.read_text() == '{"changed":"synthetic"}'


def test_stage_is_used_by_every_plain_verification(workflow, monkeypatch):
    config, _, _ = workflow
    import healthcheck.profile_backup as primitives

    original = primitives.tempfile.TemporaryDirectory
    seen = []

    def temporary(*args, **kwargs):
        seen.append(kwargs.get("dir"))
        return original(*args, **kwargs)

    monkeypatch.setattr(primitives.tempfile, "TemporaryDirectory", temporary)
    point = published(workflow)
    assert seen and all(path and fs.overlaps(Path(path), config.staging) for path in seen)
    assert point["destination_verified"]


def test_incompatible_revision_and_post_restore_failure_are_distinct(workflow, monkeypatch):
    _, root, _ = workflow
    point = published(workflow)
    with monkeypatch.context() as change:
        change.setattr(
            offsite,
            "_require_current_revision",
            lambda _: (_ for _ in ()).throw(fs.OffsiteError("recovery_runtime_revision_required")),
        )
        report = recover(workflow, point)
        assert not report["target_created"] and not (root / "restored").exists()
    monkeypatch.setattr(
        offsite,
        "_domain_readiness",
        lambda *args: (_ for _ in ()).throw(fs.OffsiteError("recovery_integrity_failed")),
    )
    report = recover(workflow, point)
    assert report["target_created"]
    assert report["data_recovery"] == "restored_readiness_unverified"
    assert report["status"] == "failed"


def test_cross_process_destination_lock(workflow):
    import sys

    config, _, _ = workflow
    script = (
        "import sys; from pathlib import Path; "
        "from healthcheck.offsite_backup import _operation_lock; "
        "lock=_operation_lock(Path(sys.argv[1]), '.hc148-operation.lock'); "
        "lock.__enter__(); print('ready', flush=True); sys.stdin.readline(); "
        "lock.__exit__(None,None,None)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(config.destination)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        report = offsite.publish_backup(config)
        assert report["action_required"] == ["operation_busy"]
        process.communicate("finish\n", timeout=10)
        assert process.returncode == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def test_retention_rechecks_changed_receipt(workflow, monkeypatch):
    config, _, _ = workflow
    points = [published(workflow) for _ in range(4)]
    original = offsite._delete_pair

    def changed(destination, record):
        (destination / (record["archive"] + ".json")).write_text("{}")
        return original(destination, record)

    monkeypatch.setattr(offsite, "_delete_pair", changed)
    assert offsite._rotate(config.profile, config.destination) == "failed"
    assert len(points) == len(list(config.destination.glob("*.zip.age")))


def test_identity_swap_during_read_is_rejected(tmp_path):
    entry, other = tmp_path / "entry", tmp_path / "other"
    entry.write_text("synthetic")
    other.write_text("replacement")
    if os.name == "nt":
        with fs.read_file(entry):
            with pytest.raises(OSError):
                os.replace(other, entry)
    else:
        with pytest.raises(fs.OffsiteError, match="identity_changed"):
            with fs.read_file(entry):
                os.replace(other, entry)


def test_empty_existing_target_rejected_by_primitive(workflow):
    config, root, _ = workflow
    archive = config.staging / "plain.zip"
    create_backup(config.profile, archive, scratch=config.staging)
    target = root / "empty"
    target.mkdir()
    from healthcheck.profile_backup import ProfileBackupError

    with pytest.raises(ProfileBackupError, match="absent new target"):
        restore_profile(archive, target, require_new=True)


def test_newest_is_preserved_even_with_identical_timestamps(workflow, monkeypatch):
    config, _, _ = workflow
    from datetime import UTC, datetime

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 3, tzinfo=UTC)

    monkeypatch.setattr(offsite, "datetime", Clock)
    points = [published(workflow, rotate=True) for _ in range(5)]
    assert all((config.destination / p["archive"]).exists() for p in points[-3:])
    assert all(not (config.destination / p["archive"]).exists() for p in points[:2])
