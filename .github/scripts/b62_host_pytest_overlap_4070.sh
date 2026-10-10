#!/usr/bin/env bash
# #4070: overlap existing full Chat pytest with independent Core pytest
# on the SAME B62 full-regression runner. Keep every case, locked command,
# original source directories, and final b62-test status fan-in.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
SCOPE="${B62_CI_IMPACT_SCOPE:-full}"
case "$SCOPE" in
  chat_only|static_only|tests_only) run_core=0 ;;
  full) run_core=1 ;;
  *) echo "B62_HOST_PYTEST_SCOPE_UNCERTAIN=$SCOPE (fail-closed: full)" >&2; run_core=1 ;;
esac

logdir="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/b62-host-tests.XXXXXXXX")"
chat_pid=""
core_pid=""
cleanup() {
  for pid in "$chat_pid" "$core_pid"; do
    if [[ -n "$pid" ]]; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  rm -rf -- "$logdir"
}
trap cleanup EXIT

# Core uses packages/padiem-ai-core/.venv; Chat uses apps/padiem-chat/.venv.
# Each has its own test conftest/pytest process. We never run two shards of
# the same Chat suite or share a pytest process, tmp outputs or test fixtures.
if (( run_core == 1 )); then
  (
    cd "$ROOT/packages/padiem-ai-core"
    uv run --extra dev python -m pytest -q
  ) > "$logdir/core.log" 2>&1 &
  core_pid="$!"
  echo "B62_CORE_PYTEST=STARTED"
else
  echo "B62_CORE_PYTEST=SKIPPED_PROVEN_UNCHANGED"
fi

(
  cd "$ROOT/apps/padiem-chat"
  uv run --locked python -m pytest -q
) > "$logdir/chat.log" 2>&1 &
chat_pid="$!"
echo "B62_CHAT_PYTEST=STARTED"

chat_rc=0
core_rc=0
if ! wait "$chat_pid"; then chat_rc=1; fi
if (( run_core == 1 )); then
  if ! wait "$core_pid"; then core_rc=1; fi
fi

# Both outputs are emitted exactly, including pytest assertions, case totals,
# Python tracebacks and plugin warnings. No suppressions, new marks or deselects.
echo '=== B62_CHAT_PYTEST_LOG_BEGIN ==='
cat "$logdir/chat.log"
echo '=== B62_CHAT_PYTEST_LOG_END ==='
if (( run_core == 1 )); then
  echo '=== B62_CORE_PYTEST_LOG_BEGIN ==='
  cat "$logdir/core.log"
  echo '=== B62_CORE_PYTEST_LOG_END ==='
fi

if (( chat_rc != 0 || core_rc != 0 )); then
  echo "B62_CHAT_PYTEST=$([[ "$chat_rc" == 0 ]] && echo PASS || echo FAIL)" >&2
  if (( run_core == 1 )); then
    echo "B62_CORE_PYTEST=$([[ "$core_rc" == 0 ]] && echo PASS || echo FAIL)" >&2
  fi
  echo 'B62_HOST_PYTEST_OVERLAP=FAIL' >&2
  exit 1
fi

echo 'B62_CHAT_PYTEST=PASS'
if (( run_core == 1 )); then
  echo 'B62_CORE_PYTEST=PASS'
fi
echo 'B62_HOST_PYTEST_OVERLAP=PASS'
