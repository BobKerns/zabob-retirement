"""Which build of the program is running (#825): a ``version`` command and a
``--version`` flag, the same on ``sim``, ``analysis`` and ``amazon``.

An installed build reports its distribution version with the commit it was
built from (``provenance.installed_version``); a source checkout reports the
distribution version with the checkout's own commit, since that is what runs.
"""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass

import click

__all__ = ["VersionInfo", "add_version", "version_info"]

DISTRIBUTION = "zabob-retirement"


@dataclass(frozen=True)
class VersionInfo:
    version: str
    """The distribution's version, with a local label naming the commit."""
    dirty: bool
    """Built from, or running in, uncommitted code."""
    checkout: str | None
    """The source checkout running, or None for an installed build."""

    def line(self) -> str:
        where = f" (checkout {self.checkout})" if self.checkout else ""
        return f"{DISTRIBUTION} {self.version}{where}"

    def as_json(self) -> dict[str, object]:
        return {
            "name": DISTRIBUTION,
            "version": self.version,
            "dirty": self.dirty,
            "checkout": self.checkout,
            "python": platform.python_version(),
            "executable": sys.executable,
        }


def version_info() -> VersionInfo:
    from zabob.retirement.sim import provenance

    installed, dirty = provenance.installed_version()
    repo = provenance.code_repo()
    if repo is None:
        return VersionInfo(version=installed, dirty=dirty, checkout=None)
    # The checkout's commit, not the one stamped at its last editable
    # install: the code running is the working tree's. Closed, so its git
    # helper processes don't outlive the command.
    with repo:
        dirty = repo.is_dirty(untracked_files=True)
        commit = repo.head.commit.hexsha
        top = repo.working_tree_dir
    base = installed.split("+", 1)[0]
    label = f"+g{commit[:12]}" + (".dirty" if dirty else "")
    return VersionInfo(version=base + label, dirty=dirty, checkout=None if top is None else str(top))


def _echo(short: bool, as_json: bool) -> None:
    info = version_info()
    if as_json:
        click.echo(json.dumps(info.as_json(), indent=2))
    elif short:
        click.echo(info.version)
    else:
        click.echo(info.line())


def _version_flag(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    _echo(short=False, as_json=False)
    ctx.exit()


@click.command(name="version")
@click.option("--short", is_flag=True, help="Print only the version string.")
@click.option("--json", "as_json", is_flag=True,
              help="Print the version, whether it is dirty, the checkout, and the Python "
                   "running it, as JSON.")
def version_command(short: bool, as_json: bool) -> None:
    """Show which build of Zabob Retirement is running."""
    if short and as_json:
        raise click.UsageError("--short and --json can't be combined")
    _echo(short=short, as_json=as_json)


def add_version(group: click.Group) -> click.Group:
    """Give ``group`` the ``version`` command and a ``--version`` flag. The
    flag is eager, so it answers before the group's callback runs (which,
    for ``sim``, would look for a data repo)."""
    group.add_command(version_command)
    group.params.append(click.Option(
        ["--version"], is_flag=True, expose_value=False, is_eager=True,
        callback=_version_flag, help="Show the version and exit.",
    ))
    return group
