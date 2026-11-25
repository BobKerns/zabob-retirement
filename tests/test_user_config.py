"""No activation step (#687): `sim init` makes the data repo it creates the
user's default, the commands use it from any folder and shell, `sim use`
switches it, and $ANALYSIS_DATA_DIR still comes first."""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from zabob.retirement import user_config
from zabob.retirement.cli import main
from zabob.retirement.sim import scenario

_ALICE = ("--id", "alice", "--display", "Alice Example", "--birthdate", "1960-05-01",
          "--sex", "f", "--filing-status", "MFJ")


def _sim(*args: str) -> Result:
    return CliRunner().invoke(main, ["sim", *args])


@pytest.fixture
def made(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A data repo `sim init` made, and a working folder outside it; returns its data dir."""
    monkeypatch.chdir(tmp_path)
    result = _sim("init", str(tmp_path / "household"), *_ALICE, "--no-builder")
    assert result.exit_code == 0, result.output
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")
    return tmp_path / "household" / "sim"


def test_the_data_repo_sim_init_made_is_found_with_no_activation(made: Path) -> None:
    assert user_config.default_data_dir() == made.resolve()
    result = _sim("check", "base")
    assert result.exit_code == 0, result.output
    assert _sim("use").output == f"{made.parent} (your default)\n"
    # Who the user is comes from the data repo too.
    assert scenario.current_user() == "alice"


def test_analysis_data_dir_comes_before_the_default(
    made: Path, test_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANALYSIS_DATA_DIR", str(test_data_dir))
    assert user_config.data_dir_setting() == str(test_data_dir)
    out = _sim("use").output
    assert "(this shell's ANALYSIS_DATA_DIR)" in out and f"your default otherwise: {made.parent}" in out


def test_sim_use_switches_the_default(made: Path, test_data_dir: Path, tmp_path: Path) -> None:
    # test_data_dir is a data dir itself, not a repo with sim/ in it: both are taken.
    result = _sim("use", str(test_data_dir))
    assert result.exit_code == 0, result.output
    assert f"made {test_data_dir} your default data repo, in place of {made.parent}" in result.output
    assert user_config.default_data_dir() == test_data_dir.resolve()

    assert _sim("use", str(made.parent)).exit_code == 0
    assert user_config.default_data_dir() == made.resolve()

    refused = _sim("use", str(tmp_path / "elsewhere"))
    assert refused.exit_code != 0 and "isn't a data repo" in refused.output


def test_with_no_data_repo_the_message_says_how_to_get_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = _sim("check", "base")
    assert result.exit_code != 0
    assert "`sim init`" in result.output and "`sim use DIR`" in result.output


def test_a_default_that_is_gone_is_no_default(made: Path) -> None:
    (made / "persons.csv").unlink()
    assert user_config.default_data_dir() is None
    assert user_config.data_dir_setting() is None


def test_the_config_file_survives_a_windows_path(tmp_path: Path) -> None:
    """A JSON string is a TOML basic string: backslashes round-trip."""
    target = tmp_path / r"back\slash"
    (target).mkdir()
    (target / "persons.csv").write_text("id\n", encoding="utf-8")
    user_config.set_default_data_dir(target)
    assert user_config.default_data_dir() == target.resolve()
