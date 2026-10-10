#!/usr/bin/env bash
set -euo pipefail
# #3989: Linux real-run phase attribution via epoch milliseconds.
# These markers are observability only; they never replace a readiness or assertion gate.
B62_PROBE_TIMING_LABEL=R2_READ
b62_probe_mark() {
  printf 'B62_WORKER_PHASE_%s_%s_MS=%s\n' "$B62_PROBE_TIMING_LABEL" "$1" "$(date +%s%3N)"
}
b62_probe_mark START
cat > .runtime-r2-read-probe.toml <<'EOF'
name = "padiem-chat-runtime-r2-read-probe"
main = "worker_runtime_r2_read_probe.py"
compatibility_date = "2026-08-25"
compatibility_flags = ["python_workers"]
workers_dev = true
EOF

# Each concurrent workerd must have its own local SQLite/persistence state.
# Distinct HTTP and inspector ports do not isolate Wrangler's default .wrangler/state.
PERSIST_DIR="$(mktemp -d "${TMPDIR:-/tmp}/b62-worker-r2_read-state.XXXXXXXX")"

npx --yes wrangler@4.130.0 dev --config .runtime-r2-read-probe.toml --port 8790 --inspector-port 9234 --persist-to "$PERSIST_DIR" > /tmp/b62-r2-read-workerd.log 2>&1 &
WORKER_PID=$!
b62_probe_mark WORKER_LAUNCHED

cleanup() {
  kill "$WORKER_PID" 2>/dev/null || true
  rm -rf -- "$PERSIST_DIR"
  rm -f .runtime-r2-read-probe.toml
}
trap cleanup EXIT

READY=0
for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8790/ready >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done
if [ "$READY" -ne 1 ]; then
  cat /tmp/b62-r2-read-workerd.log
  exit 1
fi

b62_probe_mark READY
b62_probe_mark REQUEST_START
HTTP_CODE="$(curl -sS -o /tmp/b62-r2-read-result.json -w '%{http_code}' http://127.0.0.1:8790/probe)"
b62_probe_mark RESPONSE
cat /tmp/b62-r2-read-result.json
if [ "$HTTP_CODE" != "200" ]; then
  cat /tmp/b62-r2-read-workerd.log
  exit 1
fi

uv run --locked python - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("/tmp/b62-r2-read-result.json").read_text())
required = (
    "js_arraybuffer_to_bytes",
    "object_arraybuffer_called_once",
    "bucket_get_called_once",
    "stream_body_not_used",
    "payload_matches",
)
failed = [name for name in required if data.get(name) is not True]
if failed or data.get("unexpected_exception") is not False:
    raise SystemExit(
        f"Worker R2 ObjectBody read probe failed: {failed}; "
        f"error_type={data.get('error_type', 'NONE')}"
    )
print("WORKER_R2_OBJECTBODY_READ_PASS")
PY
b62_probe_mark ASSERT_PASS
