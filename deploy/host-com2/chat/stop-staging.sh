#!/usr/bin/env bash
# Stops the COM2 Chat staging unit only. Never disables it, never touches the
# staging queue unit, the production Chat, its tunnel, or Cloudflare.
set -euo pipefail
unit=padiem-chat-staging.service
fail() { echo "CHAT_STAGING_STOP=$1" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || fail ROOT_REQUIRED
if ! systemctl is-active --quiet "$unit"; then
  echo "CHAT_STAGING_STOP=ALREADY_STOPPED"
  exit 0
fi
systemctl stop "$unit"
if systemctl is-active --quiet "$unit"; then fail STILL_ACTIVE; fi
echo "CHAT_STAGING_STOP=PASS"
