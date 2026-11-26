"""#785: several clones of one data repo, one builder writing what they share."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import git
import pytest
from click.testing import CliRunner

from zabob.retirement.sim import builder, price_schedule, research_schedule, roll_schedule, shared_writer
from zabob.retirement.sim.cli import sim_group_command

ME = "alice@laptop"
SCHEDULES = (price_schedule, roll_schedule, research_schedule)


@pytest.fixture
def me(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(shared_writer, "this_machine", lambda: ME)
    return ME


@pytest.fixture
def catching_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(price_schedule.CATCH_UP_ENV, raising=False)


@pytest.fixture
def schedules_on(monkeypatch: pytest.MonkeyPatch) -> None:
    for module in SCHEDULES:
        monkeypatch.delenv(module.SWITCH_ENV, raising=False)


def _named(data_dir: Path, ref: str = "main") -> str | None:
    return shared_writer.read_writer(data_dir, ref)


def test_the_machine_name_is_the_login_at_the_short_host_in_lower_case(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shared_writer, "login_name", lambda: "Bill")
    monkeypatch.setattr(shared_writer, "_host", lambda: "Desk.example.com")
    assert shared_writer.this_machine() == "bill@desk"
    assert shared_writer.normalize(" Bill@Desk.example.com ") == "bill@desk"
    assert shared_writer.valid("Bill@Desk") and not shared_writer.valid("bill") \
        and not shared_writer.valid("a@b@c") and not shared_writer.valid("bill@ desk")


def test_the_name_recorded_at_install_outlasts_a_new_host_name(me: str) -> None:
    """A container recreated, or a laptop on another network, keeps the name
    its install recorded."""
    assert shared_writer.machine(None, {"machine": "Bill@Desk"}) == "bill@desk"
    assert shared_writer.machine(None, {}) == ME


def test_the_writer_is_read_from_mains_last_commit(data_repo_sim: Path, me: str) -> None:
    assert _named(data_repo_sim) is None and shared_writer.writes_here(data_repo_sim, {})
    shared_writer.write_writer(data_repo_sim, "bill@desk")
    assert _named(data_repo_sim) is None  # not committed: changes nothing
    assert "committed" in shared_writer.set_writer(data_repo_sim, "Bill@Desk")
    assert _named(data_repo_sim) == "bill@desk"
    assert not shared_writer.writes_here(data_repo_sim, {})
    assert shared_writer.elsewhere(data_repo_sim, {}) == "bill@desk"
    assert shared_writer.elsewhere(data_repo_sim, {"machine": "bill@desk"}) is None
    shared_writer.write_writer(data_repo_sim, None)  # an edit not committed
    assert _named(data_repo_sim) == "bill@desk"
    with git.Repo(data_repo_sim.parent) as repo:
        repo.git.checkout("-q", "--", "sim/.builder.toml")
        repo.git.checkout("-q", "-b", "old", "HEAD~1")  # a branch from before the file
    assert _named(data_repo_sim) == "bill@desk"
    assert "not changed: the data repo has old checked out" in shared_writer.set_writer(data_repo_sim, ME)
    assert _named(data_repo_sim) == "bill@desk"


def test_naming_the_machine_already_named_changes_nothing(data_repo_sim: Path, me: str) -> None:
    shared_writer.set_writer(data_repo_sim, ME)
    assert shared_writer.set_writer(data_repo_sim, ME).endswith("already; nothing changed")
    assert shared_writer.set_writer(data_repo_sim, None).endswith("(sim/.builder.toml, committed)")
    assert shared_writer.set_writer(data_repo_sim, None).endswith("already; nothing changed")
    assert not (data_repo_sim / shared_writer.FILE).exists()


def test_outside_git_naming_a_machine_says_so(tmp_path: Path, me: str) -> None:
    assert "isn't in a git repository" in shared_writer.set_writer(tmp_path, ME)


def test_an_unreadable_file_names_no_one(data_repo_sim: Path, commit_files: Callable[..., str]) -> None:
    with git.Repo(data_repo_sim.parent) as repo:
        commit_files(repo, {"sim/.builder.toml": "writer = ["}, "broken")
    assert _named(data_repo_sim) is None


def test_another_machine_named_turns_off_fetch_roll_and_research(
    data_repo_sim: Path, me: str, schedules_on: None,
) -> None:
    config = {"data_dir": str(data_repo_sim)}
    assert all(m.enabled(config) for m in SCHEDULES)
    shared_writer.set_writer(data_repo_sim, "bill@desk")
    assert not any(m.enabled(config) for m in SCHEDULES)
    assert all(m.configured(config) for m in SCHEDULES)  # what it committed still merges
    shared_writer.set_writer(data_repo_sim, ME)
    assert all(m.enabled(config) for m in SCHEDULES)


def test_a_lone_clone_claims_nothing(data_repo_sim: Path, me: str) -> None:
    assert shared_writer.claim(data_repo_sim, {}) == []
    assert not (data_repo_sim / shared_writer.FILE).exists()


def test_install_names_this_machine_commits_it_and_pushes(
    data_repo_sim: Path, data_repo_origin: Path, me: str,
) -> None:
    said = shared_writer.claim(data_repo_sim, {})
    assert said[0].startswith(f"{ME} fetches prices") and "committed and pushed" in said[0]
    with git.Repo(data_repo_sim.parent) as repo:
        assert not repo.is_dirty(untracked_files=True)
        assert repo.head.commit.message.startswith(f"Background builder: {ME} writes")
    with git.Repo(data_repo_origin) as origin:
        assert f'writer = "{ME}"' in origin.git.show("main:sim/.builder.toml")
    assert shared_writer.claim(data_repo_sim, {}) == []  # named already: nothing more to say


def test_an_install_that_does_none_of_the_three_claims_nothing(
    data_repo_sim: Path, data_repo_origin: Path, me: str,
) -> None:
    assert shared_writer.claim(data_repo_sim, {"prices": False, "roll": False, "research": False}) == []
    assert _named(data_repo_sim) is None


def test_install_sees_a_claim_another_clone_pushed(
    data_repo_sim: Path, other_clone: Callable[..., str], me: str, catching_up: None,
) -> None:
    other_clone({"sim/.builder.toml": 'writer = "bill@desk"\n'})
    said = shared_writer.claim(data_repo_sim, {})
    assert said[0] == "caught up with origin/main (1 commit)"
    assert "bill@desk's builder" in said[1]
    assert _named(data_repo_sim) == "bill@desk"


def test_install_sees_a_claim_on_an_upstream_it_cant_catch_up_with(
    data_repo_sim: Path, other_clone: Callable[..., str], commit_files: Callable[..., str],
    me: str, catching_up: None,
) -> None:
    other_clone({"sim/.builder.toml": 'writer = "bill@desk"\n'})
    with git.Repo(data_repo_sim.parent) as repo:
        commit_files(repo, {"sim/mine.txt": "here\n"}, "this machine's commit")
    said = shared_writer.claim(data_repo_sim, {})
    assert "diverged" in said[0] and "bill@desk's builder" in said[1]
    assert _named(data_repo_sim) is None


def test_the_writer_command_shows_and_moves_the_writer(data_repo_sim: Path, me: str) -> None:
    def run(*args: str, code: int = 0) -> str:
        out = CliRunner().invoke(sim_group_command, ["builder", "writer", *args, "--data-dir", str(data_repo_sim)])
        assert out.exit_code == code, out.output
        return out.output

    assert "no machine is named" in run()
    assert "committed" in run("--machine", "Bill@Desk")
    assert "bill@desk writes" in run()
    assert "isn't LOGIN@HOST" in run("--machine", "desk", code=2)
    run("--here")
    assert f"this machine ({ME}) writes" in run()
    run("--anyone")
    assert "no machine is named" in run()
    with git.Repo(data_repo_sim.parent) as repo:
        assert not repo.is_dirty(untracked_files=True)


def test_a_non_writer_refuses_to_fetch_roll_or_research_by_hand(
    data_repo_sim: Path, me: str, schedules_on: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(builder, "read_config", lambda _paths: {"data_dir": str(data_repo_sim)})
    shared_writer.set_writer(data_repo_sim, "bill@desk")
    for command in ("prices", "roll", "research"):
        out = CliRunner().invoke(sim_group_command, ["builder", command, "--data-dir", str(data_repo_sim)])
        assert out.exit_code == 1 and "bill@desk's builder" in out.output, out.output
        due = CliRunner().invoke(sim_group_command, ["builder", command, "--if-due", "--data-dir",
                                                     str(data_repo_sim)])
        assert due.exit_code == 0 and "not due here" in due.output, due.output


def test_catch_up_fast_forwards_a_clean_main(
    data_repo_sim: Path, other_clone: Callable[..., str], catching_up: None,
) -> None:
    made = other_clone({"sim/notes.txt": "from elsewhere\n"})
    assert price_schedule.catch_up(data_repo_sim) == ["caught up with origin/main (1 commit)"]
    with git.Repo(data_repo_sim.parent) as repo:
        assert repo.head.commit.hexsha == made
    assert price_schedule.catch_up(data_repo_sim) == []  # nothing new


def test_catch_up_is_hourly_across_the_daemon_and_the_timer(
    data_repo_sim: Path, other_clone: Callable[..., str], catching_up: None,
) -> None:
    other_clone({"sim/notes.txt": "one\n"})
    assert price_schedule.catch_up_if_due(data_repo_sim) == ["caught up with origin/main (1 commit)"]
    other_clone({"sim/notes.txt": "two\n"})
    assert price_schedule.catch_up_if_due(data_repo_sim) == []  # within the hour, whoever looks
    with git.Repo(data_repo_sim.parent) as repo:
        top = Path(str(repo.working_tree_dir))
    price_schedule._update_state(top, caught_up=0)
    assert price_schedule.catch_up_if_due(data_repo_sim) == ["caught up with origin/main (1 commit)"]


def test_catch_up_waits_for_a_dirty_main_and_leaves_a_diverged_one(
    data_repo_sim: Path, other_clone: Callable[..., str], commit_files: Callable[..., str],
    catching_up: None,
) -> None:
    other_clone({"sim/notes.txt": "from elsewhere\n"})
    persons = data_repo_sim / "persons.csv"
    persons.write_text(persons.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert price_schedule.catch_up(data_repo_sim) == [
        "not catching up with origin/main yet: main has uncommitted changes"]
    with git.Repo(data_repo_sim.parent) as repo:
        repo.git.checkout("--", "sim/persons.csv")
        commit_files(repo, {"sim/mine.txt": "here\n"}, "this machine's commit")
    assert price_schedule.catch_up(data_repo_sim) == [
        "not catching up: main and origin/main have diverged; git pull on main merges them"]


def test_tests_never_catch_up(data_repo_sim: Path, other_clone: Callable[..., str]) -> None:
    other_clone({"sim/notes.txt": "from elsewhere\n"})
    assert price_schedule.catch_up_off()
    assert price_schedule.catch_up(data_repo_sim) == []
    assert price_schedule.catch_up_if_due(data_repo_sim) == []


def test_without_an_upstream_there_is_nothing_to_catch_up_with(data_repo_sim: Path, catching_up: None) -> None:
    assert not price_schedule.has_upstream(data_repo_sim)
    assert price_schedule.catch_up(data_repo_sim) == []
    assert price_schedule.catch_up_if_due(data_repo_sim) == []
