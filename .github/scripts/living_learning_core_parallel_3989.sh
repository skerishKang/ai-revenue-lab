#!/usr/bin/env bash
# #3989 Living Learning full + Core full regressions in ONE Linux Actions job.
# Do not weaken either suite, environment, or independent success requirement.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
logs="$(mktemp -d)"
ll_pid=''
core_pid=''
cleanup() {
  if [[ -n "$ll_pid" ]]; then kill "$ll_pid" 2>/dev/null || :; fi
  if [[ -n "$core_pid" ]]; then kill "$core_pid" 2>/dev/null || :; fi
  rm -rf "$logs"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

(
  cd "$root/apps/living-learning"
  export LL_PROVIDER_TYPE=mock
  pytest -q
) > "$logs/living-learning.log" 2>&1 &
ll_pid=$!

(
  cd "$root/packages/padiem-ai-core"
  pytest -q
) > "$logs/core.log" 2>&1 &
core_pid=$!

ll_status=0
core_status=0
wait "$ll_pid" || ll_status=$?
wait "$core_pid" || core_status=$?

echo '=== Living Learning full tests (unabridged log) ==='
cat "$logs/living-learning.log"
echo '=== Padiem AI Core full tests (unabridged log) ==='
cat "$logs/core.log"
printf 'LIVING_LEARNING_TEST_EXIT=%s\n' "$ll_status"
printf 'PADIEM_CORE_TEST_EXIT=%s\n' "$core_status"
if [[ "$ll_status" -ne 0 || "$core_status" -ne 0 ]]; then
  echo 'LIVING_LEARNING_CORE_PARALLEL=FAIL' >&2
  exit 1
fi
echo 'LIVING_LEARNING_CORE_PARALLEL=PASS'
