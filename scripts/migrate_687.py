#!/usr/bin/env python3
"""One-time migration of a simulator data repo's aux/ folders to tables/ (#687).

Windows reserves the name ``aux`` for a device, so Git for Windows can't
check out a folder by that name. The lookup tables' folders are named
``tables/`` now: the data dir's shared one and each scenario's own. This
renames each ``aux/`` to ``tables/``, with ``git mv`` when the data dir is
in a git work tree (so the rename shows as one in history), and plainly
otherwise. A folder that already has a ``tables/`` beside its ``aux/`` is
reported, and nothing is renamed until it is sorted out by hand.

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
    if not folders:
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
    if not args.write:
        print("run again with --write to rename")
    elif git:
        print("commit the renames in the data repo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
