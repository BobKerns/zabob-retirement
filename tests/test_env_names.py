"""The environment variables' old names (#782): ``ANALYSIS_*`` is now
``ZABOB_*``, and a command run with an old one set says so."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from zabob.retirement.cli import main
from zabob.retirement.env_names import old_env_names
from zabob.retirement.sim.cli import sim_group_command


def test_old_names_are_split_into_stale_and_merely_repeated() -> None:
    environ = {"ANALYSIS_KEEP_SCENARIO": "1", "ANALYSIS_DATA_DIR": "/d", "ZABOB_DATA_DIR": "/d",
               "_ANALYSIS_COMPLETE": "bash_source", "ZABOB_ROLL": "off"}
    assert old_env_names(environ) == (["ANALYSIS_KEEP_SCENARIO"], ["ANALYSIS_DATA_DIR"])


def test_an_old_name_stops_the_command_and_names_the_new_one(
    test_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANALYSIS_KEEP_SCENARIO", "1")

    result = CliRunner().invoke(sim_group_command, ["switch", "base", "--data-dir", str(test_data_dir)])

    assert result.exit_code == 1
    assert "ANALYSIS_KEEP_SCENARIO is now ZABOB_KEEP_SCENARIO" in result.stderr
    assert "unset them: ANALYSIS_KEEP_SCENARIO" in result.stderr


def test_an_old_activated_shell_is_told_how_to_replace_its_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANALYSIS_DATA_DIR", str(tmp_path / "sim"))

    result = CliRunner().invoke(main, ["sim", "switch"])

    assert result.exit_code == 1
    assert result.stderr.count("ANALYSIS_DATA_DIR is now ZABOB_DATA_DIR") == 1  # both groups, one report
    assert f"git -C {tmp_path / 'sim'} mv activate-analysis activate-retirement" in result.stderr


def test_an_old_name_repeating_its_new_one_only_warns(
    test_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ZABOB_DATA_DIR", str(test_data_dir))
    monkeypatch.setenv("ANALYSIS_DATA_DIR", str(test_data_dir))

    result = CliRunner().invoke(sim_group_command, ["switch"])

    assert result.exit_code == 0, result.output
    assert "warning: ANALYSIS_DATA_DIR is now ZABOB_DATA_DIR; unset ANALYSIS_DATA_DIR" in result.stderr
