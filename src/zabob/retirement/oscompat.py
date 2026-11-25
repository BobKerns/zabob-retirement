"""#687: the few things macOS, Linux and Windows do differently, in one place."""

from __future__ import annotations

import getpass
import os
import signal
import subprocess
import sys
from pathlib import Path

__all__ = ["WINDOWS", "is_link", "kill_tree", "link_dir", "login_name", "pid_alive", "remove_link", "utf8_stdio"]

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



def kill_tree(proc: subprocess.Popen) -> None:
    """Kill ``proc`` and whatever it started. On POSIX it must have been
    started with ``start_new_session=True`` (its own process group); Windows
    has no process groups, so ``taskkill /T`` walks its children instead."""
    # Not skipped once proc has exited: a child it started may still hold
    # its output open, and on POSIX the group outlives its leader.
    if WINDOWS:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)
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

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            # Access denied means it exists, as someone else's.
            return ctypes.get_last_error() == 5
        try:
            code = ctypes.c_ulong()
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
