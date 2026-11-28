"""What the hub runs as each user, before their JupyterLab (#766): clone
their own data repo when it isn't there yet, give it the program's
notebooks, let git work in a shared one, and, the first time, record who
they are and that data repo in their own settings (#773). Then it becomes
``jupyterhub-singleuser``, unless the data repo can't be opened (#834):
JupyterLab would start without the hub's extension and never answer it,
and the hub would report only a timeout."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _trust(repo: Path) -> None:
    # git refuses a repository another login owns ("dubious ownership")
    # unless the user's own config says it is safe; only global config counts.
    try:
        found = subprocess.run(["git", "config", "--global", "--get-all", "safe.directory"],
                               capture_output=True, text=True, check=False).stdout.splitlines()
        if str(repo) not in found and "*" not in found:
            subprocess.run(["git", "config", "--global", "--add", "safe.directory", str(repo)], check=False)
    except OSError as exc:  # no git: JupyterLab starts anyway
        print(f"zabob: couldn't run git to trust {repo}: {exc}", file=sys.stderr)


def _record(login: str | None, data_dir: Path | None) -> None:
    """What `sim login` and `sim switch --data` would record, when nothing
    is yet: a name or data repo the person has chosen since is theirs."""
    from zabob.retirement import user_config

    try:
        if login and user_config.user_name() is None:
            user_config.set_user(login)
        if data_dir is not None and user_config.default_data_dir() is None:
            user_config.set_default_data_dir(data_dir)
    except OSError as exc:
        print(f"zabob: couldn't record your settings in {user_config.config_dir()}: {exc}", file=sys.stderr)


class Unreachable(Exception):
    """The data repo is there but this login can't get to it, or a shared
    one isn't there at all."""


def _check_reachable(repo: Path, shared: bool) -> None:
    # Walked from the top: a folder that keeps them out makes everything
    # below it look missing.
    blocker = None
    for folder in (*reversed(repo.parents), repo):
        if not os.access(folder, os.F_OK):
            if shared:
                raise Unreachable(f"the shared data repo {repo} isn't there")
            return  # their own, cloned or made next
        if not os.access(folder, os.X_OK if folder != repo else os.R_OK | os.X_OK):
            blocker = folder
            break
    if blocker is None:
        return
    raise Unreachable(
        f"can't open the data repo {repo}: {blocker} doesn't let this login in. A shared data repo, "
        "and every folder above it, must let in a group everyone sharing it is in; see \"A shared "
        "data repo needs shared permissions\" in the hub guide (docs/guides/jupyterhub.md)")


def prepare(env: dict[str, str]) -> None:
    """Make the user's data repo ready, as far as it can be; a failure is
    printed to the server's log, and JupyterLab starts anyway. A repo the
    login can't open raises ``Unreachable``: JupyterLab couldn't serve it."""
    login = env.get("ZABOB_HUB_LOGIN")
    if not (value := env.get("ZABOB_HUB_REPO")):
        _record(login, None)
        return
    repo = Path(value)
    _check_reachable(repo, env.get("ZABOB_HUB_DATA") == "shared")
    if not repo.exists() and (url := env.get("ZABOB_HUB_CLONE_URL")):
        try:
            done = subprocess.run(["git", "clone", url, str(repo)], check=False)  # noqa: S603, S607 - the user's URL
        except OSError as exc:
            print(f"zabob: couldn't run git to clone {url}: {exc}", file=sys.stderr)
        else:
            if done.returncode:
                print(f"zabob: couldn't clone {url} to {repo}", file=sys.stderr)
    if not (repo / "sim" / "persons.csv").is_file():
        _record(login, None)  # their own, not made yet: `sim init` records it
        return
    _record(login, repo / "sim")
    if repo.stat().st_uid != os.getuid():
        _trust(repo)
    if not (repo / "notebooks").exists():
        from zabob.retirement.sim.data_repo import copy_notebooks

        try:
            copy_notebooks(repo / "notebooks")
        except OSError as exc:
            print(f"zabob: couldn't copy the notebooks into {repo}: {exc}", file=sys.stderr)


def main() -> None:
    try:
        prepare(dict(os.environ))
    except Unreachable as exc:
        # The hub reports the exit at once, and this in its log.
        print(f"zabob: {os.environ.get('ZABOB_HUB_LOGIN', 'this login')}: {exc}", file=sys.stderr)
        sys.exit(1)
    singleuser = Path(sys.executable).parent / "jupyterhub-singleuser"
    os.execv(singleuser, [str(singleuser), *sys.argv[1:]])  # noqa: S606 - our own program


if __name__ == "__main__":
    main()
