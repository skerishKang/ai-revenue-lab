#!/usr/bin/env bash
set -euo pipefail
unit=padiem-chat-expired-purge-com2.service
systemctl show "$unit" --property=Result --property=ExecMainStatus --property=ActiveState --property=ExecMainStartTimestamp --property=ExecMainExitTimestamp
journalctl -u "$unit" --no-pager --output=cat -n 20 | grep -E '^CHAT_EXPIRED_PURGE(_RUN)?=' || true
