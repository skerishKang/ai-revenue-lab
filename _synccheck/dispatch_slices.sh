#!/usr/bin/env bash
set -uo pipefail
REPO=skerishKang/ai-revenue-lab
WF=b54-claw-502-retained-telemetry-readonly.yml
OUT=/e/claw-1012-1/_synccheck/slices.log
: > "$OUT"

log() { printf '%s\n' "$*" | tee -a "$OUT"; }

run_keys() {
  local rid="$1"
  gh run view "$rid" --repo "$REPO" --log 2>/dev/null \
    | grep -oE '(B62|ENGINE|B14|CP_ADMISSION|CP_IDENTITY)_(ANALYTICS_(REQUESTS|ERRORS|SUBREQUESTS)|ACTIVE_SECOND_COUNT|WORKER_OUTCOMES|ACTIVE_SECONDS)=[A-Za-z0-9_,-]*' \
    | tail -40
}

# slice: label from_ms to_ms
slices=(
"2 1791834844000 1791835144000"
"3 1791835144000 1791835444000"
"4 1791835444000 1791835744000"
"5 1791835744000 1791836044000"
"6 1791836044000 1791836344000"
"7 1791836344000 1791836644000"
"8 1791836644000 1791836944000"
"9 1791836944000 1791837244000"
"10 1791837244000 1791837544000"
"11 1791837544000 1791837624000"
)

for entry in "${slices[@]}"; do
  set -- $entry
  label="$1"; from="$2"; to="$3"
  ok=0
  for attempt in 1 2 3; do
    git fetch origin main --quiet
    sha="$(git rev-parse origin/main)"
    gh api -X POST "repos/$REPO/actions/workflows/$WF/dispatches" \
      -f ref=main -f "inputs[from_ms]=$from" -f "inputs[to_ms]=$to" >/dev/null 2>&1
    if [ $? -ne 0 ]; then log "SLICE_${label}_DISPATCH_FAIL attempt=$attempt sha=$sha"; sleep 10; continue; fi
    sleep 8
    rid="$(gh api "repos/$REPO/actions/workflows/$WF/runs?per_page=10&event=workflow_dispatch" \
      --jq "[.workflow_runs[] | select(.head_sha==\"$sha\")] | .[0].databaseId // empty" 2>/dev/null)"
    if [ -z "$rid" ]; then log "SLICE_${label}_RUN_NOT_FOUND attempt=$attempt sha=$sha"; sleep 10; continue; fi
    st=""
    for _ in $(seq 1 40); do
      st="$(gh run view "$rid" --repo "$REPO" --json status,conclusion --jq '.status+"/"+(.conclusion//"-")' 2>/dev/null)"
      case "$st" in completed/*) break;; esac
      sleep 15
    done
    log "SLICE_${label} run=$rid sha=$sha from=$from to=$to state=$st"
    if [[ "$st" == completed/failure ]]; then
      log "SLICE_${label}_RETRY_ON_FAILURE"
      continue
    fi
    ok=1
    break
  done
  if [ "$ok" -ne 1 ]; then log "SLICE_${label}_UNRESOLVED"; continue; fi
  log "SLICE_${label}_KEYS_BEGIN"
  run_keys "$rid" >> "$OUT"
  log "SLICE_${label}_KEYS_END"
done
log "ALL_SLICES_DONE"
