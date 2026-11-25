#!/usr/bin/env python3
"""One-time migration of a simulator data repo's aux/ folders to tables/ (#687).

Windows reserves the name ``aux`` for a device, so Git for Windows can't
check out a folder by that name. The lookup tables' folders are named
``tables/`` now: the data dir's shared one and each scenario's own. This
renames each ``aux/`` to ``tables/``, with ``git mv`` when the data dir is
in a git work tree (so the rename shows as one in history), and plainly
otherwise. A folder that already has a ``tables/`` beside its ``aux/`` is
reported, and nothing is renamed until it is sorted out by hand.

In a git work tree it also adds ``* text=auto`` to the repository's
``.gitattributes``, as ``sim init`` does for a new data repo, so a CSV saved
with CRLF on Windows (Excel's way) keeps the scenario's tree id whatever
the machine's ``core.autocrlf``.

Usage: scripts/migrate_687.py [DATA_DIR] [--write]

DATA_DIR defaults to $ANALYSIS_DATA_DIR. Without --write it only reports what
it would rename. Run it on a Mac or Linux checkout, or WSL: a Windows
checkout of the old layout can't be made. Delete this script once every
data repo is migrated.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def old_folders(data_dir: Path) -> list[Path]:
    """Every ``aux/`` the loader would refuse: the shared one and each scenario's."""
    candidates = [data_dir / "aux", *sorted((data_dir / "scenarios").glob("*/aux"))]
    return [path for path in candidates if path.is_dir()]


def _in_git(data_dir: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(data_dir), "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _tracked(folder: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(folder.parent), "ls-files", "--", folder.name],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    return bool(result.stdout.strip())


TEXT_AUTO = "* text=auto"


def _toplevel(data_dir: Path) -> Path:
    result = subprocess.run(["git", "-C", str(data_dir), "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True, encoding="utf-8", check=True)
    return Path(result.stdout.strip())


def missing_text_auto(data_dir: Path) -> Path | None:
    """The repository's ``.gitattributes`` when it lacks ``* text=auto``, else None."""
    if not _in_git(data_dir):
        return None
    attributes = _toplevel(data_dir) / ".gitattributes"
    try:
        lines = attributes.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    return None if TEXT_AUTO in (line.strip() for line in lines) else attributes


def _add_text_auto(attributes: Path) -> None:
    try:
        text = attributes.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    if text and not text.endswith("\n"):
        text += "\n"
    attributes.write_text(f"{text}{TEXT_AUTO}\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(attributes.parent), "add", ".gitattributes"], check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("data_dir", nargs="?", type=Path,
                        default=os.environ.get("ANALYSIS_DATA_DIR"))
    parser.add_argument("--write", action="store_true", help="rename (default: only report)")
    args = parser.parse_args(argv)
    if args.data_dir is None:
        parser.error("give DATA_DIR or set ANALYSIS_DATA_DIR")
    data_dir: Path = args.data_dir.resolve()

    folders = old_folders(data_dir)
    attributes = missing_text_auto(data_dir)
    if not folders and attributes is None:
        print(f"{data_dir}: no aux/ folders; nothing to migrate")
        return 0
    clashes = [path for path in folders if (path.parent / "tables").exists()]
    for path in clashes:
        print(f"{path}: {path.parent / 'tables'} exists too; merge them by hand", file=sys.stderr)
    if clashes:
        return 1

    git = _in_git(data_dir)
    for path in folders:
        target = path.parent / "tables"
        print(f"{'renaming' if args.write else 'would rename'} "
              f"{path.relative_to(data_dir)} -> {target.relative_to(data_dir)}")
        if not args.write:
            continue
        if git and _tracked(path):
            # Untracked files in it move along: git mv renames the folder itself.
            subprocess.run(["git", "-C", str(path.parent), "mv", "aux", "tables"], check=True)
        else:
            path.rename(target)
    if attributes is not None:
        print(f"{'adding' if args.write else 'would add'} {TEXT_AUTO} to {attributes}")
        if args.write:
            _add_text_auto(attributes)
    if not args.write:
        print("run again with --write to make these changes")
    elif git:
        print("commit the changes in the data repo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
