"""scripts/promote_dev.py and scripts/bisect_dev.py, the dev branch's helpers."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest


def _load(repo_root: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, repo_root / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses look their module up in sys.modules.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def promote(repo_root: Path) -> ModuleType:
    return _load(repo_root, "promote_dev")


@pytest.fixture(scope="module")
def bisect(repo_root: Path) -> ModuleType:
    return _load(repo_root, "bisect_dev")


class _Repo:
    """A scratch git repo with main and dev, to merge and revert pull requests in."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        self.commit("base", "base")
        self.git("branch", "dev")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, content: str, message: str) -> str:
        (self.root / "file.txt").write_text(content)
        self.git("add", "file.txt")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def merge_pull(self, number: int, make, title: str = "") -> str:
        """Merge, as GitHub does, a branch off dev on which make() commits:
        the merge's message names the pull request, then gives its title."""
        self.git("checkout", "-q", "-b", f"pr{number}", "dev")
        make()
        self.git("checkout", "-q", "dev")
        self.git("merge", "-q", "--no-ff", "-m", f"Merge pull request #{number} from x/pr{number}",
                 *(["-m", title] if title else []), f"pr{number}")
        return self.git("rev-parse", "HEAD")

    def revert(self, sha: str) -> None:
        parents = self.git("rev-list", "--parents", "-n", "1", sha).split()[1:]
        self.git("revert", "--no-edit", *(["-m", "1"] if len(parents) > 1 else []), sha)

    def presence(self, promote: ModuleType) -> dict[int, bool]:
        return {m.number: m.present for m in promote.dev_merges(self.root, "main", "dev")}


@pytest.fixture
def repo(tmp_path: Path) -> _Repo:
    return _Repo(tmp_path)


def test_merges_list_pull_requests_and_what_their_commits_close(promote: ModuleType, repo: _Repo) -> None:
    repo.merge_pull(714, lambda: repo.commit("714", "Test areas\n\nCloses #706"))
    repo.git("checkout", "-q", "dev")
    repo.commit("hotfix", "Fix the loader (#712)")  # a plain commit names an issue, not a pull request
    [merge] = promote.dev_merges(repo.root, "main", "dev")
    assert (merge.number, merge.present, merge.commit_closes) == (714, True, (706,))


def test_a_merge_reverted_through_a_pull_request_is_left_out(promote: ModuleType, repo: _Repo) -> None:
    m714 = repo.merge_pull(714, lambda: repo.commit("714", "Test areas"))
    repo.merge_pull(800, lambda: repo.revert(m714))
    assert repo.presence(promote) == {714: False, 800: True}


def test_reverting_the_revert_pull_request_restores_the_merge(promote: ModuleType, repo: _Repo) -> None:
    m714 = repo.merge_pull(714, lambda: repo.commit("714", "Test areas"))
    m800 = repo.merge_pull(800, lambda: repo.revert(m714))
    repo.merge_pull(801, lambda: repo.revert(m800))
    assert repo.presence(promote) == {714: True, 800: False, 801: True}


def test_a_chain_of_reverts_and_reapplies_on_dev(promote: ModuleType, repo: _Repo) -> None:
    m714 = repo.merge_pull(714, lambda: repo.commit("714", "Test areas"))
    repo.revert(m714)
    assert repo.presence(promote) == {714: False}
    repo.revert(repo.git("rev-parse", "HEAD"))  # git titles this one "Reapply ..."
    assert repo.presence(promote) == {714: True}
    repo.revert(repo.git("rev-parse", "HEAD"))
    assert repo.presence(promote) == {714: False}


def test_closed_issues_follow_github_keywords(promote: ModuleType) -> None:
    text = ("Fixes #704. Closes: #12, resolved #9; see #3 and fix #704 again. "
            "Closes BobKerns/zabob-retirement#13, fixes https://github.com/BobKerns/zabob-retirement/issues/14, "
            "fixes other/repo#15.")
    assert promote.closed_issues(text) == (704, 12, 9, 13, 14)


def test_the_merge_commits_own_message_counts(promote: ModuleType, repo: _Repo) -> None:
    """GitHub's merge message carries the title, and reaches main with the rest."""
    repo.merge_pull(1, lambda: repo.commit("a", "Plain change"), title="Fix #9 in passing")
    assert [m.commit_closes for m in promote.dev_merges(repo.root, "main", "dev")] == [(9,)]


def test_promotion_body_closes_every_issue_once(promote: ModuleType) -> None:
    pulls = [promote.Pull(714, "Test areas", (706,)), promote.Pull(716, "Typo", ()),
             promote.Pull(717, "Dev branch", (707, 706))]
    body = promote.promotion_body(pulls)
    assert "3 pull requests" in body
    assert "- #714 Test areas (for #706)\n- #716 Typo\n- #717 Dev branch (for #707, #706)" in body
    assert body.endswith("\nFixes #706\nFixes #707\n")


def test_promotion_body_leaves_reverted_pulls_out_and_names_issues_to_reopen(promote: ModuleType) -> None:
    reverted = [promote.Pull(714, "Fixes #704: test areas", (706, 705), commit_closes=(705,))]
    body = promote.promotion_body([promote.Pull(716, "Typo", ())], reverted)
    assert "- #714 Fixes issue 704: test areas (left open: #706, #705)" in body
    assert "#705 with a closing keyword, so GitHub closes those when this merges: reopen them afterwards." in body
    # Nothing in the body closes a reverted pull request's issues.
    assert promote.closed_issues(body) == ()


def test_only_the_fixes_lines_close_anything(promote: ModuleType) -> None:
    pulls = [promote.Pull(716, "Closes #3 by accident: typo", (706,))]
    body = promote.promotion_body(pulls, [promote.Pull(714, "Resolves BobKerns/zabob-retirement#5", (8,))])
    assert promote.closed_issues(body) == (706,)


def test_an_issue_a_promoted_pull_fixes_is_not_listed_against_a_reverted_one(promote: ModuleType) -> None:
    body = promote.promotion_body([promote.Pull(716, "Typo", (706,))], [promote.Pull(714, "Areas", (706,))])
    assert "- #714 Areas\n" in body
    assert body.endswith("Fixes #706\n")


@pytest.mark.parametrize(("node", "found"), [
    ("tests/test_x.py::TestThing::test_old", True),
    ("tests/test_x.py::TestThing::test_new", False),
    ("tests/test_x.py::test_case[1]", True),
    ("tests/test_x.py::test_case[2]", False),
])
def test_bisect_skips_a_node_pytest_cant_find(bisect: ModuleType, tmp_path: Path, node: str, found: bool) -> None:
    """A method or parameter case added later skips the merge, through pytest itself."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "import pytest\n\n\nclass TestThing:\n    def test_old(self):\n        pass\n\n\n"
        "@pytest.mark.parametrize('n', [1])\ndef test_case(n):\n    pass\n")
    assert bisect.collects([node], tmp_path, dict(os.environ)) is found


def test_bisect_lets_a_collection_error_be_blamed(bisect: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("import no_such_module\n\n\ndef test_old():\n    pass\n")
    assert bisect.collects(["tests/test_x.py::test_old"], tmp_path, dict(os.environ))


@pytest.mark.parametrize(("pytest_code", "verdict"), [(0, 0), (1, 1), (2, 1), (4, 1), (5, 1), (-9, 128)])
def test_bisect_blames_any_failure(bisect: ModuleType, pytest_code: int, verdict: int) -> None:
    """A collection error (2) or a broken conftest (4) is a bad merge too."""
    assert bisect.verdict(pytest_code) == verdict


@pytest.mark.parametrize(("test", "present"), [
    ("tests/test_x.py", True),
    ("tests/test_x.py::test_old", True),
    ("tests/test_x.py::TestThing::test_old[case-1]", True),
    ("tests/test_x.py::TestThing", True),
    ("tests/test_x.py::TestThing::test_inherited", True),
    ("tests/test_x.py::TestOther", False),
    ("tests/test_x.py::test_new", False),
    ("tests/test_y.py", False),
])
def test_bisect_skips_a_merge_where_the_test_is_missing(bisect: ModuleType, tmp_path: Path,
                                                        test: str, present: bool) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_old(case):\n    pass\n\n\nclass TestThing(Base):\n"
                                                  "    def test_old(self):\n        pass\n")
    assert bisect.present(test, tmp_path) is present
