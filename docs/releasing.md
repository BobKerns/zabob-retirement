![Releasing to PyPI](assets/brand/banners/releasing.svg)

# Releasing to PyPI

The program is published as `zabob-retirement`, by
[`.github/workflows/publish.yml`](../.github/workflows/publish.yml).

PyPI trusts the workflow itself (trusted publishing), in two GitHub
environments: `testpypi`, open to any branch, and `pypi`, open to `main`
and to `v*.*.*` tags. A release's run is on its tag, not on `main`, so the
tag rule is the one a real release passes. No token is stored.

## Branches and versions

Releases are made from `main`, trunk-based: a release is a tag on `main`.
Work reaches `main` only through promotions of `dev` and hotfix pull
requests (see [CONTRIBUTING.md](../CONTRIBUTING.md#branches)), after the
whole test suite has passed, so any commit on `main` can be released.

A `release/x.y` branch is made only when a release can't come from `main`:
a point release for an earlier version, once `main` has moved on, or a fix
whose cherry-pick onto the old code would conflict and so needs testing
there on its own. Branch it from the release's tag
(`git switch -c release/1.2 v1.2.0`), make the fix in a pull request into
it, and tag the point release (`v1.2.1`) on it. The fix goes to `dev` too,
in its own pull request, unless `dev` no longer has the bug. `release/*`
branches have `main`'s ruleset, and Gates runs the whole suite on a pull
request into one.

The first upload to an index creates the project, through a pending
publisher (one that creates its project on first upload): register it for
`zabob-retirement`, with `publish.yml` and environment `testpypi` or
`pypi`, then run the workflow. Register no other pending publisher with the
same workflow and environment: the index uses one of them when the
workflow's token is minted, and won't take another with the same identity
afterwards. (The empty `zabob-retire` project on PyPI, from an earlier
plan, holds that name with no publisher and no files; #775.)

## A release

1. Set the new version in `pyproject.toml`. Run `uv lock` (only the
   version line of `zabob-retirement` changes). Merge that into `dev` and promote `dev` to
   `main` (`/promote`, or `scripts/promote_dev.py`; see
   [Promoting dev](../CONTRIBUTING.md#promoting-dev)), or, for a point
   release, merge it into the `release/x.y` branch.
2. Try it on TestPyPI: run **Publish** from the Actions tab on `main`, or
   push a pre-release tag, `git tag v1.0.0b1 && git push origin v1.0.0b1`.
3. Test the install in a clean Ubuntu container, as a new user would make
   it (it needs Docker):

   ```sh
   scripts/start-container.sh --install --test --version 1.0.0b1 --run-tests
   ```

   It installs uv, then `zabob-retirement` from TestPyPI (its dependencies
   from PyPI), and runs `tests/install`: `sim init --example`, activation,
   `sim check --all`, a run and its report, the notebooks and Jupyter. You
   are left in a shell in the container to look further. Before uploading,
   `--local` in place of `--test` does the same with wheels built from your
   checkout. After step 4, run it without `--test` to check the real PyPI
   install.

4. Publish a GitHub release for the tag (`v` and the version). That
   publishes to PyPI.

A version can be uploaded to each index only once, ever, even if it is
deleted afterwards: a mistake means a new version. The build job checks
that the tag is `v` and the version, that the two packages agree, and that
the wheel installs and runs `sim init --example` and `sim check --all` with
no checkout, before anything is uploaded.

To chase a problem someone sees only on a fresh machine,
`--run-tests=all` runs the whole test suite against the install, less the
few tests that need a code checkout (marked `checkout`).

An installed program records its version and the commit it was built from
in each run (`1.0.0b1+g0123456789ab`), so its runs stay traceable to the
code without a checkout.
