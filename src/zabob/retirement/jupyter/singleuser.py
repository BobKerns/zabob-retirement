"""What the hub runs as each user, before their JupyterLab (#766): clone
their own data repo when it isn't there yet, give it the program's
notebooks, and let git work in a shared one. Then it becomes
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


def prepare(env: dict[str, str]) -> None:
    """Make the user's data repo ready, as far as it can be; a failure is
    printed to the server's log, and JupyterLab starts anyway."""
    if not (value := env.get("ZABOB_HUB_REPO")):
        return
    repo = Path(value)
    if not repo.exists() and (url := env.get("ZABOB_HUB_CLONE_URL")):
        done = subprocess.run(["git", "clone", url, str(repo)], check=False)  # noqa: S603, S607 - the user's URL
        if done.returncode:
            print(f"zabob: couldn't clone {url} to {repo}", file=sys.stderr)
    if not (repo / "sim").is_dir():
        return
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
