#!/usr/bin/env bash
set -euo pipefail
# #3989: Linux monotonic phase attribution using UTC epoch milliseconds.
# These markers are observability only; they never replace a readiness or assertion gate.
B62_PROBE_TIMING_LABEL=WEB_TRANSPORT
b62_probe_mark() {
  printf 'B62_WORKER_PHASE_%s_%s_MS=%s\n' "$B62_PROBE_TIMING_LABEL" "$1" "$(date +%s%3N)"
}
b62_probe_mark START
cat > .runtime-web-transport-probe.toml <<'EOF'
name = "padiem-chat-runtime-web-transport-probe"
main = "worker_runtime_web_transport_probe.py"
compatibility_date = "2026-08-25"
compatibility_flags = ["python_workers"]
workers_dev = true
EOF

# Each concurrent workerd must have its own local SQLite/persistence state.
# Distinct HTTP and inspector ports do not isolate Wrangler's default .wrangler/state.
PERSIST_DIR="$(mktemp -d "${TMPDIR:-/tmp}/b62-worker-web_transport-state.XXXXXXXX")"

uv run --locked python tests/worker_runtime_probe_origin.py --port 9100 > /tmp/b62-web-origin.log 2>&1 &
ORIGIN_PID=$!
npx --yes wrangler@4.130.0 dev --config .runtime-web-transport-probe.toml --port 8788 --inspector-port 9232 --persist-to "$PERSIST_DIR" > /tmp/b62-web-workerd.log 2>&1 &
WORKER_PID=$!
b62_probe_mark WORKER_LAUNCHED

cleanup() {
  kill "$WORKER_PID" "$ORIGIN_PID" 2>/dev/null || true
  rm -rf -- "$PERSIST_DIR"
  rm -f .runtime-web-transport-probe.toml
}
trap cleanup EXIT

READY=0
for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8788/ready >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done
if [ "$READY" -ne 1 ]; then
  cat /tmp/b62-web-workerd.log
  exit 1
fi

b62_probe_mark READY
b62_probe_mark REQUEST_START
HTTP_CODE="$(curl -sS -o /tmp/b62-web-result.json -w '%{http_code}' http://127.0.0.1:8788/probe)"
b62_probe_mark RESPONSE
cat /tmp/b62-web-result.json
if [ "$HTTP_CODE" != "200" ]; then
  cat /tmp/b62-web-workerd.log
  exit 1
fi

uv run --locked python - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("/tmp/b62-web-result.json").read_text())
required = (
    "real_httpx_transport_class",
    "js_fetch_import",
    "abortsignal_import",
    "fetch_accepts_signal",
    "local_normal_fetch",
    "local_post_body_headers",
    "local_incremental_body",
    "local_delay_timeout",
    "local_body_timeout",
    "early_close_release",
)
failed = [name for name in required if data.get(name) is not True]
if failed:
    raise SystemExit(f"Worker web transport runtime probe failed: {failed}; data={data}")
print("WORKER_WEB_TRANSPORT_PASS")
PY
b62_probe_mark ASSERT_PASS
