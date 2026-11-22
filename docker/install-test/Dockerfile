# The shared clean Ubuntu (docker/base) for installing the program as a user
# would, from PyPI, TestPyPI or wheels built from the checkout (#674), with
# no code checkout and nothing kept from one run to the next.
#
# Start it with `scripts/start-container.sh --install`; entrypoint.sh says
# what it does.

ARG BASE=analysis-test-base
FROM ${BASE}

COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh
WORKDIR /home/ubuntu
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["bash", "-l"]
