#!/usr/bin/env bash
# #5479/#5664: distinguish sequential from concurrent cold-init NoGilError.
#
# The upstream race (cloudflare/workerd#6624) fires inside the Cloudflare
# runtime while it prepares the Python instance (preparePython ->
# initPyInstance -> Proxy) — before any route dispatch. #5479 recorded it on
# repeated poll requests arriving on a cold isolate; #5664 recorded the same
# non-JSON 500/503 shape on register/login/reset.
#
# This probe separates the two traffic shapes on fresh Workerd instances at
# the deployed compatibility date:
#
#   Phase S (sequential)  — one fresh Workerd; /ready first, then N sequential
#                           requests. A single caller serializes prepare, so a
#                           NoGilError here would be a new, unexpected signal.
#   Phase C (cold burst)  — a second, fresh Workerd; N simultaneous requests
#                           fired before anything warms the isolate. This is
#                           the incident shape. The upstream race is reported
#                           as OBSERVED, not failed: it is a platform defect,
#                           and this probe exists to measure it, not to hide
#                           it behind a pass.
#
# The script fails only on probe-infrastructure errors (a Workerd that never
# becomes ready, a transport that cannot serve the probe route).
set -euo pipefail
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if (( $# != 0 )); then echo 'B62_NOGIL_REPRO_INVALID_ARGUMENTS' >&2; exit 2; fi
CHAT_MANIFEST="$(cd -- "$SOURCE_DIR/../../apps/padiem-chat" && pwd)/wrangler.toml"
COMPAT_DATE="$(sed -n 's/^compatibility_date = "\(.*\)"$/\1/p' "$CHAT_MANIFEST" | head -n 1)"
if [ -z "$COMPAT_DATE" ]; then
  echo 'B62_NOGIL_REPRO_COMPAT_DATE_MISSING=FAIL' >&2
  exit 2
fi

PERSIST_DIR="$(mktemp -d "${TMPDIR:-/tmp}/b62-nogil-state.XXXXXXXX")"
LOGDIR="$(mktemp -d "${TMPDIR:-/tmp}/b62-nogil-logs.XXXXXXXX")"
WORKER_PID=""
cleanup() {
  if [[ -n "$WORKER_PID" ]]; then
    kill -TERM -- "-$WORKER_PID" 2>/dev/null || true
    sleep 0.2
    kill -KILL -- "-$WORKER_PID" 2>/dev/null || true
    wait "$WORKER_PID" 2>/dev/null || true
  fi
  rm -rf -- "$PERSIST_DIR" "$LOGDIR"
  rm -f .runtime-nogil-probe.toml
}
trap cleanup EXIT

cat > .runtime-nogil-probe.toml <<EOF
name = "padiem-chat-nogil-repro"
main = "worker_runtime_combined_probe.py"
compatibility_date = "$COMPAT_DATE"
compatibility_flags = ["python_workers"]
workers_dev = true
EOF

start_worker() {
  local port="$1"
  setsid npx --yes wrangler@4.130.0 dev --config .runtime-nogil-probe.toml --port "$port" --persist-to "$PERSIST_DIR" >"$LOGDIR/workerd-$port.log" 2>&1 &
  WORKER_PID="$!"
  local ready=0 body=""
  for _ in $(seq 1 120); do
    if body="$(curl -fsS "http://127.0.0.1:$port/ready" 2>/dev/null)"; then ready=1; break; fi
    sleep 1
  done
  if [[ "$ready" -ne 1 ]]; then
    cat "$LOGDIR/workerd-$port.log" >&2
    echo "B62_NOGIL_WORKER_READY_${port}=FAIL" >&2
    exit 1
  fi
  echo "B62_NOGIL_WORKER_READY_${port}=$body"
}

# ---------------------------------------------------------------- Phase S --
# Sequential traffic on a cold isolate: /ready warms prepare, then twelve
# sequential requests must all answer 200.
start_worker 8891
SEQUENTIAL_OK=0
SEQUENTIAL_FAIL=0
for _ in $(seq 1 12); do
  code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8891/ready 2>/dev/null || echo 000)"
  if [[ "$code" == "200" ]]; then SEQUENTIAL_OK=$((SEQUENTIAL_OK + 1)); else SEQUENTIAL_FAIL=$((SEQUENTIAL_FAIL + 1)); fi
done
echo "B62_NOGIL_SEQUENTIAL_OK=$SEQUENTIAL_OK B62_NOGIL_SEQUENTIAL_FAIL=$SEQUENTIAL_FAIL"
if (( SEQUENTIAL_FAIL > 0 )); then
  echo 'B62_NOGIL_SEQUENTIAL=FAIL (sequential cold traffic must not race prepare)' >&2
  exit 1
fi
echo 'B62_NOGIL_SEQUENTIAL=PASS'

# ---------------------------------------------------------------- Phase C --
# Cold burst: kill the warmed instance, boot a fresh one, and fire ten
# simultaneous requests BEFORE anything warms the isolate. This is the
# #5479/#5664 incident shape. Outcomes are classified, not failed: an
# observed race is the upstream defect, not an application regression.
kill -TERM -- "-$WORKER_PID" 2>/dev/null || true
sleep 1
kill -KILL -- "-$WORKER_PID" 2>/dev/null || true
wait "$WORKER_PID" 2>/dev/null || true
WORKER_PID=""
start_worker 8892

BURST_OUT="$LOGDIR/burst"
mkdir -p "$BURST_OUT"
for i in $(seq 1 10); do
  curl -s -o "$BURST_OUT/$i.body" -w '%{http_code}' "http://127.0.0.1:8892/ready?burst=$i" >"$BURST_OUT/$i.code" 2>/dev/null &
done
wait
COLD_OK=0
COLD_5XX=0
for i in $(seq 1 10); do
  code="$(cat "$BURST_OUT/$i.code" 2>/dev/null || echo 000)"
  if [[ "$code" == "200" ]]; then
    COLD_OK=$((COLD_OK + 1))
  elif [[ "$code" =~ ^5 ]]; then
    COLD_5XX=$((COLD_5XX + 1))
  fi
done
echo "B62_NOGIL_COLD_BURST_OK=$COLD_OK B62_NOGIL_COLD_BURST_5XX=$COLD_5XX"
if (( COLD_5XX > 0 )); then
  echo "B62_NOGIL_CONCURRENT_COLD=OBSERVED (the workerd#6624 race — upstream, see #5479/#5664)"
else
  echo 'B62_NOGIL_CONCURRENT_COLD=CLEAR'
fi
echo 'B62_NOGIL_REPRO=COMPLETE'
