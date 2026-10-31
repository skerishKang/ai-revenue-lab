#!/usr/bin/env bash
# Starts the COM2 Chat staging unit only. Never enables it, never touches the
# staging queue unit, the production Chat, its tunnel, or Cloudflare.
set -euo pipefail
app=/opt/padiem/chat-staging
unit=padiem-chat-staging.service
queue_unit=padiem-mesh-queue-staging.service
fail() { echo "CHAT_STAGING_START=$1" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || fail ROOT_REQUIRED
[[ -f "/etc/systemd/system/$unit" ]] || fail UNIT_NOT_INSTALLED
[[ -f "$app/.env" ]] || fail ENV_MISSING
command -v ss >/dev/null 2>&1 || fail SS_REQUIRED
systemctl is-active --quiet "$queue_unit" || fail STAGING_QUEUE_NOT_ACTIVE
if systemctl is-active --quiet "$unit"; then
  echo "CHAT_STAGING_START=ALREADY_ACTIVE PORT=8801"
  exit 0
fi
if ss -ltn 2>/dev/null | grep -qE '[:.]8801[[:space:]]'; then fail PORT_8801_IN_USE; fi
runuser -u padiem-chat -- "$app/venv/bin/python" "$app/check_config_staging.py" >/dev/null \
  || fail CONFIG_NOT_READY
systemctl start "$unit"
if ! systemctl is-active --quiet "$unit"; then
  systemctl --no-pager --full status "$unit" >&2 || true
  fail NOT_ACTIVE
fi
runuser -u padiem-chat -- "$app/venv/bin/python" "$app/health.py" \
  --url http://127.0.0.1:8801/health || fail HEALTH_FAILED
echo "CHAT_STAGING_START=PASS PORT=8801"
