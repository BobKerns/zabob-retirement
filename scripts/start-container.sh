#!/bin/sh
# Build a test container and start it: a clean Ubuntu (docker/base) for
# trying an install from scratch.
#
#   scripts/start-container.sh [--fresh] [--setup] [--run-tests[=all]] [command ...]
#   scripts/start-container.sh --install [--test | --local] [--version V]
#                              [--run-tests[=all]] [command ...]
#
# The setup test (docker/setup-test) runs scripts/setup.sh in a clone, with
# the code and data repos cloned into the analysis-test volume on first
# start. --fresh deletes the volume first, so the clones (and anything
# setup.sh left in them) start over. --setup runs scripts/setup.sh in the
# container's clone before the command, which defaults to an interactive
# bash. --run-tests (which implies --setup) first brings a kept clone up to
# date with its branch, then runs the clone's tests not marked slow;
# --run-tests=all runs all of them.
#
# The install test (docker/install-test, with --install) installs the
# program as SETUP.md says, with no checkout and nothing kept between runs:
# from PyPI, from TestPyPI with --test, or with --local from wheels built
# from this checkout (uncommitted changes included). --version picks the
# version. --run-tests then runs this checkout's tests/install against it, the
# checks of a new user's first session; --run-tests=all runs every test that
# doesn't need a checkout, to chase a problem seen only on a fresh machine.
# The checkout is mounted read-only at /repo for them.
#
# The setup test clones this checkout's origin at its current branch (which
# must be pushed); CODE_REPO_URL and CODE_REPO_REF override them. It clones
# a data repo only if DATA_REPO_URL is set, e.g. in your shell profile.
set -eu

cd "$(dirname "$0")/.."

base=analysis-test-base
volume=analysis-test

fresh=
setup=
install=
from=pypi
version=
tests=
while [ $# -gt 0 ]; do
    case $1 in
        --fresh) fresh=1 ;;
        --setup) setup=1 ;;
        --install) install=1 ;;
        --test) from=testpypi ;;
        --local) from=wheels ;;
        --version) shift; version=${1:?start-container: --version needs a version} ;;
        --version=*) version=${1#*=} ;;
        --run-tests) tests=default ;;
        --run-tests=all) tests=all ;;
        -h|--help) sed -n '2,29s/^# \{0,1\}//p' "$0"; exit 0 ;;
        --) shift; break ;;
        -*) echo "start-container: unknown option $1" >&2; exit 2 ;;
        *) break ;;
    esac
    shift
done

if [ -n "$install" ]; then
    if [ -n "$fresh$setup" ]; then
        echo "start-container: --fresh and --setup are for the setup test, not --install" >&2
        exit 2
    fi
elif [ "$from$version" != pypi ]; then
    echo "start-container: --test, --local and --version go with --install" >&2
    exit 2
fi

# docker run's arguments are put in front of the command, one at a time,
# so a path with a space in it stays one argument.
if [ -t 0 ] && [ -t 1 ]; then
    tty=-it
else
    tty=-i
fi

# Each image is built FROM the base, so a change to the base reaches both.
docker build -q -t "$base" docker/base >/dev/null

if [ -n "$install" ]; then
    image=analysis-install-test
    docker build -q -t "$image" docker/install-test >/dev/null
    set -- "$image" "$@"
    if [ -n "$tests" ]; then
        set -- -e "RUN_TESTS=$tests" -v "$(pwd):/repo:ro" "$@"
    fi
    if [ "$from" = wheels ]; then
        wheels=out/install-test/wheels
        rm -rf "$wheels"
        echo "Building wheels from this checkout..."
        uv build --quiet --out-dir "$wheels"
        set -- -v "$(pwd)/$wheels:/wheels:ro" "$@"
    fi
    if [ -n "$version" ]; then
        set -- -e "INSTALL_VERSION=$version" "$@"
    fi
    exec docker run --rm "$tty" -e "INSTALL_FROM=$from" "$@"
fi

image=analysis-setup-test
if [ -n "$fresh" ]; then
    echo "Removing volume $volume..."
    docker volume rm -f "$volume" >/dev/null
fi
docker build -q -t "$image" docker/setup-test >/dev/null

CODE_REPO_URL=${CODE_REPO_URL:-$(git remote get-url origin)}
CODE_REPO_REF=${CODE_REPO_REF:-$(git branch --show-current)}
export CODE_REPO_URL CODE_REPO_REF

set -- -v "$volume":/work -v "$HOME/.ssh":/home/ubuntu/.ssh-host:ro "$image" "$@"
for v in CODE_REPO_URL CODE_REPO_REF DATA_REPO_URL; do
    if eval "[ -n \"\${$v:-}\" ]"; then
        set -- -e "$v" "$@"
    fi
done
if [ -n "$setup$tests" ]; then
    set -- -e RUN_SETUP=1 "$@"
fi
if [ -n "$tests" ]; then
    set -- -e "RUN_TESTS=$tests" "$@"
fi
exec docker run --rm "$tty" "$@"
