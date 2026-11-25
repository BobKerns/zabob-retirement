"""#687: advisory file locks that behave like ``flock`` on every platform.

The callers (``locks``, ``builder``, ``price_schedule``) rely on flock's
semantics: shared and exclusive locks, a non-blocking try that raises
:class:`BlockingIOError`, ownership by the open file (so a second open of the
same file in one process waits on the first), and release on close.

On Windows, ``LockFileEx`` has all of these. Its locks are mandatory for the
range they cover, though: a locked byte can't be read through another handle,
and ``lock_holder`` reads the holder's record from the locked file. So the
lock covers one byte far past any content, where nothing reads or writes.
"""

from __future__ import annotations

import os
import sys

__all__ = ["O_BINARY", "lock", "unlock"]

# os.open is text mode on Windows unless asked otherwise; a lock file's
# record is bytes.
O_BINARY: int = getattr(os, "O_BINARY", 0)

if sys.platform == "win32":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _LOCKFILE_FAIL_IMMEDIATELY = 0x1
    _LOCKFILE_EXCLUSIVE_LOCK = 0x2
    _ERROR_LOCK_VIOLATION = 33
    _ERROR_IO_PENDING = 997
    # Far past any lock file's content (2**62), so reads of the record
    # never touch the locked byte.
    _OFFSET_HIGH = 1 << 30

    class _Overlapped(ctypes.Structure):
        _fields_ = (
            ("Internal", ctypes.c_void_p),
            ("InternalHigh", ctypes.c_void_p),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        )

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _LockFileEx = _kernel32.LockFileEx
    _LockFileEx.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                            wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_Overlapped))
    _LockFileEx.restype = wintypes.BOOL
    _UnlockFileEx = _kernel32.UnlockFileEx
    _UnlockFileEx.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                              wintypes.DWORD, ctypes.POINTER(_Overlapped))
    _UnlockFileEx.restype = wintypes.BOOL

    def _overlapped() -> _Overlapped:
        return _Overlapped(Offset=0, OffsetHigh=_OFFSET_HIGH)

    def lock(fd: int, *, shared: bool = False, block: bool = True) -> None:
        """Lock ``fd``'s file; without ``block``, raise BlockingIOError if
        another open file holds a conflicting lock."""
        flags = (0 if shared else _LOCKFILE_EXCLUSIVE_LOCK) | (0 if block else _LOCKFILE_FAIL_IMMEDIATELY)
        handle = msvcrt.get_osfhandle(fd)
        if not _LockFileEx(handle, flags, 0, 1, 0, ctypes.byref(_overlapped())):
            error = ctypes.get_last_error()
            if error in (_ERROR_LOCK_VIOLATION, _ERROR_IO_PENDING):
                raise BlockingIOError(error, "file is locked")
            raise ctypes.WinError(error)

    def unlock(fd: int) -> None:
        """Release ``fd``'s lock (closing ``fd`` releases it too)."""
        handle = msvcrt.get_osfhandle(fd)
        if not _UnlockFileEx(handle, 0, 1, 0, ctypes.byref(_overlapped())):
            raise ctypes.WinError(ctypes.get_last_error())

else:
    import fcntl

    def lock(fd: int, *, shared: bool = False, block: bool = True) -> None:
        """Lock ``fd``'s file; without ``block``, raise BlockingIOError if
        another open file holds a conflicting lock."""
        fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | (0 if block else fcntl.LOCK_NB))

    def unlock(fd: int) -> None:
        """Release ``fd``'s lock (closing ``fd`` releases it too)."""
        fcntl.flock(fd, fcntl.LOCK_UN)
