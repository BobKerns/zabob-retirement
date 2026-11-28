"""The ``sim`` program's entry point.

The data repo's clean filter runs ``sim _clean-notebook`` once per changed
notebook on every ``git status``, ``add`` and ``diff`` (#840), so it is
dispatched here, before ``sim/cli.py`` and pandas load (most of a second).
Everything else goes to the click group, which also has ``_clean-notebook``
(hidden), for a ``sim`` installed before this entry point was.
"""

from __future__ import annotations

import sys

CLEAN_NOTEBOOK = "_clean-notebook"


def main() -> None:
    if sys.argv[1:2] == [CLEAN_NOTEBOOK]:
        from zabob.retirement.notebook_clean import main as clean

        sys.exit(clean(sys.argv[2:]))
    from zabob.retirement.sim.cli import sim_group_command

    sim_group_command()
