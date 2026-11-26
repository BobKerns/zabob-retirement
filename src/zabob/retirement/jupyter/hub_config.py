"""The hub's configuration (#766), run by JupyterHub from the stub
``hub.write_config`` writes, so it follows this program's upgrades. It
imports JupyterHub, which only the hub's own process has.

The users are read from ``users.toml`` at every login and spawn, so
``sim jupyter user`` changes need no restart.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from jupyterhub.auth import PAMAuthenticator

from zabob.retirement.jupyter import hub

__all__ = ["HouseholdAuthenticator", "configure", "spawn_environment"]

# Set by configure: the hub's folder, for the authenticator and spawn hook.
_folder: Path | None = None


class HouseholdAuthenticator(PAMAuthenticator):
    """The machine's own logins, those `sim jupyter user add` named."""

    def check_allowed(self, username: str, authentication: Any = None) -> bool:  # noqa: ARG002
        return username in hub.read_users(_folder)


def spawn_environment(user: hub.HubUser) -> tuple[dict[str, str], str, str]:
    """For ``user``'s JupyterLab: its environment, the folder it serves, and
    the page it opens on. Nothing here says who they are or which data repo
    they use: ``singleuser.prepare`` records those in their own settings, as
    `sim login` would (#773), so a terminal there and `sim switch` agree."""
    env = {"ZABOB_HUB_LOGIN": user.name, "ZABOB_HUB_REPO": str(user.repo)}
    if user.url:
        env["ZABOB_HUB_CLONE_URL"] = user.url
    if user.data == hub.SHARED:
        return env, str(user.repo), "/lab/tree/notebooks"
    # Their own repo sits in their home, which is what they see: it may not
    # be cloned yet, or they make it with `sim init` in a terminal.
    return env, str(user.repo.parent), f"/lab/tree/{user.repo.name}/notebooks"


def _pre_spawn(spawner: Any) -> None:
    user = hub.read_users(_folder).get(spawner.user.name)
    if user is None:
        raise RuntimeError(f"{spawner.user.name} is not one of this hub's users (`sim jupyter user add`)")
    env, root, url = spawn_environment(user)
    spawner.environment.update(env)
    spawner.notebook_dir = root
    spawner.default_url = url


def configure(c: Any, folder: Path) -> None:
    """Fill in JupyterHub's config object ``c`` from the hub folder."""
    global _folder  # noqa: PLW0603 - JupyterHub hands us one config per process
    _folder = folder
    settings = hub.read_settings(folder)
    run = hub.run_dir(folder)
    run.mkdir(parents=True, exist_ok=True)
    c.JupyterHub.bind_url = f"http://{settings.ip}:{settings.port}/"
    c.JupyterHub.db_url = f"sqlite:///{run / 'jupyterhub.sqlite'}"
    c.JupyterHub.cookie_secret_file = str(run / "jupyterhub_cookie_secret")
    c.JupyterHub.pid_file = str(run / "jupyterhub.pid")
    c.ConfigurableHTTPProxy.pid_file = str(run / "proxy.pid")
    c.JupyterHub.authenticator_class = HouseholdAuthenticator
    # This program's Python, so each JupyterLab and its kernels have it.
    c.Spawner.cmd = [sys.executable, "-m", "zabob.retirement.jupyter.singleuser"]
    c.Spawner.pre_spawn_hook = _pre_spawn
