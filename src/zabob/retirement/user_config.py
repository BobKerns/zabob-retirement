"""The user's own settings, in their home rather than any data repo
(#687, #773): who they are, which data repo they work on, and each data
repo's current scenario.

A command takes its data repo from, in order: its ``--data-dir``,
``$ANALYSIS_DATA_DIR``, the data repo the working folder is in
(``local_data_dir``), and the one recorded here (``default_data_dir``). The
``sim`` commands record a data repo the working folder is in as they find it,
saying so (``sim.cli``), so the last two agree after any command run there;
notebooks use it without recording it. Who the user is comes from
``$ANALYSIS_USER``, else ``sim login`` (``current_user``): a free name, for
attribution only, defaulting to the login name.

The files are plain text, one value each, so a shell prompt can read them,
in ``zabob-retirement`` under the user's config folder (``%APPDATA%`` on
Windows, else ``$XDG_CONFIG_HOME``, by default ``~/.config``)::

    user                      who you are (`sim login`)
    data_dir                  the current data repo's folder name under repos/
    repos/<name>/location     a data repo's data dir (its sim/)
    repos/<name>/scenario     your current scenario in it (empty: none)

``<name>`` is the data repo's folder name, with ``-2``, ``-3``... when two
have the same one. Versions before #773 kept the data repo in
``config.toml`` (``[data] dir``) and the current scenario in the data repo's
``.current_scenario``; both are still read until these files exist.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
import tomllib
from pathlib import Path

from zabob.retirement.oscompat import WINDOWS

__all__ = ["config_dir", "config_path", "current_user", "data_dir_setting", "default_data_dir", "in_checkout",
           "local_data_dir",
           "read_scenario", "repo_folder", "set_default_data_dir", "set_user", "user_name", "write_scenario"]


def config_path() -> Path:
    """Where the user's settings are kept."""
    if WINDOWS and (appdata := os.environ.get("APPDATA")):
        base = Path(appdata)
    else:
        value = os.environ.get("XDG_CONFIG_HOME")
        # The XDG spec says to ignore a relative value.
        base = Path(value) if value and Path(value).is_absolute() else Path.home() / ".config"
    return base / "zabob-retirement" / "config.toml"


def config_dir() -> Path:
    """The folder of the user's settings (``config_path``'s)."""
    return config_path().parent


def _read() -> dict:
    # Every command reads this, TAB completion too: a file that can't be read,
    # or isn't what this writes, is no default rather than a traceback.
    try:
        return tomllib.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}


def _read_value(path: Path) -> str | None:
    """The first line of ``path``, or None when it is missing, unreadable
    or empty."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    return (lines[0].strip() or None) if lines else None


def _write_value(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A temporary file of its own, so two commands writing at once each
    # replace the file whole; a prompt never reads half of it.
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            out.write(f"{value}\n" if value else "")
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def _repos() -> Path:
    return config_dir() / "repos"


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def repo_folder(data_dir: Path | str, *, create: bool = False) -> Path | None:
    """The folder under ``repos/`` that holds this data dir's settings, or
    None when it has none (and ``create`` is False)."""
    data_dir = Path(data_dir)
    repos = _repos()
    if repos.is_dir():
        for folder in sorted(repos.iterdir()):
            if (location := _read_value(folder / "location")) and _same(Path(location), data_dir):
                return folder
    if not create:
        return None
    resolved = data_dir.resolve()
    base = (resolved.parent if resolved.name == "sim" else resolved).name or "data"
    repos.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        folder = repos / (base if n == 1 else f"{base}-{n}")
        try:
            folder.mkdir()  # claimed: a command recording another data repo at once takes the next name
            break
        except FileExistsError:
            n += 1
    _write_value(folder / "location", str(resolved))
    return folder


def default_data_dir() -> Path | None:
    """The data dir (a data repo's ``sim/``) recorded as the current one, or
    None when none is recorded or it is gone."""
    path: Path | None = None
    if name := _read_value(config_dir() / "data_dir"):
        if location := _read_value(_repos() / name / "location"):
            path = Path(location)
    else:  # before #773
        data = _read().get("data")
        value = data.get("dir") if isinstance(data, dict) else None
        path = Path(value) if isinstance(value, str) and value else None
    return path if path is not None and (path / "persons.csv").is_file() else None


def set_default_data_dir(data_dir: Path) -> Path:
    """Record ``data_dir`` as the current data repo; returns its folder
    under ``repos/``."""
    folder = repo_folder(data_dir, create=True)
    assert folder is not None  # noqa: S101 - create=True always makes one
    _write_value(config_dir() / "data_dir", folder.name)
    return folder


def read_scenario(data_dir: Path | str) -> tuple[bool, str | None]:
    """``(recorded, name)``: whether this user has recorded a current
    scenario in this data dir, and which (None: recorded as none)."""
    folder = repo_folder(data_dir)
    if folder is None or not (folder / "scenario").is_file():
        return False, None
    return True, _read_value(folder / "scenario")


def write_scenario(data_dir: Path | str, scenario: str) -> None:
    """Record ``scenario`` (empty: none) as this user's current one in this data dir."""
    folder = repo_folder(data_dir, create=True)
    assert folder is not None  # noqa: S101 - create=True always makes one
    _write_value(folder / "scenario", scenario)


def user_name() -> str | None:
    """Who `sim login` says the user is, or None before they've logged in."""
    return _read_value(config_dir() / "user")


def set_user(name: str) -> None:
    _write_value(config_dir() / "user", name)


def in_checkout(data_dir: Path) -> bool:
    """Whether ``data_dir`` is a code checkout's ``data/private/sim``, not a
    data repo's own ``sim/``: often template data a worktree links."""
    return Path(data_dir).parts[-3:] == ("data", "private", "sim")


def local_data_dir(start: Path | None = None) -> Path | None:
    """The data dir of the data repo the working folder is in: a folder at or
    above it holding ``sim/persons.csv`` (a data repo, such as the one an
    installed program's notebooks sit in), or a code checkout's
    ``data/private/sim`` (#654). It comes before the recorded one, so a
    command run in a checkout and a notebook opened there use the same data
    repo; the sim commands record it as they find it (#773)."""
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        for data_dir in (folder / "sim", folder / "data" / "private" / "sim"):
            if (data_dir / "persons.csv").is_file():
                return data_dir
    return None


def data_dir_setting() -> str | None:
    """The data dir a command uses when not given one: ``$ANALYSIS_DATA_DIR``,
    else the data repo the working folder is in, else the recorded one."""
    if env := os.environ.get("ANALYSIS_DATA_DIR"):
        return env
    found = local_data_dir() or default_data_dir()
    return str(found) if found is not None else None


def current_user(data_dir: Path | str | None = None) -> str | None:  # noqa: ARG001 - callers pass theirs
    """``$ANALYSIS_USER``, else who `sim login` recorded; None before either.
    The same in every data repo (#773): it names who did something, not a
    person of the household's model."""
    if user := os.environ.get("ANALYSIS_USER", "").strip():
        return user
    return user_name()
