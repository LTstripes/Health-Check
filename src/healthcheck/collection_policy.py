"""Explicit, reversible Owner collection policy for selected streams.

Persistent collection intent lives in one profile-root JSON document that only
the supported Owner operation writes. Reads are side-effect free, and a missing
file is legacy behavior rather than an inferred opt-out.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.exc import SQLAlchemyError

from healthcheck.config import Settings
from healthcheck.db.engine import database_readiness
from healthcheck.external_runtime_lock import (
    ExternalRuntimeOperationBusyError,
    ExternalRuntimeOperationLock,
    ExternalRuntimeOperationLockError,
)
from healthcheck.runtime import RuntimePaths, resolve_runtime_paths

COLLECTION_POLICY_FILENAME = "collection-policy.json"
COLLECTION_POLICY_CONTRACT_VERSION = "healthcheck-collection-policy-v1"
COLLECTION_POLICY_PROVENANCE = "owner-explicit"
ALLOWED_DISABLED_SCOPES = frozenset({"google:heart_rate"})
MAX_POLICY_BYTES = 64 * 1024
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_SEMANTIC_KEYS = frozenset(
    {
        "contract_version",
        "provenance",
        "revision",
        "updated_at_utc",
        "disabled_streams",
    }
)


class CollectionPolicyStatus(StrEnum):
    """Typed outcome of one side-effect-free policy read."""

    ABSENT = "absent"
    VALID = "valid"
    INVALID = "invalid"
    UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class CollectionPolicySnapshot:
    """Strict v1 semantic payload plus a derived local content hash."""

    contract_version: str
    provenance: str
    revision: int
    updated_at_utc: datetime
    disabled_streams: tuple[str, ...]
    content_sha256: str


@dataclass(frozen=True, slots=True)
class CollectionPolicyResolution:
    """One resolved policy read, including honest uncertainty states."""

    status: CollectionPolicyStatus
    snapshot: CollectionPolicySnapshot | None = None
    problem_code: str | None = None


@dataclass(frozen=True, slots=True)
class CollectionPolicyUpdate:
    """Result of one supported Owner policy update."""

    changed: bool
    previous_revision: int | None
    policy: CollectionPolicySnapshot


class CollectionPolicyError(ValueError):
    """Base error carrying one allowlisted error code."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class CollectionPolicyRuntimeError(CollectionPolicyError):
    """The target profile is not an established external runtime."""


class CollectionPolicyBusyError(CollectionPolicyError):
    """Another supported operation currently owns the runtime lock."""


class CollectionPolicyUpdateError(CollectionPolicyError):
    """A supported policy update could not be completed."""


def collection_policy_path(paths: RuntimePaths) -> Path:
    return paths.root / COLLECTION_POLICY_FILENAME


def resolve_profile_collection_policy(settings: Settings) -> CollectionPolicyResolution:
    """Resolve the profile policy without creating or modifying any path."""

    return resolve_collection_policy(collection_policy_path(resolve_runtime_paths(settings)))


def resolve_collection_policy(path: Path) -> CollectionPolicyResolution:
    """Read one policy document without any filesystem side effects."""

    try:
        if not path.exists():
            return CollectionPolicyResolution(status=CollectionPolicyStatus.ABSENT)
        raw = path.read_bytes()
    except OSError:
        return CollectionPolicyResolution(
            status=CollectionPolicyStatus.UNREADABLE, problem_code="read_error"
        )
    if len(raw) > MAX_POLICY_BYTES:
        return CollectionPolicyResolution(
            status=CollectionPolicyStatus.INVALID, problem_code="oversize"
        )
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except ValueError:
        return CollectionPolicyResolution(
            status=CollectionPolicyStatus.INVALID, problem_code="invalid_json"
        )
    return _validated_resolution(payload)


def project_collection_policy_resolution(
    resolution: CollectionPolicyResolution,
) -> dict[str, Any]:
    """Return the allowlisted compact projection of one policy resolution."""

    if resolution.status is CollectionPolicyStatus.VALID and resolution.snapshot is not None:
        return {
            "status": resolution.status.value,
            "contract_version": resolution.snapshot.contract_version,
            "revision": resolution.snapshot.revision,
        }
    if resolution.status is CollectionPolicyStatus.ABSENT:
        return {"status": resolution.status.value}
    return {"status": resolution.status.value, "problem_code": resolution.problem_code}


def set_collection_policy(
    settings: Settings,
    *,
    stream: str,
    state: Literal["on", "off"],
    expected_revision: int | None = None,
) -> CollectionPolicyUpdate:
    """Apply one explicit Owner policy change under the shared operation lock."""

    if stream not in ALLOWED_DISABLED_SCOPES:
        raise CollectionPolicyUpdateError("unsupported_policy_stream")
    if state not in {"on", "off"}:
        raise CollectionPolicyUpdateError("invalid_policy_state")
    if expected_revision is not None and (
        type(expected_revision) is not int or expected_revision < 1
    ):
        raise CollectionPolicyUpdateError("invalid_expected_revision")
    paths = _require_established_runtime(settings)
    try:
        with ExternalRuntimeOperationLock(paths, allow_reentrant=False):
            return _update_locked(
                collection_policy_path(paths),
                stream=stream,
                state=state,
                expected_revision=expected_revision,
            )
    except ExternalRuntimeOperationBusyError as exc:
        raise CollectionPolicyBusyError("collection_policy_busy") from exc
    except ExternalRuntimeOperationLockError as exc:
        raise CollectionPolicyRuntimeError("runtime_lock_unavailable") from exc


def _update_locked(
    path: Path,
    *,
    stream: str,
    state: Literal["on", "off"],
    expected_revision: int | None,
) -> CollectionPolicyUpdate:
    current = resolve_collection_policy(path)
    if current.status is CollectionPolicyStatus.UNREADABLE:
        raise CollectionPolicyUpdateError("collection_policy_unreadable")
    if current.status is CollectionPolicyStatus.INVALID:
        raise CollectionPolicyUpdateError("collection_policy_invalid")
    previous = current.snapshot
    if expected_revision is not None and (
        previous is None or previous.revision != expected_revision
    ):
        raise CollectionPolicyUpdateError("collection_policy_revision_conflict")
    existing = previous.disabled_streams if previous is not None else ()
    if state == "off":
        desired = tuple(sorted({*existing, stream}))
    else:
        desired = tuple(item for item in existing if item != stream)
    if previous is not None and desired == previous.disabled_streams:
        return CollectionPolicyUpdate(
            changed=False, previous_revision=previous.revision, policy=previous
        )
    revision = previous.revision + 1 if previous is not None else 1
    updated_at = datetime.now(UTC).replace(microsecond=0)
    snapshot = CollectionPolicySnapshot(
        contract_version=COLLECTION_POLICY_CONTRACT_VERSION,
        provenance=COLLECTION_POLICY_PROVENANCE,
        revision=revision,
        updated_at_utc=updated_at,
        disabled_streams=desired,
        content_sha256=_content_sha256(
            COLLECTION_POLICY_CONTRACT_VERSION,
            COLLECTION_POLICY_PROVENANCE,
            revision,
            updated_at,
            desired,
        ),
    )
    _atomic_replace_with_readback(path, _serialize(snapshot), snapshot)
    return CollectionPolicyUpdate(
        changed=True,
        previous_revision=previous.revision if previous is not None else None,
        policy=snapshot,
    )


def _require_established_runtime(settings: Settings) -> RuntimePaths:
    """Fail closed unless the target is an already-established profile.

    Mirrors ``owner_refresh.require_established_runtime`` without importing the
    owner-refresh module (it depends on this one).
    """

    paths = resolve_runtime_paths(settings)
    if not paths.root.is_dir():
        raise CollectionPolicyRuntimeError("runtime_missing")
    if not paths.config.is_file() or not paths.database.is_file():
        raise CollectionPolicyRuntimeError("runtime_not_established")
    try:
        readiness = database_readiness(paths)
    except (OSError, SQLAlchemyError) as exc:
        raise CollectionPolicyRuntimeError("runtime_not_established") from exc
    if not readiness["ready"]:
        raise CollectionPolicyRuntimeError("runtime_not_established")
    return paths


def _validated_resolution(payload: Any) -> CollectionPolicyResolution:
    def invalid(problem_code: str) -> CollectionPolicyResolution:
        return CollectionPolicyResolution(
            status=CollectionPolicyStatus.INVALID, problem_code=problem_code
        )

    if not isinstance(payload, dict) or set(payload) != _SEMANTIC_KEYS:
        return invalid("invalid_shape")
    if payload["contract_version"] != COLLECTION_POLICY_CONTRACT_VERSION:
        return invalid("invalid_contract_version")
    if payload["provenance"] != COLLECTION_POLICY_PROVENANCE:
        return invalid("invalid_provenance")
    revision = payload["revision"]
    if type(revision) is not int or revision < 1:
        return invalid("invalid_revision")
    timestamp = payload["updated_at_utc"]
    if not isinstance(timestamp, str) or not _timestamp_is_strict(timestamp):
        return invalid("invalid_updated_at")
    disabled = payload["disabled_streams"]
    if (
        not isinstance(disabled, list)
        or any(not isinstance(item, str) for item in disabled)
        or len(disabled) != len(set(disabled))
        or disabled != sorted(disabled)
        or set(disabled) - ALLOWED_DISABLED_SCOPES
    ):
        return invalid("invalid_disabled_streams")
    updated_at = datetime.strptime(timestamp, _TIMESTAMP_FORMAT).replace(tzinfo=UTC)
    disabled_streams = tuple(disabled)
    snapshot = CollectionPolicySnapshot(
        contract_version=COLLECTION_POLICY_CONTRACT_VERSION,
        provenance=COLLECTION_POLICY_PROVENANCE,
        revision=revision,
        updated_at_utc=updated_at,
        disabled_streams=disabled_streams,
        content_sha256=_content_sha256(
            COLLECTION_POLICY_CONTRACT_VERSION,
            COLLECTION_POLICY_PROVENANCE,
            revision,
            updated_at,
            disabled_streams,
        ),
    )
    return CollectionPolicyResolution(
        status=CollectionPolicyStatus.VALID, snapshot=snapshot
    )


def _serialize(snapshot: CollectionPolicySnapshot) -> str:
    payload = _semantic_payload(snapshot)
    text = json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    if json.loads(text) != payload:
        raise CollectionPolicyUpdateError("policy_serialization_failed")
    return text


def _semantic_payload(snapshot: CollectionPolicySnapshot) -> dict[str, Any]:
    return {
        "contract_version": snapshot.contract_version,
        "provenance": snapshot.provenance,
        "revision": snapshot.revision,
        "updated_at_utc": format_policy_timestamp(snapshot.updated_at_utc),
        "disabled_streams": list(snapshot.disabled_streams),
    }


def _content_sha256(
    contract_version: str,
    provenance: str,
    revision: int,
    updated_at: datetime,
    disabled_streams: tuple[str, ...],
) -> str:
    payload = {
        "contract_version": contract_version,
        "provenance": provenance,
        "revision": revision,
        "updated_at_utc": format_policy_timestamp(updated_at),
        "disabled_streams": list(disabled_streams),
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return sha256(encoded).hexdigest()


def format_policy_timestamp(value: datetime) -> str:
    """Render the canonical strict UTC policy timestamp."""

    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _timestamp_is_strict(value: str) -> bool:
    if len(value) != 20 or value[10] != "T" or value[19] != "Z":
        return False
    try:
        datetime.strptime(value, _TIMESTAMP_FORMAT)
    except ValueError:
        return False
    return True


def _atomic_replace_with_readback(
    path: Path, text: str, expected: CollectionPolicySnapshot
) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        _remove_quietly(temporary)
        raise CollectionPolicyUpdateError("policy_write_failed") from exc
    read_back = resolve_collection_policy(path)
    if (
        read_back.status is not CollectionPolicyStatus.VALID
        or read_back.snapshot is None
        or read_back.snapshot.content_sha256 != expected.content_sha256
    ):
        raise CollectionPolicyUpdateError("policy_readback_mismatch")


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"unsupported JSON constant {value!r}")


__all__ = [
    "ALLOWED_DISABLED_SCOPES",
    "COLLECTION_POLICY_CONTRACT_VERSION",
    "COLLECTION_POLICY_FILENAME",
    "COLLECTION_POLICY_PROVENANCE",
    "CollectionPolicyBusyError",
    "CollectionPolicyError",
    "CollectionPolicyResolution",
    "CollectionPolicyRuntimeError",
    "CollectionPolicySnapshot",
    "CollectionPolicyStatus",
    "CollectionPolicyUpdate",
    "CollectionPolicyUpdateError",
    "collection_policy_path",
    "format_policy_timestamp",
    "project_collection_policy_resolution",
    "resolve_collection_policy",
    "resolve_profile_collection_policy",
    "set_collection_policy",
]
