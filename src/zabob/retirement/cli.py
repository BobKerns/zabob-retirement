from __future__ import annotations

import click

from zabob.retirement.oscompat import utf8_stdio
from zabob.retirement.amazon.cli import amazon_group_command
from zabob.retirement.historical.cli import historical_charts_command
from zabob.retirement.sim.cli import completion_group, sim_group_command
from zabob.retirement.version_cli import add_version
from zabob.retirement.videos.cli import video_group_command


@click.group()
def main() -> None:
    """Zabob Retirement's internal and not-yet-general tools; `sim` is the
    simulator's own command."""
    utf8_stdio()


main.add_command(amazon_group_command)
main.add_command(sim_group_command)
main.add_command(historical_charts_command)
main.add_command(video_group_command)
main.add_command(completion_group)  # the same group as sim's (#844)
add_version(main)


if __name__ == "__main__":
    main()
