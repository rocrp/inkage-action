#!/usr/bin/env bash
# Chain step: sleep until the Site's earliest next_due, then dispatch the next Run of the calling workflow.
# GitHub drops and delays `schedule` events for hours; a workflow_dispatch issued by GITHUB_TOKEN is not
# dropped, so each Run hands over to the next. The cron only resurrects the chain after a broken link.
set -euo pipefail
: "${GITHUB_TOKEN:?}" "${GITHUB_REPOSITORY:?}" "${GITHUB_WORKFLOW_REF:?}" "${GITHUB_REF_NAME:?}"
next_due="${1:-}"        # RFC 3339 UTC or empty
lead="${LEAD_SECONDS:-60}"   # wake early: checkout + setup take about this long
max="${MAX_SLEEP_SECONDS:-21000}"  # 5 h 50 min: a job may run 6 h

now=$(date -u +%s)
if [[ -n "$next_due" ]]; then
  due=$(date -u -d "$next_due" +%s)
  wait=$(( due - lead - now ))
else
  wait=$max
fi
(( wait < 0 )) && wait=0
(( wait > max )) && wait=$max
echo "next_due=${next_due:-none}; sleeping ${wait}s before dispatching the next Run"
sleep "$wait"

wf="${GITHUB_WORKFLOW_REF#*/.github/workflows/}"
gh workflow run "${wf%@*}" -R "$GITHUB_REPOSITORY" --ref "$GITHUB_REF_NAME"
