"""Run only the tests a change needs, from the areas in tests/areas.toml.

    .venv/bin/python scripts/affected_tests.py [--base REF] [--list] [--slow] [-- PYTEST-ARGS]

The change is everything between the merge base of HEAD and REF (default
origin/main) and the working tree: commits, staged and unstaged edits, and
untracked files. Each changed path selects the tests of every area that owns
it; a path no area owns selects the whole suite. Slow tests are left out
unless --slow is given, as in the everyday local gate.

--list prints the selection instead of running it: nothing when no test is
needed, `tests` for the whole suite, otherwise one test path per line.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tomllib

REPO = Path(__file__).resolve().parent.parent
AREAS = REPO / "tests" / "areas.toml"
ALL = "tests"


@dataclass(frozen=True)
class Area:
    name: str
    paths: tuple[str, ...]
    tests: tuple[str, ...]


@dataclass(frozen=True)
class Areas:
    ignore: tuple[str, ...]
    areas: tuple[Area, ...]


def load_areas(path: Path = AREAS) -> Areas:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return Areas(
        ignore=tuple(data.get("ignore", ())),
        areas=tuple(Area(a["name"], tuple(a["paths"]), tuple(a["tests"])) for a in data.get("area", ())),
    )


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    pure = PurePosixPath(path)
    return any(pure.full_match(p) for p in patterns)


def select(changed: list[str], areas: Areas, root: Path = REPO) -> tuple[list[str], list[str]]:
    """The test paths `changed` needs, and the changed paths that alone
    select the whole suite. A selection of [ALL] means every test."""
    tests: set[str] = set()
    everything: list[str] = []
    for path in changed:
        if path == "tests/conftest.py" or path.startswith("tests/data/"):
            everything.append(path)
            continue
        if PurePosixPath(path).full_match("tests/**/test_*.py"):
            # A deleted test file has nothing left to run.
            if (root / path).exists():
                tests.add(path)
            continue
        if _matches(path, areas.ignore):
            continue
        owners = [a for a in areas.areas if _matches(path, a.paths)]
        if not owners:
            everything.append(path)
            continue
        for area in owners:
            for pattern in area.tests:
                tests.update(str(p.relative_to(root)) for p in root.glob(pattern))
    if everything:
        return [ALL], everything
    return sorted(tests), []


def changed_files(base: str, root: Path = REPO) -> list[str]:
    def git(*args: str) -> list[str]:
        out = subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout
        return [line for line in out.splitlines() if line]

    merge_base = git("merge-base", base, "HEAD")[0]
    paths = set(git("diff", "--name-only", merge_base))
    paths.update(git("ls-files", "--others", "--exclude-standard"))
    return sorted(paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="origin/main",
                        help="branch the change is measured from (default origin/main)")
    parser.add_argument("--list", action="store_true", help="print the selection instead of running it")
    parser.add_argument("--slow", action="store_true", help="include tests marked slow")
    parser.add_argument("pytest_args", nargs="*", help="extra pytest arguments, after --")
    args = parser.parse_args(argv)

    tests, everything = select(changed_files(args.base), load_areas())
    if args.list:
        print("\n".join(tests))
        return 0
    if not tests:
        print("No tests needed: nothing changed that a test reads.", file=sys.stderr)
        return 0
    if everything:
        shown = ", ".join(everything[:5]) + (" ..." if len(everything) > 5 else "")
        print(f"Whole suite: no area owns {shown}", file=sys.stderr)
    else:
        print(f"{len(tests)} test path(s) from tests/areas.toml", file=sys.stderr)
    command = [sys.executable, "-m", "pytest", "-q", "-n", "auto"]
    if not args.slow:
        command += ["-m", "not slow"]
    return subprocess.run([*command, *tests, *args.pytest_args], cwd=REPO).returncode


if __name__ == "__main__":
    sys.exit(main())
