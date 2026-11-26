"""#785: one background builder per data repo writes what every clone shares.

Each clone of a data repo (another machine, another account under ``sim
login`` or the hub, a container beside a laptop) can run its own builder.
Builds are each clone's own, but the price fetch (#560), the nightly roll
(#564) and the morning research (#640) commit to ``main`` and push: two
clones doing them fetch twice, research the same symbol twice (the pick is
deterministic), and make commits that conflict when either pulls. So a
committed file in the data dir, ``.builder.toml``, names the one machine that
does them:

    writer = "bob@laptop"

Every other builder only builds runs, and gets the prices, rolls and weights
by catching up with ``origin`` (``price_schedule.catch_up``). With no file,
or no ``writer`` in it, every builder writes, as one clone alone always did.
``sim builder install`` names its machine when the data repo has a remote
and nothing is named yet; ``sim builder writer`` shows, moves or clears it.

A machine is named ``<login>@<host>``: the login name, since two accounts on
one machine are two clones, and the host's short name, lower case.
"""

from __future__ import annotations

import platform
import tomllib
from pathlib import Path

from zabob.retirement.oscompat import login_name

__all__ = ["FILE", "claim", "elsewhere", "read_writer", "set_writer", "this_machine", "write_writer", "writes_here"]

FILE = ".builder.toml"
_HEADER = ("# Which machine's background builder fetches prices, rolls scenarios forward and\n"
           "# researches symbols for this data repo (#785); the others only build runs.\n"
           "# `sim builder writer` shows or changes it.\n")


def this_machine() -> str:
    """This login on this machine, as :data:`FILE` names one."""
    host = platform.node().split(".")[0].strip().lower() or "unknown"
    return f"{login_name()}@{host}"


def read_writer(data_dir: Path) -> str | None:
    """The machine :data:`FILE` names, or None when it names none (or is
    unreadable, which counts as none rather than stopping every builder)."""
    try:
        text = (Path(data_dir) / FILE).read_text(encoding="utf-8")
        writer = tomllib.loads(text).get("writer")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    return writer.strip() or None if isinstance(writer, str) else None


def write_writer(data_dir: Path, writer: str | None) -> Path:
    """Name ``writer`` in :data:`FILE`, or with None remove the file; its path."""
    path = Path(data_dir) / FILE
    if writer is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(f'{_HEADER}writer = "{_quoted(writer)}"\n', encoding="utf-8")
    return path


def _quoted(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def writes_here(data_dir: Path | str | None) -> bool:
    """Whether this machine's builder fetches, rolls and researches for
    ``data_dir``: when it is the one named, or none is."""
    return data_dir is None or elsewhere(Path(data_dir)) is None


def elsewhere(data_dir: Path) -> str | None:
    """The other machine named to write for ``data_dir``, or None when it is
    this one or none is."""
    writer = read_writer(data_dir)
    return writer if writer is not None and writer != this_machine() else None


def set_writer(data_dir: Path, writer: str | None) -> str:
    """Name ``writer`` (or with None, no machine) in :data:`FILE` and commit
    just that file; a line saying what was done. Not committed (mid-merge,
    say) it is left written, and the line says to commit it."""
    from zabob.retirement.sim import data_commit

    data_dir = Path(data_dir)
    if writer is None and not (data_dir / FILE).exists():
        return "no machine was named: every machine's builder fetches prices, rolls scenarios and researches symbols"
    path = write_writer(data_dir, writer)
    root = data_commit.repo_top(data_dir)
    rel = path.resolve().relative_to(root.resolve()).as_posix()
    what = f"{writer} fetches prices, rolls scenarios and researches symbols" if writer else \
        "every machine's builder fetches prices, rolls scenarios and researches symbols"
    subject = f"Background builder: {writer} writes for this data repo" if writer else \
        "Background builder: no one machine writes for this data repo"
    try:
        data_commit.commit(data_dir, [("D" if writer is None else "M", rel)], subject=subject)
    except data_commit.CommitError as exc:
        return f"{what} (in {path}, not committed: {exc}; commit it so the other clones see it)"
    return f"{what} ({rel}, committed; it reaches the other clones with the next push)"


def claim(data_dir: Path) -> list[str]:
    """What ``sim builder install`` says and does about :data:`FILE`: name
    this machine when nothing is named yet and the data repo has a remote
    (so other clones may share it; a lone clone needs no file), or say which
    other machine is named."""
    from zabob.retirement.sim import price_schedule

    data_dir = Path(data_dir)
    if (other := elsewhere(data_dir)) is not None:
        return [f"prices, rolls and research come from {other}'s builder, by catching up with origin; "
                "`sim builder writer --here` moves them to this machine"]
    if read_writer(data_dir) is not None or not price_schedule.has_upstream(data_dir):
        return []
    return [set_writer(data_dir, this_machine()),
            "the other clones' builders only build runs; `sim builder writer` changes which machine writes"]
