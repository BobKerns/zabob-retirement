"""The data repo's own git setup (#840): the preamble its hooks share, and
the notebook clean filter.

Notebook outputs don't belong in the data repo's history: they churn it and
show numbers that go stale. So ``sim init`` sets up a filter, named for us
rather than for the tool behind it, that commits notebooks without them.
``sim builder install`` sets it up again, as a second layer for data repos
made before this, and ``sim check`` says when it's missing.

Nothing stored names a path to the program. The filter runs a script in
the data repo's hooks folder, which sources ``preamble.sh`` there to find
``sim``: the one ``sim/.analysis`` names, else the one on ``PATH``. So
moving or upgrading the program leaves it working, and so does carrying the
data repo to another machine (a removable drive): its hooks folder and
config travel with it. ``sim`` then cleans the notebook
(``notebook_clean.py``), and what cleaning means changes with the program.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from zabob.retirement.resources import INSTALLED

# Scripts this module and the builder write into the data repo's hooks
# folder carry this line, second. Its text is older than this module: the
# builder's hooks were the first, and those already installed are known by it.
HOOK_MARKER = "# analysis sim builder hook (#300)"

PREAMBLE_NAME = "preamble.sh"
CLEAN_FILTER_NAME = "clean-filter"
DRIVER = "zabob-notebook"
ATTRIBUTES = f"*.ipynb filter={DRIVER} diff={DRIVER}"
# git runs these through sh in the worktree's top folder; --git-path finds
# the hooks folder from there, in a linked worktree too.
_RUN_FILTER = f'sh "$(git rev-parse --git-path hooks)/{CLEAN_FILTER_NAME}"'
CONFIG = {
    f"filter.{DRIVER}.clean": _RUN_FILTER,
    # A filter that can't run fails `git add` rather than commit the outputs.
    f"filter.{DRIVER}.required": "true",
    f"diff.{DRIVER}.textconv": f"{_RUN_FILTER} --textconv",
}
# What `nbstripout --install` sets up, which this replaces: it records the
# whole path of the Python it ran under, which goes stale when that moves.
_OLD_SECTIONS = ("filter.nbstripout", "diff.ipynb")
_OLD_ATTRIBUTES = {"filter=nbstripout": f"filter={DRIVER}", "diff=ipynb": f"diff={DRIVER}"}

PREAMBLE = f"""#!/bin/sh
{HOOK_MARKER}
# Sourced by the data repo's hooks and its notebook clean filter (#840),
# which find it beside themselves. Sets top, this worktree's top folder
# (empty outside one), and sim: the program sim/.analysis names, a code
# worktree or an installed program (#662), else the sim on PATH (a data
# repo carried to another machine), else empty.
top="$(git rev-parse --show-toplevel 2>/dev/null)" || top=
sim=
# tr: sim init on Windows wrote .analysis with CRLF before #748.
if [ -n "$top" ] && code="$(tr -d '\\r' 2>/dev/null < "$top/sim/.analysis")" && [ -n "$code" ]; then
    case "$code" in
        {INSTALLED}*) dir="${{code#{INSTALLED}}}" ;;
        *) dir="$code/.venv/bin" ;;
    esac
    # Git for Windows's sh: the Windows path sim/.analysis holds, as its own,
    # and a venv's programs in Scripts, as .exe (#748).
    if command -v cygpath >/dev/null 2>&1; then dir="$(cygpath -u "$dir")"; fi
    [ -d "$dir" ] || dir="${{dir%/bin}}/Scripts"
    sim="$dir/sim"
    [ -x "$sim" ] || sim="$dir/sim.exe"
    [ -x "$sim" ] || sim=
fi
[ -n "$sim" ] || sim="$(command -v sim 2>/dev/null)" || sim=
"""

CLEAN_FILTER = f"""#!/bin/sh
{HOOK_MARKER}
# The data repo's notebook clean filter and diff textconv (#840): the
# notebook on stdin, or with --textconv FILE, cleaned onto stdout by sim.
here="$(dirname "$0")"
. "$here/{PREAMBLE_NAME}"
if [ -z "$sim" ]; then
    echo "notebook filter: can't find sim (sim/.analysis names none here, and none is on PATH)" >&2
    exit 1
fi
exec "$sim" _clean-notebook "$@"
"""

SCRIPTS = {PREAMBLE_NAME: PREAMBLE, CLEAN_FILTER_NAME: CLEAN_FILTER}


class SetupError(ValueError):
    """The data repo's git setup can't be made as it stands."""


def _git(root: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=check)


def _git_path(root: Path, name: str) -> Path:
    out = _git(root, "rev-parse", "--git-path", name, check=True).stdout.strip()
    path = Path(out)
    return path if path.is_absolute() else (root / path).resolve()


def hooks_dir(root: Path) -> Path:
    """Where the data repo's git looks for hooks: one folder for all its worktrees."""
    return _git_path(root, "hooks")


def ours(script: Path) -> bool:
    """Whether ``script`` is one this module or the builder wrote."""
    return script.read_text(encoding="utf-8", errors="replace").split("\n")[1:2] == [HOOK_MARKER]


def write_script(path: Path, text: str) -> None:
    # LF even on Windows: Git for Windows's sh reads a CR as part of a word.
    path.write_text(text, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def is_repo(root: Path) -> bool:
    """Whether ``root`` is a git worktree's top folder: not merely inside
    one, as a data repo not yet made one may be (in a checkout's ignored
    data/private), whose config isn't this one's to change."""
    done = _git(root, "rev-parse", "--show-toplevel")
    return done.returncode == 0 and Path(done.stdout.strip()).resolve() == root.resolve()


def _rewrite_attributes(text: str) -> str:
    """``text`` (an attributes file) with nbstripout's attributes made ours,
    dropping a line that then only repeats part of ours."""
    lines = []
    for line in text.splitlines():
        words = line.split()
        if words and not line.lstrip().startswith("#") and any(w in _OLD_ATTRIBUTES for w in words[1:]):
            words = [words[0], *(_OLD_ATTRIBUTES.get(w, w) for w in words[1:])]
            if words[0] == "*.ipynb" and set(words[1:]) <= set(ATTRIBUTES.split()[1:]):
                continue
            line = " ".join(words)
        lines.append(line)
    return "".join(f"{line}\n" for line in lines)


def _uses_old(text: str) -> bool:
    return any(not line.lstrip().startswith("#") and any(w in _OLD_ATTRIBUTES for w in line.split()[1:])
               for line in text.splitlines())


def _attribute_files(root: Path) -> list[Path]:
    """The attributes files nbstripout may have written: the tracked one,
    and ``.git/info/attributes``, where ``nbstripout --install`` puts it."""
    return [root / ".gitattributes", _git_path(root, "info/attributes")]


def gitattributes_text(text: str) -> str:
    """The tracked ``.gitattributes`` ``text`` with the filter set up."""
    text = _rewrite_attributes(text)
    return text if ATTRIBUTES in text.splitlines() else f"{text}{ATTRIBUTES}\n"


def install(root: Path) -> list[str]:
    """Set up the data repo at ``root`` (its top folder) for the notebook
    filter: the scripts, the config and the tracked ``.gitattributes``,
    replacing an nbstripout filter. Returns what it changed; nothing when
    it was all set up already."""
    if not is_repo(root):
        raise SetupError(f"{root} isn't the top of a git repository")
    done: list[str] = []
    hooks = hooks_dir(root)
    for name in SCRIPTS:
        path = hooks / name
        if path.exists() and not ours(path):
            raise SetupError(f"{path} is already there and isn't ours; move it, then run this again")
    hooks.mkdir(parents=True, exist_ok=True)
    for name, text in SCRIPTS.items():
        path = hooks / name
        if not path.exists() or path.read_text(encoding="utf-8", errors="replace") != text:
            write_script(path, text)
            done.append(f"installed {path}")
    for key, value in CONFIG.items():
        if _git(root, "config", "--local", "--get", key).stdout.rstrip("\n") != value:
            _git(root, "config", "--local", key, value, check=True)
            done.append(f"set git config {key}")
    for path in _attribute_files(root):
        before = path.read_text(encoding="utf-8") if path.exists() else None
        if path.name == ".gitattributes":
            after = gitattributes_text(before or "")
        elif before is None:
            continue
        else:
            after = _rewrite_attributes(before)
        if after != before:
            path.write_text(after, encoding="utf-8", newline="\n")
            done.append(f"updated {path}" + (" (commit it)" if path.name == ".gitattributes" else ""))
    for section in _OLD_SECTIONS:
        if _git(root, "config", "--local", "--get-regexp", f"^{section}\\.").returncode == 0:
            _git(root, "config", "--local", "--remove-section", section, check=True)
            done.append(f"removed git config {section}, which this filter replaces")
    return done


def problems(root: Path) -> list[str]:
    """What keeps the data repo at ``root`` from cleaning its notebooks
    as ``install`` sets it up; none outside a git repository."""
    if not is_repo(root):
        return []
    found: list[str] = []
    hooks = hooks_dir(root)
    for name, text in SCRIPTS.items():
        path = hooks / name
        if not path.exists():
            found.append(f"{path} is missing")
        elif path.read_text(encoding="utf-8", errors="replace") != text:
            found.append(f"{path} is out of date" if ours(path) else f"{path} isn't ours")
    for key, value in CONFIG.items():
        if _git(root, "config", "--local", "--get", key).stdout.rstrip("\n") != value:
            found.append(f"git config {key} isn't set up")
    attributes = root / ".gitattributes"
    text = attributes.read_text(encoding="utf-8") if attributes.exists() else ""
    if ATTRIBUTES not in text.splitlines():
        found.append(f"{attributes} lacks {ATTRIBUTES!r}")
    for path in _attribute_files(root):
        if path.exists() and _uses_old(path.read_text(encoding="utf-8")):
            found.append(f"{path} still uses nbstripout's filter")
    for section in _OLD_SECTIONS:
        if _git(root, "config", "--local", "--get-regexp", f"^{section}\\.").returncode == 0:
            found.append(f"git config still has {section}, which this filter replaces")
    return found
