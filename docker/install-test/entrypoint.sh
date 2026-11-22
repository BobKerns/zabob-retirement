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
#      chase a problem seen only on a fresh machine. Only the dev group's
#      tools are added to the install, leaving what it has as it is.
#
# A failure is reported but still leaves you in the container to look
# around, and becomes the container's exit status. (The steps return on
# failure themselves: errexit doesn't reach into an `if`.)
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
    # Only the dev group's own packages, at versions that keep every package
    # the install already has as it is: the tests must see what a fresh
    # machine got, not uv.lock's versions. A clash fails here, loudly.
    uv pip freeze --python "$python" > /tmp/installed.txt || return
    python3 -c '
import sys, tomllib
with open("/repo/pyproject.toml", "rb") as f:
    print("\n".join(tomllib.load(f)["dependency-groups"]["dev"]))' > /tmp/test-tools.txt || return
    uv pip install --quiet --python "$python" -r /tmp/test-tools.txt -c /tmp/installed.txt || return
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

# The command's status, or a failure before it: so a script or CI using the
# container (`start-container.sh --install --run-tests true`) sees one.
failed=0
if install; then
    if [ -n "${RUN_TESTS:-}" ]; then
        run_tests || { failed=$?; echo "The tests failed (exit $failed)." >&2; }
    fi
else
    failed=$?
    echo "The install failed (exit $failed)." >&2
fi
"$@" && exit "$failed"
