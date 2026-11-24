"""scripts/promote_dev.py and scripts/bisect_dev.py, the dev branch's helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
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


def test_pull_numbers_come_from_merge_and_squash_subjects(promote: ModuleType) -> None:
    subjects = [
        "Merge pull request #714 from BobKerns/issue/706-test-areas",
        "Fix a typo (#716)",
        "Merge branch 'main' into dev",
        "Merge pull request #714 from BobKerns/issue/706-test-areas",
    ]
    assert promote.pull_numbers(subjects) == [714, 716]


def test_closed_issues_follow_github_keywords(promote: ModuleType) -> None:
    text = "Shard Gates\n\nFixes #704. Closes: #12, resolved #9; see #3 and fix #704 again."
    assert promote.closed_issues(text) == (704, 12, 9)


def test_promotion_body_closes_every_issue_once(promote: ModuleType) -> None:
    pulls = [promote.Pull(714, "Test areas", (706,)), promote.Pull(716, "Typo", ()),
             promote.Pull(717, "Dev branch", (707, 706))]
    body = promote.promotion_body(pulls)
    assert "3 pull requests" in body
    assert "- #714 Test areas (closes #706)\n- #716 Typo\n- #717 Dev branch (closes #707, #706)" in body
    assert body.endswith("\nFixes #706\nFixes #707\n")


def test_a_reverted_merge_is_left_out_until_its_revert_is_reverted(promote: ModuleType) -> None:
    sha = "0123456789abcdef0123456789abcdef01234567"
    message = f'Revert "Merge pull request #714 from x/y"\n\nThis reverts commit {sha}, reversing\nchanges.\n'
    assert promote.reverted_commits(["Plain commit\n", message]) == [sha]
    merge = "Merge pull request #714 from x/y"
    assert promote.reverted_pulls([merge]) == {714}
    assert promote.reverted_pulls([merge, f'Revert "{merge}"']) == set()
    assert promote.reverted_pulls(["Fix a typo (#716)", "Unrelated commit"]) == {716}


def test_promotion_body_names_reverted_pulls_and_keeps_their_issues_open(promote: ModuleType) -> None:
    body = promote.promotion_body([promote.Pull(716, "Typo", ())], [promote.Pull(714, "Test areas", (706,))])
    assert "- #714 Test areas (#706 stay open)" in body
    assert "Fixes #706" not in body


@pytest.mark.parametrize(("pytest_code", "verdict"), [(0, 0), (1, 1), (2, 1), (4, 1), (5, 1), (-9, 128)])
def test_bisect_blames_any_failure(bisect: ModuleType, pytest_code: int, verdict: int) -> None:
    """A collection error (2) or a broken conftest (4) is a bad merge too."""
    assert bisect.verdict(pytest_code) == verdict


@pytest.mark.parametrize(("test", "present"), [
    ("tests/test_x.py", True),
    ("tests/test_x.py::test_old", True),
    ("tests/test_x.py::TestThing::test_old[case-1]", True),
    ("tests/test_x.py::test_new", False),
    ("tests/test_y.py", False),
])
def test_bisect_skips_a_merge_where_the_test_is_missing(bisect: ModuleType, tmp_path: Path,
                                                        test: str, present: bool) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_old(case):\n    pass\n")
    assert bisect.present(test, tmp_path) is present
