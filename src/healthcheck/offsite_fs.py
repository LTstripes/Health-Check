"""Fail-closed local Windows filesystem boundary for protected off-site IO.

Directory handles deny deletion/rename for the operation lifetime. Read handles
also deny writers; lstat/fstat identity and link-count checks bind every read.
No network filesystem, reparse entry, or PATH executable discovery is supported.
"""

from __future__ import annotations

import ctypes
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from healthcheck.runtime import _repository_root


class OffsiteError(ValueError):
    """Only a public, constant action code may escape this boundary."""


def absolute(value: Path | str) -> Path:
    path = Path(value)
    if not path.is_absolute() or any(":" in part for part in path.parts[1:]):
        raise OffsiteError("absolute_path_required")
    if str(path).startswith(("\\\\", "//")):
        raise OffsiteError("unsupported_filesystem")
    return Path(os.path.abspath(path))


def overlaps(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def outside_checkout(path: Path) -> None:
    if overlaps(path, _repository_root().resolve()):
        raise OffsiteError("checkout_overlap")


def identity(path: Path, *, directory: bool = False) -> os.stat_result:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise OffsiteError("unsafe_reparse")
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise OffsiteError("unsafe_directory")
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise OffsiteError("unsafe_file_identity")
    return info


def same(a: os.stat_result, b: os.stat_result) -> bool:
    return (a.st_dev, a.st_ino, a.st_nlink) == (b.st_dev, b.st_ino, b.st_nlink)


def require_ntfs(path: Path) -> None:
    if os.name != "nt":
        raise OffsiteError("unsupported_filesystem")
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetVolumePathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    api.GetVolumePathNameW.restype = wintypes.BOOL
    volume = ctypes.create_unicode_buffer(32768)
    if not api.GetVolumePathNameW(str(path), volume, len(volume)):
        raise OffsiteError("filesystem_unknown")
    api.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    api.GetDriveTypeW.restype = wintypes.UINT
    if api.GetDriveTypeW(volume.value) not in {2, 3}:  # removable or fixed, never remote
        raise OffsiteError("unsupported_filesystem")
    api.GetVolumeInformationW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    api.GetVolumeInformationW.restype = wintypes.BOOL
    fs = ctypes.create_unicode_buffer(64)
    if not api.GetVolumeInformationW(volume.value, None, 0, None, None, None, fs, len(fs)):
        raise OffsiteError("filesystem_unknown")
    if fs.value != "NTFS":
        raise OffsiteError("unsupported_filesystem")


def require_private(path: Path) -> None:
    """Reject allow ACEs for anyone beyond this user, SYSTEM and local admins.

    These privileged OS principals are inside the local-host trust boundary.
    Unsupported ACL forms and null DACLs are uncertainty, not private access.
    """
    if os.name != "nt":
        raise OffsiteError("private_context_required")
    from ctypes import wintypes

    from healthcheck.google.protection import _current_windows_user_sid

    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p
    adv.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        pointer,
        pointer,
        ctypes.POINTER(pointer),
        pointer,
        ctypes.POINTER(pointer),
    ]
    adv.GetNamedSecurityInfoW.restype = wintypes.DWORD
    adv.GetAclInformation.argtypes = [pointer, pointer, wintypes.DWORD, wintypes.DWORD]
    adv.GetAclInformation.restype = wintypes.BOOL
    adv.GetAce.argtypes = [pointer, wintypes.DWORD, ctypes.POINTER(pointer)]
    adv.GetAce.restype = wintypes.BOOL
    adv.ConvertSidToStringSidW.argtypes = [pointer, ctypes.POINTER(wintypes.LPWSTR)]
    adv.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [pointer]
    kernel.LocalFree.restype = pointer

    class ACLSize(ctypes.Structure):
        _fields_ = [("count", wintypes.DWORD), ("used", wintypes.DWORD), ("free", wintypes.DWORD)]

    descriptor, dacl = pointer(), pointer()
    if adv.GetNamedSecurityInfoW(
        str(path), 1, 4, None, None, ctypes.byref(dacl), None, ctypes.byref(descriptor)
    ):
        raise OffsiteError("private_context_required")
    try:
        if not dacl:
            raise OffsiteError("private_context_required")
        size = ACLSize()
        if not adv.GetAclInformation(dacl, ctypes.byref(size), ctypes.sizeof(size), 2):
            raise OffsiteError("private_context_required")
        allowed = {_current_windows_user_sid(), "S-1-5-18", "S-1-5-32-544"}
        for index in range(size.count):
            ace = pointer()
            if not adv.GetAce(dacl, index, ctypes.byref(ace)):
                raise OffsiteError("private_context_required")
            kind = ctypes.c_ubyte.from_address(ace.value).value
            if kind == 1:  # deny ACE cannot grant access
                continue
            if kind != 0:
                raise OffsiteError("private_context_required")
            sid = wintypes.LPWSTR()
            if not adv.ConvertSidToStringSidW(pointer(ace.value + 8), ctypes.byref(sid)):
                raise OffsiteError("private_context_required")
            try:
                if sid.value not in allowed:
                    raise OffsiteError("private_context_required")
            finally:
                kernel.LocalFree(ctypes.cast(sid, pointer))
    finally:
        kernel.LocalFree(descriptor)


def _windows_handle(
    path: Path, *, directory: bool, writable: bool = False, deletable: bool = False
) -> int:
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    api.CreateFileW.restype = wintypes.HANDLE
    access = 0x80000000  # GENERIC_READ: metadata-only directory opens do not pin renames
    if writable:
        access |= 0x40000000
    if deletable:
        access |= 0x00010000  # DELETE, for handle-bound retention only
    flags = 0x00200000 | (0x02000000 if directory else 0)  # no-follow + backup semantics
    share = 3 if directory or writable else 1  # never FILE_SHARE_DELETE
    handle = api.CreateFileW(str(path), access, share, None, 3, flags, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OffsiteError("file_access_failed")
    return handle


@contextmanager
def pin_directories(path: Path) -> Iterator[None]:
    """Pin every existing ancestor without following reparse entries."""
    opened: list[int] = []
    try:
        for parent in reversed((path, *path.parents)):
            before = identity(parent, directory=True)
            if os.name == "nt":
                handle = _windows_handle(parent, directory=True)
                opened.append(handle)
            if not same(before, identity(parent, directory=True)):
                raise OffsiteError("identity_changed")
        yield
    finally:
        if opened:
            from ctypes import wintypes

            api = ctypes.WinDLL("kernel32", use_last_error=True)
            api.CloseHandle.argtypes = [wintypes.HANDLE]
            api.CloseHandle.restype = wintypes.BOOL
            for handle in reversed(opened):
                api.CloseHandle(handle)


@contextmanager
def read_file(path: Path, *, writable: bool = False, deletable: bool = False) -> Iterator[BinaryIO]:
    before = identity(path)
    if os.name == "nt":
        import msvcrt

        handle = _windows_handle(path, directory=False, writable=writable, deletable=deletable)
        fd = msvcrt.open_osfhandle(handle, os.O_BINARY | (os.O_RDWR if writable else os.O_RDONLY))
    else:
        fd = os.open(path, (os.O_RDWR if writable else os.O_RDONLY) | os.O_NOFOLLOW)
    with os.fdopen(fd, "r+b" if writable else "rb") as stream:
        if not same(before, os.fstat(stream.fileno())):
            raise OffsiteError("identity_changed")
        yield stream
        if not deletable and not same(before, identity(path)):
            raise OffsiteError("identity_changed")


def retire_file(stream: BinaryIO) -> None:
    """Mark the opened, validated file for deletion without a path reopen race."""
    if os.name != "nt":
        raise OffsiteError("unsupported_filesystem")
    import msvcrt
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    api.SetFileInformationByHandle.restype = wintypes.BOOL
    disposition = ctypes.c_ubyte(1)  # FILE_DISPOSITION_INFO.DeleteFile
    if not api.SetFileInformationByHandle(
        msvcrt.get_osfhandle(stream.fileno()), 4, ctypes.byref(disposition), 1
    ):
        raise OffsiteError("retention_delete_failed")
