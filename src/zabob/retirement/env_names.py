"""The environment variables' old names (#782).

They were ``ANALYSIS_*`` and are now ``ZABOB_*``. The old names aren't read,
but one still set stops every command with the new name, rather than being
quietly ignored: an agent that sets ``ANALYSIS_KEEP_SCENARIO`` would
otherwise move the user's current scenario, and a shell activated by a data
repo's old ``activate-analysis`` would run without its settings. An old name
holding the same value as its new one (both scripts sourced) only warns.

This check goes at 1.0.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

import click

__all__ = ["OLD_PREFIX", "NEW_PREFIX", "check_old_env_names", "old_env_names"]

OLD_PREFIX = "ANALYSIS_"
NEW_PREFIX = "ZABOB_"

def old_env_names(environ: Mapping[str, str]) -> tuple[list[str], list[str]]:
    """The old names set in ENVIRON: those set differently from (or without)
    their new name, then those set to the same value as it."""
    stale, shadowed = [], []
    for name in sorted(environ):
        if not name.startswith(OLD_PREFIX):
            continue
        new = NEW_PREFIX + name.removeprefix(OLD_PREFIX)
        (shadowed if environ.get(new) == environ[name] else stale).append(name)
    return stale, shadowed


def check_old_env_names() -> None:
    """Stop with the new names if any old one is set on its own; warn about
    one that only repeats its new one."""
    # `analysis sim ...` runs both groups' callbacks; one report is enough.
    if (ctx := click.get_current_context(silent=True)) is not None:
        meta = ctx.find_root().meta
        if meta.get("zabob.env_names.checked"):
            return
        meta["zabob.env_names.checked"] = True
    stale, shadowed = old_env_names(os.environ)
    for name in shadowed:
        click.echo(f"warning: {name} is now {_new(name)}; unset {name}", err=True)
    if not stale:
        return
    lines = [f"{name} is now {_new(name)}" for name in stale]
    if data_dir := (os.environ.get(f"{OLD_PREFIX}DATA_DIR") if f"{OLD_PREFIX}DATA_DIR" in stale else None):
        from shlex import quote

        from zabob.retirement.resources import TEMPLATES_DIR

        # The data repo's own copy: git mv keeps its history, cp brings it up to date.
        lines += ["This shell was activated by the data repo's activate-analysis, from before the rename.",
                  "Replace it with activate-retirement, then source that in a new shell:",
                  f"  git -C {quote(data_dir)} mv activate-analysis activate-retirement",
                  f"  cp {quote(str(TEMPLATES_DIR / 'activate-retirement'))} {quote(data_dir)}/"]
    else:
        lines.append(f"Rename them, or unset them: {' '.join(stale)}")
    raise click.ClickException("\n".join(lines))


def _new(name: str) -> str:
    return NEW_PREFIX + name.removeprefix(OLD_PREFIX)
