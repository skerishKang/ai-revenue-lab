#!/usr/bin/env bash
set -euo pipefail
for unit in padiem-chat-cron-com2.service padiem-chat-cron-com2.timer padiem-chat-expired-purge-com2.service padiem-chat-expired-purge-com2.timer; do
  state="$(systemctl show "$unit" --property=LoadState --value 2>/dev/null || true)"
  printf 'UNIT_BEFORE=%s:%s\n' "$unit" "${state:-not-found}"
  if [[ -n "$state" && "$state" != "not-found" ]]; then
    printf 'INSTALL_REFUSED=unit_already_loaded unit=%s state=%s\n' "$unit" "$state" >&2
    exit 20
  fi
done
bash /opt/padiem/com2-deploy/ops/deploy/host-com2/cron/install-cron.sh --profile production --schedule '*-*-* 18:00:00' --apply
for unit in padiem-chat-cron-com2.service padiem-chat-cron-com2.timer padiem-chat-expired-purge-com2.service padiem-chat-expired-purge-com2.timer; do
  systemctl show "$unit" --property=LoadState --property=UnitFileState --property=ActiveState
done
