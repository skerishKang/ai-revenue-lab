#!/usr/bin/env bash
# Isolated restore smoke only. Never point this script at a production data path.
set -euo pipefail

: "${PADIEM_LIVE_BACKUP_DATE:?set PADIEM_LIVE_BACKUP_DATE to the backup date}"
: "${COM2_OFFSITE_KEY_FILE:?set COM2_OFFSITE_KEY_FILE in the local environment}"
: "${COM2_OFFSITE_KEY_ID:?set COM2_OFFSITE_KEY_ID in the local environment}"
: "${OFFSITE_STATE_DIR:?set OFFSITE_STATE_DIR to the existing backup state directory}"
export OFFSITE_STATE_DIR COM2_OFFSITE_KEY_FILE COM2_OFFSITE_KEY_ID

repo_root="$(git rev-parse --show-toplevel)"
chat_dir="$repo_root/apps/padiem-chat"
restore_root="$(mktemp -d "${TMPDIR:-/tmp}/padiem-chat-live-restore.XXXXXX")"
server_pid=""

cleanup() {
  if [[ -n "$server_pid" ]]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -rf -- "$restore_root"
}
trap cleanup EXIT INT TERM

restored_data="$restore_root/chat-data"
mkdir -m 700 "$restored_data"

python3 "$repo_root/deploy/host-com2/offsite-backup/offsite.py" restore \
  --service chat \
  --date "$PADIEM_LIVE_BACKUP_DATE" \
  --target "$restored_data" \
  --replace

port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
(
  cd "$chat_dir"
  export PADIEM_CHAT_LOCAL_DATA_DIR="$restored_data"
  export PADIEM_LOCAL_DEV=1
  python3 -m app.local_server --host 127.0.0.1 --port "$port" --no-server-header
) &
server_pid=$!

for _ in $(seq 1 60); do
  if curl --fail --silent --show-error "http://127.0.0.1:$port/health" >/dev/null; then
    break
  fi
  sleep 1
done

curl --fail --silent --show-error "http://127.0.0.1:$port/" >/dev/null
curl --fail --silent --show-error "http://127.0.0.1:$port/health" >/dev/null
printf '%s\n' "temporary_restore_smoke=PASS"
