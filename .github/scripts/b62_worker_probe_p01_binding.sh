#!/usr/bin/env bash
set -euo pipefail
# #3989: Linux real-run phase attribution via epoch milliseconds.
# These markers are observability only; they never replace a readiness or assertion gate.
B62_PROBE_TIMING_LABEL=P01_BINDING
b62_probe_mark() {
  printf 'B62_WORKER_PHASE_%s_%s_MS=%s\n' "$B62_PROBE_TIMING_LABEL" "$1" "$(date +%s%3N)"
}
b62_probe_mark START
cat > .runtime-p01-binding-probe.toml <<'EOF'
name = "padiem-chat-runtime-p01-binding-probe"
main = "worker_runtime_p01_binding_probe.py"
compatibility_date = "2026-08-25"
compatibility_flags = ["python_workers"]
workers_dev = true
EOF

# Each concurrent workerd must have its own local SQLite/persistence state.
# Distinct HTTP and inspector ports do not isolate Wrangler's default .wrangler/state.
PERSIST_DIR="$(mktemp -d "${TMPDIR:-/tmp}/b62-worker-p01_binding-state.XXXXXXXX")"

setsid npx --yes wrangler@4.130.0 dev --config .runtime-p01-binding-probe.toml --port 8789 --inspector-port 9233 --persist-to "$PERSIST_DIR" > /tmp/b62-p01-binding-workerd.log 2>&1 &
WORKER_PID=$!
b62_probe_mark WORKER_LAUNCHED

cleanup() {
  # #3989: setsid isolates this Wrangler/npm/workerd tree from the CI shell.
  # The prior kill of only npx left workerd grandchildren alive until runner
  # teardown. Signal this probe-only process group, not the host runner group.
  kill -TERM -- "-$WORKER_PID" 2>/dev/null || true
  sleep 0.2
  kill -KILL -- "-$WORKER_PID" 2>/dev/null || true
  wait "$WORKER_PID" 2>/dev/null || true
  rm -rf -- "$PERSIST_DIR"
  rm -f .runtime-p01-binding-probe.toml
}
trap cleanup EXIT

READY=0
for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8789/ready >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done
if [ "$READY" -ne 1 ]; then
  cat /tmp/b62-p01-binding-workerd.log
  exit 1
fi

b62_probe_mark READY
b62_probe_mark REQUEST_START
HTTP_CODE="$(curl -sS -o /tmp/b62-p01-binding-result.json -w '%{http_code}' http://127.0.0.1:8789/probe)"
b62_probe_mark RESPONSE
cat /tmp/b62-p01-binding-result.json
if [ "$HTTP_CODE" != "200" ]; then
  cat /tmp/b62-p01-binding-workerd.log
  exit 1
fi

uv run --locked python - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("/tmp/b62-p01-binding-result.json").read_text())
required = (
    "adapter_composed",
    "worker_request_factory_real",
    "plus_route_entered",
    "binding_fetch_called_once",
    "bounded_error_after_fetch",
)
failed = [name for name in required if data.get(name) is not True]
if failed or data.get("unexpected_exception") is not False:
    raise SystemExit(
        f"Worker P01 binding composition probe failed: {failed}; "
        f"error_type={data.get('error_type', 'NONE')}"
    )
print("WORKER_P01_BINDING_COMPOSITION_PASS")
PY
b62_probe_mark ASSERT_PASS
