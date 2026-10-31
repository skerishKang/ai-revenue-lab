#!/bin/bash
# #5881 follow-on — one recorded health read of the PC queue, on the host that can reach it.
#
# The queue listens on 127.0.0.1 only, so no CI runner and no GitHub workflow can ask
# it anything. This is the side of the monitoring that has to live on 컴2: the numbers
# the cutover decision is made from, written to the journal on a schedule, so the
# answer to "was the PC lane alive at 03:40, and was anyone waiting for it" is a read
# rather than a reconstruction.
#
# It restarts nothing. A wedged process is the in-service watchdog's job (exit code 87,
# Restart=always brings a clean one) and a crashed one is systemd's; what this adds is a
# record, so that the hours before an incident are readable instead of inferred.
set -uo pipefail

URL="${MESH_QUEUE_HEALTH_URL:-http://127.0.0.1:8797/health}"
MAX_TIME="${MESH_QUEUE_HEALTH_TIMEOUT_SECONDS:-10}"

BODY=$(curl -sS --max-time "$MAX_TIME" "$URL" 2>&1)
CURL=$?
if [ "$CURL" -ne 0 ]; then
  echo "MESH_QUEUE_HEALTH=UNREACHABLE curl=$CURL target=$URL"
  exit 0
fi

printf '%s' "$BODY" | python3 -c '
import json, sys
raw = sys.stdin.read()
try:
    row = json.loads(raw)
except Exception:
    print("MESH_QUEUE_HEALTH=UNPARSED bytes=%d" % len(raw))
    raise SystemExit(0)
if not isinstance(row, dict) or row.get("ok") is not True:
    print("MESH_QUEUE_HEALTH=UNEXPECTED shape=%s" % type(row).__name__)
else:
    print("MESH_QUEUE_HEALTH=OK pending_unclaimed=%s pending_claimed=%s received=%s" % (
        row.get("pending_unclaimed"), row.get("pending_claimed"), row.get("received")))
' 2>/dev/null || echo "MESH_QUEUE_HEALTH=UNPARSED"
