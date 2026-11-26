"""A new user's first session with an installed program, run with no shell
(#687): the commands as PowerShell or cmd would run them, so the same checks
pass on Windows, macOS and Linux.

Like ``test_install_check``, they skip from a checkout (the ``installed``
marker) and run where the program was installed: the install-test
container, or the Windows job (``.github/workflows/windows.yml``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Each runs the program in a subprocess, which takes seconds.
pytestmark = [pytest.mark.installed, pytest.mark.slow]

BIN = Path(sys.executable).parent
"""The installed program's scripts: ``sim``, ``analysis``."""
WINDOWS = sys.platform == "win32"


@pytest.fixture(scope="module")
def session(new_user_env: dict[str, str]) -> dict[str, str]:
    """A new user's environment. The rest of this machine's (git and the
    system folders on PATH, SYSTEMROOT on Windows) stays, less anything of
    the program's. On Windows the builder stays on, so its foreground
    builds (#748) are what is checked; elsewhere its daemon would outlive
    the test."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ZABOB_", "ANALYSIS_")) and k != "VIRTUAL_ENV"}
    env.update(new_user_env)
    env["USERPROFILE"] = env["HOME"]  # Path.home() on Windows
    # Where `sim init` records the data repo (#687) and `sim login` the user (#773): the new user's.
    env["APPDATA"] = str(Path(env["HOME"]) / "AppData" / "Roaming")
    env["XDG_CONFIG_HOME"] = str(Path(env["HOME"]) / ".config")
    env["PATH"] = os.pathsep.join([str(BIN), env.get("PATH", "")])
    if not WINDOWS:
        env["ZABOB_NO_BUILDER"] = "1"
    return env


def _sim(env: dict[str, str], *args: str) -> str:
    """Run ``sim ARGS`` in the user's home folder, with no activation and
    no ``--data-dir``: the default ``sim init`` recorded is what finds the
    data repo (#687). Returns its stdout and stderr."""
    done = subprocess.run([str(BIN / "sim"), *args], cwd=env["HOME"], env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout + done.stderr


@pytest.fixture(scope="module")
def data_dir(session: dict[str, str]) -> Path:
    """``sim init --example``: the prototype household in ~/zabob-retirement."""
    out = _sim(session, "init", "--example")
    assert "your data repo" in out
    return Path(session["HOME"]) / "zabob-retirement" / "sim"


def test_init_stores_text_with_lf_line_endings(data_dir: Path) -> None:
    assert (data_dir.parent / ".gitattributes").read_text(encoding="utf-8") == "* text=auto\n"


def test_a_new_user_is_asked_to_log_in(session: dict[str, str], data_dir: Path) -> None:
    """`sim init` records the data repo, not who you are (#773)."""
    assert "Not logged in: `sim login` says who you are" in _sim(session, "switch")
    out = _sim(session, "login", "alice")
    assert "User: alice" in out and "Current scenario: base" in out
    assert "Not logged in" not in _sim(session, "switch")


def test_every_scenario_loads(session: dict[str, str], data_dir: Path) -> None:
    _sim(session, "check", "--all")


def test_a_scenario_runs_and_reports(session: dict[str, str], data_dir: Path) -> None:
    _sim(session, "run", "retire_alice")
    assert "net_worth" in _sim(session, "networth", "retire_alice")
    # A rich table: its box characters must survive the console's encoding.
    assert "2030" in _sim(session, "report", "income", "retire_alice")


@pytest.mark.skipif(not WINDOWS, reason="the foreground build is Windows's (#748)")
def test_a_changed_scenario_is_rebuilt_before_it_is_shown(session: dict[str, str], data_dir: Path) -> None:
    _sim(session, "run", "base")
    persons = data_dir / "persons.csv"
    persons.write_text(persons.read_text(encoding="utf-8").replace("1965-03-15", "1965-04-15"), encoding="utf-8")
    _sim(session, "commit", "base")
    assert "building base first" in _sim(session, "networth", "base")


def test_a_notebook_runs_headless(session: dict[str, str], data_dir: Path) -> None:
    """net_worth.ipynb, executed as Jupyter would, against the example."""
    _sim(session, "run", "base")
    notebook = data_dir.parent / "notebooks" / "net_worth.ipynb"
    script = ("import sys, nbformat\nfrom nbclient import NotebookClient\n"
              "nb = nbformat.read(sys.argv[1], as_version=4)\n"
              "NotebookClient(nb, timeout=600, kernel_name='python3',"
              " resources={'metadata': {'path': sys.argv[2]}}).execute()\n")
    env = {**session, "MPLBACKEND": "Agg"}
    done = subprocess.run([sys.executable, "-c", script, str(notebook), str(notebook.parent)], env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert done.returncode == 0, done.stdout + done.stderr[-4000:]
