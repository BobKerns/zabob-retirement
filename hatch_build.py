"""Build hook: what a wheel needs that a checkout has beside ``src/`` (#662).

- The checkout's ``templates/``, ``notebooks/``, ``prototype_data/`` and ``plugins/`` go into
  the wheel as ``zabob/retirement/_shipped/``, where
  ``zabob.retirement.resources`` finds them when there is no checkout.
- ``zabob/retirement/_build_info.py`` records the git commit the build came
  from, and whether the code was committed, for a run's provenance.

``uv build`` makes the sdist from the checkout, then the wheel from the
sdist, which has no ``.git``: so the sdist carries ``_build_info.py`` in
``src/``, and the wheel built from it keeps that one. An editable install
(``uv sync``) gets neither: it runs from the checkout itself.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

SHIPPED = ("templates", "notebooks", "prototype_data", "plugins")
# The code a build's commit stamp vouches for; changes elsewhere (docs,
# tests) don't make a build dirty.
STAMPED = ("src", *SHIPPED, "pyproject.toml", "hatch_build.py")
BUILD_INFO = "src/zabob/retirement/_build_info.py"
SKIP = {"__pycache__", ".ipynb_checkpoints", ".DS_Store"}


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if version == "editable":
            return
        root = Path(self.root)
        self._scratch = Path(tempfile.mkdtemp(prefix="zabob-build-"))
        force: dict[str, str] = build_data["force_include"]
        stamp = _stamp(root)
        if self.target_name == "sdist":
            if stamp is not None:
                force[str(_write(self._scratch, stamp))] = BUILD_INFO
            return
        for name in SHIPPED:
            for path in _files(root, name):
                force[str(root / path)] = f"zabob/retirement/_shipped/{path}"
        # The sdist's own stamp, when built from one; it is gitignored (a
        # checkout must never have one), so hatch would leave it out unforced.
        info = root / BUILD_INFO if stamp is None and (root / BUILD_INFO).is_file() \
            else _write(self._scratch, stamp or ("", False))
        force[str(info)] = "zabob/retirement/_build_info.py"

    def finalize(self, version: str, build_data: dict[str, Any], artifact_path: str) -> None:
        scratch = getattr(self, "_scratch", None)
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)


def _git(root: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return done.stdout


def _stamp(root: Path) -> tuple[str, bool] | None:
    """The commit at HEAD and whether the stamped paths differ from it;
    None outside a git checkout (an unpacked sdist)."""
    if not (root / ".git").exists():
        return None
    commit = _git(root, "rev-parse", "HEAD")
    if commit is None:
        return None
    status = _git(root, "status", "--porcelain", "--", *STAMPED) or ""
    return commit.strip(), bool(status.strip())


def _write(scratch: Path, stamp: tuple[str, bool]) -> Path:
    commit, dirty = stamp
    path = scratch / "_build_info.py"
    path.write_text(
        '"""Written by hatch_build.py when the package was built."""\n\n'
        f"COMMIT = {commit!r}\nDIRTY = {dirty!r}\n", encoding="utf-8")
    return path


def _files(root: Path, name: str) -> list[str]:
    """The files of the folder ``name`` to ship, relative to ``root``: those
    git tracks in a checkout (so nothing ignored or local slips in), else
    every file of the unpacked sdist, which only tracked files reached. A
    tracked link to a folder (``notebooks/docs``, so the notebooks' links to
    the docs work) ships the folder's files, as the sdist does."""
    listed = _git(root, "ls-files", "-z", "--", name) if (root / ".git").exists() else None
    if listed is None:
        return _walk(root, root / name)
    out: list[str] = []
    for p in filter(None, listed.split("\0")):
        path = root / p
        if path.is_dir():  # a link: the files git tracks where it leads
            target = path.resolve().relative_to(root.resolve()).as_posix()
            out.extend(p + f[len(target):] for f in _files(root, target))
        elif path.is_file():
            out.append(p)
    return sorted(out)


def _walk(root: Path, folder: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in folder.rglob("*")
                  if p.is_file() and not SKIP.intersection(p.relative_to(root).parts))
