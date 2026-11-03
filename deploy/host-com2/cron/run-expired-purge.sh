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
else
  echo "CHAT_EXPIRED_PURGE_RUN=FAILED reason=python_missing path=$python" >&2
  status=1
fi

echo "CHAT_EXPIRED_PURGE_RUN=END profile=$profile status=$status at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
exit "$status"
