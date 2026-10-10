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

# #3989 CPU contention trial: three simultaneous real Workerd/Pyodide
# startups, followed by the fourth alone. Original four scripts, distinct
# ports/SQLite roots, pinned Wrangler and every assertion remain unchanged.
# Batch two executes even when any probe from the first batch fails.
failed=0
report_probe() {
  local completed_index="$1"
  if wait "${pids[$completed_index]}"; then
    echo "B62_WORKER_PROBE_$completed_index=PASS"
  else
    echo "B62_WORKER_PROBE_$completed_index=FAIL" >&2
    failed=1
  fi
  cat "$logdir/probe-$completed_index.log"
}
for index in 0 1 2 3; do
  if (( index == 3 )); then
    for completed_index in 0 1 2; do
      report_probe "$completed_index"
    done
    echo 'B62_WORKER_WAVE=FIRST_THREE_FINISHED'
  fi
  bash "${probes[$index]}" >"$logdir/probe-$index.log" 2>&1 &
  pids+=("$!")
done
report_probe 3
echo 'B62_WORKER_WAVE=FOURTH_FINISHED'
echo 'B62_WORKER_PROBE_COUNT=4'
if (( failed )); then
  echo 'B62_WORKER_PROBES=FAIL' >&2
  exit 1
fi
echo 'B62_WORKER_PROBES=PASS'
