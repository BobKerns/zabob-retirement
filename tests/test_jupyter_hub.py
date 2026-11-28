"""``sim jupyter hub`` and ``sim jupyter user`` (#766)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from traitlets.config import Config

from zabob.retirement import user_config
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
    monkeypatch.setenv("ZABOB_DATA_DIR", str(data_repo_sim))
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
    # Who they are and their data repo go in their own settings (#773), not
    # the environment, which would come before anything they choose later.
    assert "ZABOB_DATA_DIR" not in env and "ZABOB_USER" not in env
    assert env["ZABOB_HUB_LOGIN"] == "alice" and env["ZABOB_HUB_REPO"] == str(repo)
    assert (root, url) == (str(repo), "/lab/tree/notebooks")

    own = hub_logins["bill"] / "zabob-retirement"
    env, root, url = hub_config.spawn_environment(hub.HubUser("bill", hub.OWN, own))
    assert (root, url) == (str(hub_logins["bill"]), "/lab/tree/zabob-retirement/notebooks")
    env, _root, _url = hub_config.spawn_environment(hub.HubUser("bill", hub.OWN, own, "file:///x"))
    assert env["ZABOB_HUB_CLONE_URL"] == "file:///x"


def test_the_first_spawn_records_who_they_are_and_their_data_repo(
    hub_logins: dict[str, Path], data_repo_sim: Path,  # noqa: ARG001 - their homes
) -> None:
    (user_config.config_dir() / "user").unlink()
    repo = data_repo_sim.parent
    singleuser.prepare({"ZABOB_HUB_LOGIN": "alice", "ZABOB_HUB_REPO": str(repo)})
    assert user_config.user_name() == "alice"
    assert user_config.default_data_dir() == data_repo_sim.resolve()
    # What they choose after is theirs: a later spawn leaves it.
    user_config.set_user("Alice E.")
    singleuser.prepare({"ZABOB_HUB_LOGIN": "alice", "ZABOB_HUB_REPO": str(repo)})
    assert user_config.user_name() == "Alice E."


def test_an_own_repo_not_made_yet_records_only_the_name(hub_logins: dict[str, Path]) -> None:
    (user_config.config_dir() / "user").unlink()
    own = hub_logins["bill"] / "zabob-retirement"
    singleuser.prepare({"ZABOB_HUB_LOGIN": "bill", "ZABOB_HUB_REPO": str(own)})
    assert user_config.user_name() == "bill"
    assert user_config.default_data_dir() is None  # `sim init` in a terminal records it


def test_an_own_repo_is_cloned_and_given_the_notebooks(
    hub_logins: dict[str, Path], data_repo_origin: Path,
) -> None:
    own = hub_logins["bill"] / "zabob-retirement"
    singleuser.prepare({"ZABOB_HUB_REPO": str(own), "ZABOB_HUB_CLONE_URL": str(data_repo_origin)})
    assert (own / "sim" / "persons.csv").is_file()
    assert any((own / "notebooks").glob("*.ipynb"))
    assert user_config.default_data_dir() == (own / "sim").resolve()


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


def test_a_bare_own_keeps_the_clone_url(hub_logins: dict[str, Path]) -> None:  # noqa: ARG001 - the logins
    assert _sim("user", "add", "bill", "--own", "https://example.com/data.git").exit_code == 0
    result = _sim("user", "edit", "bill", "--own")
    assert result.exit_code == 0, result.output
    assert hub.read_users()["bill"].url == "https://example.com/data.git"


def test_the_service_gets_a_hub_folder_its_admin_owns(
    hub_logins: dict[str, Path], monkeypatch: pytest.MonkeyPatch,  # noqa: ARG001 - its folder
) -> None:
    """Made before root's first start, so the admin can still add users."""
    monkeypatch.setenv("SUDO_UID", str(os.getuid()))
    monkeypatch.setenv("SUDO_GID", str(os.getgid()))
    hub.prepare_for_service()
    assert hub.run_dir().is_dir()
    assert hub.hub_dir().stat().st_uid == os.getuid()


def test_with_no_git_jupyterlab_still_starts(
    hub_logins: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "")
    own = hub_logins["bill"] / "zabob-retirement"
    singleuser.prepare({"ZABOB_HUB_LOGIN": "bill", "ZABOB_HUB_REPO": str(own), "ZABOB_HUB_CLONE_URL": "file:///x"})
    assert not own.exists()


def test_an_ipv6_address_goes_in_brackets() -> None:
    assert hub.Settings("::1", 8000).url == "http://[::1]:8000/"
    assert hub.Settings("::1", 8000).bind_url == "http://[::1]:8000/"
    assert hub.Settings("::", 8000).url == "http://localhost:8000/"
    assert hub.Settings("::", 8000).bind_url == "http://[::]:8000/"
    assert hub.Settings("100.64.0.1", 8000).bind_url == "http://100.64.0.1:8000/"


def test_a_port_that_is_not_a_number_is_named(hub_logins: dict[str, Path]) -> None:  # noqa: ARG001 - its folder
    (hub.hub_dir()).mkdir(parents=True, exist_ok=True)
    (hub.hub_dir() / "hub.toml").write_text('[hub]\nport = "80a"\n', encoding="utf-8")
    with pytest.raises(hub.HubError, match="port must be a number"):
        hub.read_settings()


def test_a_pid_file_naming_another_process_is_no_hub(hub_logins: dict[str, Path]) -> None:  # noqa: ARG001 - its folder
    """After a reboot, the number in a leftover pid file may be another
    process's: it isn't taken for a running hub."""
    hub.run_dir().mkdir(parents=True, exist_ok=True)
    other = subprocess.Popen(["sleep", "30"])  # noqa: S607 - any process that isn't the hub
    try:
        (hub.run_dir() / "jupyterhub.pid").write_text(f"{other.pid}\n", encoding="utf-8")
        assert hub.hub_pid() is None
    finally:
        other.kill()
        other.wait()


def test_start_while_running_keeps_the_address_it_runs_at(
    hub_logins: dict[str, Path], monkeypatch: pytest.MonkeyPatch,  # noqa: ARG001 - its folder
) -> None:
    monkeypatch.setattr(hub, "hub_pid", lambda folder=None: 4242)
    monkeypatch.setattr(hub, "proxy_command", lambda: "/usr/bin/true")
    result = _sim("hub", "start", "--port", "8124")
    assert result.exit_code == 0, result.output
    assert "already running (process 4242) at http://127.0.0.1:8000/; stop it first to move it" in result.output
    assert hub.read_settings().port == hub.DEFAULT_PORT


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


# ---------- spawning as root with many groups (#834) ----------

def test_the_data_repos_groups_come_before_the_cut() -> None:
    # 20 is the primary, 70 the repo's; 99 owns a folder above it the login isn't in.
    member_of = [20, *range(100, 120), 70]
    keep, dropped = hub_config.spawn_groups(member_of, 20, [70, 99, 20], 16)
    assert keep[:2] == [20, 70] and len(keep) == 16
    assert 99 not in keep and 70 not in dropped
    assert sorted(keep + dropped) == sorted(member_of)
    assert hub_config.spawn_groups([20, 70], 20, [70], 16) == ([20, 70], [])


def test_the_hub_spawns_with_the_household_spawner(hub_logins: dict[str, Path]) -> None:  # noqa: ARG001 - its folder
    c = Config()
    hub_config.configure(c, hub.hub_dir())
    assert c.JupyterHub.spawner_class is hub_config.HouseholdSpawner


def _me() -> tuple[str, int]:
    import pwd

    me = pwd.getpwuid(os.getuid())
    return me.pw_name, me.pw_gid


def test_a_login_in_too_many_groups_keeps_its_data_repos(
    hub_logins: dict[str, Path], data_repo_sim: Path, monkeypatch: pytest.MonkeyPatch,  # noqa: ARG001 - its folder
) -> None:
    name, primary = _me()
    repo = data_repo_sim.parent
    repo_gid = 4321
    hub_config.configure(Config(), hub.hub_dir())
    hub.write_user(hub.HubUser(name, hub.SHARED, repo))
    monkeypatch.setattr(hub_config, "_path_groups", lambda paths: [repo_gid] if repo in paths else [])
    monkeypatch.setattr(os, "getgrouplist", lambda _name, _gid: [primary, *range(5000, 5020), repo_gid])
    monkeypatch.setattr(hub_config, "_group_limit", lambda: 16)
    seen: dict[str, list[int]] = {}

    def setuid(_uid: int, _gid: int, groups: list[int], _home: str, _fallback: object) -> object:
        seen["groups"] = groups
        return lambda: None

    monkeypatch.setattr(hub_config, "_setuid", setuid)
    hub_config.HouseholdSpawner().make_preexec_fn(name)
    assert len(seen["groups"]) == 16 and seen["groups"][:2] == [primary, repo_gid]


def test_a_login_whose_groups_fit_gets_jupyterhub_s_own_switch(
    hub_logins: dict[str, Path], monkeypatch: pytest.MonkeyPatch,  # noqa: ARG001 - its folder
) -> None:
    name, primary = _me()
    monkeypatch.setattr(os, "getgrouplist", lambda _name, _gid: [primary])
    monkeypatch.setattr(hub_config, "_setuid", lambda *_: pytest.fail("not needed when the groups fit"))

    def jupyterhub_s(_name: str) -> object:
        return jupyterhub_s

    monkeypatch.setattr(hub_config, "set_user_setuid", jupyterhub_s)
    assert hub_config.HouseholdSpawner().make_preexec_fn(name) is jupyterhub_s


def test_refused_groups_fall_back_to_jupyterhub_s_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def refuse(_groups: list[int]) -> None:
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(os, "setgid", lambda _gid: calls.append("setgid"))
    monkeypatch.setattr(os, "setgroups", refuse)
    monkeypatch.setattr(os, "setuid", lambda _uid: calls.append("setuid"))
    hub_config._setuid(1000, 20, [20, 70], "/nowhere", lambda: calls.append("fallback"))()
    assert calls == ["setgid", "fallback"]


def test_a_shared_repo_it_cant_get_to_stops_the_server_at_once(
    hub_logins: dict[str, Path], data_repo_sim: Path, monkeypatch: pytest.MonkeyPatch,  # noqa: ARG001 - their homes
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = data_repo_sim.parent
    env = {"ZABOB_HUB_LOGIN": "alice", "ZABOB_HUB_REPO": str(repo / "gone"), "ZABOB_HUB_DATA": hub.SHARED}
    with pytest.raises(singleuser.Unreachable, match="isn't there"):
        singleuser.prepare(env)

    # As if the folder holding the repo kept them out (root's access is never refused).
    blocked = repo.parent
    real_access = os.access
    monkeypatch.setattr(os, "access", lambda path, mode: (
        not (Path(path) == blocked and mode & os.X_OK) and real_access(path, mode)))
    monkeypatch.setattr(os, "environ", {**env, "ZABOB_HUB_REPO": str(repo)})
    monkeypatch.setattr(os, "execv", lambda *_: pytest.fail("JupyterLab must not start"))
    with pytest.raises(SystemExit) as stopped:
        singleuser.main()
    assert stopped.value.code == 1
    expected = f"zabob: alice: can't open the data repo {repo}: {blocked} doesn't let this login in"
    assert expected in capsys.readouterr().err


def test_an_own_repo_not_cloned_yet_is_no_failure(hub_logins: dict[str, Path]) -> None:
    own = hub_logins["bill"] / "zabob-retirement"
    singleuser.prepare({"ZABOB_HUB_LOGIN": "bill", "ZABOB_HUB_REPO": str(own), "ZABOB_HUB_DATA": hub.OWN})
    assert not own.exists()


# ---------- sim jupyter hub log (#834) ----------

def test_the_log_shows_the_last_lines_of_the_newest_log(hub_logins: dict[str, Path]) -> None:  # noqa: ARG001 - its folder
    result = _sim("hub", "log")
    assert result.exit_code != 0 and "hasn't written a log" in result.output
    run = hub.run_dir()
    run.mkdir(parents=True)
    (run / "jupyterhub.log").write_text("old\n", encoding="utf-8")
    service = run / "service.log"
    service.write_text("".join(f"line {n}\n" for n in range(1, 6)), encoding="utf-8")
    os.utime(run / "jupyterhub.log", (1, 1))
    assert hub.log_file() == service
    result = _sim("hub", "log", "-n", "2")
    assert result.exit_code == 0, result.output
    assert result.stdout == "line 4\nline 5\n"
    assert str(service) in result.stderr
    assert _sim("hub", "log", "-n", "0").stdout.count("line") == 5


def test_the_log_follows_until_interrupted(
    hub_logins: dict[str, Path], monkeypatch: pytest.MonkeyPatch,  # noqa: ARG001 - its folder
) -> None:
    run = hub.run_dir()
    run.mkdir(parents=True)
    log = run / "jupyterhub.log"
    log.write_text("first\n", encoding="utf-8")
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        if sleeps:
            raise KeyboardInterrupt
        sleeps.append(seconds)
        with log.open("a", encoding="utf-8") as out:
            out.write("second\n")

    monkeypatch.setattr("time.sleep", sleep)
    result = _sim("hub", "log", "--follow")
    assert result.exit_code == 0, result.output
    assert result.stdout == "first\nsecond\n"


def test_the_linux_service_logs_beside_the_hub(hub_logins: dict[str, Path]) -> None:  # noqa: ARG001 - its folder
    assert f"StandardOutput=append:{hub.run_dir() / 'service.log'}" in hub.systemd_unit()
