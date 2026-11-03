#!/usr/bin/env bash
set -euo pipefail
ops=/opt/padiem/com2-deploy/ops
app=/opt/padiem/chat-com2
printf '%s\n' '--- runtime paths ---'
printf 'APP_ROOT_REALPATH='
readlink -f "$app" || true
pid="$(systemctl show padiem-chat-com2.service --property=MainPID --value)"
printf 'CHAT_MAINPID=%s\n' "$pid"
if [ -d "/proc/$pid" ]; then
  printf 'CHAT_CWD='
  readlink -f "/proc/$pid/cwd" || true
  printf 'CHAT_DATA_DIR_ENV='
  tr '\0' '\n' <"/proc/$pid/environ" | sed -n 's/^PADIEM_CHAT_DATA_DIR=//p'
fi
printf '%s\n' '--- local_data_dir source ---'
rg -n -C 4 'def local_data_dir|PADIEM_CHAT_DATA_DIR' "$app/app/local_cpython.py" "$ops/apps/padiem-chat/app/local_cpython.py" 2>/dev/null || true
printf '%s\n' '--- runtime file readiness ---'
for f in "$app/app/expired_purge.py" "$app/app/local_cpython.py" "$app/venv/bin/python" /mnt/d/padiem/chat-com2/chat.sqlite3; do
  if [ -e "$f" ]; then
    printf 'present '
    readlink -f "$f"
  else
    printf 'missing %s\n' "$f"
  fi
done
printf '%s\n' '--- database metadata ---'
if [ -f /mnt/d/padiem/chat-com2/chat.sqlite3 ]; then
  stat -c 'CHAT_DB size=%s owner=%U:%G mode=%a modified=%y' /mnt/d/padiem/chat-com2/chat.sqlite3
fi
