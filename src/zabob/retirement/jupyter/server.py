"""Find, start and stop the JupyterLab that serves the notebooks (#762).

A server is found through the files Jupyter itself writes to its runtime
folder, one per running server, matched on the folder it serves: so
`sim jupyter stop` finds a server however it was started, and nothing here
keeps a pid file of its own. Stopping goes through the server's HTTP API,
which works the same on Windows, where there are no signals to send.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from zabob.retirement.jupyter.config import JupyterMcpSettings, find_repo_root
from zabob.retirement.oscompat import WINDOWS, pid_alive
from zabob.retirement.user_config import data_dir_setting

START_TIMEOUT = 60.0  # seconds; a first start builds JupyterLab's caches


@dataclass(frozen=True)
class Server:
    """A running Jupyter server, from its runtime file."""

    url: str  # ends with "/"
    token: str
    root_dir: Path
    pid: int
    port: int

    def lab_url(self, notebook: str | None = None) -> str:
        """The page to open: JupyterLab, or ``notebook`` in it, with the token."""
        path = f"lab/tree/{quote(notebook)}" if notebook else "lab"
        return f"{self.url}{path}?token={self.token}" if self.token else f"{self.url}{path}"

    def info(self) -> dict[str, object]:
        """The runtime-file form jupyter_server's shutdown_server takes."""
        return {"url": self.url, "token": self.token, "pid": self.pid}


def root() -> Path:
    """Where the notebooks and .mcp.json are: the code checkout's top, or,
    installed (#662), the data repo's (the one `sim init`/`sim use`
    recorded, or $ANALYSIS_DATA_DIR's), where `sim init` copied the
    notebooks."""
    from zabob.retirement.resources import CHECKOUT_DIR

    if CHECKOUT_DIR is None and (data := data_dir_setting()):
        return Path(data).parent
    return find_repo_root()


def notebook_names(notebook_dir: Path) -> list[str]:
    """The notebooks under ``notebook_dir``, as paths relative to it."""
    if not notebook_dir.is_dir():
        return []
    return sorted(
        p.relative_to(notebook_dir).as_posix() for p in notebook_dir.rglob("*.ipynb")
        if ".ipynb_checkpoints" not in p.parts
    )


def _runtime_servers() -> Iterator[dict]:
    # Imported here: jupyter_server brings tornado and more, too slow for
    # every `sim` command's start (TAB completion runs it).
    from jupyter_server.serverapp import list_running_servers

    return list_running_servers()


def running() -> list[Server]:
    """Every Jupyter server this user runs."""
    for _ in range(3):
        try:
            return _read_servers()
        except OSError:
            # list_running_servers lists the runtime folder, then opens each
            # file: one whose server exits in between is gone. Read again.
            continue
    return _read_servers()


def _read_servers() -> list[Server]:
    found = []
    for info in _runtime_servers():
        try:
            found.append(Server(
                url=info["url"], token=info.get("token", ""),
                root_dir=Path(info.get("root_dir") or info["notebook_dir"]).resolve(),
                pid=int(info["pid"]), port=int(info["port"]),
            ))
        except (KeyError, TypeError, ValueError):
            continue  # some other tool's file, or an old server's
    return found


def serving(notebook_dir: Path) -> Server | None:
    """The server for ``notebook_dir``, if one is running."""
    target = notebook_dir.resolve()
    return next((s for s in running() if s.root_dir == target), None)


def lab_argv(settings: JupyterMcpSettings, notebook_dir: Path, port: int | None = None) -> list[str]:
    """JupyterLab's command line, before any extra arguments. Run as this
    Python's module, so no `jupyter` (or `jupyter.exe`) need be on PATH.
    A ``port`` asked for is that port or none: Jupyter would otherwise
    move to the next free one without a word."""
    return [
        sys.executable, "-m", "jupyterlab",
        f"--port={port or settings.port}",
        *(["--ServerApp.port_retries=0"] if port else []),
        f"--IdentityProvider.token={settings.token}",
        f"--notebook-dir={notebook_dir}",
    ]


# Windows: no console window of its own, and Ctrl+C in the terminal that
# started it doesn't reach it (CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP).
_DETACHED_FLAGS = 0x08000000 | 0x00000200 if WINDOWS else 0


class StartError(Exception):
    """The server exited, or didn't answer in time."""


def start(argv: list[str], log: Path, cwd: Path, root_dir: Path, *, timeout: float = START_TIMEOUT) -> Server:
    """Start ``argv``, a server for ``root_dir``, in the background, its
    output appended to ``log``, and return the server once its runtime file
    appears."""
    root_dir = root_dir.resolve()
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as out:
        # A header per start, so the tail an error shows begins at this one.
        out.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} starting JupyterLab ---\n".encode())
        out.flush()
        proc = subprocess.Popen(  # noqa: S603 - our own Python and arguments
            argv, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
            cwd=cwd, close_fds=True,
            # Outlives this command and the terminal it was typed in.
            start_new_session=not WINDOWS, creationflags=_DETACHED_FLAGS,
        )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # By pid, or by the folder it serves: on Windows a venv's python.exe
        # is a launcher that runs the real interpreter as its child, so the
        # runtime file holds the child's pid, not proc.pid.
        found = running()
        server = next((s for s in found if s.pid == proc.pid), None) or next(
            (s for s in found if s.root_dir == root_dir), None)
        if server is not None:
            # Left running on purpose and never waited for: a return code
            # keeps Popen from warning, when collected, that it still runs.
            proc.returncode = 0
            return server
        if proc.poll() is not None:
            raise StartError(f"JupyterLab exited (status {proc.returncode}) before it was ready")
        time.sleep(0.25)
    proc.returncode = 0  # still starting, perhaps; left to run, as above
    raise StartError(f"JupyterLab didn't answer within {timeout:.0f} seconds; it may still be starting")


def stop(server: Server, *, timeout: int = 5) -> bool:
    """Ask ``server`` to shut down (its kernels with it); if it doesn't,
    end its process. Returns whether it is gone."""
    from jupyter_server.serverapp import shutdown_server

    try:
        # On POSIX this falls back to SIGTERM, then SIGKILL, itself.
        if shutdown_server(server.info(), timeout=timeout):
            return True
    except Exception:  # noqa: BLE001, S110 - an unanswered request; end the process below
        pass
    if pid_alive(server.pid):
        # On Windows, os.kill with SIGTERM is TerminateProcess.
        with contextlib.suppress(OSError):  # it may exit on its own meanwhile
            os.kill(server.pid, signal.SIGTERM)
        for _ in range(timeout * 10):
            if not pid_alive(server.pid):
                break
            time.sleep(0.1)
    return not pid_alive(server.pid)


def log_tail(log: Path, lines: int = 15) -> str:
    """The last ``lines`` of ``log`` from its latest start, for an error
    message."""
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    latest = text.splitlines()
    starts = [i for i, line in enumerate(latest) if line.startswith("--- ") and "starting JupyterLab" in line]
    if starts:
        latest = latest[starts[-1] + 1:]
    return "\n".join(latest[-lines:])
