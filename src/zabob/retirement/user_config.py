"""The user's own settings, beside any data repo (#687): which data repo the
commands use when nothing else names one.

Activation (``source activate-analysis``) used to be the only way a command
found its data repo, and it works only in bash and zsh. Now ``sim init``
records the data repo it makes as the user's default, ``sim use`` changes
it, and a command takes, in order: its ``--data-dir``, ``$ANALYSIS_DATA_DIR``
(which activation still sets, for the prompt and TAB completion), the data
repo the working folder is in (``local_data_dir``), and this default. Who
the user is follows the same way: ``$ANALYSIS_USER``, else the data repo's
``.analysis_user``.

The file is ``config.toml`` in ``zabob-retirement`` under the user's config
folder: ``%APPDATA%`` on Windows, else ``$XDG_CONFIG_HOME`` (by default
``~/.config``)::

    [data]
    dir = "/Users/alice/zabob-retirement/sim"
"""
from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

from zabob.retirement.oscompat import WINDOWS

__all__ = ["config_path", "current_user", "data_dir_setting", "default_data_dir", "local_data_dir",
           "set_default_data_dir"]


def config_path() -> Path:
    """Where the user's settings are kept."""
    if WINDOWS and (appdata := os.environ.get("APPDATA")):
        base = Path(appdata)
    else:
        value = os.environ.get("XDG_CONFIG_HOME")
        # The XDG spec says to ignore a relative value.
        base = Path(value) if value and Path(value).is_absolute() else Path.home() / ".config"
    return base / "zabob-retirement" / "config.toml"


def _read() -> dict:
    # Every command reads this, TAB completion too: a file that can't be read,
    # or isn't what this writes, is no default rather than a traceback.
    try:
        return tomllib.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}


def default_data_dir() -> Path | None:
    """The data dir (a data repo's ``sim/``) recorded as the default, or
    None when none is recorded or it is gone."""
    data = _read().get("data")
    value = data.get("dir") if isinstance(data, dict) else None
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if (path / "persons.csv").is_file() else None


def set_default_data_dir(data_dir: Path) -> Path:
    """Record ``data_dir`` as the default; returns the file written."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # A JSON string is a TOML basic string, backslashes and all, as long as
    # it keeps non-ASCII as itself: TOML has no surrogate-pair escapes.
    path.write_text(f"[data]\ndir = {json.dumps(str(data_dir.resolve()), ensure_ascii=False)}\n",
                    encoding="utf-8")
    return path


def local_data_dir(start: Path | None = None) -> Path | None:
    """The data dir of the data repo the working folder is in: a folder at or
    above it holding ``sim/persons.csv`` (a data repo, such as the one an
    installed program's notebooks sit in), or a code checkout's
    ``data/private/sim`` (#654). It comes before the user's default, as it
    does for the notebooks, so a command run in a checkout and a notebook
    opened there use the same data repo."""
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        for data_dir in (folder / "sim", folder / "data" / "private" / "sim"):
            if (data_dir / "persons.csv").is_file():
                return data_dir
    return None


def data_dir_setting() -> str | None:
    """The data dir a command uses when not given one: ``$ANALYSIS_DATA_DIR``,
    else the data repo the working folder is in, else the user's default."""
    if env := os.environ.get("ANALYSIS_DATA_DIR"):
        return env
    found = local_data_dir() or default_data_dir()
    return str(found) if found is not None else None


def current_user(data_dir: Path | str | None = None) -> str | None:
    """``$ANALYSIS_USER``, else the id the data repo remembers in
    ``.analysis_user`` (written by ``sim init`` and activation)."""
    if user := os.environ.get("ANALYSIS_USER", "").strip():
        return user
    if data_dir is None and (setting := data_dir_setting()):
        data_dir = setting
    if data_dir is None:
        return None
    try:
        first = (Path(data_dir) / ".analysis_user").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    return first[0].strip() or None if first else None
