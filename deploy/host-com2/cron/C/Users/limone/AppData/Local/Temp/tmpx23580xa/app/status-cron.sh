#!/usr/bin/env bash
# Read-only status for the COM2 cron timer. Changes nothing.
set -uo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
profile=${CRON_PROFILE:-${1:-staging}}
unit=""
case "$profile" in
  staging) unit=padiem-chat-cron-staging ;;
  production) unit=padiem-chat-cron-com2 ;;
  *) echo "CRON_STATUS=UNKNOWN reason=profile_unknown profile=$profile"; exit 0 ;;
esac

echo "CRON_PROFILE=$profile"
echo "CRON_UNIT=$unit"
if command -v systemctl >/dev/null 2>&1; then
  echo "CRON_TIMER_ENABLED=$(systemctl is-enabled "$unit.timer" 2>/dev/null || echo unknown)"
  echo "CRON_TIMER_ACTIVE=$(systemctl is-active "$unit.timer" 2>/dev/null || echo unknown)"
  echo "CRON_SERVICE_ACTIVE=$(systemctl is-active "$unit.service" 2>/dev/null || echo unknown)"
  systemctl --no-pager list-timers "$unit.timer" 2>/dev/null | sed -n '1,3p' || true
  journalctl --no-pager -u "$unit.service" -n 5 2>/dev/null | sed -n '1,10p' || true
else
  echo "CRON_TIMER_ACTIVE=unknown reason=systemctl_missing"
fi
echo "CRON_STATUS=REPORTED profile=$profile"
