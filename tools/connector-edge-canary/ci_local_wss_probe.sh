#!/usr/bin/env bash
# Separate, local-only Python Workerd server fixture with the *same* external SDK.
# The real worker.py remains fail-closed on absent Cloudflare edge TLS.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
CONFIG=".local-workerd-wss-ci.toml"
LOG="$(mktemp)"
WORKER_PID=""
cleanup() {
  if [[ -n "$WORKER_PID" ]]; then
    kill "$WORKER_PID" 2>/dev/null || true
    wait "$WORKER_PID" 2>/dev/null || true
  fi
  rm -f -- "$CONFIG" "$LOG"
}
trap cleanup EXIT
cat > "$CONFIG" <<'EOF'
name = "padiem-connector-local-asgi-transport-only"
main = "worker_transport_fixture.py"
compatibility_date = "2026-10-13"
compatibility_flags = ["python_workers"]
workers_dev = false
preview_urls = false
EOF
# No account binding, token, public deployment, or privileged service.
uv run pywrangler dev --config "$CONFIG" --port 8800 --inspector-port 9240 >"$LOG" 2>&1 &
WORKER_PID="$!"
READY=0
for _ in $(seq 1 75); do
  if ! kill -0 "$WORKER_PID" 2>/dev/null; then
    echo "CONNECTOR_CANARY_LOCAL_ASGI_WSS_EARLY_EXIT=FAIL" >&2
    tail -n 35 "$LOG" >&2
    exit 1
  fi
  status="$(curl --silent --max-time 2 --output /dev/null --write-out '%{http_code}'     http://127.0.0.1:8800/__padiem_canary/wss || true)"
  if [[ "$status" == "426" ]]; then READY=1; break; fi
  sleep 1
done
if [[ "$READY" != 1 ]]; then
  echo "CONNECTOR_CANARY_LOCAL_ASGI_WSS_READY=FAIL" >&2
  tail -n 35 "$LOG" >&2
  exit 1
fi
echo "CONNECTOR_CANARY_LOCAL_ASGI_HTTP_426=PASS"
node local_workerd_wss_client.mjs
echo "CONNECTOR_CANARY_LOCAL_ASGI_101_ROUNDTRIP=PASS"
echo "REAL_CLOUDFLARE_EDGE_TLS_PROVEN=NO"
echo "REAL_DEVICE_AUTH_PROVEN=NO"
echo "CLOUDFLARE_ACCOUNT_MUTATION=0"
