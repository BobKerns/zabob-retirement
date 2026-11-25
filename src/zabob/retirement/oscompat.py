"""#687: the few things macOS, Linux and Windows do differently, in one place."""

from __future__ import annotations

import getpass
import os
import signal
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

__all__ = ["WINDOWS", "is_link", "kill_tree", "link_dir", "login_name", "pid_alive", "remove_link", "start_tree",
           "utf8_stdio"]

WINDOWS = sys.platform == "win32"


def login_name(default: str = "unknown") -> str:
    """The login name ($USER on POSIX, %USERNAME% on Windows), else ``default``."""
    try:
        return getpass.getuser() or default
    except OSError:  # no user in the environment or the password database
        return default


def link_dir(link: Path, target: Path) -> None:
    """Make ``link`` a symlink to the folder ``target``. On Windows, where a
    symlink needs Developer Mode or an administrator, fall back to a directory
    junction, which needs neither; both read as the folder they point at."""
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if not WINDOWS:
            raise
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(Path(target).resolve())],
                              capture_output=True, text=True, check=False)
        if done.returncode:
            raise OSError(f"could not link {link} to {target}: {done.stderr.strip() or done.stdout.strip()}") \
                from None


def is_link(path: Path) -> bool:
    """Whether ``path`` is a symlink or (on Windows) a junction."""
    return path.is_symlink() or path.is_junction()


def remove_link(path: Path) -> None:
    """Remove the link at ``path`` without touching what it points at."""
    if path.is_junction():
        os.rmdir(path)  # a junction is removed as an empty folder
    else:
        path.unlink()



def _kernel32():  # noqa: ANN202 - a ctypes.WinDLL, which exists only on Windows
    """kernel32, with the types of the calls used here declared: ctypes
    would otherwise pass a pointer-sized HANDLE as a 32-bit int."""
    assert sys.platform == "win32"  # and so the checker knows it
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    for name, restype, argtypes in (
        ("OpenProcess", wintypes.HANDLE, (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)),
        ("GetExitCodeProcess", wintypes.BOOL, (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))),
        ("CloseHandle", wintypes.BOOL, (wintypes.HANDLE,)),
        ("CreateJobObjectW", wintypes.HANDLE, (ctypes.c_void_p, wintypes.LPCWSTR)),
        ("SetInformationJobObject", wintypes.BOOL,
         (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)),
        ("AssignProcessToJobObject", wintypes.BOOL, (wintypes.HANDLE, wintypes.HANDLE)),
        ("TerminateJobObject", wintypes.BOOL, (wintypes.HANDLE, wintypes.UINT)),
    ):
        function = getattr(kernel32, name)
        function.restype = restype
        function.argtypes = argtypes
    return kernel32


# Windows: the Job Object each process start_tree started is in, by pid.
_JOBS: dict[int, int] = {}


def start_tree(command: Sequence[str], **kwargs: Any) -> subprocess.Popen:
    """``subprocess.Popen(command, **kwargs)``, so that :func:`kill_tree`
    can later stop it and whatever it starts, even once it has exited. On
    POSIX that is its own process group; on Windows, which has none, a Job
    Object, which (unlike ``taskkill /T``) still holds the children after
    their parent is gone."""
    if not WINDOWS:
        return subprocess.Popen(command, start_new_session=True, **kwargs)
    proc = subprocess.Popen(command, **kwargs)
    try:
        _JOBS[proc.pid] = _job_for(proc.pid)
    except OSError:
        pass  # kill_tree falls back to taskkill /T
    return proc


def _job_for(pid: int) -> int:
    assert sys.platform == "win32"
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32 = _kernel32()
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    # Closing the last handle (this process exiting, say) ends the job too.
    info = _Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    process = kernel32.OpenProcess(0x0100 | 0x0001, False, pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
    try:
        if not (process and kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
                and kernel32.AssignProcessToJobObject(job, process)):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise ctypes.WinError(error)
    finally:
        if process:
            kernel32.CloseHandle(process)
    return job


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill ``proc``, started by :func:`start_tree`, and whatever it started."""
    # Not skipped once proc has exited: a child it started may still hold
    # its output open, and on POSIX the group outlives its leader.
    if WINDOWS:
        job = _JOBS.pop(proc.pid, None)
        if job is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)
            return
        kernel32 = _kernel32()
        kernel32.TerminateJobObject(job, 1)
        kernel32.CloseHandle(job)
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def pid_alive(pid: int) -> bool:
    """Whether process ``pid`` is running. Not ``os.kill(pid, 0)`` on
    Windows, where any signal but the console ones terminates the process."""
    if WINDOWS:
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = _kernel32()
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            # Access denied means it exists, as someone else's.
            return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # someone else's, but there
    return True


def utf8_stdio() -> None:
    """Write UTF-8 to a pipe or a file on Windows, as everywhere else. A
    console gets Unicode from Python whatever this says, but a redirect
    (``sim report income > out.txt``) gets the ANSI code page, cp1252,
    which has no box-drawing characters for a table at all."""
    if not WINDOWS:
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None and (getattr(stream, "encoding", "") or "").lower().replace("-", "") != "utf8":
            reconfigure(encoding="utf-8")
