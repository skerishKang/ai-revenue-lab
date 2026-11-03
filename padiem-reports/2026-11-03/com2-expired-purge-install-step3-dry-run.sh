#!/usr/bin/env bash
set -u
out="$(systemd-run --quiet --wait --pipe --collect \
  --unit=padiem-chat-expired-purge-dry-run-20261103 \
  --uid=padiem-chat \
  --working-directory=/opt/padiem/chat-com2 \
  --property=EnvironmentFile=/opt/padiem/chat-com2/.env \
  /usr/bin/env PADIEM_CHAT_CPYTHON_HOST=1 PADIEM_CHAT_LOCAL_DATA_DIR=/opt/padiem/chat-com2/data \
  /opt/padiem/chat-com2/venv/bin/python -m app.expired_purge --dry-run 2>&1)"
rc=$?
status_line="$(printf '%s\n' "$out" | grep -E '^CHAT_EXPIRED_PURGE=' | tail -n 1 || true)"
if [[ $rc -ne 0 ]]; then
  printf 'DRY_RUN_EXIT=%s\n' "$rc"
  if [[ -n "$status_line" ]]; then printf '%s\n' "$status_line"; else printf 'DRY_RUN_STATUS=missing\n'; fi
  exit 21
fi
if [[ "$status_line" != CHAT_EXPIRED_PURGE=dry_run\ detail=* ]]; then
  if [[ -n "$status_line" ]]; then printf 'DRY_RUN_REJECTED=%s\n' "$status_line"; else printf 'DRY_RUN_STATUS=missing\n'; fi
  exit 22
fi
printf '%s\n' "$status_line"
