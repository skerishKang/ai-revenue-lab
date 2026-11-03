#!/usr/bin/env bash
set +e
unit=padiem-chat-expired-purge-com2.service
started="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
systemctl start "$unit"
start_rc=$?
printf 'PURGE_SERVICE_START_RC=%s\n' "$start_rc"
journalctl -u "$unit" --since "$started" --no-pager --output=cat 2>/dev/null | grep -E '^CHAT_EXPIRED_PURGE(_RUN)?=' || true
systemctl show "$unit" --property=Result --property=ExecMainStatus --property=ActiveState
if [[ $start_rc -ne 0 ]]; then
  exit 41
fi
