"""``sim jupyter hub`` and ``sim jupyter user`` (#766): one JupyterHub for a
household, each login with their own JupyterLab.

Each user either shares a data repo with others (``shared``: the same
folder, so the same CSVs and the same ``state/``) or has their own clone in
their home folder (``own``), kept in step with the others by git. Which is a
setting per user, in ``users.toml`` in the hub folder. The hub reads it at
every login and spawn, so a change needs no restart.

The hub folder is ``$ZABOB_HUB_DIR``, else ``hub/`` beside the user's
``config.toml`` (``user_config.config_path``). Its ``run/`` holds what the
hub writes: its database, cookie secret, pid file and log.

Logging in as another login and starting their JupyterLab as them needs
root, so for a household the hub runs as a system service
(``sim jupyter hub service``). Run by anyone else, only its own login can
log in. Linux and macOS only: JupyterHub's local logins and processes are
POSIX ones.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from zabob.retirement.oscompat import WINDOWS, pid_alive
from zabob.retirement.user_config import config_path

__all__ = [
    "DEFAULT_IP", "DEFAULT_PORT", "HUB_DIR_ENV", "OWN_REPO_NAME", "SERVICE_NAME", "HubError", "HubUser",
    "Settings", "config_file", "delete_user", "home_of", "hub_dir", "hub_pid", "launchd_plist", "logins",
    "own_repo", "read_settings", "read_users", "run_dir", "service_path", "start", "stop", "systemd_unit",
    "write_settings", "write_user",
]

HUB_DIR_ENV = "ZABOB_HUB_DIR"
DEFAULT_IP = "127.0.0.1"
DEFAULT_PORT = 8000
# An own data repo is the folder `sim init` makes by default, in that login's home.
OWN_REPO_NAME = "zabob-retirement"
SERVICE_NAME = "zabob-retirement-hub"
_LAUNCHD_LABEL = "org.zabob-retirement.hub"
SHARED, OWN = "shared", "own"


class HubError(Exception):
    """Something the hub commands can't do, said for the user."""


@dataclass(frozen=True)
class HubUser:
    """One login's setting: which data repo their JupyterLab works on."""

    name: str
    data: str  # SHARED or OWN
    repo: Path
    url: str | None = None  # OWN: what to clone when the repo isn't there yet

    def describe(self) -> str:
        if self.data == SHARED:
            return f"{self.name}: shares {self.repo}"
        source = f", cloned from {self.url}" if self.url else ""
        return f"{self.name}: own data repo {self.repo}{source}"


@dataclass(frozen=True)
class Settings:
    """Where the hub listens."""

    ip: str = DEFAULT_IP
    port: int = DEFAULT_PORT

    @property
    def url(self) -> str:
        host = self.ip if self.ip not in ("", "0.0.0.0", "::") else "localhost"  # noqa: S104 - a bind address, not a bind
        return f"http://{host}:{self.port}/"


def _require_posix() -> None:
    if WINDOWS:
        raise HubError("the hub runs on Linux and macOS; on Windows, use `sim jupyter start`")


def hub_dir() -> Path:
    """The hub's folder: ``$ZABOB_HUB_DIR``, else ``hub/`` beside
    ``config.toml``: that of whoever ran sudo, under sudo, so
    `sudo sim jupyter hub service --install` points the service at the
    users `sim jupyter user` wrote."""
    if env := os.environ.get(HUB_DIR_ENV):
        return Path(env).expanduser().resolve()
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and not WINDOWS and os.geteuid() == 0 and (home := home_of(sudo_user)) is not None:
        return home / ".config" / "zabob-retirement" / "hub"
    return config_path().parent / "hub"


def run_dir(folder: Path | None = None) -> Path:
    return (folder or hub_dir()) / "run"


def config_file(folder: Path | None = None) -> Path:
    return (folder or hub_dir()) / "jupyterhub_config.py"


def _users_file(folder: Path | None) -> Path:
    return (folder or hub_dir()) / "users.toml"


def _read_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise HubError(f"can't read {path}: {exc}") from exc


def _toml_value(value: object) -> str:
    # A JSON string is a TOML basic string while non-ASCII stays as itself.
    if isinstance(value, bool | int):
        return json.dumps(value)
    return json.dumps(str(value), ensure_ascii=False)


def _write_toml(path: Path, header: str, tables: Mapping[str, Mapping[str, object]]) -> None:
    lines = [header, ""]
    for name, table in tables.items():
        lines.append(f"[{name}]")
        lines.extend(f"{key} = {_toml_value(value)}" for key, value in table.items() if value is not None)
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(path)  # whole, so the hub never reads half of it


def read_users(folder: Path | None = None) -> dict[str, HubUser]:
    """The hub's users by login, from ``users.toml``."""
    users: dict[str, HubUser] = {}
    path = _users_file(folder)
    table = _read_toml(path).get("users", {})
    for name, entry in table.items() if isinstance(table, dict) else ():
        if not isinstance(entry, dict) or entry.get("data") not in (SHARED, OWN) or not entry.get("repo"):
            raise HubError(f"{path}: users.{name} needs data = \"shared\" or \"own\" and a repo")
        users[name] = HubUser(name, entry["data"], Path(entry["repo"]), entry.get("url") or None)
    return users


def _write_users(users: Mapping[str, HubUser], folder: Path | None) -> None:
    _write_toml(
        _users_file(folder),
        "# The hub's users (`sim jupyter user`): which data repo each one's JupyterLab uses.",
        {f"users.{json.dumps(u.name)}": {"data": u.data, "repo": u.repo, "url": u.url}
         for u in sorted(users.values(), key=lambda u: u.name)},
    )


def write_user(user: HubUser, folder: Path | None = None) -> None:
    users = read_users(folder)
    users[user.name] = user
    _write_users(users, folder)


def delete_user(name: str, folder: Path | None = None) -> bool:
    users = read_users(folder)
    if users.pop(name, None) is None:
        return False
    _write_users(users, folder)
    return True


def read_settings(folder: Path | None = None) -> Settings:
    hub = _read_toml((folder or hub_dir()) / "hub.toml").get("hub", {})
    ip = hub.get("ip", DEFAULT_IP) if isinstance(hub, dict) else DEFAULT_IP
    port = hub.get("port", DEFAULT_PORT) if isinstance(hub, dict) else DEFAULT_PORT
    return Settings(str(ip), int(port))


def write_settings(settings: Settings, folder: Path | None = None) -> None:
    _write_toml((folder or hub_dir()) / "hub.toml",
                "# Where the hub listens; `sim jupyter hub start --ip/--port` sets it.",
                {"hub": {"ip": settings.ip, "port": settings.port}})


def home_of(login: str) -> Path | None:
    """``login``'s home folder, or None when there is no such login."""
    _require_posix()
    import pwd

    try:
        return Path(pwd.getpwnam(login).pw_dir)
    except KeyError:
        return None


def logins() -> list[str]:
    """The machine's people: logins with a home folder and a uid above the
    system ones (1000 on Linux, 500 on macOS)."""
    if WINDOWS:
        return []
    import pwd

    floor = 500 if sys.platform == "darwin" else 1000
    return sorted(p.pw_name for p in pwd.getpwall()
                  if p.pw_uid >= floor and p.pw_uid != 65534 and Path(p.pw_dir).is_dir())


def own_repo(login: str) -> Path:
    home = home_of(login)
    if home is None:
        raise HubError(f"there is no login {login!r} on this machine")
    return home / OWN_REPO_NAME


def write_config(folder: Path | None = None) -> Path:
    """Write ``jupyterhub_config.py``: a stub that hands the configuration to
    ``hub_config.configure``, so it follows this program's upgrades."""
    path = config_file(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Written by `sim jupyter hub start`; the settings are in hub.toml and users.toml beside it.\n"
        "from pathlib import Path\n\n"
        "from zabob.retirement.jupyter.hub_config import configure\n\n"
        f"configure(c, Path({json.dumps(str(path.parent))}))  # noqa: F821 - JupyterHub's config object\n",
        encoding="utf-8",
    )
    return path


def hub_argv(folder: Path | None = None) -> list[str]:
    return [sys.executable, "-m", "jupyterhub", "-f", str(config_file(folder))]


def proxy_command() -> str | None:
    """Where ``configurable-http-proxy`` is, which the hub runs in front of
    itself; None when it isn't installed."""
    return shutil.which("configurable-http-proxy")


def hub_pid(folder: Path | None = None) -> int | None:
    """The running hub's process, or None."""
    try:
        pid = int((run_dir(folder) / "jupyterhub.pid").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if pid_alive(pid) else None


def _answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}hub/api", timeout=2) as response:  # noqa: S310 - our own http URL
            return response.status == 200
    except urllib.error.HTTPError as exc:  # the proxy is up, the hub's route not yet
        exc.close()
        return False
    except (urllib.error.URLError, OSError, ValueError):
        return False


def start(folder: Path | None = None, *, timeout: float = 60) -> int:
    """Start the hub in the background; returns its process id once it
    answers. Its output goes to ``run/jupyterhub.log``."""
    _require_posix()
    folder = folder or hub_dir()
    run = run_dir(folder)
    run.mkdir(parents=True, exist_ok=True)
    log = run / "jupyterhub.log"
    settings = read_settings(folder)
    with log.open("a", encoding="utf-8") as out:
        out.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} starting JupyterHub ---\n")
        out.flush()
        proc = subprocess.Popen(  # noqa: S603 - our own Python and arguments
            hub_argv(folder), cwd=run, stdout=out, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise HubError(f"JupyterHub exited ({proc.returncode})")
        if _answers(settings.url):
            proc.returncode = 0  # it runs on without us; nothing to warn about at exit
            return proc.pid
        time.sleep(0.5)
    proc.terminate()
    raise HubError(f"JupyterHub didn't answer at {settings.url} within {timeout:.0f}s")


def stop(folder: Path | None = None, *, timeout: float = 30) -> bool:
    """Stop the running hub (it stops its proxy and users' servers); returns
    whether one was running."""
    pid = hub_pid(folder)
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError as exc:
        how = (f"sudo launchctl bootout system {service_path()}" if sys.platform == "darwin"
               else f"sudo systemctl stop {SERVICE_NAME}")
        raise HubError(f"the hub (process {pid}) isn't yours to stop; if the service runs it: {how}") from exc
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and pid_alive(pid):
        # One this process started (a test's) lingers as a zombie until reaped.
        with contextlib.suppress(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)
        time.sleep(0.2)
    if pid_alive(pid):
        raise HubError(f"JupyterHub (process {pid}) didn't stop within {timeout:.0f}s")
    return True


def _service_path_env() -> str:
    # The service starts with a bare PATH; the hub needs this program's
    # Python scripts and node (for configurable-http-proxy).
    folders = [str(Path(sys.executable).parent)]
    if (proxy := proxy_command()) is not None:
        folders.append(str(Path(proxy).resolve().parent))
    if (node := shutil.which("node")) is not None:
        folders.append(str(Path(node).resolve().parent))
    folders += ["/usr/local/bin", "/usr/bin", "/bin"]
    return ":".join(dict.fromkeys(folders))


def _sim() -> str:
    sim = Path(sys.executable).parent / "sim"
    return str(sim) if sim.exists() else "sim"


def systemd_unit(folder: Path | None = None) -> str:
    folder = folder or hub_dir()
    return (
        "[Unit]\n"
        "Description=Zabob Retirement JupyterHub (sim jupyter hub)\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        f"Environment={HUB_DIR_ENV}={folder}\n"
        f"Environment=PATH={_service_path_env()}\n"
        f"ExecStart={_sim()} jupyter hub start --foreground\n"
        "Restart=on-failure\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def launchd_plist(folder: Path | None = None) -> str:
    folder = folder or hub_dir()

    def string(value: object) -> str:
        return f"<string>{str(value).replace('&', '&amp;').replace('<', '&lt;')}</string>"

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        f"  <key>Label</key>{string(_LAUNCHD_LABEL)}\n"
        "  <key>ProgramArguments</key>\n  <array>"
        f"{string(_sim())}{string('jupyter')}{string('hub')}{string('start')}{string('--foreground')}</array>\n"
        "  <key>EnvironmentVariables</key>\n  <dict>\n"
        f"    <key>{HUB_DIR_ENV}</key>{string(folder)}\n"
        f"    <key>PATH</key>{string(_service_path_env())}\n"
        "  </dict>\n"
        "  <key>RunAtLoad</key><true/>\n"
        "  <key>KeepAlive</key><true/>\n"
        f"  <key>StandardOutPath</key>{string(run_dir(folder) / 'service.log')}\n"
        f"  <key>StandardErrorPath</key>{string(run_dir(folder) / 'service.log')}\n"
        "</dict>\n</plist>\n"
    )


def service_path() -> Path:
    if sys.platform == "darwin":
        return Path("/Library/LaunchDaemons") / f"{_LAUNCHD_LABEL}.plist"
    return Path("/etc/systemd/system") / f"{SERVICE_NAME}.service"


def service_text(folder: Path | None = None) -> str:
    return launchd_plist(folder) if sys.platform == "darwin" else systemd_unit(folder)


def service_enable_command() -> str:
    if sys.platform == "darwin":
        return f"sudo launchctl bootstrap system {service_path()}"
    return f"sudo systemctl daemon-reload && sudo systemctl enable --now {SERVICE_NAME}"
