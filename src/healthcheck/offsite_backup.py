"""Protected filesystem publication and clean data recovery (#148).

Authority: issue 148, Integrator freeze 5962166816. age is an explicit external
executable, never discovered or installed. Receipts are evidence, not trust;
only the profile ledger plus a current safe hash can authorize retention.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from healthcheck import offsite_fs as fs
from healthcheck.external_runtime_lock import _lock_file, _unlock_file
from healthcheck.profile_backup import (
    FORMAT_VERSION,
    ProfileBackupError,
    _profile_files,
    create_backup,
    restore_profile,
    verify_backup,
)

CONTRACT = "healthcheck-offsite-v1"
LEDGER_NAME = "offsite-backup-ledger.json"
AGE_VERSION = "v1.3.2"
PROTECTION = "age-v1-x25519"
KEEP = 3
MAX_JSON_BYTES = 1024 * 1024
MAX_INVENTORY = 256
MAX_CIPHERTEXT_BYTES = 9 * 1024**3
NAME = re.compile(r"hc148-v1-(\d{8}T\d{6}Z)-([0-9a-f]{32})\.zip\.age")
HASH = re.compile(r"[0-9a-f]{64}")
RECEIPT_KEYS = {
    "contract",
    "version",
    "archive",
    "uuid",
    "created_utc",
    "size",
    "sha256",
    "protection",
    "age_version",
    "archive_version",
    "destination_verified",
}


@dataclass(frozen=True)
class OffsiteConfig:
    profile: Path
    destination: Path
    staging: Path
    executable: Path
    identity: Path
    recipient: str
    staging_nonsynced: bool = False
    destination_alias: str = "offsite"


def _hash(stream: BinaryIO) -> str:
    stream.seek(0)
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _hash_path(path: Path) -> str:
    with fs.read_file(path) as stream:
        return _hash(stream)


def _decode_json(raw: bytes) -> dict[str, Any]:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise fs.OffsiteError("invalid_metadata")
            result[key] = value
        return result

    if len(raw) > MAX_JSON_BYTES:
        raise fs.OffsiteError("metadata_limit")
    try:
        result = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, RecursionError, UnicodeError) as exc:
        raise fs.OffsiteError("invalid_metadata") from exc
    if not isinstance(result, dict):
        raise fs.OffsiteError("invalid_metadata")
    return result


def _json(path: Path) -> dict[str, Any]:
    with fs.read_file(path) as stream:
        return _decode_json(stream.read(MAX_JSON_BYTES + 1))


def _receipt(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != RECEIPT_KEYS:
        raise fs.OffsiteError("invalid_receipt")
    name = value.get("archive")
    match = NAME.fullmatch(name) if isinstance(name, str) else None
    if not match:
        raise fs.OffsiteError("invalid_receipt")
    try:
        datetime.strptime(match[1], "%Y%m%dT%H%M%SZ")
    except ValueError as exc:
        raise fs.OffsiteError("invalid_receipt") from exc
    size = value.get("size")
    checksum = value.get("sha256")
    if (
        value["contract"] != CONTRACT
        or type(value["version"]) is not int
        or value["version"] != 1
        or value["uuid"] != match[2]
        or value["created_utc"] != match[1]
        or type(size) is not int
        or not 0 < size <= MAX_CIPHERTEXT_BYTES
        or not isinstance(checksum, str)
        or not HASH.fullmatch(checksum)
        or value["protection"] != PROTECTION
        or value["age_version"] != AGE_VERSION
        or type(value["archive_version"]) is not int
        or value["archive_version"] != 1
        or value["destination_verified"] is not True
    ):
        raise fs.OffsiteError("invalid_receipt")
    return value


def _ledger(path: Path) -> tuple[list[dict[str, Any]], bool]:
    try:
        value = _json(path)
    except FileNotFoundError:
        return [], False
    if (
        set(value) != {"contract", "version", "records"}
        or value["contract"] != CONTRACT
        or type(value["version"]) is not int
        or value["version"] != 1
        or not isinstance(value["records"], list)
        or len(value["records"]) > MAX_INVENTORY
    ):
        raise fs.OffsiteError("invalid_ledger")
    records = [
        _receipt(item) if isinstance(item, dict) else _receipt({}) for item in value["records"]
    ]
    if len({r["archive"] for r in records}) != len(records):
        raise fs.OffsiteError("invalid_ledger")
    return records, True


def _rename_new(source: Path, target: Path) -> None:
    # Windows os.rename rejects an existing destination, including a race.
    # Never use os.replace/copy-delete as an archive publication fallback.
    if os.name != "nt":
        raise fs.OffsiteError("unsupported_filesystem")
    os.rename(source, target)


def _write_json(
    path: Path, value: dict[str, Any], *, replace: bool = False, expected_hash: str | None = None
) -> None:
    if expected_hash is not None and _hash_path(path) != expected_hash:
        raise fs.OffsiteError("ledger_changed")
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(raw) > MAX_JSON_BYTES:
        raise fs.OffsiteError("metadata_limit")
    existing = None
    if replace:
        try:
            existing = fs.identity(path)
        except FileNotFoundError:
            pass
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.partial")
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if existing is not None:
        current = fs.identity(path)
        if not fs.same(existing, current) or (existing.st_size, existing.st_mtime_ns) != (
            current.st_size,
            current.st_mtime_ns,
        ):
            raise fs.OffsiteError("identity_changed")
        os.replace(temporary, path)
    else:
        _rename_new(temporary, path)


@contextmanager
def _operation_lock(directory: Path, name: str):
    path = directory / name
    try:
        with path.open("xb") as stream:
            stream.write(b"\0")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        pass
    with fs.read_file(path, writable=True) as stream:
        if os.fstat(stream.fileno()).st_size != 1:
            raise fs.OffsiteError("unsafe_lock")
        try:
            _lock_file(stream)
        except OSError as exc:
            raise fs.OffsiteError("operation_busy") from exc
        try:
            yield
        finally:
            _unlock_file(stream)


def _age_process(arguments: list[str], output: BinaryIO) -> None:
    # Do not surface process stderr: it may contain local paths or malicious text.
    try:
        result = subprocess.run(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.DEVNULL,
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise fs.OffsiteError("age_unavailable") from exc
    if result.returncode != 0:
        raise fs.OffsiteError("age_failed")


class _Age:
    def __init__(self, executable: Path, identity: Path, scratch: Path):
        self.executable = executable
        self.identity = identity
        self.scratch = scratch
        with tempfile.TemporaryFile(dir=scratch) as stream:
            _age_process([str(executable), "--version"], stream)
            stream.seek(0)
            if stream.read(65) not in {b"v1.3.2", b"v1.3.2\n", b"v1.3.2\r\n"}:
                raise fs.OffsiteError("age_version_mismatch")
        with fs.read_file(identity) as stream:
            raw = stream.read(4097)
        try:
            lines = [
                line.strip()
                for line in raw.decode("ascii").splitlines()
                if line.strip() and not line.startswith("#")
            ]
        except UnicodeError as exc:
            raise fs.OffsiteError("native_identity_required") from exc
        if (
            len(raw) > 4096
            or len(lines) != 1
            or not re.fullmatch(r"AGE-SECRET-KEY-1[0-9A-Z]{58}", lines[0])
        ):
            raise fs.OffsiteError("native_identity_required")

    def encrypt(self, plaintext: Path, ciphertext: Path, recipient: str) -> None:
        with ciphertext.open("xb") as output:
            _age_process(
                [str(self.executable), "--encrypt", "--recipient", recipient, str(plaintext)],
                output,
            )
            output.flush()
            os.fsync(output.fileno())
        _header(ciphertext)

    def decrypt(self, ciphertext: Path, plaintext: Path) -> None:
        _header(ciphertext)
        with plaintext.open("xb") as output:
            _age_process(
                [
                    str(self.executable),
                    "--decrypt",
                    "--identity",
                    str(self.identity),
                    str(ciphertext),
                ],
                output,
            )
            output.flush()
            os.fsync(output.fileno())
        if fs.identity(plaintext).st_size > MAX_CIPHERTEXT_BYTES:
            raise fs.OffsiteError("archive_limit")


def _header(path: Path) -> None:
    with fs.read_file(path) as stream:
        size = os.fstat(stream.fileno()).st_size
        header = stream.read(512).split(b"\n--- ", 1)[0]
    if not 0 < size <= MAX_CIPHERTEXT_BYTES:
        raise fs.OffsiteError("archive_limit")
    lines = header.splitlines()
    if (
        len(lines) != 3
        or lines[0] != b"age-encryption.org/v1"
        or not lines[1].startswith(b"-> X25519 ")
    ):
        raise fs.OffsiteError("native_protection_required")


@contextmanager
def _environment(
    profile: Path | None,
    destination: Path | None,
    staging: Path,
    executable: Path,
    identity: Path,
    *,
    nonsynced: bool,
    target: Path | None = None,
):
    if not nonsynced:
        raise fs.OffsiteError("staging_attestation_required")
    if executable.suffix.lower() != ".exe":
        raise fs.OffsiteError("explicit_executable_required")
    directories = tuple(p for p in (profile, destination, staging) if p is not None)
    with fs.pin_disjoint_paths(directories, (executable, identity), new_directory=target):
        for path in directories:
            fs.require_ntfs(path)
        fs.require_private(staging)
        if target is not None:
            fs.require_ntfs(target.parent)
            fs.require_private(target.parent)
        if profile is not None:
            fs.require_private(profile)  # trusted ledger cannot be writable by unrelated users
            for item in _profile_files(profile):
                fs.identity(item)
        fs.require_private(identity)
        yield


def _status(alias: str = "offsite") -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", alias):
        raise fs.OffsiteError("invalid_destination_alias")
    return {
        "contract": CONTRACT,
        "archive_version": FORMAT_VERSION,
        "protection": PROTECTION,
        "age_version": AGE_VERSION,
        "destination_alias": alias,
        "destination_class": "local_ntfs",
        "created": False,
        "protected": False,
        "published": False,
        "destination_verified": False,
        "retention": "not_run",
        "rehearsal": "UNVERIFIED",
        "offsite_presence": "UNVERIFIED",
        "status": "failed",
        "action_required": [],
    }


def _error(result: dict[str, Any], exc: Exception) -> dict[str, Any]:
    code = str(exc) if isinstance(exc, fs.OffsiteError) else "operation_failed"
    result["status"] = "publication_uncertain" if result["published"] else "failed"
    result["action_required"] = [code]
    return result


def _config_paths(config: OffsiteConfig) -> OffsiteConfig:
    return OffsiteConfig(
        *(
            fs.absolute(p)
            for p in (
                config.profile,
                config.destination,
                config.staging,
                config.executable,
                config.identity,
            )
        ),
        config.recipient,
        config.staging_nonsynced,
        config.destination_alias,
    )


def publish_backup(config: OffsiteConfig, *, rotate: bool = False) -> dict[str, Any]:
    """Publish one point. Rotation is explicit; listing is the default inspection path."""
    result = _status(config.destination_alias)
    try:
        config = _config_paths(config)
        if not re.fullmatch(r"age1[023456789acdefghjklmnpqrstuvwxyz]{58}", config.recipient):
            raise fs.OffsiteError("native_recipient_required")
        with (
            _environment(
                config.profile,
                config.destination,
                config.staging,
                config.executable,
                config.identity,
                nonsynced=config.staging_nonsynced,
            ),
            _operation_lock(config.profile, ".offsite-ledger.lock"),
            _operation_lock(config.destination, ".hc148-operation.lock"),
        ):
            records, ledger_existed = _ledger(config.profile / LEDGER_NAME)
            ledger_hash = _hash_path(config.profile / LEDGER_NAME) if ledger_existed else None
            if len(records) >= MAX_INVENTORY:
                raise fs.OffsiteError("ledger_limit")
            with tempfile.TemporaryDirectory(prefix="hc148-", dir=config.staging) as temporary:
                scratch = Path(temporary)
                age = _Age(config.executable, config.identity, scratch)
                plain = scratch / "profile.zip"
                create_backup(config.profile, plain, scratch=scratch)
                result["created"] = True
                cipher = scratch / "profile.zip.age"
                age.encrypt(plain, cipher, config.recipient)
                verified = scratch / "verified.zip"
                age.decrypt(cipher, verified)
                verify_backup(verified, scratch=scratch)
                if _hash_path(verified) != _hash_path(plain):
                    raise fs.OffsiteError("round_trip_mismatch")
                result["protected"] = True
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                token = uuid.uuid4().hex
                name = f"hc148-v1-{stamp}-{token}.zip.age"
                final = config.destination / name
                partial = config.destination / f".{name}.partial"
                with fs.read_file(cipher) as source, partial.open("xb") as output:
                    expected_hash = _hash(source)
                    source.seek(0)
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                original = fs.identity(partial)
                # Once rename is attempted, a lost response may be ambiguous.
                result["published"] = "uncertain"
                _rename_new(partial, final)
                result["published"] = True
                if not fs.same(original, fs.identity(final)):
                    raise fs.OffsiteError("identity_changed")
                with fs.read_file(final) as source:
                    if _hash(source) != expected_hash:
                        raise fs.OffsiteError("destination_hash_mismatch")
                    destination_plain = scratch / "destination.zip"
                    age.decrypt(final, destination_plain)
                    verify_backup(destination_plain, scratch=scratch)
                    if _hash_path(destination_plain) != _hash_path(plain):
                        raise fs.OffsiteError("round_trip_mismatch")
                    size = os.fstat(source.fileno()).st_size
                result["destination_verified"] = True
                receipt = _receipt(
                    {
                        "contract": CONTRACT,
                        "version": 1,
                        "archive": name,
                        "uuid": token,
                        "created_utc": stamp,
                        "size": size,
                        "sha256": expected_hash,
                        "protection": PROTECTION,
                        "age_version": AGE_VERSION,
                        "archive_version": FORMAT_VERSION,
                        "destination_verified": True,
                    }
                )
                _write_json(config.destination / f"{name}.json", receipt)
                _write_json(
                    config.profile / LEDGER_NAME,
                    {
                        "contract": CONTRACT,
                        "version": 1,
                        "records": [*records, receipt],
                    },
                    replace=ledger_existed,
                    expected_hash=ledger_hash,
                )
                result.update(
                    status="succeeded",
                    archive=name,
                    uuid=token,
                    created_utc=stamp,
                    size=size,
                    sha256=expected_hash,
                )
                if rotate and ledger_existed:
                    try:
                        result["retention"] = _rotate(config.profile, config.destination)
                    except (fs.OffsiteError, OSError):
                        result["retention"] = "failed"
                    if result["retention"] not in {"succeeded", "ledger_initialized"}:
                        result["action_required"] = ["retention_inspection_required"]
                else:
                    result["retention"] = "not_requested" if not rotate else "ledger_initialized"
    except (fs.OffsiteError, ProfileBackupError, OSError, sqlite3.Error) as exc:
        return _error(result, exc)
    return result


def _inventory(profile: Path, destination: Path) -> dict[str, Any]:
    result = {"ledger": "invalid", "ambiguous": True, "verified": [], "preserved": 0}
    try:
        records, present = _ledger(profile / LEDGER_NAME)
        result["ledger"] = "valid" if present else "absent"
        from itertools import islice

        entries = list(islice(destination.iterdir(), MAX_INVENTORY + 1))
        if len(entries) > MAX_INVENTORY:
            result["reason"] = "inventory_limit"
            return result
        known = {r["archive"] for r in records}
        result["ambiguous"] = not present
        for entry in entries:
            if entry.name == ".hc148-operation.lock":
                continue
            archive_name = entry.name.removesuffix(".json")
            if NAME.fullmatch(archive_name):
                if archive_name not in known:
                    result["ambiguous"] = True
                    result["preserved"] += 1
            else:
                result["preserved"] += 1
        for record in records:
            archive = destination / record["archive"]
            receipt = destination / f"{record['archive']}.json"
            try:
                if _receipt(_json(receipt)) != record:
                    raise fs.OffsiteError("receipt_ledger_mismatch")
                with fs.read_file(archive) as stream:
                    if os.fstat(stream.fileno()).st_size != record["size"] or (
                        _hash(stream) != record["sha256"]
                    ):
                        raise fs.OffsiteError("inventory_hash_mismatch")
                result["verified"].append(record)
            except (fs.OffsiteError, OSError):
                result["ambiguous"] = True
        # The trusted append order, not wall clock/UUID/mtime, defines creation order.
        result["verified"].reverse()
    except (fs.OffsiteError, OSError):
        result["reason"] = "ledger_untrusted"
    return result


def _delete_pair(destination: Path, record: dict[str, Any]) -> None:
    archive = destination / record["archive"]
    receipt = destination / f"{record['archive']}.json"
    with (
        fs.read_file(archive, deletable=True) as cipher,
        fs.read_file(receipt, deletable=True) as metadata,
    ):
        if (
            _receipt(_decode_json(metadata.read(MAX_JSON_BYTES + 1))) != record
            or os.fstat(cipher.fileno()).st_size != record["size"]
            or _hash(cipher) != record["sha256"]
        ):
            raise fs.OffsiteError("retention_identity_changed")
        fs.retire_file(cipher)
        fs.retire_file(metadata)


def _rotate(profile: Path, destination: Path) -> str:
    ledger_hash = _hash_path(profile / LEDGER_NAME) if (profile / LEDGER_NAME).exists() else None
    inventory = _inventory(profile, destination)
    if inventory["ambiguous"]:
        return "blocked_untrusted_inventory"
    records = list(reversed(inventory["verified"]))  # oldest first, newest publication last
    deleted = 0
    try:
        for record in records[:-KEEP]:
            if _hash_path(profile / LEDGER_NAME) != ledger_hash:
                raise fs.OffsiteError("ledger_changed")
            _delete_pair(destination, record)
            deleted += 1
            current = [item for item in records if item != record]
            _write_json(
                profile / LEDGER_NAME,
                {
                    "contract": CONTRACT,
                    "version": 1,
                    "records": current,
                },
                replace=True,
                expected_hash=ledger_hash,
            )
            ledger_hash = _hash_path(profile / LEDGER_NAME)
            records = current
    except (fs.OffsiteError, OSError):
        return "partial" if deleted else "failed"
    return "succeeded"


def list_backups(profile: Path, destination: Path) -> dict[str, Any]:
    """Bounded read-only retention dry-run; never decrypt or infer trust from a receipt."""
    result = {
        "contract": CONTRACT,
        "keep": KEEP,
        "dry_run": True,
        "status": "failed",
        "offsite_presence": "UNVERIFIED",
    }
    try:
        profile, destination = fs.absolute(profile), fs.absolute(destination)
        with fs.pin_disjoint_paths((profile, destination)):
            fs.require_ntfs(destination)
            fs.require_private(profile)
            inventory = _inventory(profile, destination)
            result.update(inventory)
            result["status"] = "unverified" if inventory["ambiguous"] else "succeeded"
            if inventory["ambiguous"]:
                result["action_required"] = ["retention_inspection_required"]
            result["would_delete"] = (
                []
                if inventory["ambiguous"]
                else [r["archive"] for r in inventory["verified"][KEEP:]]
            )
    except (fs.OffsiteError, OSError):
        result["action_required"] = ["inventory_unavailable"]
    return result


def _domain_readiness(target: Path, migration_revision: str | None) -> dict[str, Any]:
    """Fixed, capped structural inventory; no provider calls, payloads or values."""
    database = target / "healthcheck.db"
    fs.identity(database)
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise fs.OffsiteError("recovery_integrity_failed")
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        if revision != [(migration_revision,)]:
            raise fs.OffsiteError("recovery_revision_mismatch")
        # Capped scans cannot enumerate a multi-GiB provider history into output.
        domains = {}
        for table in (
            "measurement_sessions",
            "context_events",
            "raw_artifacts",
            "garmin_source_records",
            "google_source_records",
            "sync_stream_state",
        ):
            count = connection.execute(
                f"SELECT COUNT(*) FROM (SELECT 1 FROM {table} LIMIT 10001)"
            ).fetchone()[0]
            domains[table] = {"count": min(count, 10000), "capped": count > 10000}
        return {"integrity": "PASS", "migration_identity": "PASS", "domains": domains}
    finally:
        connection.close()


def _require_current_revision(revision: str | None) -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from healthcheck.runtime import _repository_root

    config = Config()
    config.set_main_option(
        "script_location", str(_repository_root() / "src" / "healthcheck" / "db" / "migrations")
    )
    if revision is None or ScriptDirectory.from_config(config).get_heads() != [revision]:
        raise fs.OffsiteError("recovery_runtime_revision_required")


def recover_backup(
    archive: Path,
    target: Path,
    staging: Path,
    executable: Path,
    identity: Path,
    *,
    expected_uuid: str,
    expected_sha256: str,
    staging_nonsynced: bool = False,
) -> dict[str, Any]:
    """Independent fingerprint + full authentication before a new-target restore.

    No auth/session inspection or refresh takes place. The supported application
    read smoke is a separate explicit follow-up on the recovered profile.
    """
    result = {
        "contract": CONTRACT,
        "status": "failed",
        "data_recovery": "not_started",
        "target_created": False,
        "provider_authorization": "reauthorization_required",
        "provider_refresh": "not_run",
        "application_read_smoke": "UNVERIFIED",
        "offsite_presence": "UNVERIFIED",
        "rehearsal": "UNVERIFIED",
    }
    try:
        archive, target, staging, executable, identity = (
            fs.absolute(p) for p in (archive, target, staging, executable, identity)
        )
        match = NAME.fullmatch(archive.name)
        if not match or expected_uuid != match[2] or not HASH.fullmatch(expected_sha256):
            raise fs.OffsiteError("independent_fingerprint_required")
        # Lexists semantics: dangling links are not an absent new target.
        if os.path.lexists(target):
            raise fs.OffsiteError("new_restore_target_required")
        with _environment(
            None,
            archive.parent,
            staging,
            executable,
            identity,
            nonsynced=staging_nonsynced,
            target=target,
        ):
            with fs.read_file(archive) as source:
                if _hash(source) != expected_sha256:
                    raise fs.OffsiteError("recovery_hash_mismatch")
                with tempfile.TemporaryDirectory(prefix="hc148-dr-", dir=staging) as temporary:
                    scratch = Path(temporary)
                    age = _Age(executable, identity, scratch)
                    plain = scratch / "recovery.zip"
                    age.decrypt(archive, plain)
                    verification = verify_backup(plain, scratch=scratch)
                    _require_current_revision(verification.migration_revision)
                    if os.path.lexists(target):
                        raise fs.OffsiteError("new_restore_target_required")
                    restore_profile(plain, target, scratch=scratch, require_new=True)
                    result["target_created"] = True
                    result["data_recovery"] = "restored_readiness_unverified"
                    result["readiness"] = _domain_readiness(target, verification.migration_revision)
                    if _hash(source) != expected_sha256:
                        raise fs.OffsiteError("recovery_archive_changed")
                    result.update(
                        status="succeeded", data_recovery="PASS", rehearsal="data_checks_passed"
                    )
    except (fs.OffsiteError, ProfileBackupError, OSError, sqlite3.Error) as exc:
        result["action_required"] = [
            str(exc) if isinstance(exc, fs.OffsiteError) else "recovery_failed"
        ]
    return result
