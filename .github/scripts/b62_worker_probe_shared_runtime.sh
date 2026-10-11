#!/usr/bin/env bash
# #3989: four original Worker assertions, one real Pyodide/Workerd startup.
set -euo pipefail
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if (( $# != 0 )); then echo 'B62_SHARED_WORKER_INVALID_ARGUMENTS' >&2; exit 2; fi
cat > .runtime-shared-probe.toml <<'EOF'
name = "padiem-chat-runtime-shared-probe"
main = "worker_runtime_combined_probe.py"
compatibility_date = "2026-08-25"
compatibility_flags = ["python_workers"]
workers_dev = true
EOF
PERSIST_DIR="$(mktemp -d "${TMPDIR:-/tmp}/b62-worker-shared-state.XXXXXXXX")"
LOGDIR="$(mktemp -d "${TMPDIR:-/tmp}/b62-worker-shared-logs.XXXXXXXX")"
ORIGIN_TIMEOUT_PID=""
ORIGIN_WEB_PID=""
WORKER_PID=""
cleanup() {
  if [[ -n "$WORKER_PID" ]]; then
    kill -TERM -- "-$WORKER_PID" 2>/dev/null || true
    sleep 0.2
    kill -KILL -- "-$WORKER_PID" 2>/dev/null || true
    wait "$WORKER_PID" 2>/dev/null || true
  fi
  for pid in "$ORIGIN_TIMEOUT_PID" "$ORIGIN_WEB_PID"; do
    if [[ -n "$pid" ]]; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  rm -rf -- "$PERSIST_DIR" "$LOGDIR"
  rm -f .runtime-shared-probe.toml
}
trap cleanup EXIT

# Same independent synthetic HTTP origins used by both original probes.
uv run --locked python tests/worker_runtime_probe_origin.py --port 9099 >"$LOGDIR/timeout-origin.log" 2>&1 &
ORIGIN_TIMEOUT_PID="$!"
uv run --locked python tests/worker_runtime_probe_origin.py --port 9100 >"$LOGDIR/web-origin.log" 2>&1 &
ORIGIN_WEB_PID="$!"
echo "B62_SHARED_WORKER_START_MS=$(date +%s%3N)"
setsid npx --yes wrangler@4.130.0 dev --config .runtime-shared-probe.toml --port 8795 --inspector-port 9235 --persist-to "$PERSIST_DIR" >"$LOGDIR/workerd.log" 2>&1 &
WORKER_PID="$!"
echo "B62_SHARED_WORKER_LAUNCHED_MS=$(date +%s%3N)"
READY=0
for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8795/ready >/dev/null 2>&1; then READY=1; break; fi
  sleep 1
done
if [[ "$READY" -ne 1 ]]; then
  cat "$LOGDIR/workerd.log" >&2
  echo 'B62_SHARED_WORKER_READY=FAIL' >&2
  exit 1
fi
echo "B62_SHARED_WORKER_READY_MS=$(date +%s%3N)"
echo 'B62_SHARED_WORKER_READY=PASS'

failed=0
count=0
# P01 synthetic monkeypatch belongs last, after transport/R2 assertions.
for case in timeout web_transport r2_read p01_binding; do
  count=$((count + 1))
  result="$LOGDIR/$case-result.json"
  case "$case" in timeout) index=0;; web_transport) index=1;; p01_binding) index=2;; r2_read) index=3;; esac
  echo "B62_WORKER_CASE_${case}_START_MS=$(date +%s%3N)"
  code=""
  if code="$(curl -sS --max-time 15 -o "$result" -w '%{http_code}' "http://127.0.0.1:8795/probe?case=$case")"; then
    if [[ -f "$result" ]]; then cat "$result"; echo; fi
    if [[ "$code" == '200' ]] && B62_PROBE_CASE="$case" B62_PROBE_RESULT_PATH="$result" uv run --locked python "$SOURCE_DIR/b62_worker_probe_shared_assertions.py"; then
      echo "B62_WORKER_CASE_${case}=PASS"
      echo "B62_WORKER_PROBE_$index=PASS"
    else
      failed=1
      echo "B62_WORKER_CASE_${case}=FAIL code=$code" >&2
      echo "B62_WORKER_PROBE_$index=FAIL" >&2
    fi
  else
    failed=1
    echo "B62_WORKER_CASE_${case}=FAIL transport" >&2
    echo "B62_WORKER_PROBE_$index=FAIL" >&2
  fi
  echo "B62_WORKER_CASE_${case}_END_MS=$(date +%s%3N)"
done
echo "B62_WORKER_PROBE_COUNT=$count"
if [[ "$failed" -ne 0 || "$count" -ne 4 ]]; then
  echo 'B62_WORKER_PROBES=FAIL' >&2
  cat "$LOGDIR/workerd.log" >&2
  exit 1
fi
echo 'B62_WORKER_PROBES=PASS'
