"""The lookup tables' folder is tables/, not aux/ (#687): Windows can't check
out a folder named aux. The loader refuses the old layout, and
scripts/migrate_687.py moves a data repo to the new one."""
from __future__ import annotations

import importlib.util
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import git
import pytest

from zabob.retirement.sim.loader import LoadError, LoadResult


def _migration():
    path = Path(__file__).parents[1] / "scripts" / "migrate_687.py"
    spec = importlib.util.spec_from_file_location("migrate_687", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _old_layout(data_dir: Path) -> list[Path]:
    """Put the copy's tables back in aux/ folders, shared and a scenario's own."""
    (data_dir / "tables").rename(data_dir / "aux")
    own = data_dir / "scenarios" / "retire_alice" / "aux"
    own.mkdir()
    shutil.copy(data_dir / "aux" / "inflation__cpi.csv", own)
    return [data_dir / "aux", own]


def test_the_loader_refuses_aux_folders_and_the_migration_renames_them(
    test_data_dir: Path, load_test_copy: Callable[[], LoadResult], capsys: pytest.CaptureFixture[str],
) -> None:
    old = _old_layout(test_data_dir)
    with pytest.raises(LoadError,
                       match=r"tables/ now \(#687\).*git mv aux tables.*scripts/migrate_687.py") as caught:
        load_test_copy()
    assert all(str(path) in str(caught.value) for path in old)

    migration = _migration()
    assert migration.main([str(test_data_dir)]) == 0
    assert "would rename scenarios/retire_alice/aux -> scenarios/retire_alice/tables" \
        in capsys.readouterr().out
    assert all(path.is_dir() for path in old)

    assert migration.main([str(test_data_dir), "--write"]) == 0
    assert not any(path.exists() for path in old)
    assert (test_data_dir / "scenarios" / "retire_alice" / "tables" / "inflation__cpi.csv").is_file()
    load_test_copy()
    assert migration.main([str(test_data_dir)]) == 0  # nothing left to migrate
    assert "nothing to migrate" in capsys.readouterr().out


def test_the_migration_renames_tracked_folders_with_git(data_repo_sim: Path) -> None:
    with git.Repo(data_repo_sim.parent) as repo:
        repo.git.mv("sim/tables", "sim/aux")
        actor = git.Actor("t", "t@t")
        repo.index.commit("old layout", author=actor, committer=actor)

        assert _migration().main([str(data_repo_sim), "--write"]) == 0
        staged = repo.git.diff("--cached", "--name-status", "-M").splitlines()
    assert staged and all(line.startswith("R100") for line in staged)
    assert any("sim/aux/inflation__cpi.csv\tsim/tables/inflation__cpi.csv" in line for line in staged)


def test_the_migration_stops_when_both_folders_exist(test_data_dir: Path) -> None:
    shutil.copytree(test_data_dir / "tables", test_data_dir / "aux")
    assert _migration().main([str(test_data_dir), "--write"]) == 1
    assert (test_data_dir / "aux").is_dir()
