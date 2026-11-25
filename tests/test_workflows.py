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

from collections.abc import Iterator
from pathlib import Path
import re

import pytest
import yaml

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


def _line_uses(text: str) -> Iterator[tuple[int, str, str]]:
    """Each block-style `uses:` line: its number, the ref, and what follows
    (where the version comment is, which a YAML parser drops)."""
    for number, line in enumerate(text.splitlines(), 1):
        if match := USES.match(line):
            yield number, match["ref"].strip("'\""), match["rest"]


def _yaml_uses(node: object) -> Iterator[str]:
    """Every `uses` value in the parsed file, however it is written."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "uses" and isinstance(value, str):
                yield value
            else:
                yield from _yaml_uses(value)
    elif isinstance(node, list):
        for item in node:
            yield from _yaml_uses(item)


def _uses(repo_root: Path) -> list[tuple[str, str, str]]:
    found = []
    for path in _files(repo_root):
        for number, ref, rest in _line_uses(path.read_text()):
            found.append((f"{path.relative_to(repo_root)}:{number}", ref, rest))
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


@pytest.mark.parametrize("text", [
    "steps:\n  - {uses: actions/checkout@v7}\n",
    'steps:\n  - "uses": actions/checkout@v7\n',
    "steps:\n  - name: x\n    uses: >-\n      actions/checkout@v7\n",
])
def test_a_uses_the_line_scan_misses_is_caught(text: str) -> None:
    lines = sorted(ref for _, ref, _ in _line_uses(text))
    assert lines != sorted(_yaml_uses(yaml.safe_load(text)))


def test_every_uses_is_one_block_style_line(repo_root: Path) -> None:
    # The pin check reads lines, to see the version comment. A `uses:` written
    # another way (flow style, a quoted key, a folded value) would slip past
    # it, so the lines must account for every `uses` YAML itself finds.
    for path in _files(repo_root):
        text = path.read_text()
        lines = sorted(ref for _, ref, _ in _line_uses(text))
        assert lines == sorted(_yaml_uses(yaml.safe_load(text))), path.relative_to(repo_root)


def test_one_action_one_version(repo_root: Path) -> None:
    # Dependabot moves them together; a hand edit that pins one step
    # differently is a mistake, or at least worth a second look.
    versions: dict[str, set[str]] = {}
    for _, ref, rest in _uses(repo_root):
        if "@" in ref and not ref.startswith(("./", "docker://")):
            action, _, sha = ref.partition("@")
            versions.setdefault(action, set()).add(f"{sha}{rest.strip()}")
    assert {a: v for a, v in versions.items() if len(v) > 1} == {}
