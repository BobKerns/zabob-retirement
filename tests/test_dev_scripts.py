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
        (self.root / "file.txt").write_text(content, encoding="utf-8")
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


def test_main_only_ignores_a_promotions_own_merge(promote: ModuleType, repo: _Repo) -> None:
    repo.merge_pull(1, lambda: repo.commit("a", "Change"))
    repo.git("checkout", "-q", "main")
    repo.git("merge", "-q", "--no-ff", "-m", "Merge pull request #2 from x/dev", "dev")
    assert promote.main_only(repo.root, "main", "dev") == []


def test_main_only_lists_a_promotion_merge_that_changed_something(promote: ModuleType, repo: _Repo) -> None:
    repo.merge_pull(1, lambda: repo.commit("a", "Change"))
    repo.git("checkout", "-q", "main")
    repo.git("merge", "-q", "--no-ff", "--no-commit", "dev")
    (repo.root / "resolved.txt").write_text("conflict resolved on main", encoding="utf-8")
    repo.git("add", "resolved.txt")
    repo.git("commit", "-q", "-m", "Merge pull request #2 from x/dev")
    [line] = promote.main_only(repo.root, "main", "dev")
    assert line.endswith(" Merge pull request #2 from x/dev")


def test_main_only_lists_a_hotfix_dev_lacks_until_dev_has_it(promote: ModuleType, repo: _Repo) -> None:
    repo.git("checkout", "-q", "main")
    (repo.root / "hotfix.txt").write_text("fix", encoding="utf-8")
    repo.git("add", "hotfix.txt")
    repo.git("commit", "-q", "-m", "Hotfix: Fixes #9")
    [line] = promote.main_only(repo.root, "main", "dev")
    assert line.endswith(" Hotfix: Fixes #9")
    repo.git("checkout", "-q", "dev")
    repo.git("merge", "-q", "--no-ff", "-m", "Merge pull request #3 from x/issue/9-hotfix", "main")
    assert promote.main_only(repo.root, "main", "dev") == []


def test_promotion_body_names_what_main_has_that_dev_lacks(promote: ModuleType) -> None:
    body = promote.promotion_body([promote.Pull(716, "Typo", (706,))], unsynced=["abc1234 Hotfix: Fixes #9"])
    assert "Merge main into dev in a pull request before this merges:\n\n- abc1234 Hotfix: Fixes issue 9" in body
    assert promote.closed_issues(body) == (706,)


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
    assert body.endswith("\nFixes #706\nFixes #707\n<!-- promote_dev.py wrote closing lines for: 706 707 -->\n")


def test_promotion_body_leaves_reverted_pulls_out_and_names_issues_to_reopen(promote: ModuleType) -> None:
    reverted = [promote.Pull(714, "Fixes #704: test areas", (706, 705), commit_closes=(705,))]
    body = promote.promotion_body([promote.Pull(716, "Typo", ())], reverted)
    assert "- #714 Fixes issue 704: test areas (left open: #706, #705)" in body
    assert "#705 with a closing keyword, so GitHub closes those when this merges: reopen them afterwards." in body
    # Nothing in the body closes a reverted pull request's issues.
    assert promote.closed_issues(body) == ()


def test_a_refresh_keeps_fixes_lines_added_by_hand(promote: ModuleType) -> None:
    body = promote.promotion_body([promote.Pull(716, "Typo", (706,))])
    old = body + "Fixes #12\nFixes #706\n"
    kept = promote.keep_added_fixes(old, body)
    assert kept.endswith("Fixes #706\nFixes #12\n<!-- promote_dev.py wrote closing lines for: 706 -->\n")
    assert promote.closed_issues(kept) == (706, 12)
    assert promote.keep_added_fixes(body, body) == body
    bare = promote.promotion_body([promote.Pull(716, "Typo", ())])
    assert promote.keep_added_fixes("Fixes #12", bare) == bare + "\nFixes #12\n"


def test_a_refresh_after_a_revert_drops_the_line_it_wrote(promote: ModuleType) -> None:
    before = promote.promotion_body([promote.Pull(714, "Test areas", (706,))]) + "Fixes #12\n"
    after = promote.promotion_body([], [promote.Pull(714, "Test areas", (706,))])
    assert promote.closed_issues(promote.keep_added_fixes(before, after)) == (12,)


def test_only_the_fixes_lines_close_anything(promote: ModuleType) -> None:
    pulls = [promote.Pull(716, "Closes #3 by accident: typo", (706,))]
    body = promote.promotion_body(pulls, [promote.Pull(714, "Resolves BobKerns/zabob-retirement#5", (8,))])
    assert promote.closed_issues(body) == (706,)


def _github(promote: ModuleType, monkeypatch: pytest.MonkeyPatch, open_body: str | None,
            payloads: list[dict] | None = None, open_title: str = "Promote dev to main") -> list[tuple[str, str]]:
    """Stand in for git and GitHub around _promote: dev carries #716, and the
    open promotion (#800) has open_title and open_body, or there is none.
    Returns the writes; payloads, if given, collects what each one sent."""
    writes: list[tuple[str, str]] = []
    monkeypatch.setattr(promote, "_run", lambda *args, **kw: "")
    monkeypatch.setattr(promote, "dev_merges", lambda: [promote.Merge(716, "abc", True, ())])
    monkeypatch.setattr(promote, "main_only", lambda: [])
    monkeypatch.setattr(promote.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0))
    repo = {"full_name": "o/r"}
    promotion = {"number": 800, "html_url": "u/800", "title": open_title, "body": open_body,
                 "head": {"ref": "dev", "repo": repo}, "base": {"repo": repo}}

    def api(path: str, method: str = "GET", fields: dict | None = None) -> object:
        if method != "GET":
            writes.append((method, path))
            if payloads is not None:
                payloads.append(fields or {})
            return {"html_url": "u"}
        if path.endswith("/pulls/716"):
            return {"title": "Typo", "body": "Fixes #706"}
        return [] if open_body is None else [promotion]

    monkeypatch.setattr(promote, "_api", api)
    return writes


@pytest.mark.parametrize(("open_body", "write"), [
    (None, ("POST", "repos/{owner}/{repo}/pulls")),
    ("Stale body\n", ("PATCH", "repos/{owner}/{repo}/pulls/800")),
])
def test_promote_opens_or_refreshes_the_promotion(promote: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                                  open_body: str | None, write: tuple[str, str]) -> None:
    writes = _github(promote, monkeypatch, open_body)
    assert promote._promote(dry_run=False) == 0
    assert writes == [write]


def test_promote_leaves_an_up_to_date_promotion_alone(promote: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    # The Promotion workflow runs on every push to dev; most leave the body as it was.
    current = promote.promotion_body([promote.Pull(716, "Typo", (706,))])
    writes = _github(promote, monkeypatch, current)
    assert promote._promote(dry_run=False) == 0
    assert writes == []


def test_promote_writes_nothing_with_a_blocked_keyword(promote: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    writes = _github(promote, monkeypatch, None)
    monkeypatch.setattr(promote, "_keywords_clear", lambda text: False)
    assert promote._promote(dry_run=False) == 3
    assert writes == []


@pytest.mark.parametrize("open_body", [None, "Stale body\nFixes #12\n"])
def test_promote_checks_exactly_what_it_writes(promote: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                              open_body: str | None) -> None:
    payloads: list[dict] = []
    _github(promote, monkeypatch, open_body, payloads, open_title="Promote dev to main, edited")
    checked: list[str] = []
    monkeypatch.setattr(promote, "_keywords_clear", lambda text: checked.append(text) or True)
    assert promote._promote(dry_run=False) == 0
    [sent] = payloads
    # A refresh sends only the body and keeps the title the promotion has.
    title = sent.get("title", "Promote dev to main, edited")
    assert checked == [title + "\n\n" + sent["body"]]
    if open_body:
        assert "Fixes #12" in sent["body"]


def test_keywords_clear_runs_the_check_on_the_text(promote: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def run(args: list[str], **kw: object) -> subprocess.CompletedProcess:
        seen.append(Path(args[-1]).read_text(encoding="utf-8"))
        # Its output is dropped: a matching line can hold a private keyword.
        assert kw.get("capture_output")
        return subprocess.CompletedProcess(args, 1 if "bad" in seen[-1] else 0)

    monkeypatch.setattr(promote.subprocess, "run", run)
    assert promote._keywords_clear("fine")
    assert not promote._keywords_clear("a bad title")
    assert seen == ["fine", "a bad title"]


def test_an_issue_a_promoted_pull_fixes_is_not_listed_against_a_reverted_one(promote: ModuleType) -> None:
    body = promote.promotion_body([promote.Pull(716, "Typo", (706,))], [promote.Pull(714, "Areas", (706,))])
    assert "- #714 Areas\n" in body
    assert promote.closed_issues(body) == (706,)


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
        "@pytest.mark.parametrize('n', [1])\ndef test_case(n):\n    pass\n", encoding="utf-8")
    assert bisect.collects([node], tmp_path, dict(os.environ)) is found


def test_bisect_lets_a_collection_error_be_blamed(bisect: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("import no_such_module\n\n\ndef test_old():\n    pass\n",
                                                  encoding="utf-8")
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
                                                  "    def test_old(self):\n        pass\n", encoding="utf-8")
    assert bisect.present(test, tmp_path) is present


def test_label_changes_follow_what_the_promotion_closes(promote: ModuleType) -> None:
    # 5 is new on dev, 6 already labeled, 7 closed by hand, 8 reverted off dev.
    assert promote.label_changes({5, 6, 7}, {6, 8}, {7}) == ([5], [8])
    # Once the promotion merges, none is wanted.
    assert promote.label_changes(set(), {5, 6}, set()) == ([], [5, 6])


@pytest.mark.parametrize(("body", "writes"), [
    # #12 needs the label, #13 is a pull request, #9 is reverted off dev.
    ("Fixes #11\nFixes #12\nFixes #13\n", [
        ("POST", "repos/{owner}/{repo}/labels"),
        ("POST", "repos/{owner}/{repo}/issues/12/labels"),
        ("DELETE", "repos/{owner}/{repo}/issues/9/labels/on%20dev"),
    ]),
    # No promotion open: it just merged.
    (None, [("DELETE", "repos/{owner}/{repo}/issues/9/labels/on%20dev"),
            ("DELETE", "repos/{owner}/{repo}/issues/11/labels/on%20dev")]),
])
def test_sync_labels_writes_only_the_changes(promote: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                            body: str | None, writes: list[tuple[str, str]]) -> None:
    done: list[tuple[str, str]] = []
    repo = {"full_name": "o/r"}

    def api(path: str, method: str = "GET", fields: dict | None = None) -> object:
        if method != "GET":
            done.append((method, path))
            return None
        if "/pulls?" in path:
            return [] if body is None else [{"body": body, "head": {"ref": "dev", "repo": repo},
                                             "base": {"repo": repo}}]
        if "/issues?" in path:
            return [{"number": 9}, {"number": 11}]
        n = int(path.rsplit("/", 1)[1])
        return {"state": "open", **({"pull_request": {}} if n == 13 else {})}

    monkeypatch.setattr(promote, "_api", api)
    assert promote._sync_labels(dry_run=False) == 0
    assert done == writes
    done.clear()
    assert promote._sync_labels(dry_run=True) == 0
    assert done == []
