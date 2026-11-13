#!/usr/bin/env bash
set -euo pipefail
ops=/opt/padiem/com2-deploy/ops
printf '%s\n' '--- production profile ---'
cat "$ops/deploy/host-com2/cron/profiles/production.conf"
printf '%s\n' '--- installer ---'
sed -n '1,280p' "$ops/deploy/host-com2/cron/install-cron.sh"
printf '%s\n' '--- purge service template ---'
cat "$ops/deploy/host-com2/cron/padiem-chat-expired-purge.service.template"
printf '%s\n' '--- purge timer template ---'
cat "$ops/deploy/host-com2/cron/padiem-chat-expired-purge.timer.template"
printf '%s\n' '--- purge runner ---'
cat "$ops/deploy/host-com2/cron/run-expired-purge.sh"
printf '%s\n' '--- purge module ---'
sed -n '1,320p' "$ops/apps/padiem-chat/app/expired_purge.py"
printf '%s\n' '--- database config references in source ---'
rg -n -i 'database_url|db_path|sqlite|chat_db' "$ops/apps/padiem-chat/app" --glob '*.py' | head -120
printf '%s\n' '--- baseline chat service state ---'
systemctl show padiem-chat-com2.service --property=ActiveState --property=SubState --property=NRestarts --property=MainPID
