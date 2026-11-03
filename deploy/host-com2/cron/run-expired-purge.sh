#!/usr/bin/env bash
# One COM2 Chat expired-row purge pass, guarded against self-overlap.
#
# The pass itself is `python -m app.expired_purge --once`; this script adds only
# what a timer needs: a lock, journal markers and an honest status. It never
# starts, enables, installs or reconfigures anything, and it never touches
# Cloudflare.
set -uo pipefail

profile=${CRON_PROFILE:-unknown}
lock=${CRON_LOCK_FILE:-/run/padiem-chat-expired-purge/$profile.lock}
python=${CHAT_CRON_PYTHON:-$(pwd)/venv/bin/python}
app_root=${CRON_APP_ROOT:-$(pwd)}

started=$(date -u +%Y-%m-%dT%H:%M:%SZ)

lock_dir=$(dirname "$lock")
mkdir -p "$lock_dir" 2>/dev/null || true
if ! exec 9>>"$lock"; then
  echo "CHAT_EXPIRED_PURGE_RUN=FAILED reason=lock_unwritable profile=$profile at=$started" >&2
  exit 1
fi

if ! flock -n 9; then
  echo "CHAT_EXPIRED_PURGE_RUN=SKIPPED reason=previous_run_active profile=$profile at=$started"
  exit 0
fi

echo "CHAT_EXPIRED_PURGE_RUN=START profile=$profile at=$started app_root=$app_root"

cd "$app_root" 2>/dev/null || {
  echo "CHAT_EXPIRED_PURGE_RUN=FAILED reason=app_root_missing app_root=$app_root" >&2
  exit 1
}

status=0
if [[ -x "$python" ]]; then
  "$python" -m app.expired_purge --once
  status=$?
  # Stage 2: rows whose *retention period* the owner decided (withdrawal record
  # one year, MCP audit 90 days). A failure here must not be hidden by stage 1
  # succeeding, and must not stop the ledger pass below.
  "$python" -m app.retention_purge --once
  retention=$?
  if [[ $retention -ne 0 && $status -eq 0 ]]; then
    status=$retention
  fi
else
  echo "CHAT_EXPIRED_PURGE_RUN=FAILED reason=python_missing path=$python" >&2
  status=1
fi

# Stage 3: B14 call-ledger retention (90 days). Runs only where the operator
# pointed this job at the ledger: the ledger lives in the B14 app root with its
# own interpreter, so guessing either would either purge the wrong file or
# report a false success.
ledger_python=${B14_LEDGER_PYTHON:-}
ledger_root=${B14_LEDGER_APP_ROOT:-}
ledger_db=${B14_LEDGER_DB:-}
if [[ -n "$ledger_python" && -n "$ledger_root" && -n "$ledger_db" && -x "$ledger_python" ]]; then
  ( cd "$ledger_root" && "$ledger_python" -m app.pilot.call_ledger_retention --db "$ledger_db" --once )
  ledger_status=$?
  if [[ $ledger_status -ne 0 && $status -eq 0 ]]; then
    status=$ledger_status
  fi
else
  echo "B14_LEDGER_RETENTION=SKIPPED reason=not_configured"
fi

echo "CHAT_EXPIRED_PURGE_RUN=END profile=$profile status=$status at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
exit "$status"
