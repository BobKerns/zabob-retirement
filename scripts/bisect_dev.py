"""Find the merge into dev that broke some tests.

    .venv/bin/python scripts/bisect_dev.py TEST [TEST ...] [--good REF] [--bad REF]

Bisects dev's merges, first parent only, from the last promotion (the merge
base of origin/main and origin/dev) to origin/dev, running only the given
tests (pytest ids, such as tests/test_engine.py::test_name) at each. A batch
of ten merges takes three or four short runs. It works in a temporary
worktree, so the current checkout and its branch are left alone; the tests
run with this checkout's virtual environment against that worktree's code.

At a merge where a given test doesn't exist yet the merge is skipped, not
blamed. The answer is the first merge where the tests fail: revert it with
`git revert -m 1 <merge>` in a pull request into dev, or fix forward.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parent.parent

# git bisect run's verdicts.
GOOD, BAD, SKIP, ABORT = 0, 1, 125, 128


def verdict(pytest_code: int) -> int:
    """git bisect run's verdict for a pytest exit code."""
    if pytest_code in (0, 1):
        return pytest_code  # passed, failed
    if pytest_code in (4, 5):
        # A usage error or nothing collected: a given test isn't there yet.
        return SKIP
    return ABORT  # interrupted, or pytest itself broke


# The nbstripout filter runs the worktree's .venv, which the bisect worktree
# lacks; bisect only checks commits out, so the filter has nothing to do.
NO_FILTER = ("-c", "filter.nbstripout.clean=cat", "-c", "filter.nbstripout.smudge=cat",
             "-c", "filter.nbstripout.required=false")


def _git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(["git", "-C", str(cwd), *NO_FILTER, *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def step(tests: list[str]) -> int:
    """One bisect step, run inside the bisect worktree."""
    tree = Path.cwd()
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(tree / "src"), os.environ.get("PYTHONPATH")]))}
    code = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests],
                          cwd=tree, env=env).returncode
    return verdict(code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tests", nargs="+", help="the failing tests, as pytest ids")
    parser.add_argument("--good", help="a commit where they passed (default: the last promotion)")
    parser.add_argument("--bad", default="origin/dev", help="a commit where they fail (default origin/dev)")
    # Internal: one step of `git bisect run`.
    parser.add_argument("--step", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.step:
        return step(args.tests)

    _git("fetch", "--quiet", "origin")
    good = args.good or _git("merge-base", "origin/main", "origin/dev")
    bad = _git("rev-parse", args.bad)
    tree = Path(tempfile.mkdtemp(prefix="bisect-dev-"))
    _git("worktree", "add", "--detach", "--force", str(tree), bad)
    try:
        private = REPO / "data" / "private"
        if private.exists():
            (tree / "data").mkdir(exist_ok=True)
            (tree / "data" / "private").symlink_to(private.resolve())
        _git("bisect", "start", "--first-parent", bad, good, cwd=tree)
        code = subprocess.run(["git", *NO_FILTER, "bisect", "run",
                               sys.executable, str(Path(__file__).resolve()), "--step", *args.tests],
                              cwd=tree).returncode
        _git("bisect", "reset", cwd=tree)
        return code
    finally:
        _git("worktree", "remove", "--force", str(tree))


if __name__ == "__main__":
    sys.exit(main())
