"""scripts/affected_tests.py picks the tests a change needs from tests/areas.toml."""

from __future__ import annotations

import importlib.util
from pathlib import Path, PurePosixPath
import subprocess
import sys
from types import ModuleType

import pytest


@pytest.fixture(scope="module")
def affected(repo_root: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("affected_tests", repo_root / "scripts" / "affected_tests.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses look their module up in sys.modules.
    sys.modules["affected_tests"] = module
    spec.loader.exec_module(module)
    return module


def _select(affected: ModuleType, *changed: str) -> tuple[list[str], list[str]]:
    return affected.select(list(changed), affected.load_areas())


def test_a_change_no_area_owns_selects_the_whole_suite(affected: ModuleType) -> None:
    tests, everything = _select(affected, "src/zabob/retirement/sim/engine.py", "src/zabob/retirement/videos/build.py")
    assert tests == [affected.ALL]
    assert everything == ["src/zabob/retirement/sim/engine.py"]


def test_a_change_an_area_owns_selects_its_tests(affected: ModuleType) -> None:
    tests, everything = _select(affected, "src/zabob/retirement/videos/build.py")
    assert "tests/test_videos.py" in tests
    assert "tests/test_engine.py" not in tests
    assert everything == []


def test_a_path_two_areas_own_selects_both_areas_tests(affected: ModuleType) -> None:
    tests, _ = _select(affected, "docs/videos/README.md")
    assert {"tests/test_videos.py", "tests/test_wheel.py"} <= set(tests)


def test_an_ignored_path_selects_nothing(affected: ModuleType) -> None:
    assert _select(affected, ".cspell/project-words.txt", ".github/copilot-instructions.md") == ([], [])


def test_a_changed_test_file_selects_itself(affected: ModuleType) -> None:
    assert _select(affected, "tests/test_dates.py") == (["tests/test_dates.py"], [])


def test_a_deleted_test_file_selects_nothing(affected: ModuleType) -> None:
    assert _select(affected, "tests/test_no_such_thing.py") == ([], [])


@pytest.mark.parametrize("path", ["tests/conftest.py", "tests/data/sim/business/README.md"])
def test_shared_test_setup_selects_the_whole_suite(affected: ModuleType, path: str) -> None:
    assert _select(affected, path) == ([affected.ALL], [path])


def test_every_area_pattern_still_matches(affected: ModuleType, repo_root: Path) -> None:
    """A renamed file leaves a pattern that matches nothing: its tests would
    silently drop out of the selection, or its paths fall to the whole suite."""
    tracked = subprocess.run(["git", "-C", str(repo_root), "ls-files"], check=True,
                             capture_output=True, text=True).stdout.splitlines()
    stale = []
    for area in affected.load_areas().areas:
        stale += [f"{area.name} path {p}" for p in area.paths
                  if not any(PurePosixPath(t).full_match(p) for t in tracked)]
        stale += [f"{area.name} test {p}" for p in area.tests if not list(repo_root.glob(p))]
    assert stale == []
