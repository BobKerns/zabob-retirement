![Share with your household: JupyterHub](../assets/brand/banners/guides-jupyterhub.svg)

# Share with your household: JupyterHub

> To read a formatted `.md` file:
> - In Jupyter: right-click on it and select `Open With / Markdown Preview`
> - In VSCode: Command `Markdown Preview Enhanced: Open Preview` or ⌘⇧V

`sim jupyter start` runs one JupyterLab for you. A **hub** runs one for each
person in the household, each logging in with their own account on the
machine, from any of their devices. It's a good fit for a small always-on
computer such as a Raspberry Pi, reached over [Tailscale](https://tailscale.com),
so nothing is exposed to the internet. It's also how you send someone a link
to look at a model: the notebooks are the same ones you use, open in their
own browser.

The hub is [JupyterHub](https://jupyterhub.readthedocs.io), run from this
program's own environment, so every person's JupyterLab and its kernels have
the same Python and the same `sim` ([#766](https://github.com/BobKerns/zabob-retirement/issues/766)).
It runs on Linux and macOS, and on Windows inside WSL (below); nothing else in the program needs WSL.

## Shared or own data repo, per person

Each person's JupyterLab works on one data repo, set per person:

- **Shared** (`--shared REPO`): the same folder as others. Everyone sees the
  same CSVs and the same runs (`state/`) at once, which makes helping your
  spouse with their model easy: you're both looking at the same files. Each
  person still has their own current scenario.
- **Own** (`--own [URL]`): their own clone, `~/zabob-retirement` in their
  home folder, with its own runs. Nobody's edits get in anyone else's way,
  and changes are shared with `git pull` and `git push`, merging when two
  people changed the same thing. Given a URL, it's cloned at their first
  login; without one, they make it with `sim init` in a JupyterLab terminal.

The notebooks can't change the data, so a person you only want to show
results to sees them without being able to alter anything through them.
They can still open a terminal in JupyterLab and run `sim` commands.

## Setting it up

1. **Install the program with the hub.** Install it where every login can
   read it, with the `hub` extra: `zabob-retirement[hub]` (in a checkout,
   `uv sync --extra hub`). A copy inside one person's home folder works only
   if the others can read that folder.
2. **Install the proxy.** JupyterHub serves everything through
   `configurable-http-proxy`, which comes from npm:

   ```sh
   sudo npm install -g configurable-http-proxy
   ```

3. **Add the people.** Each one is a login that already exists on the
   machine; nothing here creates accounts. For example, Alice and Bill
   sharing Alice's data repo:

   ```sh
   sim jupyter user add alice --shared ~/zabob-retirement
   sim jupyter user add bill --shared ~/zabob-retirement
   ```

   or Bill with his own clone of the household's remote:

   ```sh
   sim jupyter user add bill --own git@github.com:alice/household-data.git
   ```

   `sim jupyter user list` shows them, `sim jupyter user edit bill` changes
   one (it asks, or takes `--shared`/`--own`), and
   `sim jupyter user delete bill` removes one. A change takes effect at that
   person's next login, with no restart.
4. **Choose where it listens.** By default the hub listens only on this
   machine, at `http://127.0.0.1:8000/`. To reach it from your other devices,
   give it the machine's Tailscale address (`tailscale ip -4`), or `0.0.0.0`
   for every network the machine is on:

   ```sh
   sim jupyter hub start --ip 100.101.102.103 --port 8000
   sim jupyter hub stop
   ```

   The address and port are remembered.
5. **Run it as a service.** Logging people in with their own passwords and
   starting their JupyterLab as them needs root, so for more than your own
   login the hub runs as a system service. `sim jupyter hub service` prints
   it (a systemd unit on Linux, a launchd daemon on macOS);
   `sudo sim jupyter hub service --install` writes it, and prints the command
   that enables and starts it.

Each person then opens the hub's address, logs in with their own account on
the machine, and lands in their data repo's notebooks. The first time, the
hub records their login name and data repo in their own settings, as
`sim login` and `sim switch --data` would, so a JupyterLab terminal's `sim`
commands use the same data repo. Whatever they change there after, with
`sim login NAME` or `sim switch --data DIR`, the hub leaves alone.

## A shared data repo needs shared permissions

Everyone sharing a data repo writes to it: their edits, and the runs under
`state/`. So the repo and its `state/` should belong to a group they're all
in, with new files staying in that group:

```sh
sudo groupadd household && sudo usermod -aG household alice && sudo usermod -aG household bill
cd ~/zabob-retirement
sudo chgrp -R household . && chmod -R g+rwX . && find . -type d -exec chmod g+s {} +
git config core.sharedRepository group
```

Git refuses to work in a repository someone else owns unless told it's
safe; the hub adds the shared repo to each person's `safe.directory` for
them.

## The hub's folder

The hub keeps its settings in `hub/` beside your `config.toml`
(`~/.config/zabob-retirement/hub/`), or in `$ZABOB_HUB_DIR`: `users.toml`
(who logs in, and to which data repo), `hub.toml` (where it listens), and
`run/`, with its log (`run/jupyterhub.log`), database and cookie secret.
`sim jupyter hub status` shows whether it's running, where, and its users.

## On Windows: inside WSL

The program itself runs on Windows as it is; only the hub needs more.
JupyterHub logs people in and starts each one's JupyterLab as them with
Linux and macOS facilities that Windows lacks, so `sim jupyter hub` runs in
WSL, the Windows Subsystem for Linux, which is a good home for the program
anyway. Install the program there ([Windows: WSL](../SETUP.md#windows-wsl),
with its video), make each person a login in the WSL distribution
(`sudo adduser bill`), and follow the steps above. WSL has no systemd by
default; turn it on with `systemd=true` under `[boot]` in `/etc/wsl.conf`
before `sim jupyter hub service`. Reaching the hub from other devices goes
through Windows: WSL forwards `localhost`, and Tailscale on Windows reaches
it there. A small Linux machine, such as a Raspberry Pi, is the other easy
host for a household's hub.

## Side by side with an editor

A separate idea that needs no hub: if you edit the data repo in VS Code while
JupyterLab has it open, a git worktree gives each tool its own checkout, so
the two don't contend for the same working folder
(`git worktree add ../zabob-retirement-jupyter <branch>`).
