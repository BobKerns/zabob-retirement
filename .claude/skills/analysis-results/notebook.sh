#!/usr/bin/env bash
# Open a notebook in the user's browser, starting JupyterLab first if it
# isn't running.
#
#   .claude/skills/analysis-results/notebook.sh NOTEBOOK.ipynb
#
# Needs env.sh sourced (the real data activated). `sim jupyter start` runs
# JupyterLab from the main checkout ($ZABOB_REPO_DIR), in the background
# with its log in state/jupyter.log, reusing one already running for its
# notebooks; it keeps running for the user afterwards (`sim jupyter stop`
# stops it).
set -euo pipefail

notebook="${1:?usage: notebook.sh NOTEBOOK.ipynb}"
repo="${ZABOB_REPO_DIR:?source env.sh first}"
[ -f "$repo/notebooks/$notebook" ] || { echo "notebook.sh: no notebooks/$notebook" >&2; exit 2; }

cd "$repo" && exec sim jupyter start "$notebook"
