"""`sim completion install|show`, `analysis completion` and PowerShell completion (#792, #844).

Runs on the Windows workflow too, where PowerShell is at hand and the
installed `sim.exe` is on PATH, so the PowerShell script is tried for real
there; elsewhere that test runs only where `pwsh` is installed.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from zabob.retirement.cli import main as analysis_command
from zabob.retirement.sim import shell_completion
from zabob.retirement.sim.cli import sim_group_command


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home of the test's own, for the startup files install writes."""
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    monkeypatch.delenv("ZDOTDIR", raising=False)
    return folder


def _sim(*args: str, env: dict[str, str] | None = None) -> str:
    result = CliRunner().invoke(sim_group_command, list(args), prog_name="sim", env=env)
    assert result.exit_code == 0, result.output
    return result.output


@pytest.mark.parametrize(("shell", "rc"), [("bash", ".bashrc"), ("zsh", ".zshrc")])
def test_install_writes_a_script_and_one_startup_line_per_program(home: Path, shell: str, rc: str) -> None:
    (home / rc).write_text("export EDITOR=vi", encoding="utf-8")  # no final newline

    first = _sim("completion", "install", shell)
    again = _sim("completion", "install", shell)

    scripts = [done.script for done in shell_completion.install(shell)]
    assert [script.name for script in scripts] == [f"sim.{shell}", f"analysis.{shell}"]
    lines = (home / rc).read_text(encoding="utf-8").splitlines()
    assert lines[0] == "export EDITOR=vi"
    for script, prog_name in zip(scripts, shell_completion.PROGRAMS, strict=True):
        assert script.read_text(encoding="utf-8") == shell_completion.source(shell, prog_name)
        assert len([line for line in lines if str(script) in line]) == 1
    assert first.count(rc) == 2
    assert rc not in again


def test_install_keeps_the_sim_line_an_earlier_install_wrote(home: Path) -> None:
    script = shell_completion.install("zsh")[0].script
    quoted = f"'{script}'"
    # What `sim completion install` wrote before #844: only sim's line.
    (home / ".zshrc").write_text(
        f"[ -f {quoted} ] && . {quoted}  # TAB completion for sim (sim completion install)\n", encoding="utf-8")

    sim_done, analysis_done = shell_completion.install("zsh")

    assert sim_done.startup_file is None
    assert analysis_done.startup_file == home / ".zshrc"


def test_analysis_completion_is_the_same_command(home: Path) -> None:
    result = CliRunner().invoke(analysis_command, ["completion", "install", "bash"], prog_name="analysis")
    assert result.exit_code == 0, result.output
    assert "sim.bash" in result.output
    assert "analysis.bash" in result.output


def test_analysis_script_completes_analysis() -> None:
    script = shell_completion.source("bash", "analysis")
    assert "_ANALYSIS_COMPLETE" in script
    assert "_SIM_COMPLETE" not in script
    env = {"_ANALYSIS_COMPLETE": "powershell_complete", "COMP_WORDS": "", "COMP_INCOMPLETE": "ama"}
    result = CliRunner().invoke(analysis_command, [], prog_name="analysis", env=env)
    assert result.output.splitlines()[0].split("\t")[:2] == ["plain", "amazon"]


def test_no_amazon_script_is_installed() -> None:
    import tomllib

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    scripts = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["scripts"]
    assert set(scripts) == set(shell_completion.PROGRAMS)


def test_zsh_script_loads_compinit_when_the_zshrc_has_not() -> None:
    first = shell_completion.source("zsh").splitlines()[0]
    assert "compinit" in first
    assert "compdef" in first


def test_fish_needs_no_startup_line(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))

    installed = shell_completion.install("fish")

    folder = home / ".config" / "fish" / "completions"
    assert [done.script for done in installed] == [folder / "sim.fish", folder / "analysis.fish"]
    for done in installed:
        assert done.startup_file is None
        assert "complete" in done.script.read_text(encoding="utf-8")


def test_powershell_install_without_powershell_says_what_to_add(
    home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shell_completion.shutil, "which", lambda _name: None)

    installed = shell_completion.install("powershell")

    assert [done.script.name for done in installed] == ["sim.ps1", "analysis.ps1"]
    for done in installed:
        assert done.startup_file is None
        assert done.note is not None and str(done.script) in done.note


def test_powershell_install_adds_a_line_to_each_profile(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profiles = {"pwsh": home / "PowerShell" / "profile.ps1", "powershell": home / "WindowsPowerShell" / "profile.ps1"}
    monkeypatch.setattr(shell_completion.shutil, "which", lambda name: name)
    monkeypatch.setattr(shell_completion, "_powershell", lambda exe, command: (
        str(profiles[exe]) if command.startswith("$PROFILE") else "RemoteSigned"))

    first = shell_completion.install("powershell")
    again = shell_completion.install("powershell")

    assert [done.startup_file for done in first] == list(profiles.values()) * 2
    assert [done.startup_file for done in again] == [None] * 4
    for profile in profiles.values():
        text = profile.read_text(encoding="utf-8")
        assert text.count("sim.ps1") == 2  # Test-Path and the dot-source
        assert text.count("analysis.ps1") == 2


def test_powershell_install_says_how_to_allow_a_restricted_profile(
    home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shell_completion.shutil, "which", lambda name: name if name == "powershell" else None)
    monkeypatch.setattr(shell_completion, "_powershell", lambda _exe, command: (
        str(home / "profile.ps1") if command.startswith("$PROFILE") else "Restricted"))

    sim_done, analysis_done = shell_completion.install("powershell")

    assert sim_done.note is not None and "Set-ExecutionPolicy -Scope CurrentUser RemoteSigned" in sim_done.note
    assert analysis_done.note is None  # said once


def test_powershell_protocol_completes_from_the_words_given() -> None:
    env = {"_SIM_COMPLETE": "powershell_complete", "COMP_WORDS": "", "COMP_INCOMPLETE": "jup"}
    assert _sim(env=env).splitlines()[0].split("\t")[:2] == ["plain", "jupyter"]

    env |= {"COMP_WORDS": "completion\ninstall", "COMP_INCOMPLETE": ""}
    values = [line.split("\t")[1] for line in _sim(env=env).splitlines()]
    assert values == list(shell_completion.SHELLS)


def test_show_prints_both_scripts() -> None:
    shown = _sim("completion", "show", "powershell")
    assert shown == shell_completion.sources("powershell")
    assert "Register-ArgumentCompleter -Native -CommandName sim " in shown
    assert "Register-ArgumentCompleter -Native -CommandName analysis " in shown


def test_zsh_show_loads_compinit_once() -> None:
    shown = shell_completion.sources("zsh")
    assert shown.count("autoload -Uz compinit") == 1
    assert shown.splitlines()[0].startswith("(( $+functions[compdef] ))")
    assert "_SIM_COMPLETE" in shown and "_ANALYSIS_COMPLETE" in shown


def test_detect_shell_reads_the_login_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shell_completion, "WINDOWS", False)
    monkeypatch.setenv("SHELL", "/usr/local/bin/pwsh")
    assert shell_completion.detect_shell() == "powershell"
    monkeypatch.setenv("SHELL", "/bin/tcsh")
    assert shell_completion.detect_shell() is None
    monkeypatch.setattr(shell_completion, "WINDOWS", True)
    assert shell_completion.detect_shell() == "powershell"


def test_install_with_no_shell_known_asks_for_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shell_completion, "detect_shell", lambda: None)
    result = CliRunner().invoke(sim_group_command, ["completion", "install"], prog_name="sim")
    assert result.exit_code == 2
    assert "name the shell" in result.output


@pytest.mark.skipif(not shutil.which("sim"), reason="needs an installed sim on PATH")
@pytest.mark.parametrize("exe", ["pwsh", "powershell"])
def test_powershell_completes_for_real(exe: str, tmp_path: Path) -> None:
    if not shutil.which(exe):
        pytest.skip(f"no {exe}")
    script = tmp_path / "sim.ps1"
    script.write_text(shell_completion.source("powershell"), encoding="utf-8")
    # TabExpansion2 is what PowerShell runs for TAB.
    command = (
        f". '{script}'; foreach ($line in 'sim jup', 'sim jupyter ', 'sim completion install p') {{ "
        "(TabExpansion2 -inputScript $line -cursorColumn $line.Length).CompletionMatches.CompletionText "
        "-join ',' }")
    done = subprocess.run(  # noqa: S603 - a PowerShell found on PATH, the test's own command
        [shutil.which(exe) or exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    jup, jupyter, shells = done.stdout.splitlines()[-3:]
    assert jup == "jupyter"
    assert "start" in jupyter.split(",")
    assert shells == "powershell"
