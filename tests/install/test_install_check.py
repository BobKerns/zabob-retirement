"""Checks of an installed Zabob Retirement (#674): what a new user's first
session does, run against the program on PATH with no code checkout.

They skip from a checkout (the ``installed`` marker; tests/conftest.py), so
they run where the program was installed from PyPI, TestPyPI or a built
wheel: the install-test container (`scripts/start-container.sh --install
--run-tests`).
"""

from __future__ import annotations

import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest

from zabob.retirement import resources
from zabob.retirement.sim import provenance

pytestmark = pytest.mark.installed

BIN = Path(sys.executable).parent
"""The installed program's scripts: `sim`, `analysis`, `jupyter`."""


@pytest.fixture(scope="module")
def session(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """A new user's environment: an empty home, and a git identity (which
    `sim init` commits with)."""
    top = tmp_path_factory.mktemp("install")
    home = top / "home"
    home.mkdir()
    (top / "gitconfig").write_text("[user]\n\tname = Alice Example\n\temail = alice@example.com\n"
                                   "[init]\n\tdefaultBranch = main\n")
    return {"PATH": f"{BIN}:/usr/bin:/bin", "HOME": str(home), "ANALYSIS_NO_BUILDER": "1",
            "GIT_CONFIG_GLOBAL": str(top / "gitconfig"), "LANG": os.environ.get("LANG", "C.UTF-8")}


def _shell(env: dict[str, str], command: str) -> str:
    """Run ``command`` in bash, in the data repo once there is one."""
    done = subprocess.run(["bash", "-c", command], cwd=env["HOME"], env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


@pytest.fixture(scope="module")
def data_repo(session: dict[str, str]) -> Path:
    """``sim init --example``: the prototype household in ~/zabob-retirement."""
    _shell(session, "sim init --example")
    return Path(session["HOME"]) / "zabob-retirement"


def _activated(env: dict[str, str], root: Path, command: str) -> str:
    return _shell(env, f"source {root / 'sim' / 'activate-analysis'} && {command}")


def test_the_package_is_installed_with_no_checkout() -> None:
    assert resources.CHECKOUT_DIR is None
    assert (resources.TEMPLATES_DIR / "activate-analysis").is_file()
    assert (resources.PROTOTYPE_DIR / "persons.csv").is_file()
    # Stamped with the commit it was built from, so runs record which build made them.
    stamped, _dirty = provenance.installed_version()
    assert stamped.startswith(metadata.version("zabob-retirement") + "+g")


def test_init_example_makes_a_data_repo_paired_with_this_install(data_repo: Path) -> None:
    assert (data_repo / "sim" / ".analysis").read_text() == f"{resources.INSTALLED}{BIN}\n"
    assert (data_repo / "notebooks" / "net_worth.ipynb").is_file()


def test_activation_puts_this_install_on_path(session: dict[str, str], data_repo: Path) -> None:
    out = _activated({**session, "PATH": "/usr/bin:/bin"}, data_repo, "command -v sim; sim switch")
    assert out.splitlines()[0] == str(BIN / "sim")
    assert "Current scenario: base" in out


def test_every_scenario_loads(session: dict[str, str], data_repo: Path) -> None:
    _activated(session, data_repo, "sim check --all")


def test_a_scenario_runs_and_reports(session: dict[str, str], data_repo: Path) -> None:
    out = _activated(session, data_repo, "sim run base && sim networth base")
    assert "net_worth" in out.lower().replace(" ", "_")


def test_the_notebooks_are_current(session: dict[str, str], data_repo: Path) -> None:
    _activated(session, data_repo, "sim notebooks copy")
    assert sorted(p.name for p in (data_repo / "notebooks").glob("*.ipynb")) == sorted(
        p.name for p in resources.NOTEBOOKS_DIR.glob("*.ipynb"))


def test_jupyter_lab_is_installed_beside_it() -> None:
    done = subprocess.run([BIN / "jupyter", "lab", "--version"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
