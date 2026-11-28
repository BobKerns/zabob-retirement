"""``sim jupyter start|stop|status``: JupyterLab for the notebooks (#762).

The server uses the token in the local ``.mcp.json``, so the Jupyter MCP
server coding agents use keeps talking to whichever JupyterLab is running.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import click

from zabob.retirement.jupyter import hub
from zabob.retirement.jupyter import server as srv
from zabob.retirement.oscompat import WINDOWS
from zabob.retirement.sim import completion


def _notebook_dir(notebook_dir: Path | None) -> tuple[Path, Path]:
    """The root (.mcp.json and state/ live there) and the notebooks folder."""
    root = srv.root()
    return root, (notebook_dir if notebook_dir is not None else root / "notebooks").resolve()


def _is_notebook(notebook_dir: Path, notebook: str) -> bool:
    name = notebook if notebook.endswith(".ipynb") else f"{notebook}.ipynb"
    return (notebook_dir / name).is_file()


def _notebook_path(notebook_dir: Path, notebook: str) -> str:
    """``notebook`` as a path under ``notebook_dir``, ``.ipynb`` optional;
    a usage error naming the notebooks there when it isn't one."""
    if _is_notebook(notebook_dir, notebook):
        return Path(notebook if notebook.endswith(".ipynb") else f"{notebook}.ipynb").as_posix()
    names = ", ".join(n.removesuffix(".ipynb") for n in srv.notebook_names(notebook_dir)) or "none"
    raise click.UsageError(f"no notebook {notebook!r} in {notebook_dir} (there: {names})")


def _open(url: str, no_browser: bool) -> None:
    click.echo(url)
    if not no_browser:
        webbrowser.open(url)


def _exec_foreground(argv: list[str]) -> None:
    """Run JupyterLab in this terminal until Ctrl+C. On POSIX this process
    becomes it, so signals and the TTY behave as for `jupyter lab`; Windows
    has no exec that keeps the console, so it waits for it instead."""
    if WINDOWS:
        sys.exit(subprocess.call(argv))  # noqa: S603 - our own Python and arguments
    os.execv(argv[0], argv)  # noqa: S606 - our own Python and arguments


@click.group(name="jupyter")
def jupyter_group() -> None:
    """JupyterLab for the notebooks: start, stop, status.

    The notebooks are the checkout's notebooks/ or, for an installed
    program, the data repo's, where `sim init` put them."""


@jupyter_group.command("start", context_settings={"ignore_unknown_options": True})
@click.argument("notebook", required=False, type=completion.NOTEBOOK)
@click.argument("jupyter_args", nargs=-1, type=click.UNPROCESSED)
@click.option("--no-browser", is_flag=True, help="Print the address; don't open a browser.")
@click.option("--port", type=click.IntRange(1, 65535), default=None,
              help="Serve on this port, or fail if it is taken (default: the one in .mcp.json, 8888 "
                   "unless changed, moving to a free one if that is taken).")
@click.option("--foreground", is_flag=True,
              help="Run in this terminal until Ctrl+C, as `jupyter lab` does, instead of in the background.")
@click.option("--notebook-dir", type=click.Path(file_okay=False, path_type=Path),
              help="Serve this folder instead of the notebooks.")
def jupyter_start_command(notebook: str | None, jupyter_args: tuple[str, ...], no_browser: bool,
                          port: int | None, foreground: bool, notebook_dir: Path | None) -> None:
    """Start JupyterLab in the background and open it in a browser, or
    NOTEBOOK in it. If it is already running for these notebooks, open
    that one instead of starting another.

    Its output goes to state/jupyter.log. JUPYTER_ARGS (after --) go to
    `jupyter lab` as they are. `sim jupyter stop` stops it.
    """
    from zabob.retirement.jupyter.config import McpConfigError, ensure_jupyter_mcp_config

    root, folder = _notebook_dir(notebook_dir)
    if notebook is not None and notebook.startswith("-"):  # an unknown option, for jupyter lab
        jupyter_args, notebook = (notebook, *jupyter_args), None
        # A notebook after such an option lands among jupyter's arguments;
        # take the first word there that names one back out.
        rest = list(jupyter_args)
        for i, arg in enumerate(rest):
            if not arg.startswith("-") and _is_notebook(folder, arg):
                notebook = rest.pop(i)
                jupyter_args = tuple(rest)
                break
    if not folder.is_dir():
        raise click.ClickException(
            f"{folder} doesn't exist; `sim notebooks copy` puts the notebooks there")
    path = _notebook_path(folder, notebook) if notebook is not None else None

    if (running := srv.serving(folder)) is not None:
        if foreground:
            raise click.ClickException(
                f"JupyterLab is already running for {folder} (process {running.pid}); "
                "`sim jupyter stop` stops it")
        click.echo(f"JupyterLab is already running for {folder}:")
        _open(running.lab_url(path), no_browser)
        return

    try:
        settings, created = ensure_jupyter_mcp_config(root)
    except McpConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    if created:
        click.echo(f"Generated {root / '.mcp.json'} with a new Jupyter token.")
    argv = srv.lab_argv(settings, folder, port)

    if foreground:
        click.echo(f"Starting JupyterLab for {folder} on port {port or settings.port}; Ctrl+C stops it.")
        # In full: jupyter lab takes a file to open relative to the working
        # folder, not to --notebook-dir.
        _exec_foreground([*argv, *(["--no-browser"] if no_browser else []), *jupyter_args,
                          *([str(folder / path)] if path else [])])
        return

    log = root / "state" / "jupyter.log"
    click.echo(f"Starting JupyterLab for {folder} (log: {log})...")
    try:
        started = srv.start([*argv, "--no-browser", *jupyter_args], log, root, folder)
    except srv.StartError as exc:
        raise click.ClickException(f"{exc}. The end of {log}:\n{srv.log_tail(log)}") from exc
    port_given = port is not None or any(
        a.split("=")[0] in ("--port", "--ServerApp.port") for a in jupyter_args)
    if started.port != settings.port:
        # The MCP server agents use reads its address from .mcp.json.
        reason = "as asked" if port_given else f"since {settings.port} was busy"
        click.echo(f"NOTE: it is on port {started.port}, {reason}; the Jupyter MCP server in "
                   f"{root / '.mcp.json'} still looks on {settings.port}.", err=True)
    click.echo("JupyterLab is running; `sim jupyter stop` stops it.")
    _open(started.lab_url(path), no_browser)


@jupyter_group.command("stop")
@click.option("--all", "stop_all", is_flag=True, help="Stop every Jupyter server you run, wherever it serves.")
@click.option("--notebook-dir", type=click.Path(file_okay=False, path_type=Path),
              help="Stop the server for this folder instead of the notebooks'.")
def jupyter_stop_command(stop_all: bool, notebook_dir: Path | None) -> None:
    """Stop the JupyterLab `sim jupyter start` started, and its notebooks'
    kernels. Unsaved changes in open notebooks are lost."""
    _root, folder = _notebook_dir(notebook_dir)
    servers = srv.running() if stop_all else [s for s in [srv.serving(folder)] if s is not None]
    if not servers:
        click.echo("No Jupyter server is running." if stop_all
                   else f"JupyterLab isn't running for {folder}.")
        return
    failed = []
    for server in servers:
        if srv.stop(server):
            click.echo(f"Stopped JupyterLab for {server.root_dir} (port {server.port}).")
        else:
            failed.append(server)
    if failed:
        raise click.ClickException("couldn't stop: " + ", ".join(
            f"process {s.pid} (port {s.port}, {s.root_dir})" for s in failed))


@jupyter_group.command("status")
@click.option("--all", "show_all", is_flag=True, help="List every Jupyter server you run.")
@click.option("--notebook-dir", type=click.Path(file_okay=False, path_type=Path),
              help="Look for the server for this folder instead of the notebooks'.")
def jupyter_status_command(show_all: bool, notebook_dir: Path | None) -> None:
    """Whether JupyterLab is running for the notebooks, and its address."""
    _root, folder = _notebook_dir(notebook_dir)
    servers = srv.running()
    mine = next((s for s in servers if s.root_dir == folder), None)
    if mine is None:
        click.echo(f"JupyterLab isn't running for {folder}.")
    else:
        click.echo(f"JupyterLab is running for {folder} (process {mine.pid}):")
        click.echo(mine.lab_url())
    others = [s for s in servers if s is not mine]
    if show_all:
        for s in others:
            click.echo(f"Also running for {s.root_dir} (process {s.pid}): {s.lab_url()}")
    elif others:
        click.echo(f"{len(others)} other Jupyter server(s) running; --all lists them.")


# ---------- the hub (#766) ----------

def _hub_error(exc: Exception) -> click.ClickException:
    if isinstance(exc, PermissionError) and exc.filename:
        # Most often a file the service (root) made in the hub folder.
        return click.ClickException(f"can't write {exc.filename}: {exc.strerror}. If root made it, "
                                    f"`sudo chown -R \"$USER\" {hub.hub_dir()}` gives the hub folder back to you")
    return click.ClickException(str(exc))


@jupyter_group.group("hub")
def hub_group() -> None:
    """A JupyterHub for the household: each login gets their own JupyterLab.

    `sim jupyter user add` says who may log in, and which data repo each
    works on. To serve more than your own login, it runs as a system
    service: `sim jupyter hub service`. Linux and macOS; it needs the
    program's `hub` extra and configurable-http-proxy (from npm)."""


@hub_group.command("start")
@click.option("--ip", help=f"Listen on this address (default {hub.DEFAULT_IP}, this machine only; "
              "0.0.0.0 for every network, or a Tailscale address). Remembered.")
@click.option("--port", type=click.IntRange(1, 65535), help=f"Listen on this port (default {hub.DEFAULT_PORT}). "
              "Remembered.")
@click.option("--foreground", is_flag=True, help="Run in this terminal until Ctrl+C (as the service does).")
def hub_start_command(ip: str | None, port: int | None, foreground: bool) -> None:
    """Start the hub in the background, once."""
    try:
        if not hasattr(os, "getuid"):
            raise hub.HubError("the hub runs on Linux and macOS; on Windows, use `sim jupyter start`")
        import importlib.util

        if importlib.util.find_spec("jupyterhub") is None:
            raise hub.HubError("JupyterHub isn't installed: install the program with its hub extra, "
                               "zabob-retirement[hub] (in a checkout, `uv sync --extra hub`)")
        if hub.proxy_command() is None:
            raise hub.HubError("configurable-http-proxy isn't on PATH: "
                               "`npm install -g configurable-http-proxy` installs it")
        settings = hub.read_settings()
        # Checked before --ip/--port are remembered: a running hub stays where it is.
        if (pid := hub.hub_pid()) is not None:
            if foreground:
                raise hub.HubError(f"the hub is already running (process {pid}); `sim jupyter hub stop` stops it")
            click.echo(f"The hub is already running (process {pid}) at {settings.url}"
                       + ("; stop it first to move it" if ip is not None or port is not None else ""))
            return
        if ip is not None or port is not None:
            settings = hub.Settings(ip if ip is not None else settings.ip,
                                    port if port is not None else settings.port)
            hub.write_settings(settings)
        hub.write_config()
        if not hub.read_users():
            click.echo("WARN: the hub has no users yet; `sim jupyter user add LOGIN` adds one.", err=True)
        if os.getuid() != 0:
            click.echo("NOTE: not running as root, so only your own login can log in; "
                       "`sim jupyter hub service` runs it for everyone.", err=True)
        if foreground:
            click.echo(f"Starting the hub at {settings.url}; Ctrl+C stops it.")
            argv = hub.hub_argv()
            hub.run_dir().mkdir(parents=True, exist_ok=True)  # a new hub's first start, as the service's
            os.chdir(hub.run_dir())
            os.execv(argv[0], argv)  # noqa: S606 - our own Python and arguments
        log = hub.run_dir() / "jupyterhub.log"
        click.echo(f"Starting the hub (log: {log})...")
        pid = hub.start()
    except (hub.HubError, OSError) as exc:
        raise _hub_error(exc) from exc
    click.echo(f"The hub is running (process {pid}) at {settings.url}; `sim jupyter hub stop` stops it.")


@hub_group.command("stop")
def hub_stop_command() -> None:
    """Stop the hub, and every user's JupyterLab and kernels with it.
    Unsaved changes in open notebooks are lost."""
    try:
        stopped = hub.stop()
    except (hub.HubError, OSError) as exc:
        raise _hub_error(exc) from exc
    click.echo("Stopped the hub." if stopped else "The hub isn't running.")


@hub_group.command("status")
def hub_status_command() -> None:
    """Whether the hub is running, where, and its users."""
    try:
        settings = hub.read_settings()
        pid = hub.hub_pid()
        users = hub.read_users()
    except hub.HubError as exc:
        raise _hub_error(exc) from exc
    if pid is None:
        click.echo(f"The hub isn't running (it would be at {settings.url}).")
    else:
        click.echo(f"The hub is running (process {pid}) at {settings.url}")
    click.echo(f"Its folder: {hub.hub_dir()}")
    for user in users.values():
        click.echo(f"  {user.describe()}")
    if not users:
        click.echo("  no users yet; `sim jupyter user add LOGIN` adds one")


@hub_group.command("log")
@click.option("-n", "--lines", type=click.IntRange(0), default=50, show_default=True,
              help="How many of the last lines to show; 0 for the whole log.")
@click.option("-f", "--follow", is_flag=True, help="Keep showing lines as they're written, until Ctrl+C.")
def hub_log_command(lines: int, follow: bool) -> None:
    """The hub's log: logins, spawns, and each user's JupyterLab, which is
    where a server that won't start says why."""
    path = hub.log_file()
    if path is None:
        raise click.ClickException(f"the hub hasn't written a log in {hub.run_dir()} yet")
    click.echo(f"==> {path} <==", err=True)
    try:
        with path.open("rb") as log:
            text = log.read()
            shown = text.splitlines(keepends=True)[-lines:] if lines else [text]
            click.echo(b"".join(shown).decode(errors="replace"), nl=False)
            while follow:
                if (more := log.read()):
                    click.echo(more.decode(errors="replace"), nl=False)
                elif path.stat().st_size < log.tell():
                    log.seek(0)  # cut short, or replaced: start again
                else:
                    time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    except PermissionError as exc:
        raise click.ClickException(f"can't read {path}; if the service (root) wrote it, "
                                   f"`sudo \"$(command -v sim)\" jupyter hub log` can") from exc
    except OSError as exc:
        raise click.ClickException(f"can't read {path}: {exc.strerror}") from exc


@hub_group.command("service")
@click.option("--install", is_flag=True, help="Write the service file (run with sudo) instead of printing it.")
def hub_service_command(install: bool) -> None:
    """The system service that runs the hub as root, so every user can log
    in: a systemd unit on Linux, a launchd daemon on macOS. Printed, or
    written with --install; the command to enable it follows."""
    if not hasattr(os, "getuid"):
        raise click.ClickException("the hub runs on Linux and macOS")
    text = hub.service_text()
    path = hub.service_path()
    if not install:
        click.echo(text, nl=False)
        # sudo's secure_path seldom has the folder `sim` is in.
        click.echo(f"\n# Save it as {path} (`sudo \"$(command -v sim)\" jupyter hub service --install` does), then:\n"
                   f"#   {hub.service_enable_command()}")
        return
    try:
        path.write_text(text, encoding="utf-8")
    except PermissionError as exc:
        raise click.ClickException(f"can't write {path}; run it with sudo") from exc
    hub.prepare_for_service()
    click.echo(f"Wrote {path}. Enable and start it with:\n  {hub.service_enable_command()}")
    if not hub.read_users():
        click.echo(f"WARN: {hub.hub_dir()} has no users yet. `sim jupyter user add` adds them there, unless "
                   "your settings are elsewhere (a custom XDG_CONFIG_HOME): then set ZABOB_HUB_DIR in "
                   f"{path} to your hub folder.", err=True)


# ---------- the hub's users (#766) ----------

@jupyter_group.group("user")
def user_group() -> None:
    """Who may log in to the hub, and which data repo each one works on.

    A user either shares a data repo with others (--shared: the same
    folder, the same CSVs and runs) or has their own clone in their home
    folder (--own), in step with the others by git. Changes take effect at
    the user's next login, with no restart."""


def _ask_login(login: str | None, choices: list[str], what: str) -> str:
    if login is not None:
        return login
    from zabob.retirement.sim.cli import _ask_name

    return _ask_name(what, choices)


def _resolve_setting(login: str, shared: str | None, own: str | None, current: hub.HubUser | None) -> hub.HubUser:
    """The setting --shared/--own give, or (neither given) the one asked for."""
    from zabob.retirement.user_config import data_dir_setting

    if shared is not None and own is not None:
        raise click.UsageError("give --shared or --own, not both")
    asked = shared is None and own is None
    if asked:
        if not sys.stdin.isatty():
            raise click.UsageError("give --shared [REPO] or --own [URL]")
        default = current.data if current is not None else hub.SHARED
        kind = click.prompt("shared or own data repo", type=click.Choice([hub.SHARED, hub.OWN]), default=default)
        if kind == hub.SHARED:
            here = str(current.repo) if current is not None and current.data == hub.SHARED else (
                str(Path(setting).parent) if (setting := data_dir_setting()) else None)
            shared = click.prompt("the data repo to share", default=here)
        else:
            own = click.prompt("clone from (blank for none)", default=(current.url if current is not None
                                                                         and current.url else ""))
    if shared is not None:
        from zabob.retirement.sim.data_repo import is_data_repo

        if shared == "":
            if not (setting := data_dir_setting()):
                raise click.UsageError("no data repo found here: name the one to share, --shared REPO")
            shared = str(Path(setting).parent)
        repo = Path(shared).expanduser().resolve()
        if not is_data_repo(repo):
            raise click.ClickException(f"{repo} isn't a data repo (it has no sim/persons.csv)")
        return hub.HubUser(login, hub.SHARED, repo)
    if own == "" and not asked and current is not None and current.data == hub.OWN:
        own = current.url or ""  # a bare --own keeps the clone URL; the guided edit can clear it
    return hub.HubUser(login, hub.OWN, hub.own_repo(login), own or None)


def _report(user: hub.HubUser, verb: str) -> None:
    click.echo(f"{verb} {user.describe()}")
    if user.data == hub.OWN and not (user.repo / "sim").is_dir() and not user.url:
        click.echo(f"NOTE: {user.repo} isn't there yet: {user.name} makes it with `sim init` in a "
                   "JupyterLab terminal, or give --own URL to clone one.", err=True)


_SHARED_HELP = ("Share this data repo (default: the one in use here) with whoever else names it: "
                "the same CSVs and runs.")
_OWN_HELP = (f"Their own data repo, ~/{hub.OWN_REPO_NAME} in their home; given a URL, cloned from it "
             "at their first login.")


@user_group.command("add")
@click.argument("login", required=False, type=completion.LOGIN)
@click.option("--shared", "shared", is_flag=False, flag_value="", default=None, metavar="[REPO]", help=_SHARED_HELP)
@click.option("--own", "own", is_flag=False, flag_value="", default=None, metavar="[URL]", help=_OWN_HELP)
def user_add_command(login: str | None, shared: str | None, own: str | None) -> None:
    """Let LOGIN, a login on this machine, use the hub."""
    try:
        login = _ask_login(login, hub.logins(), "login")
        if hub.home_of(login) is None:
            raise hub.HubError(f"there is no login {login!r} on this machine")
        if login in hub.read_users():
            raise hub.HubError(f"{login} is already a hub user; `sim jupyter user edit {login}` changes it")
        user = _resolve_setting(login, shared, own, None)
        hub.write_user(user)
    except (hub.HubError, OSError) as exc:
        raise _hub_error(exc) from exc
    _report(user, "Added")


@user_group.command("edit")
@click.argument("login", required=False, type=completion.HUB_USER)
@click.option("--shared", "shared", is_flag=False, flag_value="", default=None, metavar="[REPO]", help=_SHARED_HELP)
@click.option("--own", "own", is_flag=False, flag_value="", default=None, metavar="[URL]", help=_OWN_HELP)
def user_edit_command(login: str | None, shared: str | None, own: str | None) -> None:
    """Change which data repo LOGIN works on; without options, asks."""
    try:
        users = hub.read_users()
        login = _ask_login(login, list(users), "hub user")
        current = users.get(login)
        if current is None:
            raise hub.HubError(f"{login} isn't a hub user; `sim jupyter user add {login}` adds them")
        if shared is None and own is None:
            click.echo(current.describe())
        user = _resolve_setting(login, shared, own, current)
        hub.write_user(user)
    except (hub.HubError, OSError) as exc:
        raise _hub_error(exc) from exc
    _report(user, "Unchanged:" if user == current else "Now")


@user_group.command("delete")
@click.argument("login", required=False, type=completion.HUB_USER)
@click.option("--yes", is_flag=True, help="Don't ask first.")
def user_delete_command(login: str | None, yes: bool) -> None:
    """Stop LOGIN using the hub. Their data repo, shared or own, is left as it is."""
    try:
        login = _ask_login(login, list(hub.read_users()), "hub user")
        if login not in hub.read_users():
            raise hub.HubError(f"{login} isn't a hub user")
        if not yes and not click.confirm(f"remove {login} from the hub?", default=False):
            raise hub.HubError("nothing was changed")
        hub.delete_user(login)
    except (hub.HubError, OSError) as exc:
        raise _hub_error(exc) from exc
    click.echo(f"Removed {login} from the hub; a JupyterLab of theirs already running keeps running "
               "until the hub stops it.")


@user_group.command("list")
def user_list_command() -> None:
    """The hub's users, and the data repo each works on."""
    try:
        users = hub.read_users()
    except hub.HubError as exc:
        raise _hub_error(exc) from exc
    for user in users.values():
        click.echo(user.describe())
    if not users:
        click.echo("No hub users yet; `sim jupyter user add LOGIN` adds one.")
