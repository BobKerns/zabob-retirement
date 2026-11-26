#!/usr/bin/env bash
# The result of a check in a workflow's push run on dev, for the promotion
# pull request (head dev) to reuse instead of rerunning on the same commit
# (#759). Prints one word:
#
#   passed  the push run for SHA finished and JOB succeeded (or was skipped)
#   failed  it finished and JOB failed
#   none    there is no push run for SHA, or it was cancelled before JOB
#           finished: the caller runs the check itself
#
# A push run still going is waited for. Needs gh with a token that can read
# actions (GITHUB_TOKEN with `actions: read`), and REPO set to owner/name.
#
# Usage: push-run-result.sh WORKFLOW_FILE JOB_NAME SHA
set -euo pipefail

workflow=$1 job=$2 sha=$3
: "${REPO:?REPO must be owner/name}"

# The push run is created at the push, a moment before the pull request's
# synchronize run, but give it a minute to show up.
run=''
for _ in $(seq 12); do
    run=$(gh api "repos/$REPO/actions/workflows/$workflow/runs?event=push&branch=dev&head_sha=$sha&per_page=1" \
        --jq '.workflow_runs[0].id // empty')
    [ -n "$run" ] && break
    sleep 5
done
if [ -z "$run" ]; then
    echo "No push run of $workflow for $sha." >&2
    echo none
    exit 0
fi
echo "Push run: https://github.com/$REPO/actions/runs/$run" >&2

while :; do
    status=$(gh api "repos/$REPO/actions/runs/$run" --jq .status)
    [ "$status" = completed ] && break
    echo "Waiting for it to finish ($status)." >&2
    sleep 20
done

# The job's own conclusion, not the run's: another job failing in the push
# run (spelling, say) is that job's check to report.
conclusion=$(gh api "repos/$REPO/actions/runs/$run/jobs?per_page=100" \
    --jq "[.jobs[] | select(.name == \"$job\")][0].conclusion // empty")
echo "$job: ${conclusion:-not found}" >&2
case "$conclusion" in
    success|skipped) echo passed ;;
    failure|timed_out) echo failed ;;
    *) echo none ;;
esac
