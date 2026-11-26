"""An installed program, with no code checkout (#662): `sim init`, the
notebooks, activate-analysis and background builds."""

from __future__ import annotations

import csv
import json
import os
import subprocess
from pathlib import Path

from click.testing import CliRunner, Result

from zabob.retirement import resources
from zabob.retirement.cli import main
from zabob.retirement.sim import builder, data_repo
from zabob.retirement.sim.loader import read_current_scenario

_ALICE = ("--id", "alice", "--display", "Alice Example", "--birthdate", "1960-05-01",
          "--sex", "f", "--filing-status", "MFJ")


def _sim(*args: str) -> Result:
    return CliRunner().invoke(main, ["sim", *args])


def _activate(script: Path, program: Path, path: str, *, then: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'source {script} && echo "$ANALYSIS_REPO_DIR|$ANALYSIS_USER|$PATH"{then}'],
        cwd=program.parent.parent, env={"PATH": path, "HOME": os.environ["HOME"]},
        capture_output=True, text=True, check=False)


def test_homes_name_a_checkout_or_an_installed_program(tmp_path: Path) -> None:
    named = resources.INSTALLED + str(tmp_path / "bin")
    assert resources.home_checkout(named) is None
    assert resources.program_sim(named) == tmp_path / "bin" / "sim"
    assert resources.home_checkout(str(tmp_path)) == tmp_path
    assert resources.program_sim(str(tmp_path)) == tmp_path / ".venv" / "bin" / "sim"
    (tmp_path / "linked").symlink_to(tmp_path)
    assert resources.same_home(str(tmp_path / "linked"), str(tmp_path))
    assert resources.same_home(named, resources.INSTALLED + str(tmp_path / "linked" / "bin"))
    assert not resources.same_home(named, str(tmp_path / "bin"))
    assert not resources.same_home("", "")


def test_init_makes_the_data_repo_in_the_home_folder_with_the_notebooks(installed_program: Path) -> None:
    result = _sim("init", "--no-builder", *_ALICE)
    assert result.exit_code == 0, result.output
    root = Path(os.environ["HOME"]) / "zabob-retirement"
    assert (root / "sim" / ".analysis").read_text(encoding="utf-8") == f"installed:{installed_program}\n"
    assert (root / "notebooks" / "net_worth.ipynb").is_file()
    assert {"/state/", "/notebooks/", "/.mcp.json"} <= set((root / ".gitignore").read_text(encoding="utf-8").split())
    assert "source home/zabob-retirement/sim/activate-analysis" in result.output  # as from here
    assert not (installed_program.parent.parent / "data").exists()  # nothing to link, nowhere
    # The notebooks aren't committed: their outputs would carry the household's numbers.
    tracked = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True,
                             check=True).stdout.split()
    assert "sim/persons.csv" in tracked and not any(p.startswith("notebooks/") for p in tracked)


def test_init_example_makes_alice_and_bill_s_household(installed_program: Path, tmp_path: Path) -> None:
    result = _sim("init", "--no-builder", "--example", str(tmp_path / "try"))
    assert result.exit_code == 0, result.output
    sim = tmp_path / "try" / "sim"
    with (sim / "persons.csv").open(newline="", encoding="utf-8") as fh:
        assert [row["id"] for row in csv.DictReader(fh)][:2] == ["alice", "bill"]
    assert (sim / ".analysis_user").read_text(encoding="utf-8") == "alice\n"
    assert read_current_scenario(sim) == "base"
    assert (sim / "scenarios" / "retire_alice").is_dir()
    assert "checking base: ok" in result.output
    assert (tmp_path / "try" / "notebooks" / "README.md").is_file()


def test_notebooks_copy_keeps_changed_notebooks_unless_replacing(installed_program: Path, tmp_path: Path) -> None:
    assert _sim("init", "--no-builder", *_ALICE).exit_code == 0
    sim = Path(os.environ["HOME"]) / "zabob-retirement" / "sim"
    mine = sim.parent / "notebooks" / "net_worth.ipynb"
    mine.write_text("mine", encoding="utf-8")
    kept = _sim("notebooks", "copy", "--data-dir", str(sim))
    assert kept.exit_code == 0 and "kept" in kept.output and mine.read_text(encoding="utf-8") == "mine"
    replaced = _sim("notebooks", "copy", "--replace", "--data-dir", str(sim))
    assert replaced.exit_code == 0 and mine.read_text(encoding="utf-8") != "mine"
    elsewhere = _sim("notebooks", "copy", str(tmp_path / "elsewhere"), "--data-dir", str(sim))
    assert elsewhere.exit_code == 0 and (tmp_path / "elsewhere" / "net_worth.ipynb").is_file()


def test_activate_puts_the_installed_program_first_and_deactivate_restores_path(installed_program: Path) -> None:
    assert _sim("init", "--no-builder", *_ALICE).exit_code == 0
    script = Path(os.environ["HOME"]) / "zabob-retirement" / "sim" / "activate-analysis"
    done = _activate(script, installed_program, "/usr/bin:/bin",
                     then=' && deactivate-analysis && echo "$PATH"')
    assert done.stdout.splitlines() == [
        f"installed:{installed_program}|alice|{installed_program}:/usr/bin:/bin", "/usr/bin:/bin"], done.stderr
    assert "differs" not in done.stderr and "Enter ANALYSIS_REPO_DIR" not in done.stderr


def test_activate_leaves_out_of_gitignore_a_name_commented_out_or_negated(installed_program: Path) -> None:
    """A shared retention policy can be committed (#712): a commented-out or
    negated line keeps activate from adding the name back."""
    assert _sim("init", "--no-builder", *_ALICE).exit_code == 0
    sim = Path(os.environ["HOME"]) / "zabob-retirement" / "sim"
    lines = ["# .retention.yaml", "!.current_scenario", "/.analysis_user", "#.analysis.bak"]
    (sim / ".gitignore").write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    done = _activate(sim / "activate-analysis", installed_program, "/usr/bin:/bin")
    assert done.returncode == 0, done.stderr
    assert (sim / ".gitignore").read_text(encoding="utf-8").splitlines() == [*lines, ".analysis"]


def test_activate_finds_an_installed_program_through_the_sim_on_path(installed_program: Path) -> None:
    """A data repo cloned onto a new machine names no program: uv links an
    installed one's commands into ~/.local/bin."""
    assert _sim("init", "--no-builder", *_ALICE).exit_code == 0
    sim = Path(os.environ["HOME"]) / "zabob-retirement" / "sim"
    (sim / ".analysis").unlink()
    local = Path(os.environ["HOME"]) / ".local" / "bin"
    local.mkdir(parents=True)
    (local / "sim").symlink_to(installed_program / "sim")
    done = _activate(sim / "activate-analysis", installed_program, f"{local}:/usr/bin:/bin")
    assert done.stdout.startswith(f"installed:{installed_program}|alice|"), done.stderr
    assert (sim / ".analysis").read_text(encoding="utf-8") == f"installed:{installed_program}\n"


def test_builder_pairs_with_the_installed_program_and_its_hooks_run_its_sim(installed_program: Path) -> None:
    assert _sim("init", "--no-builder", *_ALICE).exit_code == 0
    sim = Path(os.environ["HOME"]) / "zabob-retirement" / "sim"
    assert builder.installed_pair_problems(sim) == []
    trees, reason = builder.main_check()
    assert reason is None and trees is not None and len(trees) == 1  # the installed version
    builder.install(sim, prices=False, roll=False, research=False)
    config = json.loads(builder.BuilderPaths.for_data(sim).config.read_text(encoding="utf-8"))
    assert config["code_dir"] == f"installed:{installed_program}"
    persons = sim / "persons.csv"
    persons.write_text(persons.read_text(encoding="utf-8") + "bill,Bill,1962-01-01,m,primary,{}\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(sim.parent), "commit", "-qam", "Add Bill"], check=True)
    hooked = installed_program / "calls"
    for _ in range(50):  # the hook starts it in the background
        if hooked.exists():
            break
        subprocess.run(["sleep", "0.1"], check=True)
    assert hooked.read_text(encoding="utf-8").split()[:3] == ["builder", "notify", "--quiet"]


def test_builder_refuses_a_data_repo_naming_another_program(installed_program: Path, tmp_path: Path) -> None:
    assert _sim("init", "--no-builder", *_ALICE).exit_code == 0
    sim = Path(os.environ["HOME"]) / "zabob-retirement" / "sim"
    (sim / ".analysis").write_text(f"{tmp_path / 'some-checkout'}\n", encoding="utf-8")
    assert builder.installed_pair_problems(sim) == [f"{sim / '.analysis'} doesn't name installed:{installed_program}"]
    assert data_repo.CODE_REPO_DIR is None
