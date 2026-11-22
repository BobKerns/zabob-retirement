#!/bin/sh
# Install Zabob Retirement as SETUP.md's "Install the program" says, then run
# the command it was given (bash by default) (#674).
#
#   1. uv, from astral's install script, as uv's own instructions say.
#   2. `uv tool install zabob-retirement` (Python 3.14 comes with it), from
#      INSTALL_FROM:
#        pypi      PyPI (the default)
#        testpypi  TestPyPI: only this package comes from there, by its
#                  wheel's URL; its dependencies still come from PyPI, so a
#                  look-alike upload to TestPyPI can't stand in for one
#        wheels    the wheels mounted at /wheels (start-container.sh
#                  --local builds them from the checkout)
#      at INSTALL_VERSION if set, else the newest release there.
#   3. With RUN_TESTS, the test suite from the checkout mounted read-only at
#      /repo, against the install: RUN_TESTS=default runs tests/install,
#      the checks of a new user's first session; RUN_TESTS=all runs every
#      test, less the few that need a checkout (marked `checkout`), to
#      chase a problem seen only on a fresh machine. Only the test tools are
#      added to the install, at the versions uv.lock names.
#
# A failure is reported but still leaves you in the container to look around
# (so the steps return on failure themselves: errexit doesn't reach into an
# `if`).
set -eu

export PATH="$HOME/.local/bin:$PATH"

step() { printf '\n== %s\n' "$*"; }

install() {
    if ! command -v uv >/dev/null; then
        step "Installing uv"
        # Fetched first: piped straight into sh, a failed download would
        # run an empty script and look like success.
        curl -LsSf -o /tmp/uv-install.sh https://astral.sh/uv/install.sh || return
        sh /tmp/uv-install.sh || return
    fi
    package=zabob-retirement
    case ${INSTALL_FROM:-pypi} in
        pypi)
            step "Installing $package${INSTALL_VERSION:+ $INSTALL_VERSION} from PyPI"
            uv tool install "$package${INSTALL_VERSION:+==$INSTALL_VERSION}" || return ;;
        testpypi)
            url=$(python3 - "$package" "${INSTALL_VERSION:-}" <<'EOF'
import json, sys, urllib.request
package, version = sys.argv[1:]
base = f"https://test.pypi.org/pypi/{package}"
with urllib.request.urlopen(f"{base}/{version}/json" if version else f"{base}/json") as r:
    info = json.load(r)
if not version:  # the newest upload, pre-releases included
    uploads = [(f["upload_time_iso_8601"], v) for v, files in info["releases"].items() for f in files]
    with urllib.request.urlopen(f"{base}/{max(uploads)[1]}/json") as r:
        info = json.load(r)
print(next(f["url"] for f in info["urls"] if f["packagetype"] == "bdist_wheel"))
EOF
            ) || return
            step "Installing $package from TestPyPI: ${url##*/}"
            uv tool install "$package @ $url" || return ;;
        wheels)
            wheel=$(ls /wheels/zabob_retirement-*.whl) || return
            step "Installing $package from ${wheel##*/}"
            uv tool install "$wheel" || return ;;
        *)
            echo "entrypoint: INSTALL_FROM is pypi, testpypi or wheels, not $INSTALL_FROM" >&2
            return 2 ;;
    esac
    sim --help >/dev/null || return
    echo "Installed: $(uv tool list | head -1)"
}

run_tests() {
    python=$(uv tool dir)/zabob-retirement/bin/python
    step "Adding the test tools"
    (cd /repo && uv export --frozen --only-group dev --no-emit-project --no-hashes --quiet) \
        > /tmp/test-requirements.txt || return
    uv pip install --quiet --python "$python" -r /tmp/test-requirements.txt || return
    case $RUN_TESTS in
        default) set -- tests/install ;;
        all) set -- ;;
        *) echo "entrypoint: RUN_TESTS is default or all, not $RUN_TESTS" >&2; return 2 ;;
    esac
    step "Running the tests ($RUN_TESTS)"
    # Some tests read the checkout's git history; its owner isn't ubuntu.
    git config --global --add safe.directory /repo
    # /repo is read-only: no bytecode or pytest cache there, and the
    # installed package, not /repo/src, is the one imported.
    (cd /repo && PYTHONDONTWRITEBYTECODE=1 "$python" -m pytest -q -n auto -p no:cacheprovider \
        -o pythonpath= "$@")
}

if install; then
    if [ -n "${RUN_TESTS:-}" ]; then
        run_tests || echo "The tests failed (exit $?)." >&2
    fi
else
    echo "The install failed (exit $?)." >&2
fi
exec "$@"
