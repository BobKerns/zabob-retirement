![Releasing to PyPI](assets/brand/banners/releasing.svg)

# Releasing to PyPI

Two packages are published together, by
[`.github/workflows/publish.yml`](../.github/workflows/publish.yml):
`zabob-retirement`, the program, and `zabob-retire`
([`packages/zabob-retire/`](../packages/zabob-retire/)), a shorter name with
no code that installs it. Both always carry the same version, and
`zabob-retire` pins `zabob-retirement` to it; `tests/test_release.py` and the
workflow check that.

PyPI trusts the workflow itself (trusted publishing), in two GitHub
environments: `testpypi` and `pypi`. No token is stored.

## A release

1. Set the new version in `pyproject.toml`, and in
   `packages/zabob-retire/pyproject.toml` both its `version` and its
   `dependencies` pin. Run `uv lock` (only the version line of
   `zabob-retirement` changes). Merge that to `main`.
2. Try it on TestPyPI: run **Publish** from the Actions tab on `main`, or
   push a pre-release tag, `git tag v1.0.0b1 && git push origin v1.0.0b1`.
3. Test the install, in a clean environment:

   ```sh
   uv tool install --index-url https://test.pypi.org/simple/ \
       --extra-index-url https://pypi.org/simple/ --index-strategy unsafe-best-match \
       zabob-retirement==1.0.0b1
   sim init --example /tmp/try && sim check --all --data-dir /tmp/try/sim
   ```

4. Publish a GitHub release for the tag (`v` and the version). That
   publishes to PyPI.

A version can be uploaded to each index only once, ever, even if it is
deleted afterwards: a mistake means a new version. The build job checks
that the tag is `v` and the version, that the two packages agree, and that
the wheel installs and runs `sim init --example` and `sim check --all` with
no checkout, before anything is uploaded.

An installed program records its version and the commit it was built from
in each run (`1.0.0b1+g0123456789ab`), so its runs stay traceable to the
code without a checkout.
