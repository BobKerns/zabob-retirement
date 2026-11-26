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

# They build the wheel from this checkout.
pytestmark = [pytest.mark.slow, pytest.mark.checkout]

SHIPPED = "zabob/retirement/_shipped/"


def test_wheel_ships_the_checkout_folders(built_wheel: Path, repo_root: Path) -> None:
    with zipfile.ZipFile(built_wheel) as wheel:
        names = set(wheel.namelist())
        info = wheel.read("zabob/retirement/_build_info.py").decode()
    for folder in ("templates", "notebooks", "prototype_data", "plugins"):
        tracked = subprocess.run(["git", "ls-files", folder], cwd=repo_root, capture_output=True, text=True,
                                 check=True).stdout.split()
        # Every tracked file ships (a link to a folder ships what it leads to).
        assert {SHIPPED + p for p in tracked if (repo_root / p).is_file()} <= names
    assert SHIPPED + "templates/scenarios/t_empty/scenario.csv" in names
    assert SHIPPED + "notebooks/net_worth.ipynb" in names
    assert SHIPPED + "notebooks/docs/user-guide.md" in names
    assert SHIPPED + "plugins/finance-research/skills/fund-tear-sheet/SKILL.md" in names
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
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"} | {"ZABOB_NO_BUILDER": "1"}
    done = subprocess.run([installed_wheel / "sim", "check", "--all", "--data-dir", data],
                          cwd=tmp_path, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "scenario(s) ok" in done.stdout


def test_installed_init_example_activates_and_runs(installed_wheel: Path, tmp_path: Path) -> None:
    """The whole first session of a `uv tool install` user, on the example data."""
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "gitconfig").write_text("[commit]\n\tgpgsign = false\n[init]\n\tdefaultBranch = main\n",
                                        encoding="utf-8")
    env = {"PATH": f"{installed_wheel}:/usr/bin:/bin", "HOME": str(home), "ZABOB_NO_BUILDER": "1",
           "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
           **{f"GIT_{who}_{what}": value for who in ("AUTHOR", "COMMITTER")
              for what, value in (("NAME", "t"), ("EMAIL", "t@t"))}}
    init = subprocess.run([installed_wheel / "sim", "init", "--example"], cwd=tmp_path, env=env,
                          capture_output=True, text=True)
    assert init.returncode == 0, init.stdout + init.stderr
    root = home / "zabob-retirement"
    assert (root / "sim" / ".analysis").read_text(encoding="utf-8") == f"installed:{installed_wheel}\n"
    assert (root / "notebooks" / "net_worth.ipynb").is_file()
    done = subprocess.run(
        ["bash", "-c", f"source {root / 'sim' / 'activate-retirement'} && sim switch && sim check base"],
        cwd=tmp_path, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Current scenario: base" in done.stdout and "ok" in done.stdout
