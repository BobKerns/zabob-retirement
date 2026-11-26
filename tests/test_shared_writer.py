"""#785: several clones of one data repo, one builder writing what they share."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import git
import pytest
from click.testing import CliRunner

from zabob.retirement.sim import price_schedule, research_schedule, roll_schedule, shared_writer
from zabob.retirement.sim.cli import sim_group_command

ME = "alice@laptop"


@pytest.fixture
def me(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(shared_writer, "this_machine", lambda: ME)
    return ME


@pytest.fixture
def catching_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(price_schedule.CATCH_UP_ENV, raising=False)


def test_the_machine_name_is_the_login_at_the_short_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shared_writer, "login_name", lambda: "bill")
    monkeypatch.setattr(shared_writer.platform, "node", lambda: "Desk.example.com")
    assert shared_writer.this_machine() == "bill@desk"


def test_with_no_machine_named_every_builder_writes(tmp_path: Path, me: str) -> None:
    assert shared_writer.read_writer(tmp_path) is None
    assert shared_writer.writes_here(tmp_path)
    shared_writer.write_writer(tmp_path, "bill@desk")
    assert shared_writer.read_writer(tmp_path) == "bill@desk"
    assert not shared_writer.writes_here(tmp_path)
    assert shared_writer.elsewhere(tmp_path) == "bill@desk"
    shared_writer.write_writer(tmp_path, me)
    assert shared_writer.writes_here(tmp_path) and shared_writer.elsewhere(tmp_path) is None
    shared_writer.write_writer(tmp_path, None)
    assert not (tmp_path / shared_writer.FILE).exists()


def test_an_unreadable_file_names_no_one(tmp_path: Path) -> None:
    (tmp_path / shared_writer.FILE).write_text("writer = [", encoding="utf-8")
    assert shared_writer.read_writer(tmp_path) is None


def test_another_machine_named_turns_off_fetch_roll_and_research(tmp_path: Path, me: str,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    for module in (price_schedule, roll_schedule, research_schedule):
        monkeypatch.delenv(module.SWITCH_ENV, raising=False)
    config = {"data_dir": str(tmp_path)}
    assert all(m.enabled(config) for m in (price_schedule, roll_schedule, research_schedule))
    shared_writer.write_writer(tmp_path, "bill@desk")
    assert not any(m.enabled(config) for m in (price_schedule, roll_schedule, research_schedule))
    shared_writer.write_writer(tmp_path, me)
    assert all(m.enabled(config) for m in (price_schedule, roll_schedule, research_schedule))


def test_install_names_this_machine_only_where_the_repo_has_a_remote(
    data_repo_sim: Path, me: str,
) -> None:
    assert shared_writer.claim(data_repo_sim) == []  # a lone clone needs no file
    assert not (data_repo_sim / shared_writer.FILE).exists()


def test_install_names_this_machine_and_commits_it(data_repo_sim: Path, data_repo_origin: Path, me: str) -> None:
    said = shared_writer.claim(data_repo_sim)
    assert said[0].startswith(f"{ME} fetches prices") and "committed" in said[0]
    assert shared_writer.read_writer(data_repo_sim) == ME
    with git.Repo(data_repo_sim.parent) as repo:
        assert not repo.is_dirty(untracked_files=True)
        assert repo.head.commit.message.startswith(f"Background builder: {ME} writes")
    assert shared_writer.claim(data_repo_sim) == []  # named already: nothing more to say


def test_a_clone_whose_writer_is_elsewhere_says_so(data_repo_sim: Path, data_repo_origin: Path, me: str) -> None:
    shared_writer.write_writer(data_repo_sim, "bill@desk")
    assert "bill@desk's builder" in shared_writer.claim(data_repo_sim)[0]


def test_the_writer_command_shows_and_moves_the_writer(data_repo_sim: Path, me: str) -> None:
    def run(*args: str) -> str:
        out = CliRunner().invoke(sim_group_command, ["builder", "writer", *args, "--data-dir", str(data_repo_sim)])
        assert out.exit_code == 0, out.output
        return out.output

    assert "no machine is named" in run()
    assert "committed" in run("--machine", "bill@desk")
    assert "bill@desk writes" in run()
    run("--here")
    assert f"this machine ({ME}) writes" in run()
    run("--anyone")
    assert "no machine is named" in run()
    with git.Repo(data_repo_sim.parent) as repo:
        assert not repo.is_dirty(untracked_files=True)


def _other_clone(origin: Path, tmp_path: Path, commit_files: Callable[..., str], text: str) -> str:
    """Another clone pushes a commit to origin; returns it."""
    with git.Repo.clone_from(origin, tmp_path / "elsewhere") as other:
        made = commit_files(other, {"sim/notes.txt": text}, "another machine's commit")
        other.git.push("-q", "origin", "main")
    return made


def test_catch_up_fast_forwards_a_clean_main(
    data_repo_sim: Path, data_repo_origin: Path, tmp_path: Path, commit_files: Callable[..., str],
    catching_up: None,
) -> None:
    made = _other_clone(data_repo_origin, tmp_path, commit_files, "from elsewhere\n")
    assert price_schedule.catch_up(data_repo_sim) == ["caught up with origin/main (1 commit)"]
    with git.Repo(data_repo_sim.parent) as repo:
        assert repo.head.commit.hexsha == made
    assert price_schedule.catch_up(data_repo_sim) == []  # nothing new


def test_catch_up_waits_for_a_dirty_main_and_leaves_a_diverged_one(
    data_repo_sim: Path, data_repo_origin: Path, tmp_path: Path, commit_files: Callable[..., str],
    catching_up: None,
) -> None:
    _other_clone(data_repo_origin, tmp_path, commit_files, "from elsewhere\n")
    persons = data_repo_sim / "persons.csv"
    persons.write_text(persons.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert price_schedule.catch_up(data_repo_sim) == [
        "not catching up with origin/main yet: main has uncommitted changes"]
    with git.Repo(data_repo_sim.parent) as repo:
        repo.git.checkout("--", "sim/persons.csv")
        commit_files(repo, {"sim/mine.txt": "here\n"}, "this machine's commit")
    assert price_schedule.catch_up(data_repo_sim) == [
        "not catching up: main and origin/main have diverged; git pull on main merges them"]


def test_tests_never_catch_up(data_repo_sim: Path, data_repo_origin: Path, tmp_path: Path,
                              commit_files: Callable[..., str]) -> None:
    _other_clone(data_repo_origin, tmp_path, commit_files, "from elsewhere\n")
    assert price_schedule.catch_up_off()
    assert price_schedule.catch_up(data_repo_sim) == []


def test_without_an_upstream_there_is_nothing_to_catch_up_with(data_repo_sim: Path, catching_up: None) -> None:
    assert not price_schedule.has_upstream(data_repo_sim)
    assert price_schedule.catch_up(data_repo_sim) == []
