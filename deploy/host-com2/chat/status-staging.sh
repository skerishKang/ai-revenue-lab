#!/usr/bin/env bash
# Read-only staging status: unit state, loopback health, queue unit state.
set -euo pipefail
app=/opt/padiem/chat-staging
unit=padiem-chat-staging.service
queue_unit=padiem-mesh-queue-staging.service

echo "CHAT_STAGING_UNIT=$(systemctl is-active "$unit" 2>/dev/null || true)"
echo "STAGING_QUEUE_UNIT=$(systemctl is-active "$queue_unit" 2>/dev/null || true)"
systemctl --no-pager --full status "$unit" 2>/dev/null | sed -n '1,12p' || true
if [[ -x "$app/venv/bin/python" && -f "$app/health.py" ]]; then
  "$app/venv/bin/python" "$app/health.py" --url http://127.0.0.1:8801/health || true
else
  echo "CHAT_STAGING_HEALTH=UNKNOWN reason=app_not_installed"
fi
