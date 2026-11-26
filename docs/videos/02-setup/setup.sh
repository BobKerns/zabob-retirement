# Prepares what video 2 shows, before any scene records (docs/videos/README.md,
# "Setting up the demo"). It runs inside a fresh, committed copy of the
# prototype data, with the installed `sim` on PATH, which this video doesn't
# use: it starts from nothing, as a new user does. So this makes the data
# repo the init scene makes, in the home folder beside the prototype copy
# (where the builder installed the program), for the scenes after `sim init`
# to start from. The init scene removes it first and makes it again on
# camera.

export HOME="$(dirname "$ZABOB_DATA_DIR")/home"
mkdir -p "$HOME"
unset ZABOB_DATA_DIR
# The same answers the init scene types. ZABOB_NO_BUILDER (set for every
# recording) keeps it from turning on builds.
sim init --id alice --display "Alice Example" --birthdate 1962-04-15 \
    --sex f --filing-status MFJ
