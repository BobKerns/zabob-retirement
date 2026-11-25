---
name: promote
description: Open or refresh the pull request that promotes dev to main, check its body against dev's merges, and watch it until it is clean to merge. Run only when the user asks to promote.
disable-model-invocation: true
---

# Promote dev to main

The user decides when dev is promoted; this skill runs only when they ask
(`/promote`). It never merges: the user merges the promotion.

## 1. Look before opening

```sh
git fetch origin
git log --first-parent --oneline origin/main..origin/dev
.venv/bin/python scripts/promote_dev.py --dry-run
```

- If dev has no pull requests main lacks, say so and stop.
- Check the body against the merges listed above:
  - Every merged pull request appears, and a reverted one is listed apart.
  - Each issue a pull request was meant to close has a "Fixes #N" line. A
    pull request into dev whose body has no closing line closes nothing,
    and nothing will close its issue later; list those issues for the user
    and ask whether the promotion should close them, rather than adding
    lines on your own.
  - A reverted pull request's commits that name an issue with a closing
    keyword are listed to reopen.
- If an open pull request into dev is meant to go out with this promotion,
  say so: promoting first leaves it for the next one.

## 2. Open or refresh it

```sh
.venv/bin/python scripts/promote_dev.py
```

It prints the pull request's URL: a new draft, or the open promotion with
its body refreshed (keeping any "Fixes" line added by hand). It uses only
GitHub's REST API, so it works from a cloud session too.

## 3. Watch it

Subscribe to the pull request's activity, if your environment can, and tell
the user it is open as a draft for them to mark ready. Marking it ready
runs the full Gates and Copilot's review, once.

- **A Copilot finding:** verify it. Fix a real one in a pull request into
  dev (`issue/<number>-<desc>` from `origin/dev`), reply on its thread
  naming that pull request, and resolve the thread once the fix is merged
  into dev. Answer a wrong one on its thread with what you traced.
- **A Gates failure:** find the cause. `scripts/bisect_dev.py TEST...`
  names the dev merge that broke a test. Fix forward in a pull request into
  dev, or revert that merge.
- After any fix merges into dev, rerun `scripts/promote_dev.py` to refresh
  the body.

Tell the user when the promotion is clean to merge: Gates green on dev's
current head, every finding fixed on dev or answered, nothing open into dev
that was meant to go with it. Remind them to merge with a merge commit,
never a squash.
