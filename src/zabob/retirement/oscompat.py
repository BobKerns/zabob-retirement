"""#687: the few things macOS, Linux and Windows do differently, in one place."""

from __future__ import annotations

import contextlib
import getpass
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Generator, Sequence
from pathlib import Path
from typing import Any

__all__ = ["BIN_DIR", "WINDOWS", "enable_vt_output", "is_link", "kill_tree", "link_dir", "login_name", "open_file",
           "pid_alive", "program", "release_tree", "remove_link", "rerun_with_console", "start_detached", "start_tree",
           "utf8_stdio", "vt_console"]

WINDOWS = sys.platform == "win32"

BIN_DIR = "Scripts" if WINDOWS else "bin"
"""A virtual environment's folder of programs: ``.venv/bin``, or ``.venv\\Scripts``."""

# Windows process creation flags (#748).
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000
_CREATE_NO_WINDOW = 0x08000000


def program(folder: Path, name: str) -> Path:
    """The program ``name`` in ``folder`` (a venv's :data:`BIN_DIR`, say):
    ``sim``, or on Windows ``sim.exe``."""
    return folder / (f"{name}.exe" if WINDOWS else name)


def start_detached(command: Sequence[str], **kwargs: Any) -> subprocess.Popen:
    """``subprocess.Popen(command, **kwargs)`` for a process that outlives
    whoever started it: its own session on POSIX. On Windows (#748) it gets
    a console with no window, which what it starts shares (so no git or
    build flashes one), its own process group (Ctrl+C in the terminal that
    started it doesn't reach it), and leaves the starter's Job Object where
    that allows it: a scheduled task's, or a :func:`start_tree` parent's,
    would otherwise end it with them."""
    if not WINDOWS:
        return subprocess.Popen(command, start_new_session=True, **kwargs)
    flags = kwargs.pop("creationflags", 0) | _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen(command, creationflags=flags | _CREATE_BREAKAWAY_FROM_JOB, **kwargs)
    except PermissionError:
        # A job that forbids breaking away: start it inside, as the best there is.
        return subprocess.Popen(command, creationflags=flags, **kwargs)


def rerun_with_console() -> None:
    """On Windows, when this process is ``pythonw`` (no console, so
    ``sys.stdout`` is None), run the same command again under ``python``
    with a console that has no window, and exit with its status; otherwise
    return. A scheduled task runs ``pythonw`` so no window opens each hour,
    but every console program it started (git, a build) would open one of
    its own; under a windowless console they share it instead (#748)."""
    if not WINDOWS or sys.stdout is not None:
        return
    python = Path(sys.executable).with_name("python.exe")
    if not python.exists():
        return
    done = subprocess.run([str(python), *sys.orig_argv[1:]], stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          creationflags=_CREATE_NO_WINDOW, check=False)
    raise SystemExit(done.returncode)


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
    their parent is gone. The process starts suspended and is resumed once
    it is in the job."""
    if not WINDOWS:
        return subprocess.Popen(command, start_new_session=True, **kwargs)
    # Suspended until it is in the job, so nothing it starts (a .cmd shim's
    # node, say) can begin outside it.
    flags = kwargs.pop("creationflags", 0) | 0x00000004  # CREATE_SUSPENDED
    proc = subprocess.Popen(command, creationflags=flags, **kwargs)
    try:
        _JOBS[proc.pid] = _job_for(proc.pid)
    except OSError:
        pass  # kill_tree falls back to taskkill /T
    finally:
        try:
            _resume(proc.pid)
        except OSError:
            proc.kill()
            raise
    return proc


def _resume(pid: int) -> None:
    """Resume a process started suspended. Popen keeps no handle on its
    thread, so the whole process, as Process Explorer's Resume does."""
    assert sys.platform == "win32"
    import ctypes
    from ctypes import wintypes

    kernel32 = _kernel32()
    ntdll = ctypes.WinDLL("ntdll")
    ntdll.NtResumeProcess.restype = ctypes.c_long
    ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
    process = kernel32.OpenProcess(0x0800, False, pid)  # PROCESS_SUSPEND_RESUME
    if not process:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if status := ntdll.NtResumeProcess(process):
            raise OSError(f"NtResumeProcess failed: NTSTATUS {status & 0xFFFFFFFF:#010x}")
    finally:
        kernel32.CloseHandle(process)


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
    # A process may still leave it by asking to (start_detached's daemon,
    # #748); one that doesn't ask stays in, as every child does by default.
    info = _Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000 | 0x0800  # KILL_ON_JOB_CLOSE | BREAKAWAY_OK
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
        # And by the tree, in case anything left the job (a child started
        # with CREATE_BREAKAWAY_FROM_JOB): harmless when the root is gone.
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def release_tree(proc: subprocess.Popen) -> None:
    """Once ``proc``, started by :func:`start_tree`, has exited on its own:
    on Windows, close its Job Object, which ends anything of its still
    running; elsewhere nothing. A long-lived starter (the builder's daemon)
    would otherwise keep a handle per process it ever started."""
    if WINDOWS and (job := _JOBS.pop(proc.pid, None)) is not None:
        _kernel32().CloseHandle(job)


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


# Console modes (SetConsoleMode). Output: interpret escape sequences rather
# than print them. Input: hand the terminal's escape-sequence replies through
# as characters, rather than line by line with echo.
_ENABLE_PROCESSED_OUTPUT = 0x0001
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_ENABLE_LINE_INPUT = 0x0002
_ENABLE_ECHO_INPUT = 0x0004
_ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
_STD_INPUT_HANDLE = -10
_STD_OUTPUT_HANDLE = -11


def _console_mode(kernel32: Any, which: int) -> tuple[Any, int] | None:
    """The console handle ``which`` names and its mode, or ``None`` when it
    isn't a console (redirected)."""
    import ctypes
    from ctypes import wintypes

    handle = kernel32.GetStdHandle(which)
    mode = wintypes.DWORD()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        return None
    return handle, mode.value


def _console_kernel32() -> Any:
    assert sys.platform == "win32"  # and so the checker knows it
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetStdHandle.restype = wintypes.HANDLE
    kernel32.GetStdHandle.argtypes = (wintypes.DWORD,)
    kernel32.GetConsoleMode.restype = wintypes.BOOL
    kernel32.GetConsoleMode.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.SetConsoleMode.restype = wintypes.BOOL
    kernel32.SetConsoleMode.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    return kernel32


def enable_vt_output() -> bool:
    """Have the Windows console pass escape sequences (colors, images) to
    the terminal instead of printing them, as every program that writes them
    does; left on, as they do. Whether output takes them: always true off
    Windows, false when the output isn't a console."""
    if not WINDOWS:
        return True
    kernel32 = _console_kernel32()
    console = _console_mode(kernel32, _STD_OUTPUT_HANDLE & 0xFFFFFFFF)
    if console is None:
        return False
    handle, mode = console
    wanted = mode | _ENABLE_PROCESSED_OUTPUT | _ENABLE_VIRTUAL_TERMINAL_PROCESSING
    return wanted == mode or bool(kernel32.SetConsoleMode(handle, wanted))


@contextlib.contextmanager
def vt_console() -> Generator[None]:
    """On Windows, the console set for asking the terminal a question:
    escape sequences out, and the reply in as characters, not echoed and not
    waiting for Enter. The input mode comes back as it was afterwards.
    Raises ``OSError`` when there is no console to ask."""
    kernel32 = _console_kernel32()
    if not enable_vt_output():
        raise OSError("the output isn't a console")
    console = _console_mode(kernel32, _STD_INPUT_HANDLE & 0xFFFFFFFF)
    if console is None:
        raise OSError("the input isn't a console")
    handle, saved = console
    mode = (saved | _ENABLE_VIRTUAL_TERMINAL_INPUT) & ~(_ENABLE_LINE_INPUT | _ENABLE_ECHO_INPUT)
    if not kernel32.SetConsoleMode(handle, mode):
        raise OSError("couldn't set the console's input mode")
    try:
        yield
    finally:
        kernel32.SetConsoleMode(handle, saved)


def open_file(path: Path) -> bool:
    """Open ``path`` in the program the desktop opens its kind of file with,
    without waiting for it. Whether something took it: false where there is
    no opener (Linux without ``xdg-open``), or it failed to start."""
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - the user's own chart, in their own viewer
            return True
        opener = "open" if sys.platform == "darwin" else shutil.which("xdg-open")
        if opener is None:
            return False
        subprocess.Popen([opener, str(path)], stdin=subprocess.DEVNULL,  # noqa: S603
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return False
    return True
