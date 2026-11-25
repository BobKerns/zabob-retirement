import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from zabob.retirement.cli import main
from zabob.retirement.jupyter import server as srv
from zabob.retirement.jupyter.config import (
    McpConfigError,
    ensure_jupyter_mcp_config,
    find_repo_root,
)


def test_ensure_jupyter_mcp_config_creates_file_with_generated_token(tmp_path: Path) -> None:
    settings, created = ensure_jupyter_mcp_config(tmp_path)

    assert created is True
    assert settings.url == "http://localhost:8888"
    assert settings.port == 8888
    assert len(settings.token) == 64  # secrets.token_hex(32)

    config_path = tmp_path / ".mcp.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["jupyter"]["env"]["JUPYTER_TOKEN"] == settings.token


def test_ensure_jupyter_mcp_config_reuses_existing_token(tmp_path: Path) -> None:
    first, created_first = ensure_jupyter_mcp_config(tmp_path)
    second, created_second = ensure_jupyter_mcp_config(tmp_path)

    assert created_first is True
    assert created_second is False
    assert first == second


def test_ensure_jupyter_mcp_config_rejects_malformed_file(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")

    with pytest.raises(McpConfigError, match="jupyter"):
        ensure_jupyter_mcp_config(tmp_path)


def test_find_repo_root_falls_back_outside_git(tmp_path: Path) -> None:
    outside_git = tmp_path / "no-git-here"
    outside_git.mkdir()

    from git import InvalidGitRepositoryError

    with patch("git.Repo", side_effect=InvalidGitRepositoryError):
        root = find_repo_root(outside_git)

    assert root == outside_git.resolve()


def test_analysis_jupyter_is_gone() -> None:
    assert "jupyter" not in main.commands  # it is `sim jupyter` now (#762)


@pytest.fixture
def notebooks_root(tmp_path: Path) -> Iterator[Path]:
    """A root with a notebooks/ holding one notebook, which the commands
    take for the checkout's or data repo's."""
    (tmp_path / "notebooks").mkdir()
    (tmp_path / "notebooks" / "net_worth.ipynb").write_text("{}", encoding="utf-8")
    with patch.object(srv, "root", return_value=tmp_path):
        yield tmp_path


def _server(root: Path, pid: int = 4321, port: int = 8888) -> srv.Server:
    return srv.Server(url=f"http://localhost:{port}/", token="t0k", root_dir=(root / "notebooks").resolve(),
                      pid=pid, port=port)


def _sim(*args: str) -> Any:
    return CliRunner().invoke(main, ["sim", "jupyter", *args])


def test_start_runs_lab_in_the_background_and_opens_the_notebook(notebooks_root: Path) -> None:
    started: dict[str, Any] = {}

    def fake_start(argv: list[str], log: Path, cwd: Path) -> srv.Server:
        started.update(argv=argv, log=log, cwd=cwd)
        return _server(notebooks_root)

    with (
        patch.object(srv, "running", return_value=[]),
        patch.object(srv, "start", side_effect=fake_start),
        patch("webbrowser.open") as opened,
    ):
        result = _sim("start", "net_worth", "--", "--ServerApp.answer=42")

    assert result.exit_code == 0, result.output
    token = json.loads((notebooks_root / ".mcp.json").read_text(encoding="utf-8"))[
        "mcpServers"]["jupyter"]["env"]["JUPYTER_TOKEN"]
    assert started["argv"] == [
        sys.executable, "-m", "jupyterlab", "--port=8888", f"--IdentityProvider.token={token}",
        f"--notebook-dir={(notebooks_root / 'notebooks').resolve()}", "--no-browser", "--ServerApp.answer=42",
    ]
    assert started["log"] == notebooks_root / "state" / "jupyter.log"
    opened.assert_called_once_with("http://localhost:8888/lab/tree/net_worth.ipynb?token=t0k")


def test_start_takes_an_option_for_jupyter_without_a_notebook(notebooks_root: Path) -> None:
    with (
        patch.object(srv, "running", return_value=[]),
        patch.object(srv, "start", return_value=_server(notebooks_root)) as start,
    ):
        result = _sim("start", "--no-browser", "--ServerApp.answer=42")

    assert result.exit_code == 0, result.output
    assert start.call_args.args[0][-1] == "--ServerApp.answer=42"
    assert "lab?token=t0k" in result.output


def test_start_reuses_a_running_server(notebooks_root: Path) -> None:
    with (
        patch.object(srv, "running", return_value=[_server(notebooks_root)]),
        patch.object(srv, "start") as start,
    ):
        result = _sim("start", "--no-browser")

    assert result.exit_code == 0, result.output
    start.assert_not_called()
    assert "already running" in result.output


def test_start_names_the_notebooks_for_an_unknown_one(notebooks_root: Path) -> None:  # noqa: ARG001
    with patch.object(srv, "running", return_value=[]):
        result = _sim("start", "nope", "--no-browser")

    assert result.exit_code == 2
    assert "no notebook 'nope'" in result.output and "net_worth" in result.output


def test_start_shows_the_log_when_lab_exits(notebooks_root: Path) -> None:
    log = notebooks_root / "state" / "jupyter.log"

    def fail(argv: list[str], log_path: Path, cwd: Path) -> srv.Server:  # noqa: ARG001
        log_path.parent.mkdir(parents=True)
        log_path.write_text("--- earlier starting JupyterLab ---\nold\n--- now starting JupyterLab ---\nport in use\n",
                            encoding="utf-8")
        raise srv.StartError("JupyterLab exited (status 1) before it was ready")

    with patch.object(srv, "running", return_value=[]), patch.object(srv, "start", side_effect=fail):
        result = _sim("start", "--no-browser")

    assert result.exit_code == 1
    assert str(log) in result.output and "port in use" in result.output and "old" not in result.output


def test_start_warns_when_the_port_was_busy(notebooks_root: Path) -> None:
    with (
        patch.object(srv, "running", return_value=[]),
        patch.object(srv, "start", return_value=_server(notebooks_root, port=8889)),
    ):
        result = _sim("start", "--no-browser")

    assert result.exit_code == 0, result.output
    assert "took 8889" in result.output


def test_foreground_runs_lab_in_this_terminal(notebooks_root: Path) -> None:
    with (
        patch.object(srv, "running", return_value=[]),
        patch("zabob.retirement.jupyter.cli._exec_foreground") as run,
    ):
        result = _sim("start", "net_worth", "--foreground", "--no-browser")

    assert result.exit_code == 0, result.output
    argv = run.call_args.args[0]
    assert argv[1:3] == ["-m", "jupyterlab"]
    assert argv[-2:] == ["--no-browser", "net_worth.ipynb"]


def test_stop_stops_only_this_folders_server(notebooks_root: Path, tmp_path: Path) -> None:
    other = _server(tmp_path / "elsewhere", pid=99)
    mine = _server(notebooks_root)
    with patch.object(srv, "running", return_value=[other, mine]), patch.object(srv, "stop", return_value=True) as stop:
        result = _sim("stop")

    assert result.exit_code == 0, result.output
    stop.assert_called_once_with(mine)
    assert "Stopped JupyterLab" in result.output


def test_stop_all_stops_every_server(notebooks_root: Path, tmp_path: Path) -> None:
    servers = [_server(tmp_path / "elsewhere", pid=99), _server(notebooks_root)]
    with patch.object(srv, "running", return_value=servers), patch.object(srv, "stop", return_value=True) as stop:
        result = _sim("stop", "--all")

    assert result.exit_code == 0, result.output
    assert stop.call_count == 2


def test_stop_with_nothing_running_says_so(notebooks_root: Path) -> None:  # noqa: ARG001
    with patch.object(srv, "running", return_value=[]):
        result = _sim("stop")

    assert result.exit_code == 0
    assert "isn't running" in result.output


def test_stop_reports_a_server_it_could_not_stop(notebooks_root: Path) -> None:
    with patch.object(srv, "running", return_value=[_server(notebooks_root)]), \
            patch.object(srv, "stop", return_value=False):
        result = _sim("stop")

    assert result.exit_code == 1
    assert "couldn't stop: process 4321" in result.output


def test_status_shows_the_address_and_counts_the_others(notebooks_root: Path, tmp_path: Path) -> None:
    servers = [_server(notebooks_root), _server(tmp_path / "elsewhere", pid=99, port=8890)]
    with patch.object(srv, "running", return_value=servers):
        result = _sim("status")

    assert result.exit_code == 0, result.output
    assert "http://localhost:8888/lab?token=t0k" in result.output
    assert "1 other Jupyter server(s)" in result.output


def test_notebook_names_complete(notebooks_root: Path) -> None:
    import click

    from zabob.retirement.sim import completion

    assert completion.NOTEBOOK.lister(click.Context(click.Command("start")), notebooks_root) == ["net_worth"]


@pytest.mark.slow
def test_start_and_stop_a_real_server(notebooks_root: Path) -> None:
    # Root may not run JupyterLab without saying so (a container).
    allow_root = ["--", "--allow-root"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []
    try:
        started = _sim("start", "--no-browser", *allow_root)
        assert started.exit_code == 0, started.output
        assert "JupyterLab is running" in started.output
        assert srv.serving(notebooks_root / "notebooks") is not None
    finally:
        stopped = _sim("stop")
    assert stopped.exit_code == 0, stopped.output
    assert srv.serving(notebooks_root / "notebooks") is None
