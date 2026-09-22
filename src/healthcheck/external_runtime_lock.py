"""Shared cross-process lock for external-runtime sync operations."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from healthcheck.runtime import RuntimePaths

EXTERNAL_RUNTIME_LOCK_FILENAME = ".external-runtime-operation.lock"


class ExternalRuntimeOperationLockError(RuntimeError):
    """The external-runtime operation lock could not be opened or used."""


class ExternalRuntimeOperationBusyError(RuntimeError):
    """Another supported operation currently owns the runtime lock."""


@dataclass(slots=True)
class _HeldLock:
    handle: object
    depth: int = 1


_thread_state = threading.local()


def _held_locks() -> dict[Path, _HeldLock]:
    locks = getattr(_thread_state, "locks", None)
    if locks is None:
        locks = {}
        _thread_state.locks = locks
    return locks


def _lock_file(handle: object) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle: object) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ExternalRuntimeOperationLock:
    """Non-blocking, thread-aware process lock for one runtime profile.

    Reentrancy is limited to the current thread so public wrapper operations can
    hold the lock across nested provider helpers without allowing unrelated
    operations in another thread or process to overlap.
    """

    busy_error_type = ExternalRuntimeOperationBusyError
    lock_error_type = ExternalRuntimeOperationLockError

    def __init__(self, paths: RuntimePaths, *, allow_reentrant: bool = True) -> None:
        self.path = paths.root / EXTERNAL_RUNTIME_LOCK_FILENAME
        self.allow_reentrant = allow_reentrant
        self._entered = False

    def __enter__(self) -> ExternalRuntimeOperationLock:
        key = self.path.resolve()
        locks = _held_locks()
        held = locks.get(key)
        if held is not None:
            if not self.allow_reentrant:
                raise self.busy_error_type
            held.depth += 1
            self._entered = True
            return self

        try:
            handle = self.path.open("a+b")
        except OSError as exc:
            raise self.lock_error_type from exc

        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            _lock_file(handle)
        except (ImportError, OSError) as exc:
            handle.close()
            raise self.busy_error_type from exc

        locks[key] = _HeldLock(handle=handle)
        self._entered = True
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if not self._entered:
            return
        key = self.path.resolve()
        locks = _held_locks()
        held = locks.get(key)
        self._entered = False
        if held is None:
            return
        held.depth -= 1
        if held.depth > 0:
            return
        try:
            _unlock_file(held.handle)
        finally:
            held.handle.close()
            del locks[key]


__all__ = [
    "EXTERNAL_RUNTIME_LOCK_FILENAME",
    "ExternalRuntimeOperationBusyError",
    "ExternalRuntimeOperationLock",
    "ExternalRuntimeOperationLockError",
]
