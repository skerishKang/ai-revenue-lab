#!/usr/bin/env bash
set -uo pipefail
REPO=skerishKang/ai-revenue-lab
OUT=/e/claw-1012-1/_synccheck/collect.log
: > "$OUT"

for rid in 38310136097 38311277012 38311318043 38311353534 38311388946 38311426024 38311462875 38311500162 38311539121 \
           38310893256 38310928640 38310966215 38311003502 38311046616 38311089270 38311127435 38311164417 38311202884 38311239208; do
  conc="$(gh run view "$rid" --repo "$REPO" --json conclusion --jq '.conclusion // "-"' 2>/dev/null)"
  log="$(gh run view "$rid" --repo "$REPO" --log 2>/dev/null)"
  from="$(printf '%s\n' "$log" | grep -m1 -oE 'CANARY_FROM_MS: [0-9]+' | grep -oE '[0-9]+')"
  to="$(printf '%s\n' "$log" | grep -m1 -oE 'CANARY_TO_MS: [0-9]+' | grep -oE '[0-9]+')"
  obs="$(printf '%s\n' "$log" | grep -m1 -oE 'OBSERVABILITY_QUERY_HTTP=[0-9]+' | cut -d= -f2)"
  echo "=== RUN $rid conclusion=$conc from=${from:-NA} to=${to:-NA} obs_http=${obs:-NA}" >> "$OUT"
  printf '%s\n' "$log" \
    | grep -oE '(B62|ENGINE|B14|CP_ADMISSION|CP_IDENTITY)_(ANALYTICS_(REQUESTS|ERRORS|SUBREQUESTS)|ACTIVE_SECOND_COUNT|WORKER_OUTCOMES)=[A-Za-z0-9_,-]*' \
    | sort -u >> "$OUT"
done
echo "COLLECT_DONE" >> "$OUT"
