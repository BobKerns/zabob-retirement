"""TAB completion for ``sim`` and ``analysis`` in bash, zsh, fish and
PowerShell (#792, #844).

``sim completion install`` (or ``analysis completion install``; either sets
up both programs) writes click's completion script for each to a file once,
and has the shell read it at start, so completion works without sourcing the
data repo's ``activate-retirement``. A saved script doesn't go stale: it only
hands the words typed so far back to the program, which answers with the
names. Reading a file is also quicker than the
usual ``eval "$(_SIM_COMPLETE=zsh_source sim)"``, which starts Python at
every new shell.

Click has bash, zsh and fish; ``PowerShellComplete`` adds PowerShell, for
native Windows (and ``pwsh`` anywhere).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import click
from click.shell_completion import CompletionItem, ShellComplete, add_completion_class, get_completion_class

from zabob.retirement import user_config
from zabob.retirement.oscompat import WINDOWS

__all__ = ["PROGRAMS", "SHELLS", "Installed", "PowerShellComplete", "detect_shell", "install", "source", "sources"]

SHELLS = ("bash", "zsh", "fish", "powershell")

# The installed commands, each with its own script: `sim` first, since it's
# the one users have.
PROGRAMS = ("sim", "analysis")

# What PowerShell hands sim: the words before the one being completed, one
# per line (PowerShell's own parse, so a quoted name or a Windows path
# arrives as typed, which re-splitting the line in Python would mangle),
# and that word. Each answer comes back as type<TAB>value<TAB>help. For a
# file or folder sim answers nothing PowerShell can use, and a completer
# that returns nothing gets PowerShell's own path completion.
_POWERSHELL_SOURCE = """\
Register-ArgumentCompleter -Native -CommandName %(prog_name)s -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
    $words = @($commandAst.CommandElements |
        Where-Object { $_.Extent.EndOffset -le $cursorPosition } |
        ForEach-Object {
            if ($_ -is [System.Management.Automation.Language.StringConstantExpressionAst]) { $_.Value }
            else { $_.Extent.Text }
        })
    # Drop the command's own name and, when there is one, the word being completed.
    $n = $words.Count
    if ($wordToComplete -ne '') { $n -= 1 }
    $words = if ($n -gt 1) { @($words[1..($n - 1)]) } else { @() }
    $encoding = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        $env:PYTHONUTF8 = '1'
        $env:COMP_WORDS = $words -join "`n"
        $env:COMP_INCOMPLETE = $wordToComplete
        $env:%(complete_var)s = 'powershell_complete'
        & %(prog_name)s 2>$null | ForEach-Object {
            $type, $value, $help = $_ -split "`t", 3
            if ($type -eq 'plain' -and $value -ne '') {
                $text = $value
                if ($value -match '[\\s''`$;,(){}@&|<>#]') { $text = "'" + ($value -replace "'", "''") + "'" }
                $tip = if ($help) { $help } else { $value }
                [System.Management.Automation.CompletionResult]::new($text, $value, 'ParameterValue', $tip)
            }
        }
    } finally {
        [Console]::OutputEncoding = $encoding
        Remove-Item Env:%(complete_var)s, Env:COMP_WORDS, Env:COMP_INCOMPLETE, Env:PYTHONUTF8 `
            -ErrorAction SilentlyContinue
    }
}
"""


class PowerShellComplete(ShellComplete):
    """Click shell completion for PowerShell (5.1 and 7), which click lacks."""

    name = "powershell"
    source_template = _POWERSHELL_SOURCE

    def get_completion_args(self) -> tuple[list[str], str]:
        words = os.environ.get("COMP_WORDS", "")
        return (words.split("\n") if words else []), os.environ.get("COMP_INCOMPLETE", "")

    def format_completion(self, item: CompletionItem) -> str:
        help_text = " ".join((item.help or "").split())
        return f"{item.type}\t{item.value}\t{help_text}"


add_completion_class(PowerShellComplete)


def detect_shell() -> str | None:
    """The shell to set up when none is named: PowerShell on Windows, else
    the login shell (``$SHELL``), when it's one of ``SHELLS``."""
    if WINDOWS:
        return "powershell"
    name = Path(os.environ.get("SHELL", "")).name
    name = "powershell" if name == "pwsh" else name
    return name if name in SHELLS else None


def _command(prog_name: str) -> click.Command:
    # Imported here: both CLIs import this module, for PowerShellComplete.
    if prog_name == "analysis":
        from zabob.retirement.cli import main

        return main
    from zabob.retirement.sim.cli import sim_group_command

    return sim_group_command


# Click's zsh script calls compdef, which only exists once compinit has run;
# a plain ~/.zshrc (no oh-my-zsh) never runs it.
_ZSH_PREAMBLE = "(( $+functions[compdef] )) || { autoload -Uz compinit && compinit }\n"


def _script(shell: str, prog_name: str) -> str:
    cls = get_completion_class(shell)
    if cls is None:  # SHELLS are all registered; a guard for a caller's typo
        raise ValueError(f"no completion for {shell!r}")
    complete_var = f"_{prog_name.replace('-', '_').upper()}_COMPLETE"
    return cls(_command(prog_name), {}, prog_name, complete_var).source()


def source(shell: str, prog_name: str = "sim") -> str:
    """Click's completion script for ``prog_name`` (one of ``PROGRAMS``) in ``shell``."""
    script = _script(shell, prog_name)
    return _ZSH_PREAMBLE + script if shell == "zsh" else script


def sources(shell: str) -> str:
    """The completion scripts for all of ``PROGRAMS`` in ``shell``, one
    after another, for ``completion show``."""
    text = "\n".join(_script(shell, prog_name).rstrip("\n") + "\n" for prog_name in PROGRAMS)
    return _ZSH_PREAMBLE + text if shell == "zsh" else text


@dataclass(frozen=True)
class Installed:
    """What ``install`` did: the script it wrote, and the startup file it
    added a line to (None when the shell reads the script by itself, or the
    line was already there)."""

    script: Path
    startup_file: Path | None
    note: str | None = None


def _mark(prog_name: str) -> str:
    # sim's mark, and so its line, is what installs before #844 wrote, so
    # running install again finds that line and adds nothing for sim.
    return f"# TAB completion for {prog_name} (sim completion install)"


def install(shell: str) -> list[Installed]:
    """Write the completion script for each of ``PROGRAMS`` in ``shell``
    and have the shell read them at start. Running it again rewrites the
    scripts (taking a newer click's) and adds nothing to a startup file that
    already reads them."""
    done = [each for prog_name in PROGRAMS for each in _install(shell, prog_name)]
    # A note about the shell (an execution policy) is the same for each
    # program; say it once.
    said: set[str] = set()
    for i, each in enumerate(done):
        if each.note in said:
            done[i] = Installed(each.script, each.startup_file)
        elif each.note:
            said.add(each.note)
    return done


def _install(shell: str, prog_name: str) -> list[Installed]:
    text = source(shell, prog_name)
    if shell == "fish":
        # fish loads completions/<command>.fish by itself when it's first needed.
        base = os.environ.get("XDG_CONFIG_HOME")
        root = Path(base) if base and Path(base).is_absolute() else Path.home() / ".config"
        script = _write(root / "fish" / "completions" / f"{prog_name}.fish", text)
        return [Installed(script, None)]
    folder = user_config.config_dir() / "completion"
    if shell == "powershell":
        script = _write(folder / f"{prog_name}.ps1", text)
        profiles = _powershell_profiles()
        if not profiles:
            return [Installed(script, None, "no PowerShell found to find its profile; add this line to $PROFILE: "
                              + _powershell_line(script, prog_name))]
        line = _powershell_line(script, prog_name)
        return [Installed(script, _add_line(profile, line), _execution_policy_note(exe)) for exe, profile in profiles]
    script = _write(folder / f"{prog_name}.{shell}", text)
    quoted = "'" + str(script).replace("'", "'\\''") + "'"
    line = f"[ -f {quoted} ] && . {quoted}  {_mark(prog_name)}"
    if shell == "zsh":
        zdotdir = os.environ.get("ZDOTDIR")
        rc = (Path(zdotdir) if zdotdir else Path.home()) / ".zshrc"
    else:
        rc = Path.home() / ".bashrc"
    return [Installed(script, _add_line(rc, line))]


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _add_line(startup_file: Path, line: str) -> Path | None:
    """Append ``line`` to ``startup_file`` unless it's there; the file when
    it was added."""
    existing = startup_file.read_text(encoding="utf-8") if startup_file.is_file() else ""
    if line in existing.splitlines():
        return None
    startup_file.parent.mkdir(parents=True, exist_ok=True)
    gap = "" if not existing or existing.endswith("\n") else "\n"
    with startup_file.open("a", encoding="utf-8") as f:
        f.write(f"{gap}{line}\n")
    return startup_file


def _powershell_line(script: Path, prog_name: str) -> str:
    quoted = "'" + str(script).replace("'", "''") + "'"
    return f"if (Test-Path {quoted}) {{ . {quoted} }}  {_mark(prog_name)}"


def _powershell(exe: str, command: str) -> str | None:
    try:
        done = subprocess.run(  # noqa: S603 - a PowerShell found on PATH, our own command
            [exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


def _powershell_profiles() -> list[tuple[str, Path]]:
    """Each PowerShell on PATH (7's ``pwsh``, Windows' own ``powershell``)
    and its profile, which each keeps in its own place (and Windows may
    move under OneDrive), so each is asked rather than guessed."""
    found: list[tuple[str, Path]] = []
    for name in ("pwsh", "powershell"):
        if (exe := shutil.which(name)) and (profile := _powershell(exe, "$PROFILE.CurrentUserCurrentHost")):
            if all(Path(profile) != p for _, p in found):
                found.append((exe, Path(profile)))
    return found


def _execution_policy_note(exe: str) -> str | None:
    """Windows' own PowerShell runs no profile under its default policy,
    Restricted; say how to allow it."""
    policy = _powershell(exe, "Get-ExecutionPolicy")
    if policy in ("Restricted", "AllSigned"):
        return (f"{Path(exe).stem}'s execution policy is {policy}, so it won't read its profile; to let it: "
                "Set-ExecutionPolicy -Scope CurrentUser RemoteSigned")
    return None
