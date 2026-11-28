"""The hub's configuration (#766), run by JupyterHub from the stub
``hub.write_config`` writes, so it follows this program's upgrades. It
imports JupyterHub, which only the hub's own process has.

The users are read from ``users.toml`` at every login and spawn, so
``sim jupyter user`` changes need no restart.

Run as root, it starts each JupyterLab as its login with
``HouseholdSpawner``, which keeps the groups that open a shared data repo
where the system caps how many a process may have (#834).
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from jupyterhub.auth import PAMAuthenticator
from jupyterhub.spawner import LocalProcessSpawner, set_user_setuid

from zabob.retirement.jupyter import hub

__all__ = ["HouseholdAuthenticator", "HouseholdSpawner", "configure", "spawn_environment", "spawn_groups"]

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
    env = {"ZABOB_HUB_LOGIN": user.name, "ZABOB_HUB_REPO": str(user.repo), "ZABOB_HUB_DATA": user.data}
    if user.url:
        env["ZABOB_HUB_CLONE_URL"] = user.url
    if user.data == hub.SHARED:
        return env, str(user.repo), "/lab/tree/notebooks"
    # Their own repo sits in their home, which is what they see: it may not
    # be cloned yet, or they make it with `sim init` in a terminal.
    return env, str(user.repo.parent), f"/lab/tree/{user.repo.name}/notebooks"


def spawn_groups(member_of: Iterable[int], primary: int, wanted: Iterable[int],
                 limit: int) -> tuple[list[int], list[int]]:
    """The supplementary groups to give a login's JupyterLab, and those
    left out: ``primary`` first, then the ``wanted`` ones the login is in
    (those of its data repo and the folders above it), then the rest of
    ``member_of``, cut at ``limit``.

    macOS lets a process have 16 groups and refuses ``setgroups`` with
    more, and JupyterHub then starts the server with none (#834): a shared
    repo's group, which may be past the 16th, must not be among those cut."""
    member = list(member_of)
    order = list(dict.fromkeys([primary, *(g for g in wanted if g in member), *member]))
    return order[:limit], order[limit:]


def _path_groups(paths: Iterable[Path]) -> list[int]:
    """The groups owning each of ``paths`` and the folders above them,
    deepest first: as root, the hub can see them all."""
    found: list[int] = []
    for path in paths:
        for folder in (path, *path.parents):
            with contextlib.suppress(OSError):
                found.append(folder.stat().st_gid)
    return found


def _group_limit() -> int:
    try:
        return max(1, os.sysconf("SC_NGROUPS_MAX"))
    except (OSError, ValueError):
        return 16  # the smallest a POSIX system caps it at


class HouseholdSpawner(LocalProcessSpawner):
    """JupyterHub's local spawner, but when a login is in more groups than
    a process may have, the ones its data repo needs are kept (#834)."""

    def make_preexec_fn(self, name: str) -> Callable[[], None]:
        import pwd

        user = hub.read_users(_folder).get(name)
        entry = pwd.getpwnam(name)
        member_of = os.getgrouplist(name, entry.pw_gid)
        limit = _group_limit()
        if len(member_of) <= limit:
            return set_user_setuid(name)  # all of them fit: JupyterHub's own
        wanted = _path_groups([user.repo] if user is not None else [])
        keep, dropped = spawn_groups(member_of, entry.pw_gid, wanted, limit)
        self.log.warning("%s is in %d groups, more than the %d a process may have; leaving out %s",
                         name, len(member_of), limit, ", ".join(_group_name(g) for g in dropped))
        return _setuid(entry.pw_uid, entry.pw_gid, keep, entry.pw_dir, set_user_setuid(name))


def _group_name(gid: int) -> str:
    import grp

    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def _setuid(uid: int, gid: int, groups: list[int], home: str,
            fallback: Callable[[], None]) -> Callable[[], None]:
    """A ``preexec_fn`` that becomes ``uid`` with ``groups``, worked out
    before the fork (after it, only system calls are safe). Should the
    system refuse them, JupyterHub's own takes over, which starts the
    server with no supplementary groups rather than root's."""

    def preexec() -> None:
        try:
            os.setgid(gid)
            os.setgroups(groups)
        except OSError:
            fallback()
            return
        os.setuid(uid)
        with contextlib.suppress(OSError):
            os.chdir(home)

    return preexec


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
    c.JupyterHub.bind_url = settings.bind_url
    c.JupyterHub.db_url = f"sqlite:///{run / 'jupyterhub.sqlite'}"
    c.JupyterHub.cookie_secret_file = str(run / "jupyterhub_cookie_secret")
    c.JupyterHub.pid_file = str(run / "jupyterhub.pid")
    c.ConfigurableHTTPProxy.pid_file = str(run / "proxy.pid")
    c.JupyterHub.authenticator_class = HouseholdAuthenticator
    c.JupyterHub.spawner_class = HouseholdSpawner
    # This program's Python, so each JupyterLab and its kernels have it.
    c.Spawner.cmd = [sys.executable, "-m", "zabob.retirement.jupyter.singleuser"]
    c.Spawner.pre_spawn_hook = _pre_spawn
