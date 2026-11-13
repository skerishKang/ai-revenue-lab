#!/usr/bin/env bash
set -euo pipefail
pid="$(systemctl show padiem-chat-com2.service --property=MainPID --value)"
printf 'CHAT_MAINPID=%s\n' "$pid"
printf 'CHAT_DATA_DIR_ENV='
tr '\0' '\n' <"/proc/$pid/environ" | sed -n 's/^PADIEM_CHAT_LOCAL_DATA_DIR=//p'
printf 'CHAT_PORT_ENV='
tr '\0' '\n' <"/proc/$pid/environ" | sed -n -e 's/^PORT=//p' -e 's/^PADIEM_CHAT_PORT=//p'
printf '%s\n' '--- chat-owned listening sockets ---'
ss -ltnpH | awk -v pid="$pid" 'index($0, "pid=" pid ",") {print $4}'
data_dir="$(tr '\0' '\n' <"/proc/$pid/environ" | sed -n 's/^PADIEM_CHAT_LOCAL_DATA_DIR=//p')"
if [ -z "$data_dir" ]; then
  data_dir=/opt/padiem/chat-com2/local_dev_data
fi
db="$data_dir/chat.sqlite3"
printf 'CHAT_DATA_DIR_REALPATH='
readlink -f "$data_dir" || true
printf 'CHAT_DB_PATH='
readlink -f "$db" || true
if [ -f "$db" ]; then
  stat -c 'CHAT_DB size=%s owner=%U:%G mode=%a modified=%y' "$db"
else
  printf 'CHAT_DB_MISSING\n'
fi
