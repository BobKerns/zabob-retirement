# The shared clean Ubuntu (docker/base) for exercising scripts/setup.sh from
# scratch.
#
# Start it with scripts/start-container.sh, which builds the image and runs
# it with a named volume at /work holding the clones (see entrypoint.sh) and
# the host's ~/.ssh mounted read-only for the clones' ssh URLs. Inside, run
# ./scripts/setup.sh (or start with --setup) and give it /work/finance-data
# as the data repo if DATA_REPO_URL cloned one, or a blank answer for
# template data; `start-container.sh --fresh` starts the next run from
# scratch.

ARG BASE=analysis-test-base
FROM ${BASE}

COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["bash", "-l"]
