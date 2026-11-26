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
import time
from collections.abc import Callable
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
    the program's. On Windows the builder stays on, so its daemon (#748)
    is checked too, without fetching, rolling or researching; elsewhere it
    would outlive the test."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ZABOB_", "ANALYSIS_")) and k != "VIRTUAL_ENV"}
    env.update(new_user_env)
    env["USERPROFILE"] = env["HOME"]  # Path.home() on Windows
    # Where `sim init` records the data repo (#687) and `sim login` the user (#773): the new user's.
    env["APPDATA"] = str(Path(env["HOME"]) / "AppData" / "Roaming")
    env["XDG_CONFIG_HOME"] = str(Path(env["HOME"]) / ".config")
    env["PATH"] = os.pathsep.join([str(BIN), env.get("PATH", "")])
    if WINDOWS:
        env.update({"ZABOB_PRICE_FETCH": "off", "ZABOB_ROLL": "off", "ZABOB_RESEARCH": "off"})
    else:
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


@pytest.mark.skipif(not WINDOWS, reason="elsewhere the daemon would outlive the test (#748)")
def test_the_background_builder_rebuilds_a_changed_scenario(session: dict[str, str], data_dir: Path) -> None:
    """A plain `git commit`'s hook (Git for Windows's sh, LF only) starts
    the daemon, with no sim command to start or poke it, and the daemon
    builds base again. Then `sim builder stop` ends it, by a request it
    reads."""
    _sim(session, "run", "base")
    _sim(session, "builder", "stop")
    assert _until(lambda: "builder: not running" in _sim(session, "builder", "status"))
    built = _sim(session, "builder", "log", "--all").count("built base")
    persons = data_dir / "persons.csv"
    persons.write_text(persons.read_text(encoding="utf-8").replace("1965-03-15", "1965-04-15"), encoding="utf-8")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-am", "birthday"],
                   cwd=data_dir, env=session, check=True, stdin=subprocess.DEVNULL)
    try:
        started = _until(lambda: "builder: not running" not in _sim(session, "builder", "status"), 60)
        rebuilt = started and _until(
            lambda: _sim(session, "builder", "log", "--all").count("built base") > built)
    finally:
        _sim(session, "builder", "stop")
    assert started, "the commit's hook didn't start the daemon"
    assert rebuilt, _sim(session, "builder", "log", "--all")
    assert _until(lambda: "builder: not running" in _sim(session, "builder", "status"))


def _until(check: Callable[[], bool], seconds: float = 120) -> bool:
    """Whether ``check`` comes true within ``seconds``."""
    deadline = time.monotonic() + seconds
    while not check():
        if time.monotonic() > deadline:
            return False
        time.sleep(1)
    return True


@pytest.mark.skipif(not WINDOWS, reason="Task Scheduler is Windows's (#748)")
def test_the_hourly_task_is_registered_and_removed(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real Task Scheduler task, run by the pythonw beside sim so no
    window opens each hour. Removed again: the runner is shared."""
    from zabob.retirement.sim import price_schedule

    monkeypatch.delenv(price_schedule.SWITCH_ENV, raising=False)
    name = price_schedule._task_name(data_dir)
    line = price_schedule.install_timer(data_dir, BIN / "sim.exe")
    try:
        assert "added the scheduled task" in line, line
        task = subprocess.run(["schtasks", "/Query", "/TN", name, "/XML"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=False)
        assert task.returncode == 0, task.stderr
        assert str(BIN / "pythonw.exe") in task.stdout
    finally:
        price_schedule.uninstall_timer(data_dir)
    assert subprocess.run(["schtasks", "/Query", "/TN", name], capture_output=True, check=False).returncode


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
