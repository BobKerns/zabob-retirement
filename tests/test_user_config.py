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


def test_the_config_file_survives_a_non_ascii_path(tmp_path: Path) -> None:
    """TOML has no surrogate-pair escapes, so the path is written as itself."""
    target = tmp_path / "café \U0001f4b0"
    target.mkdir()
    (target / "persons.csv").write_text("id\n", encoding="utf-8")
    user_config.set_default_data_dir(target)
    assert user_config.default_data_dir() == target.resolve()


@pytest.mark.parametrize("text", [
    'data = "x"\n',                   # not a table
    "[data]\ndir = 3\n",              # not a string
    "[data\n",                        # not TOML
])
def test_a_config_file_this_did_not_write_is_no_default(text: str) -> None:
    path = user_config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    assert user_config.default_data_dir() is None


def test_an_unreadable_config_file_is_no_default() -> None:
    path = user_config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"[data]\ndir = \"\xff\"\n")
    assert user_config.default_data_dir() is None
    path.unlink()
    path.mkdir()  # a folder where the file should be: OSError
    assert user_config.default_data_dir() is None


def test_the_data_repo_the_working_folder_is_in_comes_before_the_default(
    made: Path, test_data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Inside a data repo, at its root or below.
    other = tmp_path / "other"
    (other / "sim").mkdir(parents=True)
    (other / "sim" / "persons.csv").write_text("id\n", encoding="utf-8")
    (other / "notebooks").mkdir()
    assert user_config.local_data_dir(other / "notebooks") == other / "sim"
    monkeypatch.chdir(other / "notebooks")
    assert user_config.data_dir_setting() == str((other / "sim").resolve())
    out = _sim("use").output
    assert "(the data repo this folder is in)" in out and f"your default otherwise: {made.parent}" in out
    # Inside a code checkout with data/private/sim.
    checkout = tmp_path / "checkout"
    (checkout / "data" / "private").mkdir(parents=True)
    (checkout / "data" / "private" / "sim").symlink_to(test_data_dir, target_is_directory=True)
    (checkout / "src").mkdir()
    assert user_config.local_data_dir(checkout / "src") == checkout / "data" / "private" / "sim"
    # Anywhere else, the default.
    monkeypatch.chdir(tmp_path / "elsewhere")
    assert user_config.data_dir_setting() == str(made.resolve())


def test_sim_init_no_builder_keeps_a_default_already_recorded(made: Path, tmp_path: Path) -> None:
    result = _sim("init", str(tmp_path / "scratch"), *_ALICE, "--no-builder")
    assert result.exit_code == 0, result.output
    assert "left your default data repo as" in result.output
    assert user_config.default_data_dir() == made.resolve()


def test_a_scenario_is_credited_to_the_user_of_the_repo_it_is_made_in(made: Path, tmp_path: Path) -> None:
    """Not the default repo's user: ``--data-dir`` names another repo."""
    result = _sim("init", str(tmp_path / "bills"), "--id", "bill", "--display", "Bill Example",
                  "--birthdate", "1958-03-01", "--sex", "m", "--filing-status", "MFJ", "--no-builder")
    assert result.exit_code == 0, result.output
    bills = tmp_path / "bills" / "sim"
    assert user_config.default_data_dir() == made.resolve()
    assert scenario.current_user() == "alice"
    made_in = scenario.create_scenario(bills, "what_if", "base")
    assert "bill" in (made_in / "scenario.csv").read_text(encoding="utf-8").splitlines()[1].split(",")
