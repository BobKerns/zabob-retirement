"""The setup-test and install-test containers (#674): one base, and
start-container.sh's options."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("name", ["setup-test", "install-test"])
def test_each_test_image_is_built_from_the_shared_base(repo_root: Path, name: str) -> None:
    dockerfile = (repo_root / "docker" / name / "Dockerfile").read_text()
    assert re.search(r"^ARG BASE=analysis-test-base$", dockerfile, re.M)
    assert re.search(r"^FROM \$\{BASE\}$", dockerfile, re.M)
    script = (repo_root / "scripts" / "start-container.sh").read_text()
    assert 'docker build -q -t "$base" docker/base' in script


@pytest.mark.parametrize("args", [["--test"], ["--local"], ["--version", "1.0"], ["--install", "--fresh"],
                                  ["--install", "--setup"], ["--bogus"]])
def test_start_container_refuses_options_that_dont_go_together(repo_root: Path, args: list[str]) -> None:
    # Refused before Docker is reached, so this runs without it.
    done = subprocess.run(["sh", repo_root / "scripts" / "start-container.sh", *args],
                          capture_output=True, text=True)
    assert done.returncode == 2, done.stdout + done.stderr
    assert done.stderr.startswith("start-container: ")
