#!/usr/bin/env bash
# #3989: overlap two independent, mandatory Engine cross-product regressions.
# Both suites retain their original working directories and command sequences.
# The independent Engine Worker Pywrangler sync overlaps both suites on the
# *same* existing runner; all 3 processes must finish successfully.
# Never suppress a nonzero child status; always wait for every child.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
log_dir="$(mktemp -d)"
core_pid=""
ll_pid=""
worker_sync_pid=""

cleanup() {
  # A cancelled job must not leave a detached background test process.
  if [[ -n "$core_pid" ]]; then kill "$core_pid" 2>/dev/null || :; fi
  if [[ -n "$ll_pid" ]]; then kill "$ll_pid" 2>/dev/null || :; fi
  if [[ -n "$worker_sync_pid" ]]; then kill "$worker_sync_pid" 2>/dev/null || :; fi
  rm -rf "$log_dir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

(
  cd "$repo_root/packages/padiem-ai-core"
  uv run --extra dev python -m pytest -q
) > "$log_dir/core.log" 2>&1 &
core_pid=$!

(
  cd "$repo_root/apps/living-learning"
  export LL_PROVIDER_TYPE=mock
  python -m pip install --disable-pip-version-check -r requirements-padiem-core.txt
  python -m pip install --disable-pip-version-check -e '.[dev]'
  python -m pip install --disable-pip-version-check 'jsonschema>=4.23,<5'
  python -m pip check
  python -m pytest -q
) > "$log_dir/living-learning.log" 2>&1 &
ll_pid=$!

# Pywrangler only writes Engine-owned .venv-workers/python_modules. Core and
# Living Learning regressions use separate component environments and still
# run their complete suites; no extra CI job or suppressed exit code.
(
  cd "$repo_root/apps/padiem-ai-engine"
  uv run pywrangler sync --force
) > "$log_dir/worker-sync.log" 2>&1 &
worker_sync_pid=$!

core_status=0
ll_status=0
worker_sync_status=0
wait "$core_pid" || core_status=$?
wait "$ll_pid" || ll_status=$?
wait "$worker_sync_pid" || worker_sync_status=$?

echo '=== Padiem AI Core full tests (unabridged log) ==='
cat "$log_dir/core.log"
echo '=== Living Learning Core-reuse regression (unabridged log) ==='
cat "$log_dir/living-learning.log"
echo '=== Engine Worker Pywrangler dependency sync (unabridged log) ==='
cat "$log_dir/worker-sync.log"
printf 'ENGINE_CORE_TEST_EXIT=%s\n' "$core_status"
printf 'ENGINE_LL_REGRESSION_EXIT=%s\n' "$ll_status"
printf 'ENGINE_WORKER_SYNC_EXIT=%s\n' "$worker_sync_status"
if [[ "$core_status" -ne 0 || "$ll_status" -ne 0 ]]; then
  echo 'ENGINE_CORE_LL_PARALLEL=FAIL' >&2
  exit 1
fi
if [[ "$worker_sync_status" -ne 0 ]]; then
  echo 'ENGINE_CORE_LL_WORKER_SYNC=FAIL' >&2
  exit 1
fi
echo 'ENGINE_CORE_LL_PARALLEL=PASS'
echo 'ENGINE_CORE_LL_WORKER_SYNC=PASS'
