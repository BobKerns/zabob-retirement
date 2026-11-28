"""The version command and --version flag on each installed tool (#825)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import click
import pytest
from click.testing import CliRunner
from git import GitCommandError, Repo

from zabob.retirement import version_cli
from zabob.retirement.amazon.cli import amazon_group_command
from zabob.retirement.cli import main
from zabob.retirement.sim import provenance
from zabob.retirement.sim.cli import sim_group_command
from zabob.retirement.version_cli import STAMPED, VersionInfo, version_info

GROUPS = [main, sim_group_command, amazon_group_command]
ROOT = Path(__file__).resolve().parents[1]

# A fixed answer for the output tests: the real one turns .dirty whenever a
# file under the checkout appears or goes, as other tests' scratch files can.
FIXED = VersionInfo(version="1.2.3+g0123456789ab", dirty=False, checkout="/somewhere")


@pytest.fixture
def fixed_version(monkeypatch: pytest.MonkeyPatch) -> VersionInfo:
    monkeypatch.setattr(version_cli, "version_info", lambda: FIXED)
    return FIXED


@pytest.mark.parametrize("group", GROUPS, ids=lambda g: g.name)
@pytest.mark.parametrize("args", [["version"], ["--version"]])
def test_version_names_the_build(group: click.Group, args: list[str], fixed_version: VersionInfo) -> None:
    result = CliRunner().invoke(group, args)
    assert result.exit_code == 0, result.output
    assert result.output == "zabob-retirement 1.2.3+g0123456789ab (checkout /somewhere)\n"


def test_version_short_is_the_bare_version(fixed_version: VersionInfo) -> None:
    result = CliRunner().invoke(sim_group_command, ["version", "--short"])
    assert result.exit_code == 0, result.output
    assert result.output == "1.2.3+g0123456789ab\n"


def test_version_json_fields(fixed_version: VersionInfo) -> None:
    result = CliRunner().invoke(sim_group_command, ["version", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert set(data) == {"name", "version", "dirty", "checkout", "python", "executable"}
    assert (data["version"], data["dirty"], data["checkout"]) == ("1.2.3+g0123456789ab", False, "/somewhere")


def test_version_short_and_json_conflict() -> None:
    result = CliRunner().invoke(sim_group_command, ["version", "--short", "--json"])
    assert result.exit_code != 0
    assert "can't be combined" in result.output


def test_checkout_version_carries_its_commit() -> None:
    info = version_info()
    repo = provenance.code_repo()
    if repo is None:
        assert info.checkout is None
        return
    with repo:
        assert f"+g{repo.head.commit.hexsha[:12]}" in info.version
        assert info.checkout == repo.working_tree_dir


def test_unborn_checkout_still_answers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A checkout with no commit yet: the version, labelled unknown."""
    monkeypatch.setattr(provenance, "code_repo", lambda: Repo.init(tmp_path))
    info = version_info()
    assert info.version.endswith("+unknown")
    assert info.checkout == str(tmp_path)


def test_git_refusing_still_answers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """git refusing the checkout ("dubious ownership", no git): still a version."""
    repo = Repo.init(tmp_path)

    def refuse(*_args: object, **_kwargs: object) -> str:
        raise GitCommandError("status", 128, b"fatal: detected dubious ownership")

    monkeypatch.setattr(type(repo.head), "commit", property(lambda _self: refuse()))
    monkeypatch.setattr(provenance, "code_repo", lambda: repo)
    result = CliRunner().invoke(sim_group_command, ["version", "--short"])
    assert result.exit_code == 0, result.output
    assert result.output.strip().endswith("+unknown")


def test_stamped_paths_match_the_build() -> None:
    """A checkout is dirty for the same paths a wheel's stamp is."""
    # Read, not run: hatch_build imports hatchling, which only a build has.
    found: dict[str, object] = {}
    for node in ast.parse((ROOT / "hatch_build.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                found[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:  # STAMPED itself refers to SHIPPED
                pass
    shipped = found["SHIPPED"]
    assert isinstance(shipped, tuple)
    assert STAMPED == ("src", *shipped, "pyproject.toml", "hatch_build.py")


def test_sim_version_skips_data_repo_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """``sim version`` works with no data repo, and says nothing about login."""
    from zabob.retirement.sim import cli

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("looked for a data repo")

    monkeypatch.setattr(cli, "_follow_working_folder", fail)
    monkeypatch.setattr(cli, "_note_not_logged_in", fail)
    result = CliRunner().invoke(sim_group_command, ["version"])
    assert result.exit_code == 0, result.output
