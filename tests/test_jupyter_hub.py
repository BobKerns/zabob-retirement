"""``sim jupyter hub`` and ``sim jupyter user`` (#766)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from traitlets.config import Config

from zabob.retirement.cli import main
from zabob.retirement.jupyter import hub, hub_config, singleuser

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the hub is Linux and macOS only")


def _sim(*args: str, input: str | None = None) -> Result:
    return CliRunner().invoke(main, ["sim", "jupyter", *args], input=input)


def test_users_are_added_listed_changed_and_deleted(
    hub_logins: dict[str, Path], data_repo_sim: Path,
) -> None:
    repo = data_repo_sim.parent
    result = _sim("user", "add", "alice", "--shared", str(repo))
    assert result.exit_code == 0, result.output
    assert f"Added alice: shares {repo}" in result.output
    result = _sim("user", "add", "bill", "--own", "https://example.invalid/household.git")
    assert result.exit_code == 0, result.output

    listed = _sim("user", "list").output.splitlines()
    assert listed == [f"alice: shares {repo}",
                      f"bill: own data repo {hub_logins['bill'] / 'zabob-retirement'}, "
                      "cloned from https://example.invalid/household.git"]

    result = _sim("user", "edit", "alice", "--own")
    assert result.exit_code == 0, result.output
    assert f"Now alice: own data repo {hub_logins['alice'] / 'zabob-retirement'}" in result.output
    assert "isn't there yet" in result.stderr  # no URL, and nothing to clone it from

    result = _sim("user", "delete", "bill", "--yes")
    assert result.exit_code == 0, result.output
    assert list(hub.read_users()) == ["alice"]


def test_a_user_must_be_a_login_and_new(hub_logins: dict[str, Path], data_repo_sim: Path) -> None:
    result = _sim("user", "add", "carol", "--own")
    assert result.exit_code == 1
    assert "there is no login 'carol' on this machine" in result.output
    assert _sim("user", "add", "alice", "--own").exit_code == 0
    result = _sim("user", "add", "alice", "--shared", str(data_repo_sim.parent))
    assert "alice is already a hub user; `sim jupyter user edit alice` changes it" in result.output
    result = _sim("user", "edit", "bill", "--own")
    assert "bill isn't a hub user" in result.output


def test_shared_needs_a_data_repo_and_defaults_to_the_one_in_use(
    hub_logins: dict[str, Path], data_repo_sim: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _sim("user", "add", "alice", "--shared", str(tmp_path))
    assert result.exit_code == 1
    assert "isn't a data repo" in result.output
    monkeypatch.setenv("ANALYSIS_DATA_DIR", str(data_repo_sim))
    result = _sim("user", "add", "alice", "--shared")
    assert result.exit_code == 0, result.output
    assert hub.read_users()["alice"].repo == data_repo_sim.parent.resolve()


def test_a_user_left_without_a_setting_is_asked_for_one(hub_logins: dict[str, Path]) -> None:
    # CliRunner's stdin isn't a terminal: a usage error, not a hang.
    result = _sim("user", "add", "alice")
    assert result.exit_code == 2
    assert "give --shared [REPO] or --own [URL]" in result.output


def test_the_users_file_round_trips_odd_names_and_paths(hub_logins: dict[str, Path], tmp_path: Path) -> None:
    odd = hub.HubUser("a.b-c", hub.OWN, tmp_path / 'quote " and ü', "file:///x y")
    hub.write_user(odd)
    assert hub.read_users() == {"a.b-c": odd}
    assert hub.delete_user("a.b-c")
    assert not hub.delete_user("a.b-c")


def test_a_damaged_users_file_is_named(hub_logins: dict[str, Path]) -> None:
    path = hub.hub_dir() / "users.toml"
    path.parent.mkdir(parents=True)
    path.write_text('[users.alice]\ndata = "neither"\n', encoding="utf-8")
    result = _sim("user", "list")
    assert result.exit_code == 1
    assert "users.alice needs data" in result.output


def test_the_config_follows_the_hub_folder(hub_logins: dict[str, Path], data_repo_sim: Path) -> None:
    folder = hub.hub_dir()
    hub.write_settings(hub.Settings("0.0.0.0", 8123))  # noqa: S104 - a setting under test
    c = Config()
    hub_config.configure(c, folder)
    assert c.JupyterHub.bind_url == "http://0.0.0.0:8123/"
    assert c.JupyterHub.pid_file == str(folder / "run" / "jupyterhub.pid")
    assert c.Spawner.cmd[1:] == ["-m", "zabob.retirement.jupyter.singleuser"]

    # Who may log in is read at each login: no restart after `user add`.
    authenticator = hub_config.HouseholdAuthenticator()
    assert not authenticator.check_allowed("alice")
    hub.write_user(hub.HubUser("alice", hub.SHARED, data_repo_sim.parent))
    assert authenticator.check_allowed("alice")

    stub = hub.write_config(folder)
    assert "configure(c, Path(" in stub.read_text(encoding="utf-8")


def test_a_users_jupyterlab_works_on_their_data_repo(hub_logins: dict[str, Path], data_repo_sim: Path) -> None:
    repo = data_repo_sim.parent
    env, root, url = hub_config.spawn_environment(hub.HubUser("alice", hub.SHARED, repo))
    assert env["ANALYSIS_DATA_DIR"] == str(data_repo_sim)
    assert env["ANALYSIS_USER"] == "alice"
    assert (root, url) == (str(repo), "/lab/tree/notebooks")

    own = hub_logins["bill"] / "zabob-retirement"
    env, root, url = hub_config.spawn_environment(hub.HubUser("bill", hub.OWN, own))
    assert "ANALYSIS_DATA_DIR" not in env  # nothing there yet: `sim init` in a terminal makes it
    assert (root, url) == (str(hub_logins["bill"]), "/lab/tree/zabob-retirement/notebooks")
    env, _root, _url = hub_config.spawn_environment(hub.HubUser("bill", hub.OWN, own, "file:///x"))
    assert env["ANALYSIS_DATA_DIR"] == str(own / "sim")
    assert env["ZABOB_HUB_CLONE_URL"] == "file:///x"


def test_an_own_repo_is_cloned_and_given_the_notebooks(
    hub_logins: dict[str, Path], data_repo_origin: Path,
) -> None:
    own = hub_logins["bill"] / "zabob-retirement"
    singleuser.prepare({"ZABOB_HUB_REPO": str(own), "ZABOB_HUB_CLONE_URL": str(data_repo_origin)})
    assert (own / "sim" / "persons.csv").is_file()
    assert any((own / "notebooks").glob("*.ipynb"))


def test_the_service_runs_the_hub_from_its_folder(hub_logins: dict[str, Path]) -> None:
    unit = hub.systemd_unit()
    assert f"Environment=ZABOB_HUB_DIR={hub.hub_dir()}" in unit
    assert "jupyter hub start --foreground" in unit
    plist = hub.launchd_plist()
    assert f"<string>{hub.hub_dir()}</string>" in plist
    result = _sim("hub", "service")
    assert result.exit_code == 0, result.output
    assert "systemctl enable" in result.output or "launchctl bootstrap" in result.output


def test_under_sudo_the_hub_folder_is_the_admins(
    hub_logins: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUDO_USER", "alice")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert hub.hub_dir() == hub_logins["alice"] / ".config" / "zabob-retirement" / "hub"


def test_status_with_nothing_running(hub_logins: dict[str, Path]) -> None:
    result = _sim("hub", "status")
    assert result.exit_code == 0, result.output
    assert "The hub isn't running (it would be at http://127.0.0.1:8000/)." in result.output
    assert "no users yet" in result.output
    assert _sim("hub", "stop").output == "The hub isn't running.\n"


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("configurable-http-proxy") is None, reason="needs configurable-http-proxy")
def test_the_hub_starts_and_stops(hub_logins: dict[str, Path], free_port: int) -> None:
    result = _sim("hub", "start", "--port", str(free_port))
    try:
        assert result.exit_code == 0, result.output
        assert f"at http://127.0.0.1:{free_port}/" in result.output
        assert hub.hub_pid() is not None
        again = _sim("hub", "start")
        assert "The hub is already running" in again.output
    finally:
        stopped = _sim("hub", "stop")
    assert stopped.output == "Stopped the hub.\n"
    assert hub.hub_pid() is None
