# What the test containers share (#674): a clean Ubuntu, as close to a fresh
# WSL Ubuntu as a container gets: the image's stock ubuntu user (uid 1000,
# with Ubuntu's default dotfiles and sudo), and of the packages a fresh
# install has, the ones installing relies on: git, curl, ssh and the
# distribution's Python. A C toolchain, uv, Node.js and a newer Python are
# left out on purpose: installing those is the job of what's being tested,
# scripts/setup.sh (docker/setup-test) or SETUP.md's "Install the program"
# (docker/install-test).
#
# Unlike WSL, sudo asks for no password, so either can run unattended.
#
# scripts/start-container.sh builds it, as analysis-test-base, before the
# image it starts.

FROM ubuntu:24.04

# UV_LINK_MODE=copy: the uv cache and /work are on different filesystems,
# so uv can't hard-link from one to the other (and warns each time it tries).
ENV LANG=C.UTF-8 \
    UV_LINK_MODE=copy

# /work is created here, owned by ubuntu, so a new volume mounted on it is
# too.
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        openssh-client \
        python3 \
        sudo \
 && rm -rf /var/lib/apt/lists/* \
 && echo 'ubuntu ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/ubuntu \
 && chmod 440 /etc/sudoers.d/ubuntu \
 && mkdir /work \
 && chown ubuntu:ubuntu /work

USER ubuntu
WORKDIR /work
# A login shell, as WSL starts.
CMD ["bash", "-l"]
