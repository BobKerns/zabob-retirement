"""What the hub runs as each user, before their JupyterLab (#766): clone
their own data repo when it isn't there yet, give it the program's
notebooks, let git work in a shared one, and, the first time, record who
they are and that data repo in their own settings (#773). Then it becomes
``jupyterhub-singleuser``."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _trust(repo: Path) -> None:
    # git refuses a repository another login owns ("dubious ownership")
    # unless the user's own config says it is safe; only global config counts.
    found = subprocess.run(["git", "config", "--global", "--get-all", "safe.directory"],
                           capture_output=True, text=True, check=False).stdout.split()
    if str(repo) not in found and "*" not in found:
        subprocess.run(["git", "config", "--global", "--add", "safe.directory", str(repo)], check=False)


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


def prepare(env: dict[str, str]) -> None:
    """Make the user's data repo ready, as far as it can be; a failure is
    printed to the server's log, and JupyterLab starts anyway."""
    login = env.get("ZABOB_HUB_LOGIN")
    if not (value := env.get("ZABOB_HUB_REPO")):
        _record(login, None)
        return
    repo = Path(value)
    if not repo.exists() and (url := env.get("ZABOB_HUB_CLONE_URL")):
        done = subprocess.run(["git", "clone", url, str(repo)], check=False)  # noqa: S603, S607 - the user's URL
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
    prepare(dict(os.environ))
    singleuser = Path(sys.executable).parent / "jupyterhub-singleuser"
    os.execv(singleuser, [str(singleuser), *sys.argv[1:]])  # noqa: S606 - our own program


if __name__ == "__main__":
    main()
