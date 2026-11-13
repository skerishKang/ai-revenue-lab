#!/usr/bin/env bash
set -euo pipefail
umask 077
src=/opt/padiem/chat-com2/data/chat.sqlite3
backup_dir=/opt/padiem/com2-deploy/backup-20261103-purge
dest="$backup_dir/chat-before-purge.sqlite3"
if [[ ! -f "$src" ]]; then
  printf 'BACKUP_REFUSED=chat_db_missing\n' >&2
  exit 30
fi
if [[ -e "$dest" ]]; then
  printf 'BACKUP_REFUSED=destination_exists\n' >&2
  exit 31
fi
mkdir -p -m 700 "$backup_dir"
chmod 700 "$backup_dir"
SRC="$src" DEST="$dest" python3 - <<'PY'
import os
import sqlite3
src = os.environ["SRC"]
dest = os.environ["DEST"]
quoted = "'" + dest.replace("'", "''") + "'"
conn = sqlite3.connect(src, timeout=30)
try:
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("VACUUM INTO " + quoted)
finally:
    conn.close()
os.chmod(dest, 0o600)
check = sqlite3.connect("file:" + dest + "?mode=ro", uri=True)
try:
    integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
finally:
    check.close()
if integrity != "ok":
    raise SystemExit("BACKUP_VERIFY_FAILED")
print(f"BACKUP_OK path={dest} size={os.path.getsize(dest)} integrity={integrity}")
PY
