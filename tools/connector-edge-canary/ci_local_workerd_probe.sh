#!/usr/bin/env bash
# #4139: Actual isolated local Workerd boot with official external Python SDK.
# No live Cloudflare account / deploy / private bindings / customer credentials.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
LOG="$(mktemp)"
RESP="$(mktemp)"
WORKER_PID=""
cleanup() {
  if [[ -n "$WORKER_PID" ]]; then
    kill "$WORKER_PID" 2>/dev/null || true
    wait "$WORKER_PID" 2>/dev/null || true
  fi
  rm -f -- "$LOG" "$RESP"
}
trap cleanup EXIT

# Local mode only. The separate CANARY wrangler.toml has no account,
# environment, secrets, routes or product service bindings.
uv run pywrangler dev --port 8799 --inspector-port 9239 >"$LOG" 2>&1 &
WORKER_PID="$!"

READY=0
for attempt in $(seq 1 90); do
  if ! kill -0 "$WORKER_PID" 2>/dev/null; then
    echo "CONNECTOR_CANARY_REAL_WORKER_EARLY_EXIT=FAIL" >&2
    tail -n 35 "$LOG" >&2
    exit 1
  fi
  if status="$(curl --silent --max-time 3 --output "$RESP" --write-out '%{http_code}'       http://127.0.0.1:8799/__padiem_canary/tls)" ; then
    # Local workerd may synthesize cf metadata. It is never edge attestation.
    value="$(cat "$RESP")"
    if { [[ "$status" == "503" ]] &&
         [[ "$value" == "CF_UNAVAILABLE" || "$value" == "TLS_VERSION_UNAVAILABLE" || "$value" == "TLS_METADATA_ERROR" || "$value" == "TLS_UNACCEPTED" ]]; } ||
       { [[ "$status" == "200" && "$value" == "TLS_OK" ]]; }; then
      READY=1
      break
    fi
    echo "CONNECTOR_CANARY_REAL_WORKER_UNEXPECTED_RESPONSE=FAIL status=$status" >&2
    exit 1
  fi
  sleep 1
done
if [[ "$READY" -ne 1 ]]; then
  echo "CONNECTOR_CANARY_REAL_WORKER_READY=FAIL" >&2
  tail -n 35 "$LOG" >&2
  exit 1
fi
echo "CONNECTOR_CANARY_REAL_WORKER_IMPORT=PASS"
echo "CONNECTOR_CANARY_LOCAL_CF_IS_EDGE_PROOF=NO"

# No owner, enrollment, secret or privileged RPC ever included.
code="$(curl --silent --max-time 3 --output "$RESP" --write-out '%{http_code}'     http://127.0.0.1:8799/__padiem_canary/wss)"
if [[ "$code" != "403" && "$code" != "426" ]]; then
  echo "CONNECTOR_CANARY_NONUPGRADE_HTTP=FAIL code=$code" >&2
  exit 1
fi
echo "CONNECTOR_CANARY_NONUPGRADE_HTTP=PASS"
echo "CLOUDFLARE_ACCOUNT_MUTATION=0"
