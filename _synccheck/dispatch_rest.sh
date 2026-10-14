#!/usr/bin/env bash
set -uo pipefail
REPO=skerishKang/ai-revenue-lab
WF=b54-claw-502-retained-telemetry-readonly.yml
OUT=/e/claw-1012-1/_synccheck/rest.log
: > "$OUT"
log() { printf '%s\n' "$*" | tee -a "$OUT"; }

for pair in "9 1791836944000 1791837244000" "10 1791837244000 1791837544000" "11 1791837544000 1791837624000"; do
  set -- $pair; label="$1"; from="$2"; to="$3"
  for attempt in 1 2 3; do
    git fetch origin main --quiet
    sha="$(git rev-parse origin/main)"
    if ! gh api -X POST "repos/$REPO/actions/workflows/$WF/dispatches" \
         -f ref=main -f "inputs[from_ms]=$from" -f "inputs[to_ms]=$to" >/dev/null 2>&1; then
      log "SLICE_${label}_DISPATCH_FAIL attempt=$attempt"; sleep 10; continue
    fi
    sleep 10
    rid="$(gh api "repos/$REPO/actions/workflows/$WF/runs?per_page=10&event=workflow_dispatch" \
      --jq "[.workflow_runs[] | select(.head_sha==\"$sha\")] | .[0].id // empty" 2>/dev/null)"
    if [ -z "$rid" ]; then log "SLICE_${label}_RUN_NOT_FOUND attempt=$attempt sha=$sha"; sleep 10; continue; fi
    st=""
    for _ in $(seq 1 40); do
      st="$(gh run view "$rid" --repo "$REPO" --json status,conclusion --jq '.status+"/"+(.conclusion//"-")' 2>/dev/null)"
      case "$st" in completed/*) break;; esac
      sleep 15
    done
    log "SLICE_${label} run=$rid sha=$sha from=$from to=$to state=$st"
    if [[ "$st" == completed/failure ]]; then continue; fi
    if [[ "$st" == completed/cancelled ]]; then log "SLICE_${label}_CANCELLED_RETRY"; continue; fi
    lg="$(gh run view "$rid" --repo "$REPO" --log 2>/dev/null)"
    log "SLICE_${label}_KEYS_BEGIN"
    printf '%s\n' "$lg" | grep -oE '(B62|ENGINE|B14)_(ANALYTICS_(REQUESTS|ERRORS|SUBREQUESTS)|ACTIVE_SECOND_COUNT|WORKER_OUTCOMES)=[A-Za-z0-9_,-]*' | sort -u >> "$OUT"
    log "SLICE_${label}_KEYS_END"
    break
  done
done
log "REST_DONE"
