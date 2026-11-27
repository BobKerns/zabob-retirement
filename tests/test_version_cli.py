"""The version command and --version flag on each installed tool (#825)."""

from __future__ import annotations

import json

import click
import pytest
from click.testing import CliRunner

from zabob.retirement.amazon.cli import amazon_group_command
from zabob.retirement.cli import main
from zabob.retirement.sim.cli import sim_group_command
from zabob.retirement.version_cli import version_info

GROUPS = [main, sim_group_command, amazon_group_command]


@pytest.mark.parametrize("group", GROUPS, ids=lambda g: g.name)
@pytest.mark.parametrize("args", [["version"], ["--version"]])
def test_version_names_the_build(group: click.Group, args: list[str]) -> None:
    result = CliRunner().invoke(group, args)
    assert result.exit_code == 0, result.output
    assert result.output.strip() == version_info().line()
    assert result.output.startswith("zabob-retirement ")


def test_version_short_is_the_bare_version() -> None:
    result = CliRunner().invoke(sim_group_command, ["version", "--short"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == version_info().version


def test_version_json_fields() -> None:
    result = CliRunner().invoke(sim_group_command, ["version", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert set(data) == {"name", "version", "dirty", "checkout", "python", "executable"}
    assert data["version"] == version_info().version


def test_version_short_and_json_conflict() -> None:
    result = CliRunner().invoke(sim_group_command, ["version", "--short", "--json"])
    assert result.exit_code != 0
    assert "can't be combined" in result.output


def test_checkout_version_carries_its_commit() -> None:
    from zabob.retirement.sim import provenance

    info = version_info()
    repo = provenance.code_repo()
    if repo is None:
        assert info.checkout is None
        return
    with repo:
        assert f"+g{repo.head.commit.hexsha[:12]}" in info.version
        assert info.checkout == repo.working_tree_dir


def test_sim_version_skips_data_repo_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """``sim version`` works with no data repo, and says nothing about login."""
    from zabob.retirement.sim import cli

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("looked for a data repo")

    monkeypatch.setattr(cli, "_follow_working_folder", fail)
    monkeypatch.setattr(cli, "_note_not_logged_in", fail)
    result = CliRunner().invoke(sim_group_command, ["version"])
    assert result.exit_code == 0, result.output
