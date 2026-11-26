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
The file is read from ``main``'s last commit, not the working tree, so a
branch checked out or an edit not yet committed changes nothing; it is
written only on ``main``, and pushed at once, so other clones see it on
their next catch-up. ``sim builder install`` names its machine when the data
repo has a remote, nothing is named yet (on ``main`` or its upstream, just
fetched) and this install fetches, rolls or researches; ``sim builder
writer`` shows, moves or clears it.

A machine is named ``<login>@<host>``, in lower case: the login name, since
two accounts on one machine are two clones, and the host's short name (on
macOS its LocalHostName, which doesn't change with the network). ``sim
builder install`` records the name it found in the builder's config, and
that recorded name is the one compared from then on, so a host name that
changes later (a container recreated, a laptop on another network) doesn't
leave the data repo with no writer.
"""

from __future__ import annotations

import platform
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

from zabob.retirement.oscompat import login_name

__all__ = ["FILE", "claim", "elsewhere", "machine", "normalize", "read_writer", "set_writer",
           "this_machine", "write_writer", "writes_here"]

FILE = ".builder.toml"
_HEADER = ("# Which machine's background builder fetches prices, rolls scenarios forward and\n"
           "# researches symbols for this data repo (#785); the others only build runs.\n"
           "# `sim builder writer` shows or changes it.\n")
_NAME = re.compile(r"[^@\s]+@[^@\s.]+")


def normalize(name: str) -> str:
    """``name`` as two machine names compare: lower case, the host's domain
    dropped, so ``Bill@Desk.example.com`` is ``bill@desk``."""
    login, at, host = name.strip().lower().partition("@")
    return f"{login}{at}{host.split('.')[0]}" if at else login


def valid(name: str) -> bool:
    """Whether ``name``, normalized, has the ``login@host`` shape."""
    return _NAME.fullmatch(normalize(name)) is not None


def _host() -> str:
    if sys.platform == "darwin":
        # platform.node() follows the network on macOS unless HostName is set.
        try:
            done = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True,
                                  text=True, check=False, timeout=5)
            if done.returncode == 0 and done.stdout.strip():
                return done.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return platform.node()


def this_machine() -> str:
    """This login on this host, as :data:`FILE` names one."""
    return normalize(f"{login_name()}@{_host().split('.')[0].strip() or 'unknown'}")


def machine(data_dir: Path | str | None, config: dict[str, Any] | None = None) -> str:
    """The name this clone goes by: the one ``sim builder install`` recorded
    in the builder's config (``config``, else read), else :func:`this_machine`."""
    if config is None and data_dir is not None:
        from zabob.retirement.sim.builder import BuilderPaths, read_config

        config = read_config(BuilderPaths.for_data(Path(data_dir)))
    recorded = (config or {}).get("machine")
    return normalize(recorded) if isinstance(recorded, str) and recorded.strip() else this_machine()


def _git(where: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True,
                          check=False, stdin=subprocess.DEVNULL)


def _rel(data_dir: Path) -> tuple[Path, str] | None:
    """The data repo's top and :data:`FILE`'s path in it, or None outside git."""
    done = _git(data_dir, "rev-parse", "--show-toplevel")
    if done.returncode:
        return None
    top = Path(done.stdout.strip())
    try:
        return top, (Path(data_dir) / FILE).resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        return None


def _parse(text: str) -> str | None:
    try:
        writer = tomllib.loads(text).get("writer")
    except tomllib.TOMLDecodeError:
        return None
    return (normalize(writer) or None) if isinstance(writer, str) else None


def read_writer(data_dir: Path, ref: str = "main") -> str | None:
    """The machine :data:`FILE` names in ``ref``'s last commit (``main``, or
    its upstream), or None when it names none (or is unreadable, which
    counts as none rather than stopping every builder)."""
    found = _rel(Path(data_dir))
    if found is None:
        return None
    top, rel = found
    done = _git(top, "show", f"{ref}:{rel}")
    return _parse(done.stdout) if done.returncode == 0 else None


def write_writer(data_dir: Path, writer: str | None) -> Path:
    """Name ``writer`` in the working tree's :data:`FILE`, or with None
    remove the file; its path. :func:`set_writer` commits it."""
    path = Path(data_dir) / FILE
    if writer is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(f'{_HEADER}writer = "{_quoted(writer)}"\n', encoding="utf-8")
    return path


def _quoted(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def writes_here(data_dir: Path | str | None, config: dict[str, Any] | None = None) -> bool:
    """Whether this machine's builder fetches, rolls and researches for
    ``data_dir``: when it is the one named, or none is."""
    return data_dir is None or elsewhere(Path(data_dir), config) is None


def elsewhere(data_dir: Path, config: dict[str, Any] | None = None) -> str | None:
    """The other machine named to write for ``data_dir``, or None when it is
    this one or none is."""
    writer = read_writer(data_dir)
    return writer if writer is not None and writer != machine(data_dir, config) else None


def set_writer(data_dir: Path, writer: str | None) -> str:
    """Name ``writer`` (or with None, no machine) in :data:`FILE`, commit
    just that file on ``main`` and push ``main`` when it is strictly ahead of
    its upstream; a line saying what was done. Refused (the line says why)
    off ``main``, or mid-merge; a failed push leaves the commit for the next."""
    from zabob.retirement.sim import data_commit, price_schedule

    data_dir = Path(data_dir)
    writer = normalize(writer) if writer is not None else None
    what = f"{writer} fetches prices, rolls scenarios and researches symbols" if writer else \
        "every machine's builder fetches prices, rolls scenarios and researches symbols"
    if read_writer(data_dir) == writer:
        return f"{what} already; nothing changed"
    found = _rel(data_dir)
    if found is None:
        return f"not changed: {data_dir} isn't in a git repository"
    top, rel = found
    branch = _git(top, "symbolic-ref", "-q", "--short", "HEAD").stdout.strip()
    if branch != price_schedule.DATA_BRANCH:
        return (f"not changed: the data repo has {branch or 'a detached HEAD'} checked out; "
                f"check out {price_schedule.DATA_BRANCH} and run this again, so every clone sees it")
    path = write_writer(data_dir, writer)
    subject = f"Background builder: {writer} writes for this data repo" if writer else \
        "Background builder: no one machine writes for this data repo"
    try:
        data_commit.commit(data_dir, [("D" if writer is None else "M", rel)], subject=subject)
    except data_commit.CommitError as exc:
        return f"{what} (in {path}, not committed: {exc}; commit it on main so the other clones see it)"
    if not price_schedule.has_upstream(data_dir):
        return f"{what} ({rel}, committed)"
    pushed = price_schedule._push(top)
    if pushed.startswith("pushed"):
        return f"{what} ({rel}, committed and pushed)"
    return f"{what} ({rel}, committed; {pushed}. It isn't settled until main is pushed)"


def _named_upstream(data_dir: Path) -> str | None:
    """The machine named on ``main``'s upstream, as last fetched."""
    from zabob.retirement.sim import price_schedule

    try:
        found = price_schedule._upstream(price_schedule._top(data_dir))
    except price_schedule.PriceScheduleError:
        return None
    return read_writer(data_dir, found[1]) if found is not None else None


def claim(data_dir: Path, config: dict[str, Any]) -> list[str]:
    """What ``sim builder install`` says and does about :data:`FILE`: name
    this machine when this install fetches, rolls or researches, the data
    repo has a remote (so other clones may share it; a lone clone needs no
    file), and nothing is named on ``main`` or its upstream after a catch-up;
    or say which other machine is named."""
    from zabob.retirement.sim import price_schedule

    data_dir = Path(data_dir)
    if not any(config.get(key, True) for key in ("prices", "roll", "research")):
        return []  # this one doesn't write, so it doesn't claim
    if not price_schedule.has_upstream(data_dir):
        return []
    me = machine(data_dir, config)
    try:
        said = price_schedule.catch_up(data_dir)
    except (price_schedule.PriceScheduleError, OSError) as exc:
        said = [f"couldn't catch up with origin first: {exc}"]
    named = read_writer(data_dir) or _named_upstream(data_dir)
    if named is not None and named != me:
        return [*said, f"prices, rolls and research come from {named}'s builder, by catching up "
                       "with origin; `sim builder writer --here` moves them to this machine"]
    if named is not None:
        return said
    return [*said, set_writer(data_dir, me),
            "the other clones' builders only build runs; `sim builder writer` changes which machine writes"]
