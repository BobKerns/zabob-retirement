"""Where the program's own folders are, in a checkout or installed (#662).

``templates/``, ``notebooks/`` and ``prototype_data/`` live at the top of a
code checkout, where the docs, the data repo and the tests name them. A wheel
has no checkout, so the build hook (``hatch_build.py``) copies the three into
the package as ``_shipped/``. Everything that reads them asks here, so a
checkout (an editable ``uv sync`` install) reads its own working copies and
an installed program reads what shipped with it.
"""

from __future__ import annotations

import os
from pathlib import Path

from zabob.retirement.checkout import is_checkout

__all__ = [
    "CHECKOUT_DIR", "NOTEBOOKS_DIR", "PACKAGE_DIR", "PROTOTYPE_DIR", "SHIPPED_DIR", "TEMPLATES_DIR",
    "cache_dir", "shipped",
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
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "zabob-retirement" / name
