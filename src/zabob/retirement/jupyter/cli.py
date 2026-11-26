"""``sim jupyter start|stop|status``: JupyterLab for the notebooks (#762).

The server uses the token in the local ``.mcp.json``, so the Jupyter MCP
server coding agents use keeps talking to whichever JupyterLab is running.
"""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path

import click

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
@click.option("--foreground", is_flag=True,
              help="Run in this terminal until Ctrl+C, as `jupyter lab` does, instead of in the background.")
@click.option("--notebook-dir", type=click.Path(file_okay=False, path_type=Path),
              help="Serve this folder instead of the notebooks.")
def jupyter_start_command(notebook: str | None, jupyter_args: tuple[str, ...], no_browser: bool,
                          foreground: bool, notebook_dir: Path | None) -> None:
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
    argv = srv.lab_argv(settings, folder)

    if foreground:
        click.echo(f"Starting JupyterLab for {folder} on port {settings.port}; Ctrl+C stops it.")
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
    port_given = any(a.split("=")[0] in ("--port", "--ServerApp.port") for a in jupyter_args)
    if started.port != settings.port and not port_given:
        click.echo(f"WARN: port {settings.port} was busy, so it took {started.port}; the Jupyter MCP "
                   f"server in {root / '.mcp.json'} still looks on {settings.port}.", err=True)
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
