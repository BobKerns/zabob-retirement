"""#840: the data repo's notebook clean filter, ``sim _clean-notebook``."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from zabob.retirement import notebook_clean
from zabob.retirement.notebook_clean import NotebookError, clean

# What scripts/setup.sh gives nbstripout in the code repo.
SETUP_KEYS = "metadata.kernelspec.display_name metadata.language_info.version"


def _run(nb: dict[str, Any]) -> dict[str, Any]:
    """``nb`` as Jupyter leaves it after a run: outputs, counts, ids and
    the metadata nbstripout drops."""
    nb["metadata"].setdefault("kernelspec", {})["display_name"] = "Python 3 (here)"
    nb["metadata"].setdefault("language_info", {})["version"] = "3.14.0"
    nb["metadata"]["widgets"] = {"state": {}}
    for i, cell in enumerate(nb["cells"]):
        cell["id"] = f"run-{i}"
        cell.setdefault("metadata", {})["scrolled"] = True
        cell["metadata"]["ExecuteTime"] = {"end_time": "now"}
        if isinstance(cell["source"], list):
            cell["source"] = "".join(cell["source"])  # as nbformat holds it in memory
        if cell["cell_type"] == "code":
            cell["execution_count"] = i + 1
            cell["outputs"] = [
                {"output_type": "stream", "name": "stdout", "text": "Alice\nBill\n"},
                {"output_type": "execute_result", "execution_count": i + 1, "metadata": {},
                 "data": {"text/plain": "1\n2", "image/png": "iVBORw0KGgo="}},
            ]
            if i == 1:
                cell["metadata"]["tags"] = ["keep_output"]
    return nb


@pytest.mark.parametrize("notebook", sorted(p.name for p in (Path(__file__).parents[1] / "notebooks").glob("*.ipynb")))
def test_cleans_as_nbstripout_with_setups_keys(repo_root: Path, notebook: str) -> None:
    """Byte for byte, so a notebook moved between the repos doesn't churn."""
    text = json.dumps(_run(json.loads((repo_root / "notebooks" / notebook).read_text(encoding="utf-8"))), indent=2)
    expected = subprocess.run(
        [sys.executable, "-m", "nbstripout", "--extra-keys", SETUP_KEYS],
        input=text, capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    assert clean(text) == expected


def test_a_cleaned_notebook_keeps_nothing_from_a_run() -> None:
    nb = {"cells": [{"cell_type": "code", "execution_count": 7, "id": "abc", "metadata": {"scrolled": True},
                     "outputs": [{"output_type": "stream", "name": "stdout", "text": ["99\n"]}],
                     "source": ["print(99)\n", "x"]}],
          "metadata": {"kernelspec": {"display_name": "Py", "name": "python3"}},
          "nbformat": 4, "nbformat_minor": 5}
    out = json.loads(clean(json.dumps(nb)))
    assert out["cells"][0] == {"cell_type": "code", "execution_count": None, "id": "0", "metadata": {},
                               "outputs": [], "source": ["print(99)\n", "x"]}
    assert out["metadata"] == {"kernelspec": {"name": "python3"}}


def test_empty_input_passes_through() -> None:
    assert clean("") == ""


@pytest.mark.parametrize("text", ["{not json", "[]", '{"cells": []}'])
def test_a_non_notebook_is_refused(text: str) -> None:
    with pytest.raises(NotebookError):
        clean(text)


def test_main_filters_stdin_or_a_textconv_file(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    nb = json.dumps({"cells": [], "metadata": {"widgets": {}}, "nbformat": 4, "nbformat_minor": 5})
    path = tmp_path / "a.ipynb"
    path.write_text(nb, encoding="utf-8")
    assert notebook_clean.main(["--textconv", str(path)]) == 0
    assert json.loads(capsysbinary.readouterr().out)["metadata"] == {}
    assert notebook_clean.main(["--textconv", str(tmp_path / "missing.ipynb")]) == 1
    assert notebook_clean.main(["--nope"]) == 2


def test_sim_runs_it_before_the_cli_loads(repo_root: Path) -> None:
    """git runs it once per changed notebook on every status, add and diff."""
    code = ("import sys, runpy; sys.argv = ['sim', '_clean-notebook']; "
            "from zabob.retirement.sim import launcher\n"
            "try:\n    launcher.main()\nexcept SystemExit as e:\n    status = e.code\n"
            "print('\\n', status, 'zabob.retirement.sim.cli' in sys.modules, 'pandas' in sys.modules)")
    done = subprocess.run([sys.executable, "-c", code], input='{"cells": [], "metadata": {}}',
                          capture_output=True, text=True, check=True)
    assert done.stdout.split()[-3:] == ["0", "False", "False"]


def test_the_sim_command_cleans_too() -> None:
    """For a sim installed before the launcher dispatched it."""
    from click.testing import CliRunner

    from zabob.retirement.sim.cli import sim_group_command

    result = CliRunner().invoke(sim_group_command, ["_clean-notebook"],
                                input='{"cells": [], "metadata": {"widgets": {}}}')
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"cells": [], "metadata": {}}
