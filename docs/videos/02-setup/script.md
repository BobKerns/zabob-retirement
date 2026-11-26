+++
series = "Planning with the simulator"
episode = "Video 2"
title = "Setup and install"
subtitle = "From nothing to a data folder of your own"
data = "prototype_data"

[youtube]
next = "03-base-scenario"
summary = """
Alice installs the simulator on her own computer from PyPI, and starts a \
folder for her household's data. Setup guide: \
https://github.com/BobKerns/zabob-retirement/blob/main/docs/SETUP.md

On Windows, the same commands work in PowerShell; the setup guide's Windows \
section has the line that installs uv there."""
contents = [
  "Getting uv, on a Mac, Linux, or Windows",
  "Installing the simulator (uv tool install zabob-retirement)",
  "Terminals that can show charts",
  "The program, and your data",
  "Starting a data folder (sim init)",
  "What's inside it",
  "Your data, from any terminal, and the current scenario (sim switch)",
  "A plan of your own (sim scenario create)",
  "The notebooks (sim jupyter start)",
  "Saving your work, so every run can be repeated (sim run, sim commit)",
  "Upgrading (uv tool upgrade)",
]
+++

The second video of #366 (issue #374): installing from PyPI with
`uv tool install zabob-retirement`, as SETUP.md's "Install the program"
does, starting a data repo with `sim init` (which makes it the default, so
there is nothing to activate, #687), the current scenario, the notebooks, what `sim run` offers to commit, and upgrading.

The tapes record the program as installed, not this checkout's venv: the
builder installs a wheel built from the checkout into the demo's home, and
the install scene removes it and installs it again on camera, from that
wheel (README, "Tapes"). uv's own installer is typed, not run: it changes
the shell's startup files, and the machine recording already has uv.

## Scene `title`: Title card

```slide
template = "title"
```

Planning with the simulator. Video two: setup and install.

In this video, Alice installs the simulator on her own computer, and starts
a folder for her household's data. By the end, she can run a plan, and
every run she makes can be repeated exactly.

## Scene `uv`: First, uv

```tape
Set FontSize 30
Sleep 500ms
Type "curl -LsSf https://astral.sh/uv/install.sh | sh"
Sleep 16s
```

The simulator is installed with a tool called {uv|U V}, which also fetches
the right version of Python for it. Open a terminal, on a Mac, on Linux, or
on Windows, where PowerShell is fine. If you don't have {uv|U V} yet, this
line from the {uv|U V} website installs it; then open a new terminal window.
On Windows, the website gives a PowerShell line instead, and you'll want git
too; the setup guide, linked in the description, has both.

> Production note: the tape stops short of Enter. uv's installer changes
> the shell's startup files, and the recording machine has uv already.

## Scene `install`: Installing the simulator

```tape
Hide
Type "export HOME=$PWD/home && uv tool uninstall zabob-retirement > /dev/null 2>&1; cd && clear"
Enter
Sleep 300ms
Show
Sleep 500ms
Type "uv tool install zabob-retirement"
Sleep 400ms
Enter
Wait
Sleep 8s
```

Then one line installs the simulator. {uv|U V} downloads it, with
everything it needs, into a place of its own, and puts the sim and analysis
commands where your terminal finds them. The first time, it may take a
minute or two. You don't need to know git, or anything about how the code
is kept.

> Production note: until 1.0.0b1 is on PyPI, the install comes from the
> wheel the builder made from this checkout (`UV_FIND_LINKS`, set while
> hidden), with the lock's versions; the line typed is the one SETUP.md
> gives.

## Scene `terminals`: A terminal that shows pictures

```slide
template = "card"
heading = "A terminal that shows pictures"
body = [
  "Mac: iTerm2 or Ghostty",
  "Linux: kitty, Ghostty or WezTerm",
  "Anywhere: VS Code's terminal",
  "Any other terminal saves the picture as a file",
]
speaker = "bill"
```

Any terminal runs the simulator. A few commands can also draw a chart right
in the terminal, and for that you want one that shows pictures. On a Mac,
iTerm2 or Ghostty. On Linux, kitty, Ghostty or WezTerm. Or, anywhere, VS
Code's own terminal, with images turned on in its settings. In any other
terminal, the chart is saved as a picture file instead, and the command says
where. The setup guide keeps the list.

## Scene `two-folders`: The program, and your data

```slide
template = "card"
heading = "The program, and your data"
body = [
  "The program: kept by uv. Upgrading it never touches your data.",
  "zabob-retirement, in your home folder: your household. Plain text files, with their history.",
]
```

So there are two parts. The program, the simulator itself, is kept by
{uv|U V}, out of your way. Your data, your household, your accounts, your
plans, goes in a folder of its own. They are kept apart on purpose. The
program can be upgraded without touching your numbers, and your numbers
never leave your computer. Your data folder keeps its history, so every run
can record exactly which version of your data, and of the program, produced
it.

## Scene `init`: Starting a data folder

```tape
Hide
Type "export HOME=$PWD/home && rm -rf ~/zabob-retirement && cd && clear"
Enter
Sleep 300ms
Show
Sleep 500ms
Type "sim init"
Sleep 400ms
Enter
Sleep 1500ms
Type "alice"
Sleep 600ms
Enter
Sleep 1s
Type "Alice Example"
Sleep 600ms
Enter
Sleep 1s
Type "1962-04-15"
Sleep 600ms
Enter
Sleep 1s
Type "f"
Sleep 600ms
Enter
Sleep 1s
Enter
Wait
Sleep 10s
```

Sim init makes your data folder: {zabob-retirement|zabob retirement}, in
your home folder, unless you name another. It asks who you are. An id, one
word, that the data uses for you. Your name. Your birth date, which sets
your age for things like Medicare and required distributions. Your sex,
which picks a life table if you want the simulator to vary how long you
live; you can leave it blank. And the household's tax filing status: married
filing jointly is the default. Then it builds the folder, checks that the
starting scenario, base, loads, copies in the notebooks, saves a first
version of everything with git, and makes it your data folder from now on. On a Mac, if a window offers to install the
command line tools, which include git, let it finish, and run sim init
again.

> Production note: the tapes' environment sets `ZABOB_NO_BUILDER`, so
> this `sim init` doesn't turn on background builds, which a real one does.

## Scene `inside`: What's inside

```tape
Set FontSize 27
Hide
Type "export HOME=$PWD/home && cd ~/zabob-retirement && clear"
Enter
Sleep 300ms
Show
Sleep 500ms
Type "ls"
Sleep 400ms
Enter
Wait
Sleep 3s
Type "ls sim sim/scenarios/base"
Sleep 400ms
Enter
Wait
Sleep 12s
```

Inside are two folders. Notebooks holds the notebooks, which we'll come to.
Sim holds your data: plain text files, mostly spreadsheets you could open in
any spreadsheet program. Persons holds the people in the household.
Scenarios holds your plans, starting with base. Base is where your
household goes: its accounts, income, spending, and the rules that move
money between them. For now it's nearly empty; the next video fills it in.
The tax tables and other standard assumptions aren't copied here. They're
{read|red} from the program, so they stay current when you upgrade it.

## Scene `current`: Your data, and the current scenario

```tape
Hide
Type "export HOME=$PWD/home && cd && unset ZABOB_DATA_DIR && clear"
Enter
Sleep 300ms
Show
Sleep 500ms
Type "sim switch"
Sleep 400ms
Enter
Wait
Sleep 8s
```

There's nothing to set up before you start. Sim init made this your data
folder, so every sim command finds it, in any terminal window you open.
Most commands work on the current scenario unless you name another one.
Sim switch says which one is current: base. In bash or zsh, an optional
line in the setup guide also shows your data and the current scenario in
the prompt, and lets the tab key finish names for you.

> Production note: the recordings set `ZABOB_DATA_DIR` to the prototype
> copy, so each tape unsets it while hidden; a new user has none, and the
> default `sim init` recorded is what the commands use.

## Scene `plan`: A plan of your own

```tape
Set FontSize 24
Hide
Type "export HOME=$PWD/home && cd && unset ZABOB_DATA_DIR && clear"
Enter
Sleep 2s
Show
Sleep 500ms
Type "sim scenario create my_plan base --description 'Our first plan'"
Sleep 400ms
Enter
Wait
Sleep 8s
Type "sim switch base"
Sleep 400ms
Enter
Wait
Sleep 6s
```

A new scenario builds on another one. Sim scenario create makes my plan,
building on base, and makes it the current scenario. It starts with nothing of its own, so for now it's the same as base.
Sim switch, with a scenario's name, changes the current scenario back. So
does naming a scenario on any other command.

> Production note: "my plan" is spelled with a space so the voice doesn't
> say "underscore".

## Scene `notebooks`: The notebooks

```slide
template = "card"
heading = "The notebooks"
body = [
  "In a terminal: sim jupyter start",
  "They're in your data folder, in notebooks",
  "Charts and tables, no code to write",
]
speaker = "bill"
```

Besides the terminal, the simulator comes with Jupyter notebooks: pages of
charts and tables that you explore with menus and sliders, without writing
any code. Sim init put them in your data folder. To open them, type
sim jupyter start in a terminal. JupyterLab opens in your web
browser, with the notebooks on the left, and sim jupyter stop closes it
when you're done. Video four goes through them.

## Scene `commit`: Saving your work

```tape
Set FontSize 26
Hide
Type "export HOME=$PWD/home && cd && unset ZABOB_DATA_DIR"
Enter
Type "sim scenario create my_plan base --description 'Our first plan' > /dev/null 2>&1 && clear"
Enter
Sleep 4s
Show
Sleep 500ms
Type "sim run"
Sleep 400ms
Enter
Sleep 12s
Enter
Wait
Sleep 10s
```

Every time you change your data, by a command like that one or by editing a
file, the change is new: nothing has recorded it yet. When you run a
scenario with changes like that, sim run lists them, and offers to save a
version first. Say yes, the default, and it saves them with a message saying
what changed, then runs. That's what makes a run repeatable: it records the
saved version it {read|red}, so you, or anyone you share it with, can get the same
answer later, and see what changed between two runs. Sim init also turned
on background builds: saving a change reruns, in the background, every
scenario it affects. And sim commit saves your changes without running.

## Scene `upgrade`: Upgrading

```slide
template = "card"
heading = "Upgrading"
body = [
  "uv tool upgrade zabob-retirement",
  "Then the new notebooks: sim notebooks copy --replace",
  "Runs made with the old version are rebuilt",
]
speaker = "alice"
```

To upgrade the simulator later, {uv|U V} tool upgrade, with its name. Then
take the new notebooks into your data folder with sim notebooks copy,
replace. That replaces your copies, so if you changed one, save it under
another name first. Your runs made with the old version are out of date,
and are rebuilt with the new one.

## Scene `end`: Next time

```slide
template = "card"
heading = "Next: your base scenario"
body = "Your household's accounts, income and spending, in the scenario everything else builds on."
speaker = "alice"
```

Next time: filling in your base scenario, with your household's accounts,
income and spending.
