"""What a release to PyPI rests on (#662): both packages carry one version,
and the page PyPI shows has no links that only work on GitHub."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


def _project(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))["project"]


def test_zabob_retire_has_and_pins_zabob_retirement_s_version(repo_root: Path) -> None:
    version = _project(repo_root / "pyproject.toml")["version"]
    retire = _project(repo_root / "packages" / "zabob-retire" / "pyproject.toml")
    assert retire["version"] == version
    assert retire["dependencies"] == [f"zabob-retirement=={version}"]
    # publish.yml checks the pin by this exact line.
    assert f'dependencies = ["zabob-retirement=={version}"]' in \
        (repo_root / "packages" / "zabob-retire" / "pyproject.toml").read_text(encoding="utf-8").splitlines()


def test_the_pypi_page_links_only_absolute_urls(repo_root: Path) -> None:
    project = _project(repo_root / "pyproject.toml")
    page = (repo_root / project["readme"]).read_text(encoding="utf-8")
    targets = re.findall(r"\]\(([^)\s]+)", page)
    assert targets, "no links found: the pattern is out of date"
    assert [t for t in targets if not t.startswith("https://")] == []
