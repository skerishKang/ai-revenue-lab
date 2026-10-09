#!/usr/bin/env bash
set -euo pipefail
cat > .runtime-timeout-probe.toml <<'EOF'
name = "padiem-chat-runtime-timeout-probe"
main = "worker_runtime_timeout_probe.py"
compatibility_date = "2026-08-25"
compatibility_flags = ["python_workers"]
workers_dev = true
EOF

uv run --locked python tests/worker_runtime_probe_origin.py --port 9099 > /tmp/b62-timeout-origin.log 2>&1 &
ORIGIN_PID=$!
npx --yes wrangler@4.130.0 dev --config .runtime-timeout-probe.toml --port 8787 --inspector-port 9231 > /tmp/b62-timeout-workerd.log 2>&1 &
WORKER_PID=$!

cleanup() {
  kill "$WORKER_PID" "$ORIGIN_PID" 2>/dev/null || true
  rm -f .runtime-timeout-probe.toml
}
trap cleanup EXIT

READY=0
for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8787/ready >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done
if [ "$READY" -ne 1 ]; then
  cat /tmp/b62-timeout-workerd.log
  exit 1
fi

HTTP_CODE="$(curl -sS -o /tmp/b62-timeout-result.json -w '%{http_code}' http://127.0.0.1:8787/probe)"
cat /tmp/b62-timeout-result.json
if [ "$HTTP_CODE" != "200" ]; then
  cat /tmp/b62-timeout-workerd.log
  exit 1
fi

uv run --locked python - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("/tmp/b62-timeout-result.json").read_text())
required = (
    "abortsignal_import",
    "abortsignal_timeout_call",
    "fetch_accepts_signal",
    "local_normal_fetch",
    "local_post_form",
    "local_delay_timeout",
    "local_body_timeout",
)
failed = [name for name in required if data.get(name) is not True]
if failed:
    raise SystemExit(f"Worker timeout runtime probe failed: {failed}; data={data}")
print("WORKER_TIMEOUT_RUNTIME_PASS")
PY
