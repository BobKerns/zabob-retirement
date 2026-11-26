"""Where the program's own folders are, in a checkout or installed (#662).

``templates/``, ``notebooks/``, ``prototype_data/`` and ``plugins/`` live at the top of a
code checkout, where the docs, the data repo and the tests name them. A wheel
has no checkout, so the build hook (``hatch_build.py``) copies them into
the package as ``_shipped/``. Everything that reads them asks here, so a
checkout (an editable ``uv sync`` install) reads its own working copies and
an installed program reads what shipped with it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from zabob.retirement.checkout import is_checkout
from zabob.retirement.oscompat import BIN_DIR, program

__all__ = [
    "CHECKOUT_DIR", "DEFAULT_DATA_REPO", "INSTALLED", "NOTEBOOKS_DIR", "PACKAGE_DIR", "PROTOTYPE_DIR",
    "SHIPPED_DIR", "TEMPLATES_DIR", "cache_dir", "data_home", "home_checkout", "program_home", "program_sim",
    "same_home", "shipped",
]

PACKAGE_DIR = Path(__file__).resolve().parent
"""``zabob/retirement`` itself."""

# src/zabob/retirement -> the checkout's top, when there is one.
_TOP = PACKAGE_DIR.parents[2]
CHECKOUT_DIR: Path | None = _TOP if is_checkout(_TOP) else None
"""The code checkout this package runs from; None when installed from a wheel."""

SHIPPED_DIR = PACKAGE_DIR / "_shipped"
"""Where a wheel carries the checkout's top-level folders."""


def shipped(name: str) -> Path:
    """The folder ``name`` from a checkout's top: the checkout's own, or the
    copy shipped in the package."""
    return (CHECKOUT_DIR if CHECKOUT_DIR is not None else SHIPPED_DIR) / name


TEMPLATES_DIR = shipped("templates")
NOTEBOOKS_DIR = shipped("notebooks")
PROTOTYPE_DIR = shipped("prototype_data")


def cache_dir(name: str) -> Path:
    """A download cache: the checkout's ``name`` folder (``historical_data``
    is committed there), else ``name`` under the user's cache folder
    (``$XDG_CACHE_HOME``, by default ``~/.cache``), in ``zabob-retirement``."""
    if CHECKOUT_DIR is not None:
        return CHECKOUT_DIR / name
    return _xdg("XDG_CACHE_HOME", Path.home() / ".cache") / "zabob-retirement" / name


def data_home(name: str) -> Path:
    """``name`` under the user's data folder (``$XDG_DATA_HOME``, by default
    ``~/.local/share``), in ``zabob-retirement``: for what an installed
    program writes and must keep, which has no checkout to go in."""
    return _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share") / "zabob-retirement" / name


def _xdg(var: str, default: Path) -> Path:
    """An XDG base folder: the variable's value when it is an absolute
    path, else ``default``. The spec says to ignore a relative one, which
    would put files wherever the command happened to run."""
    value = os.environ.get(var)
    return Path(value) if value and Path(value).is_absolute() else default


# -- the program a data repo is paired with ---------------------------------

INSTALLED = "installed:"
"""How ``sim/.analysis`` (and the builder's config) names an installed
program: this, then the folder holding its ``sim`` and ``python``."""

DEFAULT_DATA_REPO = Path("~/zabob-retirement")
"""Where an installed program's ``sim init`` makes the data repo when given
no folder: a checkout's goes in its ``data/private`` instead."""


def program_home() -> str:
    """What a data repo's ``sim/.analysis`` records for this program: the
    checkout's path, or, installed, ``installed:`` and the folder of the
    Python running it (a ``uv tool install``'s own environment, which
    ``uv tool upgrade`` upgrades in place)."""
    if CHECKOUT_DIR is not None:
        return str(CHECKOUT_DIR)
    return INSTALLED + str(Path(sys.executable).parent)


def home_checkout(home: str) -> Path | None:
    """The checkout a recorded home names; None for an installed one."""
    return None if not home or home.startswith(INSTALLED) else Path(home)


def program_sim(home: str) -> Path:
    """The ``sim`` of the program a recorded home names."""
    checkout = home_checkout(home)
    folder = checkout / ".venv" / BIN_DIR if checkout is not None else Path(home.removeprefix(INSTALLED))
    return program(folder, "sim")


def same_home(a: str, b: str) -> bool:
    """Whether two recorded homes are one program: a checkout compared as
    the folder it is, however spelled; an installed one by its folder."""
    if a.startswith(INSTALLED) or b.startswith(INSTALLED):
        return a.startswith(INSTALLED) and b.startswith(INSTALLED) and \
            Path(a.removeprefix(INSTALLED)).resolve() == Path(b.removeprefix(INSTALLED)).resolve()
    return bool(a) and bool(b) and Path(a).resolve() == Path(b).resolve()
