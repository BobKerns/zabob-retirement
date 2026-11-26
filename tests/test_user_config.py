"""No activation step (#687, #773): `sim init` makes the data repo it creates
the user's, the commands use it from any folder and shell, `sim switch --data`
or a command run in another data repo switches it, `sim login` says who the
user is, and $ANALYSIS_DATA_DIR and --data-dir still come first."""
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


def _lines(result: Result) -> dict[str, str]:
    """`sim switch`'s summary, by label: User, Data repo, Current scenario."""
    return dict(line.split(": ", 1) for line in result.stdout.splitlines() if ": " in line)


def test_the_data_repo_sim_init_made_is_found_with_no_activation(made: Path) -> None:
    assert user_config.default_data_dir() == made.resolve()
    result = _sim("check", "base")
    assert result.exit_code == 0, result.output
    shown = _lines(_sim("switch"))
    assert shown["Data repo"] == str(made.parent) and shown["Current scenario"] == "base"


def test_sim_init_leaves_the_user_to_log_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """#773: `sim init` records the data repo and its scenario, but not who
    you are, so the next command points at `sim login`."""
    (user_config.config_dir() / "user").unlink()
    monkeypatch.chdir(tmp_path)
    made = _sim("init", "household", *_ALICE, "--no-builder")
    assert made.exit_code == 0, made.output
    assert "Then `sim login` says who you are." in made.output
    assert user_config.user_name() is None
    assert user_config.read_scenario(tmp_path / "household" / "sim") == (True, "base")

    noted = _sim("account", "list")
    assert noted.exit_code == 0, noted.output
    assert "Not logged in: `sim login` says who you are" in noted.stderr
    assert "Not logged in" not in noted.stdout


def test_sim_login_records_a_name_the_same_in_every_data_repo(
    made: Path, test_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _sim("login", "bill")
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0].startswith("Logged in as bill (was ")
    assert _lines(result)["User"] == "bill"
    assert "Not logged in" not in result.stderr
    assert user_config.user_name() == "bill"
    assert scenario.current_user(made) == scenario.current_user(test_data_dir) == "bill"
    # Not one of the household's people: any name will do.
    assert _sim("login", "the accountant").exit_code == 0
    assert user_config.current_user() == "the accountant"
    # $ANALYSIS_USER, for scripts, comes first.
    monkeypatch.setenv("ANALYSIS_USER", "script")
    assert user_config.current_user() == "script"
    warned = _sim("login", "bill")
    assert "this shell's ANALYSIS_USER, script, comes first" in warned.stderr


def test_sim_login_with_no_name_takes_the_login_name(made: Path) -> None:  # noqa: ARG001 - a data repo to show
    from zabob.retirement.oscompat import login_name

    (user_config.config_dir() / "user").unlink()
    result = _sim("login")
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == f"Logged in as {login_name()}"
    assert user_config.user_name() == login_name()


@pytest.mark.uses_current_scenario_write
def test_sim_login_can_name_the_data_repo_and_scenario_too(made: Path, test_data_dir: Path) -> None:
    result = _sim("login", "alice", "--data", str(test_data_dir), "--scenario", "retire_alice")
    assert result.exit_code == 0, result.output
    shown = _lines(result)
    assert shown["User"] == "alice" and shown["Current scenario"] == "retire_alice"
    assert user_config.default_data_dir() == test_data_dir.resolve()
    assert user_config.read_scenario(test_data_dir) == (True, "retire_alice")
    assert user_config.read_scenario(made) == (True, "base")  # each data repo keeps its own


def test_analysis_data_dir_comes_before_the_default(
    made: Path, test_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANALYSIS_DATA_DIR", str(test_data_dir))
    assert user_config.data_dir_setting() == str(test_data_dir)
    assert _lines(_sim("switch"))["Data repo"] == str(test_data_dir)
    assert user_config.default_data_dir() == made.resolve()  # not recorded


def test_sim_switch_data_switches_the_data_repo(made: Path, test_data_dir: Path, tmp_path: Path) -> None:
    # test_data_dir is a data dir itself, not a repo with sim/ in it: both are taken.
    result = _sim("switch", "--data", str(test_data_dir))
    assert result.exit_code == 0, result.output
    assert f"Data repo is now {test_data_dir} (was {made.parent})" in result.stdout
    assert user_config.default_data_dir() == test_data_dir.resolve()

    assert _sim("switch", "--data", str(made.parent)).exit_code == 0
    assert user_config.default_data_dir() == made.resolve()
    assert "Data repo is now" not in _sim("switch", "--data", str(made)).stdout  # already it

    refused = _sim("switch", "--data", str(tmp_path / "elsewhere"))
    assert refused.exit_code != 0 and "isn't a data repo" in refused.output


def test_with_no_data_repo_the_message_says_how_to_get_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = _sim("check", "base")
    assert result.exit_code != 0
    assert "`sim init`" in result.output and "`sim switch --data DIR`" in result.output


def test_a_default_that_is_gone_is_no_default(made: Path) -> None:
    (made / "persons.csv").unlink()
    assert user_config.default_data_dir() is None
    assert user_config.data_dir_setting() is None


def test_the_config_file_survives_a_windows_path(tmp_path: Path) -> None:
    """The settings are plain text: backslashes round-trip."""
    target = tmp_path / r"back\slash"
    (target).mkdir()
    (target / "persons.csv").write_text("id\n", encoding="utf-8")
    user_config.set_default_data_dir(target)
    assert user_config.default_data_dir() == target.resolve()


def test_the_config_file_survives_a_non_ascii_path(tmp_path: Path) -> None:
    """The path is written as itself, in UTF-8."""
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
    # Inside a code checkout with data/private/sim.
    checkout = tmp_path / "checkout"
    (checkout / "data" / "private").mkdir(parents=True)
    (checkout / "data" / "private" / "sim").symlink_to(test_data_dir, target_is_directory=True)
    (checkout / "src").mkdir()
    assert user_config.local_data_dir(checkout / "src") == checkout / "data" / "private" / "sim"
    # Using it isn't recording it: a notebook opened there doesn't move the
    # user's data repo.
    monkeypatch.chdir(tmp_path / "elsewhere")
    assert user_config.data_dir_setting() == str(made.resolve())


def test_a_sim_command_in_a_data_repo_makes_it_yours_and_says_so(
    made: Path, other_data_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#773: `cd` into a data repo and run a command there, and it is the one
    every command uses after, wherever they're run."""
    (other_data_repo.parent / "notes").mkdir()
    monkeypatch.chdir(other_data_repo.parent / "notes")

    result = _sim("account", "list", "--scenario", "retire_alice")
    assert result.exit_code == 0, result.output
    assert f"Data repo is now {other_data_repo.parent} (was {made.parent}): the one this folder is in" \
        in result.stderr
    assert user_config.default_data_dir() == other_data_repo.resolve()
    assert "Data repo is now" not in _sim("switch").stderr  # already it

    monkeypatch.chdir(tmp_path / "elsewhere")
    assert user_config.data_dir_setting() == str(other_data_repo.resolve())


def test_a_checkouts_data_private_is_used_there_but_not_recorded(
    made: Path, test_data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A worktree's data/private is often template data, gone with the
    worktree: the user's data repo stays theirs."""
    checkout = tmp_path / "checkout"
    (checkout / "data" / "private").mkdir(parents=True)
    (checkout / "data" / "private" / "sim").symlink_to(test_data_dir, target_is_directory=True)
    monkeypatch.chdir(checkout)
    result = _sim("switch")
    assert result.exit_code == 0, result.output
    assert "Data repo is now" not in result.stderr
    assert user_config.data_dir_setting() == str(checkout / "data" / "private" / "sim")
    assert user_config.default_data_dir() == made.resolve()


def test_a_lookup_never_moves_the_data_repo(
    made: Path, other_data_repo: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANALYSIS_KEEP_SCENARIO", "1")
    monkeypatch.chdir(other_data_repo)
    result = _sim("switch")
    assert result.exit_code == 0, result.output
    assert "Data repo is now" not in result.stderr
    assert user_config.default_data_dir() == made.resolve()


def test_settings_that_cant_be_written_only_warn(
    made: Path, other_data_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,  # noqa: ARG001 - a repo to leave
) -> None:
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(blocked))
    monkeypatch.setenv("APPDATA", str(blocked))
    monkeypatch.setenv("ANALYSIS_USER", "alice")
    monkeypatch.chdir(other_data_repo)
    result = _sim("account", "list", "--scenario", "retire_alice")
    assert result.exit_code == 0, result.output
    assert "warning: couldn't record" in result.stderr


def test_sim_login_follows_the_working_folder_too(
    made: Path, other_data_repo: Path, monkeypatch: pytest.MonkeyPatch,  # noqa: ARG001 - the one it replaces
) -> None:
    monkeypatch.chdir(other_data_repo)
    result = _sim("login", "bill")
    assert result.exit_code == 0, result.output
    assert "Data repo is now" in result.stderr
    assert user_config.default_data_dir() == other_data_repo.resolve()


def test_switch_login_before_logging_in_has_no_note(made: Path) -> None:  # noqa: ARG001 - a data repo to show
    (user_config.config_dir() / "user").unlink()
    result = _sim("switch", "--login", "bill")
    assert result.exit_code == 0, result.output
    assert "Not logged in" not in result.stderr
    assert user_config.user_name() == "bill"


@pytest.mark.parametrize("given", ["--data-dir", "env"])
def test_a_data_repo_given_for_one_command_or_shell_is_not_recorded(
    given: str, made: Path, test_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--data-dir and $ANALYSIS_DATA_DIR are for scripts: neither the one they
    name nor the working folder's becomes the user's."""
    monkeypatch.chdir(test_data_dir)
    args = ["switch"]
    if given == "env":
        monkeypatch.setenv("ANALYSIS_DATA_DIR", str(made))
    else:
        args += ["--data-dir", str(made)]
    result = _sim(*args)
    assert result.exit_code == 0, result.output
    assert "Data repo is now" not in result.output
    assert user_config.default_data_dir() == made.resolve()


def test_sim_init_no_builder_keeps_a_default_already_recorded(made: Path, tmp_path: Path) -> None:
    result = _sim("init", str(tmp_path / "scratch"), *_ALICE, "--no-builder")
    assert result.exit_code == 0, result.output
    assert "left your data repo as" in result.output
    assert user_config.default_data_dir() == made.resolve()


def test_a_scenario_is_credited_to_who_is_logged_in_in_any_data_repo(made: Path, tmp_path: Path) -> None:
    """Not a person of the data repo (#773): ``.analysis_user`` no longer counts."""
    result = _sim("init", str(tmp_path / "bills"), "--id", "bill", "--display", "Bill Example",
                  "--birthdate", "1958-03-01", "--sex", "m", "--filing-status", "MFJ", "--no-builder")
    assert result.exit_code == 0, result.output
    bills = tmp_path / "bills" / "sim"
    assert user_config.default_data_dir() == made.resolve()
    user_config.set_user("carol")
    made_in = scenario.create_scenario(bills, "what_if", "base")
    assert "carol" in (made_in / "scenario.csv").read_text(encoding="utf-8").splitlines()[1].split(",")
