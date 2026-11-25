"""Every action a workflow uses is pinned to a commit (#733).

A tag or branch can be moved by whoever controls the action's repository,
and the code behind it then runs with our tokens (the publish job holds
PyPI's trusted-publishing credentials). A full commit SHA can't be moved.
The trailing `# vX.Y.Z` comment says which release the SHA is, and is what
Dependabot (.github/dependabot.yml) rewrites along with the SHA.

The repository setting that requires SHA pins rejects a bad workflow only
when it runs; this test catches one before it merges.
"""

# cspell:ignore pypa

from __future__ import annotations

from pathlib import Path
import re

import pytest

USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<ref>\S+)(?P<rest>.*)$")
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"^\s+#\s*v\d+(\.\d+)*\s*$")
# A Docker image is pinned by its digest instead.
DOCKER = re.compile(r"^docker://[^@\s]+@sha256:[0-9a-f]{64}$")


def _files(repo_root: Path) -> list[Path]:
    github = repo_root / ".github"
    return sorted([
        *github.glob("workflows/*.y*ml"),
        *github.glob("actions/**/action.y*ml"),
    ])


def _uses(repo_root: Path) -> list[tuple[str, str, str]]:
    found = []
    for path in _files(repo_root):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if match := USES.match(line):
                where = f"{path.relative_to(repo_root)}:{number}"
                found.append((where, match["ref"].strip("'\""), match["rest"]))
    return found


def test_workflows_use_actions(repo_root: Path) -> None:
    # Guards the regex: a pattern that matched nothing would pass every test below.
    assert len(_uses(repo_root)) > 10


@pytest.mark.parametrize("ref, rest, ok", [
    ("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "  # v7.0.1", True),
    ("github/codeql-action/init@3d3c42e5aac5ba805825da76410c181273ba90b1", "  # v3.29.0", True),
    ("actions/checkout@v7", "", False),
    ("pypa/gh-action-pypi-publish@release/v1", "", False),
    ("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "", False),
    ("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "  # pinned", False),
    ("actions/checkout@3d3c42e", "  # v7.0.1", False),
])
def test_what_counts_as_pinned(ref: str, rest: str, ok: bool) -> None:
    assert _pinned(ref, rest) is ok


def _pinned(ref: str, rest: str) -> bool:
    if ref.startswith("./") or DOCKER.match(ref):
        return True
    return bool(PINNED.match(ref) and VERSION_COMMENT.match(rest))


def test_every_action_is_pinned_to_a_commit(repo_root: Path) -> None:
    unpinned = [f"{where}: {ref}{rest}" for where, ref, rest in _uses(repo_root) if not _pinned(ref, rest)]
    assert not unpinned, (
        "Pin each to a full commit SHA with its release as a comment, "
        "e.g. actions/checkout@<40-hex sha>  # v7.0.1\n" + "\n".join(unpinned)
    )


def test_one_action_one_version(repo_root: Path) -> None:
    # Dependabot moves them together; a hand edit that pins one step
    # differently is a mistake, or at least worth a second look.
    versions: dict[str, set[str]] = {}
    for _, ref, rest in _uses(repo_root):
        if "@" in ref and not ref.startswith(("./", "docker://")):
            action, _, sha = ref.partition("@")
            versions.setdefault(action, set()).add(f"{sha}{rest.strip()}")
    assert {a: v for a, v in versions.items() if len(v) > 1} == {}
