#!/usr/bin/env bash
# B62 Worker real-Pyodide probes run concurrently, preserving original behavior.
# Each probe has a unique worker port, origin port (when applicable), temp
# wrangler config and output path; each script cleans its own spawned processes.
set -euo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if (( $# == 0 )); then
  probes=(
    "$SOURCE_DIR/b62_worker_probe_timeout.sh"
    "$SOURCE_DIR/b62_worker_probe_web_transport.sh"
    "$SOURCE_DIR/b62_worker_probe_p01_binding.sh"
    "$SOURCE_DIR/b62_worker_probe_r2_read.sh"
  )
elif (( $# == 4 )); then
  # Exactly four mock scripts, used by the offline failure-propagation canary.
  probes=("$@")
else
  echo 'B62_WORKER_PROBES_INVALID_COUNT' >&2
  exit 2
fi
for probe in "${probes[@]}"; do
  if [[ ! -f "$probe" ]]; then
    echo "B62_WORKER_PROBE_MISSING=$probe" >&2
    exit 2
  fi
done

# npx performs a first-use install of the pinned Wrangler package in the shared
# npm _npx cache. Four concurrent cold-cache installs can race creating the same
# node_modules/.bin symlink (npm EEXIST); serialize only the install/warmup.
# The four real Worker runtime probes still execute concurrently afterward.
# Offline 4-mock-script canaries must not require network or npm.
if (( $# == 0 )); then
  if [[ "${B62_WORKER_NPX_PREWARMED:-}" == '1' ]]; then
    # The preceding same-job CI step proves the exact Wrangler version and
    # writes this marker to GITHUB_ENV only after both preflights PASS.
    echo 'B62_WORKER_NPX_PREWARM=VERIFIED_PRIOR_STEP'
  else
    # Standalone runs retain their original fail-closed npm prewarm.
    if ! npx --yes wrangler@4.130.0 --version; then
      echo 'B62_WORKER_NPX_PREWARM=FAIL' >&2
      exit 1
    fi
    echo 'B62_WORKER_NPX_PREWARM=PASS'
  fi
fi

logdir="$(mktemp -d)"
pids=()
cleanup() {
  for pid in "${pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  for pid in "${pids[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
  rm -rf -- "$logdir"
}
trap cleanup EXIT

# Four simultaneous cold Python Worker/Pyodide starts on the same runner
# showed correlated 90-129s readiness (HTTP assertions are <1s). Test two
# concurrent starts per wave, keeping all four REAL probes and their exit gates.
# The final marker stays fail-closed even if an earlier wave fails.
failed=0
echo 'B62_WORKER_PROBE_BOOT_CONCURRENCY=2'
for batch_start in 0 2; do
  pids=()
  for offset in 0 1; do
    index=$((batch_start + offset))
    bash "${probes[$index]}" >"$logdir/probe-$index.log" 2>&1 &
    pids+=("$!")
  done
  for offset in 0 1; do
    index=$((batch_start + offset))
    if wait "${pids[$offset]}"; then
      echo "B62_WORKER_PROBE_$index=PASS"
    else
      echo "B62_WORKER_PROBE_$index=FAIL" >&2
      failed=1
    fi
    # Include all original probe contract markers and bounded failure detail.
    cat "$logdir/probe-$index.log"
  done
done
echo 'B62_WORKER_PROBE_COUNT=4'
if (( failed )); then
  echo 'B62_WORKER_PROBES=FAIL' >&2
  exit 1
fi
echo 'B62_WORKER_PROBES=PASS'
