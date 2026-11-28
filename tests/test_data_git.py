"""#840: the data repo's git setup: the hooks' preamble and the notebook
clean filter, set up by ``sim init`` and again by ``sim builder install``."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from zabob.retirement.oscompat import WINDOWS
from zabob.retirement.sim import data_git

RUN_NOTEBOOK = json.dumps({
    "cells": [{"cell_type": "code", "execution_count": 4, "id": "x", "metadata": {},
               "outputs": [{"output_type": "stream", "name": "stdout", "text": ["$1,234,567\n"]}],
               "source": ["net_worth()"]}],
    "metadata": {"kernelspec": {"display_name": "Py", "name": "python3"}}, "nbformat": 4, "nbformat_minor": 5,
})


def _git(root: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False, env=env)


def _program_sim(repo_root: Path) -> Path:
    for sim in (repo_root / ".venv" / "bin" / "sim", repo_root / ".venv" / "Scripts" / "sim.exe"):
        if sim.exists():
            return sim
    pytest.skip("no .venv sim in this checkout")


def test_install_sets_up_the_filter_once(data_repo_sim: Path) -> None:
    root = data_repo_sim.parent
    done = data_git.install(root)
    assert any(line.startswith("installed") and line.endswith(data_git.CLEAN_FILTER_NAME) for line in done)
    hooks = data_git.hooks_dir(root)
    assert data_git.ours(hooks / data_git.PREAMBLE_NAME) and data_git.ours(hooks / data_git.CLEAN_FILTER_NAME)
    assert b"\r" not in (hooks / data_git.PREAMBLE_NAME).read_bytes()
    assert data_git.ATTRIBUTES in (root / ".gitattributes").read_text(encoding="utf-8").splitlines()
    for key, value in data_git.CONFIG.items():
        assert _git(root, "config", "--get", key).stdout.strip() == value
    assert data_git.problems(root) == []
    assert data_git.install(root) == []  # nothing left to do


def test_a_notebook_is_committed_without_its_outputs(data_repo_sim: Path, repo_root: Path) -> None:
    """Through the program sim/.analysis names."""
    root = data_repo_sim.parent
    _program_sim(repo_root)
    (data_repo_sim / ".analysis").write_text(f"{repo_root}\n", encoding="utf-8")
    data_git.install(root)
    (root / "a.ipynb").write_text(RUN_NOTEBOOK, encoding="utf-8")
    assert _git(root, "add", "a.ipynb").returncode == 0
    staged = json.loads(_git(root, "show", ":a.ipynb").stdout)
    assert staged["cells"][0]["outputs"] == [] and staged["cells"][0]["execution_count"] is None
    # diff's textconv cleans the working copy the same way: nothing to show.
    assert _git(root, "diff", "--stat").stdout == ""


@pytest.mark.skipif(WINDOWS, reason="PATH lookup of a POSIX shim")
def test_without_analysis_the_filter_finds_sim_on_path(data_repo_sim: Path, repo_root: Path, tmp_path: Path) -> None:
    """A data repo carried to a machine its sim/.analysis doesn't name."""
    root = data_repo_sim.parent
    sim = _program_sim(repo_root)
    (data_repo_sim / ".analysis").write_text(f"{tmp_path / 'gone'}\n", encoding="utf-8")
    data_git.install(root)
    (root / "a.ipynb").write_text(RUN_NOTEBOOK, encoding="utf-8")
    bare = {**os.environ, "PATH": os.pathsep.join(p for p in os.environ["PATH"].split(os.pathsep)
                                                   if not (Path(p) / "sim").exists())}
    failed = _git(root, "add", "a.ipynb", env=bare)
    assert failed.returncode != 0 and "can't find sim" in failed.stderr  # required: no outputs slip in
    on_path = tmp_path / "bin"
    on_path.mkdir()
    (on_path / "sim").symlink_to(sim)
    assert _git(root, "add", "a.ipynb", env={**bare, "PATH": f"{on_path}{os.pathsep}{bare['PATH']}"}).returncode == 0


def test_install_replaces_an_nbstripout_filter(data_repo_sim: Path) -> None:
    """As `nbstripout --install` leaves it, naming a Python since moved."""
    root = data_repo_sim.parent
    _git(root, "config", "filter.nbstripout.clean", "'/gone/.venv/bin/python' -m nbstripout")
    _git(root, "config", "filter.nbstripout.required", "true")
    _git(root, "config", "diff.ipynb.textconv", "'/gone/.venv/bin/python' -m nbstripout -t")
    info = data_git._git_path(root, "info/attributes")
    info.parent.mkdir(parents=True, exist_ok=True)
    info.write_text("*.ipynb filter=nbstripout\n*.zpln filter=nbstripout\n*.ipynb diff=ipynb\n", encoding="utf-8")
    (root / ".gitattributes").write_text("* text=auto\n*.ipynb filter=nbstripout diff=ipynb\n", encoding="utf-8")
    assert len(data_git.problems(root)) >= 4
    done = data_git.install(root)
    assert "removed git config filter.nbstripout, which this filter replaces" in done
    assert _git(root, "config", "--get-regexp", "nbstripout|^diff\\.ipynb").stdout == ""
    assert info.read_text(encoding="utf-8") == "*.zpln filter=zabob-notebook\n"
    assert (root / ".gitattributes").read_text(encoding="utf-8") == f"* text=auto\n{data_git.ATTRIBUTES}\n"
    assert data_git.problems(root) == []


def test_install_refuses_a_script_not_its_own(data_repo_sim: Path) -> None:
    root = data_repo_sim.parent
    hooks = data_git.hooks_dir(root)
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / data_git.PREAMBLE_NAME).write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    with pytest.raises(data_git.SetupError, match="isn't ours"):
        data_git.install(root)
    assert data_git.problems(root)[0].endswith("isn't ours")


def test_a_folder_inside_another_repository_is_left_alone(tmp_path: Path) -> None:
    """A checkout's ignored data/private, say: that config isn't the data repo's."""
    if shutil.which("git") is None:
        pytest.skip("no git")
    _git(tmp_path, "init", "-q")
    inner = tmp_path / "data" / "private"
    inner.mkdir(parents=True)
    assert not data_git.is_repo(inner) and data_git.problems(inner) == []
    with pytest.raises(data_git.SetupError):
        data_git.install(inner)
