"""Open or refresh the pull request that promotes dev to main.

    .venv/bin/python scripts/promote_dev.py [--dry-run]

It lists the pull requests merged into dev since the last promotion and the
issues they close. "Fixes #N" in a pull request into dev closes nothing,
because GitHub acts on it only in a pull request into the default branch, so
the promotion's body repeats each one and merging it closes them all.

A pull request whose merge was reverted on dev, and not restored, is listed
apart, without its "Fixes" lines. Its commits still reach main, though, so
an issue one of their messages names with a closing keyword closes anyway;
the body names those to reopen.

The pull request opens as a draft, so Gates leaves it alone while dev
keeps moving; mark it ready when it's time to promote, which runs the full
gates on it once. Merge it with a merge commit, never a squash: dev's merges then
stay on main's history, where scripts/bisect_dev.py and
`git log --first-parent` find them. Needs `gh`, signed in; it uses only
GitHub's REST API.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import cache
import json
from pathlib import Path
import re
import subprocess
import sys

REPO = Path(__file__).resolve().parent.parent
TITLE = "Promote dev to main"

# GitHub's merge commit. Squash merges are off in this repo, and a plain
# commit's "(#N)" names an issue, not a pull request.
_MERGED_PR = re.compile(r"^Merge pull request #(\d+) ")
# `git revert`'s message, for a merge (-m 1) or a plain commit, whatever its
# subject says (git titles a revert of a revert "Reapply ...").
_REVERTS = re.compile(r"^This reverts commit ([0-9a-f]{7,40})\b", re.MULTILINE)
# GitHub's closing keywords, with an issue of this repository as #N,
# owner/repo#N or its URL.
_CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+"
                     r"(?:BobKerns/zabob-retirement#|https://github\.com/BobKerns/zabob-retirement/issues/|#)"
                     r"(\d+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Merge:
    """A pull request's merge on dev's first-parent line."""
    number: int
    sha: str
    present: bool  # its change is still on dev: not reverted, or restored
    commit_closes: tuple[int, ...]  # what its commits' messages close


@dataclass(frozen=True)
class Pull:
    number: int
    title: str
    closes: tuple[int, ...]  # from the title and body, and the commits' messages
    commit_closes: tuple[int, ...] = ()


def closed_issues(text: str) -> tuple[int, ...]:
    """The issues a text names with GitHub's closing keywords, in order."""
    return tuple(dict.fromkeys(int(n) for n in _CLOSES.findall(text)))


def _defused(text: str) -> str:
    """text with each closing reference made inert ("fixes #5" becomes "fixes
    issue 5"), so the promotion closes only what its "Fixes" lines name."""
    return _CLOSES.sub(lambda m: re.sub(r"\s*:?\s+\S*$", "", m.group(0)) + f" issue {m.group(1)}", text)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def dev_merges(root: Path = REPO, base: str = "origin/main", tip: str = "origin/dev") -> list[Merge]:
    """The pull requests merged on tip's first-parent line since base, oldest
    first, and whether each one's change is still there.

    A revert undoes the commit it names, and every commit a merge brought in
    when it names a merge. A commit's change is there unless a revert whose
    own change is there undid it, so reverting a revert, however it was done
    (git revert of the revert commit, or of the merge of a pull request that
    reverted), restores it."""
    commits = _git(root, "rev-list", f"{base}..{tip}").split()
    undone_by: dict[str, list[str]] = {}
    for sha in commits:
        for named in _REVERTS.findall(_git(root, "log", "-1", "--format=%B", sha)):
            target = _git(root, "rev-parse", f"{named}^{{commit}}").strip()
            undone_by.setdefault(target, []).append(sha)
            for brought in _brought_in(root, target):
                undone_by.setdefault(brought, []).append(sha)

    @cache
    def there(sha: str) -> bool:
        # Reverts come after what they revert, so this recursion ends.
        return not any(there(r) for r in undone_by.get(sha, ()))

    merges = []
    for line in _git(root, "log", "--first-parent", "--reverse", "--format=%H %s", f"{base}..{tip}").splitlines():
        sha, _, subject = line.partition(" ")
        if m := _MERGED_PR.match(subject):
            # The merge commit reaches main too, and GitHub's default message
            # for it carries the pull request's title.
            messages = "\n".join(_git(root, "log", "-1", "--format=%B", c) for c in [sha, *_brought_in(root, sha)])
            merges.append(Merge(int(m.group(1)), sha, there(sha), closed_issues(messages)))
    return merges


def main_only(root: Path = REPO, base: str = "origin/main", tip: str = "origin/dev") -> list[str]:
    """The commits ("<sha> <subject>") that bring base changes tip lacks: a
    hotfix not yet merged into dev, or a pull request merged into main by
    mistake. Empty when merging base into tip would change nothing, which
    is the usual case: a promotion's own merge commit, which main always has
    and dev never does, changes no file."""
    merged = subprocess.run(["git", "-C", str(root), "merge-tree", "--write-tree", tip, base],
                            capture_output=True, text=True)
    if merged.returncode == 0 and merged.stdout.split()[0] == _git(root, "rev-parse", f"{tip}^{{tree}}").strip():
        return []
    lines = _git(root, "log", "--format=%h %s", f"{tip}..{base}").splitlines()
    return [line for line in lines if not re.search(r"^\S+ Merge pull request #\d+ from \S+/dev$", line)]


def _brought_in(root: Path, sha: str) -> list[str]:
    """The commits a merge brought in (none for a plain commit)."""
    parents = _git(root, "rev-list", "--parents", "-n", "1", sha).split()[1:]
    if len(parents) < 2:
        return []
    return _git(root, "rev-list", f"{parents[0]}..{parents[1]}").split()


def promotion_body(pulls: list[Pull], reverted: tuple[Pull, ...] | list[Pull] = (),
                   unsynced: list[str] | tuple[str, ...] = ()) -> str:
    def issues(numbers: tuple[int, ...] | list[int]) -> str:
        return ", ".join(f"#{n}" for n in numbers)

    lines = [f"Promotes dev to main: {len(pulls)} pull request{'s' if len(pulls) != 1 else ''}.", "",
             "Merge with a merge commit, not a squash, so dev's merges stay on main's history.", ""]
    # A title's own closing words are made inert: only the "Fixes" lines at
    # the end close anything.
    lines += [f"- #{p.number} {_defused(p.title)}" + (f" (for {issues(p.closes)})" if p.closes else "") for p in pulls]
    fixes = dict.fromkeys(n for p in pulls for n in p.closes)
    if reverted:
        lines += ["", "Reverted on dev, so left out:", ""]
        for p in reverted:
            # An issue another promoted pull request fixes closes either way.
            own = [n for n in p.closes if n not in fixes]
            lines.append(f"- #{p.number} {_defused(p.title)}" + (f" (left open: {issues(own)})" if own else ""))
        # A commit message's closing keyword acts once the commit is on main,
        # reverted or not.
        reopen = [n for p in reverted for n in p.commit_closes if n not in fixes]
        if reopen:
            lines += ["", f"Their commits' messages name {issues(list(dict.fromkeys(reopen)))} with a closing "
                      "keyword, so GitHub closes those when this merges: reopen them afterwards."]
    if unsynced:
        # They belong on dev too, or dev goes on without them and every
        # later promotion has to reconcile the two again.
        lines += ["", "main has changes dev lacks. Merge main into dev in a pull request before this "
                  "merges:", "", *(f"- {_defused(c)}" for c in unsynced)]
    if fixes:
        lines += ["", *(f"Fixes #{n}" for n in fixes)]
    return "\n".join(lines) + "\n"


def keep_added_fixes(old_body: str, body: str) -> str:
    """body, plus the "Fixes #N" lines someone added to the promotion by hand
    (old_body) that body doesn't already close. A refresh rewrites the whole
    body, and would otherwise drop them."""
    have = set(closed_issues(body))
    added = [line.strip() for line in old_body.splitlines()
             if re.fullmatch(r"Fixes #\d+", line.strip()) and int(line.strip()[7:]) not in have]
    if not added:
        return body
    return body.rstrip("\n") + ("\n" if "\nFixes #" in body else "\n\n") + "\n".join(dict.fromkeys(added)) + "\n"


def _run(*args: str, input: str | None = None) -> str:
    return subprocess.run(args, cwd=REPO, check=True, capture_output=True, text=True, input=input).stdout


def _api(path: str, method: str = "GET", fields: dict | None = None) -> object:
    """A GitHub REST call through `gh api` ({owner}/{repo} is this checkout's
    repository). REST rather than `gh pr`, whose GraphQL some environments
    (cloud agent sessions) can't reach."""
    args = ["gh", "api", "-X", method, path]
    if fields is not None:
        args += ["--input", "-"]
    out = _run(*args, input=None if fields is None else json.dumps(fields))
    return json.loads(out) if out.strip() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="print the body instead of opening the pull request")
    args = parser.parse_args(argv)
    try:
        return _promote(args.dry_run)
    except subprocess.CalledProcessError as e:
        print(f"{' '.join(e.cmd)} failed:\n{e.stderr}", file=sys.stderr)
        return 1


def _promote(dry_run: bool) -> int:
    _run("git", "fetch", "--quiet", "origin")
    if subprocess.run(["git", "rev-parse", "--verify", "--quiet", "origin/dev"], cwd=REPO,
                      capture_output=True).returncode != 0:
        print("There is no origin/dev to promote.", file=sys.stderr)
        return 2
    merges = dev_merges()
    if not merges:
        print("dev has no pull requests main lacks.", file=sys.stderr)
        return 0
    pulls, reverted = [], []
    for merge in merges:
        data = _api(f"repos/{{owner}}/{{repo}}/pulls/{merge.number}")
        assert isinstance(data, dict)
        # GitHub reads closing keywords in a pull request's body, not its title.
        closes = closed_issues(data["body"] or "") + merge.commit_closes
        pull = Pull(merge.number, data["title"], tuple(dict.fromkeys(closes)), merge.commit_closes)
        (pulls if merge.present else reverted).append(pull)
    unsynced = main_only()
    if unsynced:
        print("main has changes dev lacks; merge main into dev first:\n  " + "\n  ".join(unsynced),
              file=sys.stderr)
    body = promotion_body(pulls, reverted, unsynced)
    if dry_run:
        print(body, end="")
        return 0
    open_pulls = _api("repos/{owner}/{repo}/pulls?base=main&state=open&per_page=100")
    assert isinstance(open_pulls, list)
    # dev of this repository: a fork's pull request from its own dev isn't it.
    existing = next((p for p in open_pulls if p["head"]["ref"] == "dev" and p["head"]["repo"]
                     and p["head"]["repo"]["full_name"] == p["base"]["repo"]["full_name"]), None)
    if existing:
        body = keep_added_fixes(existing["body"] or "", body)
        pull = _api(f"repos/{{owner}}/{{repo}}/pulls/{existing['number']}", "PATCH", {"body": body})
    else:
        # A draft, which Gates skips: an open promotion would run the full
        # suite again on every push to dev. Mark it ready to promote.
        pull = _api("repos/{owner}/{repo}/pulls", "POST",
                    {"title": TITLE, "head": "dev", "base": "main", "body": body, "draft": True})
    assert isinstance(pull, dict)
    print(pull["html_url"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
