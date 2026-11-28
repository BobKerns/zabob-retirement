"""The data repo's notebook clean filter (#840): ``sim _clean-notebook``.

git runs it for every notebook whose file changed, on ``status``, ``add``
and ``diff``, so it imports only the standard library: ``sim``'s launcher
(``sim/launcher.py``) calls it before the CLI and pandas load, and it does
the work nbstripout does here without nbformat, whose jsonschema import
alone takes most of a second.

It keeps what ``scripts/setup.sh`` keeps in the code repo: nbstripout's
default stripping plus the kernel's display name and the language version,
which differ from machine to machine. Its output is what nbstripout with
those keys writes, byte for byte (``tests/test_notebook_clean.py``), so a
notebook moved between the repos doesn't churn.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import Any

USAGE = "usage: sim _clean-notebook [--textconv FILE]"

# nbstripout's defaults, and the keys setup.sh adds (`--extra-keys`).
NOTEBOOK_KEYS = (
    "signature", "widgets", "kernelspec.display_name", "language_info.version",
    # nbformat's strip_transient: never stored in a file.
    "orig_nbformat", "orig_nbformat_minor",
)
CELL_METADATA_KEYS = (
    "collapsed", "ExecuteTime", "execution", "heading_collapsed", "hidden", "scrolled",
    "trusted",  # transient, as above
)
# Mime bundle values nbformat stores as lists of lines, besides text/*.
_SPLIT_MIMES = frozenset({"application/javascript", "image/svg+xml"})


class NotebookError(ValueError):
    """The input isn't a notebook this can clean."""


def _pop(d: Any, dotted: str) -> None:
    head, _, tail = dotted.partition(".")
    if not isinstance(d, dict):
        return
    if tail:
        _pop(d.get(head), tail)
    else:
        d.pop(head, None)


def _keeps_output(cell: dict[str, Any], default: bool) -> bool:
    """nbstripout's ``determine_keep_output``: a cell keeps its outputs when
    its metadata or tags say ``keep_output``, or it is an ``init_cell``."""
    metadata = cell.get("metadata", {})
    if "init_cell" in metadata:
        return bool(metadata["init_cell"])
    if "keep_output" in metadata or "keep_output" in metadata.get("tags", []):
        return bool(metadata.get("keep_output", False)) or "keep_output" in metadata.get("tags", [])
    return default


def _split_bundle(data: dict[str, Any]) -> None:
    for key, value in list(data.items()):
        if isinstance(value, str) and (key.startswith("text/") or key in _SPLIT_MIMES):
            data[key] = value.splitlines(True)


def _split_lines(cell: dict[str, Any]) -> None:
    """nbformat's ``split_lines``: multi-line text as lists, as Jupyter saves it."""
    if isinstance(cell.get("source"), str):
        cell["source"] = cell["source"].splitlines(True)
    for attachment in cell.get("attachments", {}).values():
        _split_bundle(attachment)
    for output in cell.get("outputs", []) if cell.get("cell_type") == "code" else ():
        if output.get("output_type") in ("execute_result", "display_data"):
            _split_bundle(output.get("data", {}))
        elif output.get("output_type") == "stream" and isinstance(output.get("text"), str):
            output["text"] = output["text"].splitlines(True)


def strip(nb: dict[str, Any]) -> dict[str, Any]:
    """Strip ``nb`` in place, as nbstripout does with setup.sh's keys."""
    cells = nb.get("cells")
    if not isinstance(nb.get("metadata"), dict) or not isinstance(cells, list):
        raise NotebookError("not a notebook (version 4): no metadata and cells")
    metadata = nb["metadata"]
    keep = bool(metadata["keep_output"]) if "keep_output" in metadata else False
    for key in NOTEBOOK_KEYS:
        _pop(metadata, key)
    for i, cell in enumerate(cells):
        if "outputs" in cell:
            if not _keeps_output(cell, keep):
                cell["outputs"] = []
            for output in cell["outputs"]:
                if "execution_count" in output:
                    output["execution_count"] = None
        for key in ("prompt_number", "execution_count"):
            if key in cell:
                cell[key] = None
        if "id" in cell:
            cell["id"] = str(i)  # stable across runs, as nbstripout numbers them
        for key in CELL_METADATA_KEYS:
            _pop(cell.get("metadata"), key)
        _split_lines(cell)
    return nb


def clean(text: str) -> str:
    """The stripped notebook ``text``, laid out as nbformat writes it.
    Empty input (a file just created) passes through."""
    if not text.strip():
        return text
    try:
        nb = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NotebookError(f"not JSON: {exc}") from None
    if not isinstance(nb, dict):
        raise NotebookError("not a notebook: not a JSON object")
    out = json.dumps(strip(nb), indent=1, sort_keys=True, separators=(",", ": "), ensure_ascii=False)
    return out + "\n"


def main(args: Sequence[str]) -> int:
    """The clean filter (the notebook on stdin) or, with ``--textconv
    FILE``, git's diff textconv; the cleaned notebook goes to stdout."""
    if not args:
        data = sys.stdin.buffer.read()
        name = "<stdin>"
    elif len(args) == 2 and args[0] == "--textconv":
        name = args[1]
        try:
            with open(name, "rb") as f:
                data = f.read()
        except OSError as exc:
            print(f"sim _clean-notebook: {exc}", file=sys.stderr)
            return 1
    else:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        out = clean(data.decode("utf-8-sig"))
    except (NotebookError, UnicodeDecodeError) as exc:
        print(f"sim _clean-notebook: {name}: {exc}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(out.encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0
