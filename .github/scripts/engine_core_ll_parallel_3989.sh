#!/usr/bin/env bash
# #3989: overlap two independent, mandatory Engine cross-product regressions.
# Both suites retain their original working directories and command sequences.
# Never suppress a nonzero child status; always wait for both children.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
log_dir="$(mktemp -d)"
core_pid=""
ll_pid=""

cleanup() {
  # A cancelled job must not leave a detached background test process.
  if [[ -n "$core_pid" ]]; then kill "$core_pid" 2>/dev/null || :; fi
  if [[ -n "$ll_pid" ]]; then kill "$ll_pid" 2>/dev/null || :; fi
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

core_status=0
ll_status=0
wait "$core_pid" || core_status=$?
wait "$ll_pid" || ll_status=$?

echo '=== Padiem AI Core full tests (unabridged log) ==='
cat "$log_dir/core.log"
echo '=== Living Learning Core-reuse regression (unabridged log) ==='
cat "$log_dir/living-learning.log"
printf 'ENGINE_CORE_TEST_EXIT=%s\n' "$core_status"
printf 'ENGINE_LL_REGRESSION_EXIT=%s\n' "$ll_status"
if [[ "$core_status" -ne 0 || "$ll_status" -ne 0 ]]; then
  echo 'ENGINE_CORE_LL_PARALLEL=FAIL' >&2
  exit 1
fi
echo 'ENGINE_CORE_LL_PARALLEL=PASS'
