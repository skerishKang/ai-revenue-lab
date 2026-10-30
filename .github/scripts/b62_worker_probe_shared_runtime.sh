#!/usr/bin/env bash
# #3989: four original Worker assertions, one real Pyodide/Workerd startup.
set -euo pipefail
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if (( $# != 0 )); then echo 'B62_SHARED_WORKER_INVALID_ARGUMENTS' >&2; exit 2; fi
# #5479: the real Pyodide probe must boot the SAME compatibility date that
# Production deploys. A literal date here lets the CI lane prove a runtime
# that Production no longer runs.
CHAT_MANIFEST="$(cd -- "$SOURCE_DIR/../../apps/padiem-chat" && pwd)/wrangler.toml"
COMPAT_DATE="$(sed -n 's/^compatibility_date = "\(.*\)"$/\1/p' "$CHAT_MANIFEST" | head -n 1)"
if [ -z "$COMPAT_DATE" ]; then
  echo 'B62_WORKER_COMPAT_DATE_MISSING=FAIL' >&2
  exit 2
fi
cat > .runtime-shared-probe.toml <<EOF
name = "padiem-chat-runtime-shared-probe"
main = "worker_runtime_combined_probe.py"
compatibility_date = "$COMPAT_DATE"
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
READY_BODY=""
for _ in $(seq 1 90); do
  if READY_BODY="$(curl -fsS http://127.0.0.1:8795/ready 2>/dev/null)"; then READY=1; break; fi
  sleep 1
done
if [[ "$READY" -ne 1 ]]; then
  cat "$LOGDIR/workerd.log" >&2
  echo 'B62_SHARED_WORKER_READY=FAIL' >&2
  exit 1
fi
echo "B62_SHARED_WORKER_READY_MS=$(date +%s%3N)"
echo 'B62_SHARED_WORKER_READY=PASS'
# #5479: the CI lane must prove the Python runtime Production actually runs.
# The compatibility date above is the deployed one, so the booted interpreter
# has to be the version that date selects.
EXPECTED_PYTHON="$(uv run --locked python -c 'from pywrangler.utils import get_python_version; print(get_python_version())' 2>/dev/null | tail -n 1)"
if [[ -z "$EXPECTED_PYTHON" || "$READY_BODY" != *"ok ${EXPECTED_PYTHON} "* ]]; then
  echo "B62_WORKER_PYTHON_RUNTIME=FAIL ready=$READY_BODY expected=$EXPECTED_PYTHON" >&2
  cat "$LOGDIR/workerd.log" >&2
  exit 1
fi
echo "B62_WORKER_PYTHON_RUNTIME=$READY_BODY"
# #5023: the deployed runtime must be able to resolve a real IANA zone, because
# the Calendar contracts validate the explicit timezone against the real
# database. A runtime without the tz database answers every Calendar read with
# HTTP 400 invalid_timezone.
if [[ "$READY_BODY" != *"tz=ok"* ]]; then
  echo "B62_WORKER_TIMEZONE_DATABASE=FAIL ready=$READY_BODY" >&2
  cat "$LOGDIR/workerd.log" >&2
  exit 1
fi
echo 'B62_WORKER_TIMEZONE_DATABASE=PASS'
# #5479/#5664: the deployed runtime must serve password authentication. The
# Pyodide 3.14 snapshot ships no _hashlib and CPython 3.14 removed the
# pure-Python PBKDF2 fallback, so it has no hashlib.pbkdf2_hmac at all; #5732
# made the KDF runtime-independent and the auth routes call only the async
# dispatch. The asserted invariant is therefore what the routes actually use:
#   kdfasync=ok  the dispatch serves this runtime (C path on 3.13, the
#                bundled cryptography package on 3.14)
#   stored=ok    a 220,000-iteration credential written by the previous 3.13
#                runtime verifies here. This is the check #5736 was missing:
#                Workers WebCrypto PBKDF2 refuses any iteration count above
#                100,000, so a 3.14 deploy passed the low-iteration bridge and
#                still answered every register/login/reset with HTTP 500.
#   digest=ok    SHA-2/HMAC match the published OpenSSL vectors
# kdf= (the sync C path) stays a printed availability report, not a gate: on
# 3.14 it is absent by design and no login path uses it.
if [[ "$READY_BODY" != *"kdfasync=ok"* || "$READY_BODY" != *"stored=ok"* || "$READY_BODY" != *"digest=ok"* ]]; then
  echo "B62_WORKER_PASSWORD_AUTH=FAIL ready=$READY_BODY" >&2
  cat "$LOGDIR/workerd.log" >&2
  exit 1
fi
echo 'B62_WORKER_PASSWORD_AUTH=PASS kdfasync=ok stored=ok digest=ok'
B62_WORKER_PASSWORD_KDF_C_PATH="$(printf '%s' "$READY_BODY" | sed -n 's/.*kdf=\([a-z0-9:-]*\) kdfasync=.*/\1/p')"
echo "B62_WORKER_PASSWORD_KDF_C_PATH=${B62_WORKER_PASSWORD_KDF_C_PATH}"
# #5479: the REAL production KDF contract — the stored credential format is
# PBKDF2-HMAC-SHA512 at 220,000 iterations through the same async dispatch the
# auth routes call. The expected provider is the C path on 3.13 and the bundled
# cryptography package on 3.14; `webcrypto-iteration-cap` is the 3.14 blocker
# being reproduced, and verify-failed / wrong-accepted / missing always fail.
KDF220K_BODY=""
for _ in $(seq 1 5); do
  if KDF220K_BODY="$(curl -fsS "http://127.0.0.1:8795/probe?case=kdf220k" 2>/dev/null)"; then break; fi
  sleep 1
done
echo "B62_WORKER_KDF220K=$KDF220K_BODY"
# H1 (#5743): the local Workerd on 3.14 accepts PBKDF2 220k that the
# Production edge rejects, so a local success is NEVER evidence of
# production-edge compatibility. A 3.14 result is therefore labelled
# `UNVERIFIED_PY314` and never `PASS_PY313_LOCAL`.
#
# It is not fatal here. The manifest's runtime is already a deploy decision,
# and stopping the lane on it would make every 3.14 manifest a permanent red
# build without adding one bit of edge evidence — an environment restriction
# no platform requires. The lane still enforces the half it can actually see
# (the stored cost served by the provider the declared bundle selects), and
# the edge verdict stays with the governed production deploy and its live auth
# E2E. A cap/error outcome below still fails, as before.
PY314_LOCAL=0
if [[ "$KDF220K_BODY" == *'"runtime_minor": 14'* || "$KDF220K_BODY" == *'"runtime_minor":14'* ]]; then
  PY314_LOCAL=1
  echo 'B62_WORKER_KDF220K_EDGE_COMPAT=UNVERIFIED_PY314'
fi
case "$KDF220K_BODY" in
  *'"state": "ok"'*|*'"state":"ok"'*)
    if [ "${PY314_LOCAL}" = "1" ]; then
      echo 'B62_WORKER_KDF220K_STATE=PASS_PY314_LOCAL_KDF_ONLY'
    else
      echo 'B62_WORKER_KDF220K_STATE=PASS_PY313_LOCAL'
    fi ;;
  *) echo "B62_WORKER_KDF220K_STATE=FAIL body=$KDF220K_BODY" >&2; exit 1 ;;
esac
# #5479: the stored cost must be served by the provider this runtime is
# SUPPOSED to use — the C path where `_hashlib` exists, the bundled
# cryptography package on 3.14. WebCrypto is not an acceptable answer at
# 220,000 iterations even though the local Workerd accepts it: the Production
# edge refuses it (#5736). This is the check #5733 lacked.
if [[ "$B62_WORKER_PASSWORD_KDF_C_PATH" == 'ok' ]]; then
  EXPECTED_KDF_PROVIDER='hashlib'
else
  EXPECTED_KDF_PROVIDER='cryptography'
fi
case "$KDF220K_BODY" in
  *"\"provider\": \"${EXPECTED_KDF_PROVIDER}\""*|*"\"provider\":\"${EXPECTED_KDF_PROVIDER}\""*)
    echo "B62_WORKER_KDF220K_PROVIDER=${EXPECTED_KDF_PROVIDER} PASS" ;;
  *) echo "B62_WORKER_KDF220K_PROVIDER=FAIL expected=${EXPECTED_KDF_PROVIDER} body=$KDF220K_BODY" >&2; exit 1 ;;
esac
# #5479: the 220,000-iteration alternatives with their real CPU cost — the
# pure-Python fallback (stdlib sha512 primitive) and the bundled cryptography
# package. Correctness (pinned external vectors) must hold on every runtime.
KDFBENCH_BODY=""
for _ in $(seq 1 5); do
  if KDFBENCH_BODY="$(curl -fsS --max-time 60 "http://127.0.0.1:8795/probe?case=kdfbench" 2>/dev/null)"; then break; fi
  sleep 1
done
echo "B62_WORKER_KDF_BENCH=$KDFBENCH_BODY"
case "$KDFBENCH_BODY" in
  *'"vector": "true"'*|*'"vector":"true"'*) echo 'B62_WORKER_KDF_BENCH_VECTOR=PASS' ;;
  *) echo 'B62_WORKER_KDF_BENCH_VECTOR=FAIL' >&2; exit 1 ;;
esac
case "$KDFBENCH_BODY" in
  *'"identity": "true"'*|*'"identity":"true"'*) echo 'B62_WORKER_KDF_BENCH_IDENTITY=PASS' ;;
  *) echo 'B62_WORKER_KDF_BENCH_IDENTITY=FAIL' >&2; exit 1 ;;
esac


# Same nonproduction Workerd: shared ES256 vectors and a synthetic
# WebCrypto sign/verify roundtrip; no production keys or resources are used.
SHARED_AUTH_BODY="$(curl -fsS --max-time 15 'http://127.0.0.1:8795/probe?case=shared_auth_es256')"
case "$SHARED_AUTH_BODY" in
  *'"state": "ok"'*|*'"state":"ok"'*) echo 'B62_WORKER_SHARED_AUTH_ES256=PASS' ;;
  *) echo 'B62_WORKER_SHARED_AUTH_ES256=FAIL' >&2; exit 1 ;;
esac

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
# #4139: same ONE nonproduction Workerd process, separate synthetic ASGI WSS
# roundtrip after the original 4 probes. No live PADIEM device/credential
# and no new Cloudflare Worker or public route is deployed.
# A plain GET to the synthetic WS path must return 426, not 200/404/500.
# This disambiguates route admission from actual WebSocket upgrade support.
plain_code="$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:8795/api/claw/connector/gateway/session" || true)"
echo "PADIEM_CONNECTOR_WSS_NONUPGRADE_HTTP_STATUS=$plain_code"
if [[ "$plain_code" != "426" ]]; then
  failed=1
  echo 'PADIEM_CONNECTOR_WSS_ROUTING_CONTRACT=FAIL' >&2
fi
if node "$SOURCE_DIR/b62_connector_wss_workerd_probe.mjs" "ws://127.0.0.1:8795/api/claw/connector/gateway/session"; then
  echo 'PADIEM_CONNECTOR_ASGI_WSS_WORKER_PROBE=PASS'
else
  failed=1
  echo 'PADIEM_CONNECTOR_ASGI_WSS_WORKER_PROBE=FAIL' >&2
fi
echo "B62_WORKER_PROBE_COUNT=$count"
if [[ "$failed" -ne 0 || "$count" -ne 4 ]]; then
  echo 'B62_WORKER_PROBES=FAIL' >&2
  cat "$LOGDIR/workerd.log" >&2
  exit 1
fi
echo 'B62_WORKER_PROBES=PASS'
