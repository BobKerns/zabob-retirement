"""Find the merge into dev that broke some tests.

    .venv/bin/python scripts/bisect_dev.py TEST [TEST ...] [--good REF] [--bad REF]

Bisects dev's merges, first parent only, from the last promotion (the merge
base of origin/main and origin/dev) to origin/dev, running only the given
tests (pytest ids, such as tests/test_engine.py::test_name) at each. A batch
of ten merges takes three or four short runs. It works in a temporary
worktree, so the current checkout and its branch are left alone; the tests
run with this checkout's virtual environment against that worktree's code.

At a merge where a given test doesn't exist yet the merge is skipped, not
blamed; any other failure, a collection error included, blames it. The
answer is the first merge where the tests fail: revert it with
`git revert -m 1 <merge>` in a pull request into dev, or fix forward.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parent.parent

# git bisect run's verdicts.
GOOD, BAD, SKIP, ABORT = 0, 1, 125, 128
# Set for the steps when this checkout has no data repo to share.
TEMPLATE_DATA = "BISECT_DEV_TEMPLATE_DATA"


def present(test: str, tree: Path) -> bool:
    """Whether the test exists at the commit checked out in tree. A test
    added later can't say anything about this commit."""
    path, _, name = test.partition("::")
    file = tree / path
    if not file.exists():
        return False
    # The node id's top-level name, a test function or class, less parameters.
    # A method below it may be inherited from another module, so only the
    # top level is looked for.
    top = name.partition("::")[0].partition("[")[0]
    if not top:
        return True
    return re.search(rf"^(?:def {re.escape(top)}\(|class {re.escape(top)}\b)",
                     file.read_text(encoding="utf-8"), re.MULTILINE) is not None


def verdict(pytest_code: int) -> int:
    """git bisect run's verdict for a pytest exit code, once the tests are present.
    Any failure blames the commit: a collection error (2), a broken conftest
    (4) or a lost test (5) is just what a bad merge does."""
    if pytest_code < 0:
        return ABORT  # killed by a signal
    return GOOD if pytest_code == 0 else BAD


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
    if not all(present(test, tree) for test in tests):
        return SKIP
    if os.environ.get(TEMPLATE_DATA):
        # Template data, built from this commit's templates/ as Gates does.
        shutil.rmtree(tree / "data" / "private", ignore_errors=True)
        subprocess.run([str(tree / "scripts" / "link-data.sh"), "--template"], check=True,
                       stdout=subprocess.DEVNULL)
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
        # The tests need data/private: this checkout's data repo, or else
        # template data, rebuilt at each step.
        private = REPO / "data" / "private"
        env = dict(os.environ)
        if private.exists():
            (tree / "data").mkdir(exist_ok=True)
            (tree / "data" / "private").symlink_to(private.resolve())
        else:
            env[TEMPLATE_DATA] = "1"
        _git("bisect", "start", "--first-parent", bad, good, cwd=tree)
        code = subprocess.run(["git", *NO_FILTER, "bisect", "run",
                               sys.executable, str(Path(__file__).resolve()), "--step", *args.tests],
                              cwd=tree, env=env).returncode
        _git("bisect", "reset", cwd=tree)
        return code
    finally:
        _git("worktree", "remove", "--force", str(tree))


if __name__ == "__main__":
    sys.exit(main())
