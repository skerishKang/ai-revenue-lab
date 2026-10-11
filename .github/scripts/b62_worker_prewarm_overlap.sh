#!/usr/bin/env bash
# #3989: overlap independent, *unchanged* Python Worker vendor sync and the
# pinned npm Wrangler cache prewarm. Do not launch a real Worker here.
# Both must succeed before any of the four real fail-closed probes run.
set -euo pipefail

if (( $# != 0 )); then
  echo 'B62_WORKER_PREWARM_INVALID_ARGUMENTS' >&2
  exit 2
fi

logdir="$(mktemp -d "${TMPDIR:-/tmp}/b62-worker-overlap.XXXXXXXX")"
vendor_pid=""
wrangler_pid=""
cleanup() {
  for pid in "$vendor_pid" "$wrangler_pid"; do
    if [[ -n "$pid" ]]; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  rm -rf -- "$logdir"
}
trap cleanup EXIT

# Python Worker/pylock vendoring only writes .venv-workers and python_modules.
# Pinned Wrangler prewarming only writes npm's _npx cache. Distinct outputs:
# no lock/package/version changes, no Production connection, no live Worker.
uv run --locked pywrangler sync --force > "$logdir/vendor.log" 2>&1 &
vendor_pid="$!"
npx --yes wrangler@4.130.0 --version > "$logdir/wrangler.log" 2>&1 &
wrangler_pid="$!"

vendor_ok=0
wrangler_ok=0
if wait "$vendor_pid"; then
  vendor_ok=1
fi
if wait "$wrangler_pid"; then
  if grep -Fxq '4.130.0' "$logdir/wrangler.log"; then
    wrangler_ok=1
  fi
fi

# Preserve the original installer diagnostics even on failure. The outputs
# contain package resolution and the public Wrangler version, not secrets.
cat "$logdir/vendor.log"
cat "$logdir/wrangler.log"
if (( vendor_ok != 1 || wrangler_ok != 1 )); then
  echo "B62_WORKER_VENDOR_SYNC=$([[ "$vendor_ok" == 1 ]] && echo PASS || echo FAIL)" >&2
  echo "B62_WORKER_NPX_PREWARM=$([[ "$wrangler_ok" == 1 ]] && echo PASS || echo FAIL)" >&2
  echo 'B62_WORKER_OVERLAP=FAIL' >&2
  exit 1
fi

echo 'B62_WORKER_VENDOR_SYNC=PASS'
echo 'B62_WORKER_NPX_PREWARM=PASS'
echo 'B62_WORKER_OVERLAP=PASS'
# Set the skip token only after both subprocesses and the exact version
# attestation succeeded. Offline mock-only canaries never require GITHUB_ENV.
if [[ -n "${GITHUB_ENV:-}" ]]; then
  printf '%s\n' 'B62_WORKER_NPX_PREWARMED=1' >> "$GITHUB_ENV"
fi
