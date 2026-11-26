from __future__ import annotations

import click

from zabob.retirement.oscompat import utf8_stdio
from zabob.retirement.amazon.cli import amazon_group_command
from zabob.retirement.historical.cli import historical_charts_command, historical_command
from zabob.retirement.research_plugin import research_plugin_command
from zabob.retirement.sim.cli import sim_group_command
from zabob.retirement.videos.cli import video_group_command


@click.group()
def main() -> None:
    """Zabob Retirement command-line tools."""
    utf8_stdio()


main.add_command(amazon_group_command)
main.add_command(sim_group_command)
main.add_command(historical_command)
main.add_command(historical_charts_command)
main.add_command(research_plugin_command)
main.add_command(video_group_command)


if __name__ == "__main__":
    main()
