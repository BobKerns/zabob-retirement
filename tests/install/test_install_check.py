"""Checks of an installed Zabob Retirement (#674): what a new user's first
session does, run against the program on PATH with no code checkout.

They skip from a checkout (the ``installed`` marker; tests/conftest.py), so
they run where the program was installed from PyPI, TestPyPI or a built
wheel: the install-test container (`scripts/start-container.sh --install
--run-tests`).
"""

from __future__ import annotations

import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest

from zabob.retirement import resources
from zabob.retirement.sim import provenance

# Each runs the program in a subprocess, which takes seconds. Through bash and
# activate-retirement, so not on native Windows: test_install_native is its
# shell-free twin (#687).
pytestmark = [pytest.mark.installed, pytest.mark.slow,
              pytest.mark.skipif(sys.platform == "win32", reason="bash and activate-retirement")]

BIN = Path(sys.executable).parent
"""The installed program's scripts: `sim`, `analysis`, `jupyter`."""


@pytest.fixture(scope="module")
def session(new_user_env: dict[str, str]) -> dict[str, str]:
    """A new user's environment, with this install's commands on PATH."""
    return {**new_user_env, "PATH": f"{BIN}:/usr/bin:/bin", "ZABOB_NO_BUILDER": "1"}


def _shell(env: dict[str, str], command: str) -> str:
    """Run ``command`` in bash, in the user's home folder."""
    done = subprocess.run(["bash", "-c", command], cwd=env["HOME"], env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


@pytest.fixture(scope="module")
def data_repo(session: dict[str, str]) -> Path:
    """``sim init --example``: the prototype household in ~/zabob-retirement."""
    _shell(session, "sim init --example")
    return Path(session["HOME"]) / "zabob-retirement"


def _activated(env: dict[str, str], root: Path, command: str) -> str:
    return _shell(env, f"source {root / 'sim' / 'activate-retirement'} && {command}")


def test_the_package_is_installed_with_no_checkout() -> None:
    assert resources.CHECKOUT_DIR is None
    assert (resources.TEMPLATES_DIR / "activate-retirement").is_file()
    assert (resources.PROTOTYPE_DIR / "persons.csv").is_file()
    # Stamped with the commit it was built from, so runs record which build made them.
    stamped, _dirty = provenance.installed_version()
    assert stamped.startswith(metadata.version("zabob-retirement") + "+g")


def test_init_example_makes_a_data_repo_paired_with_this_install(data_repo: Path) -> None:
    assert (data_repo / "sim" / ".analysis").read_text(encoding="utf-8") == f"{resources.INSTALLED}{BIN}\n"
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
