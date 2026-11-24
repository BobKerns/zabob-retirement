"""Open or refresh the pull request that promotes dev to main.

    .venv/bin/python scripts/promote_dev.py [--dry-run]

It lists the pull requests merged into dev since the last promotion and the
issues they close. "Fixes #N" in a pull request into dev closes nothing,
because GitHub acts on it only in a pull request into the default branch, so
the promotion's body repeats each one and merging it closes them all.

Merge the promotion with a merge commit, never a squash: dev's merges then
stay on main's history, where scripts/bisect_dev.py and
`git log --first-parent` find them. Needs `gh`, signed in.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys

REPO = Path(__file__).resolve().parent.parent
TITLE = "Promote dev to main"

# GitHub's merge commit, and a squash merge's "Title (#N)".
_MERGED_PR = re.compile(r"^Merge pull request #(\d+) |\(#(\d+)\)$")
# GitHub's closing keywords.
_CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Pull:
    number: int
    title: str
    closes: tuple[int, ...]


def pull_numbers(subjects: list[str]) -> list[int]:
    """The pull requests that dev's first-parent commit subjects merged, oldest first."""
    numbers = []
    for subject in subjects:
        if m := _MERGED_PR.search(subject):
            number = int(m.group(1) or m.group(2))
            if number not in numbers:
                numbers.append(number)
    return numbers


def closed_issues(text: str) -> tuple[int, ...]:
    """The issues a pull request's title and body say it closes, in order."""
    return tuple(dict.fromkeys(int(n) for n in _CLOSES.findall(text)))


def promotion_body(pulls: list[Pull]) -> str:
    lines = [f"Promotes dev to main: {len(pulls)} pull request{'s' if len(pulls) != 1 else ''}.", "",
             "Merge with a merge commit, not a squash, so dev's merges stay on main's history.", ""]
    lines += [f"- #{p.number} {p.title}" + (f" (closes {', '.join(f'#{n}' for n in p.closes)})" if p.closes else "")
              for p in pulls]
    issues = dict.fromkeys(n for p in pulls for n in p.closes)
    if issues:
        lines += ["", *(f"Fixes #{n}" for n in issues)]
    return "\n".join(lines) + "\n"


def _run(*args: str, input: str | None = None) -> str:
    return subprocess.run(args, cwd=REPO, check=True, capture_output=True, text=True, input=input).stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="print the body instead of opening the pull request")
    args = parser.parse_args(argv)

    _run("git", "fetch", "--quiet", "origin")
    try:
        _run("git", "rev-parse", "--verify", "--quiet", "origin/dev")
    except subprocess.CalledProcessError:
        print("There is no origin/dev to promote.", file=sys.stderr)
        return 2
    subjects = _run("git", "log", "--first-parent", "--reverse", "--format=%s", "origin/main..origin/dev").splitlines()
    if not subjects:
        print("dev has nothing main lacks.", file=sys.stderr)
        return 0
    pulls = []
    for number in pull_numbers(subjects):
        data = json.loads(_run("gh", "pr", "view", str(number), "--json", "title,body"))
        pulls.append(Pull(number, data["title"], closed_issues(f"{data['title']}\n{data['body']}")))
    body = promotion_body(pulls)
    if args.dry_run:
        print(body, end="")
        return 0
    existing = _run("gh", "pr", "list", "--base", "main", "--head", "dev", "--state", "open",
                    "--json", "number", "--jq", ".[0].number // empty").strip()
    if existing:
        _run("gh", "pr", "edit", existing, "--body-file", "-", input=body)
        print(_run("gh", "pr", "view", existing, "--json", "url", "--jq", ".url").strip())
    else:
        print(_run("gh", "pr", "create", "--base", "main", "--head", "dev", "--title", TITLE,
                   "--body-file", "-", input=body).strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
