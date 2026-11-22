"""The wheel a release ships (#662): what it carries beside the code, and
that an install with no checkout runs the simulator."""

from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from zabob.retirement import resources
from zabob.retirement.checkout import is_checkout

pytestmark = pytest.mark.slow

SHIPPED = "zabob/retirement/_shipped/"


def test_wheel_ships_the_checkout_folders(built_wheel: Path, repo_root: Path) -> None:
    with zipfile.ZipFile(built_wheel) as wheel:
        names = set(wheel.namelist())
        info = wheel.read("zabob/retirement/_build_info.py").decode()
    for folder in ("templates", "notebooks", "prototype_data"):
        tracked = subprocess.run(["git", "ls-files", folder], cwd=repo_root, capture_output=True, text=True,
                                 check=True).stdout.split()
        # Every tracked file ships (a link to a folder ships what it leads to).
        assert {SHIPPED + p for p in tracked if (repo_root / p).is_file()} <= names
    assert SHIPPED + "templates/scenarios/t_empty/scenario.csv" in names
    assert SHIPPED + "notebooks/net_worth.ipynb" in names
    assert SHIPPED + "notebooks/docs/user-guide.md" in names
    assert not any("__pycache__" in n or ".ipynb_checkpoints" in n for n in names)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True,
                          check=True).stdout.strip()
    assert f"COMMIT = {head!r}" in info


def test_checkout_reads_its_own_folders(repo_root: Path) -> None:
    assert resources.CHECKOUT_DIR == repo_root.resolve()
    assert resources.TEMPLATES_DIR == repo_root.resolve() / "templates"


def test_installed_program_runs_without_a_checkout(
    installed_wheel: Path, tmp_path: Path,
) -> None:
    python = installed_wheel / "python"
    probe = subprocess.run(
        [python, "-c", "from zabob.retirement import resources as r; from zabob.retirement.sim.provenance "
                       "import code_stamps; print(r.CHECKOUT_DIR, r.TEMPLATES_DIR, code_stamps().version)"],
        cwd=tmp_path, capture_output=True, text=True, check=True).stdout.split()
    checkout, templates, version = probe
    assert checkout == "None"
    assert Path(templates).is_dir() and not is_checkout(Path(templates).parents[3])
    assert "+g" in version  # the version, with the commit it was built from
    # The prototype data, as shipped, loads with the shipped templates.
    data = tmp_path / "data"
    shutil.copytree(Path(templates).parent / "prototype_data", data)
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"} | {"ANALYSIS_NO_BUILDER": "1"}
    done = subprocess.run([installed_wheel / "sim", "check", "--all", "--data-dir", data],
                          cwd=tmp_path, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "scenario(s) ok" in done.stdout
