#!/bin/bash
# #5881 follow-on — one verified daily copy of the PC queue database.
#
# `VACUUM INTO` is used instead of a file copy: it is a consistent snapshot taken
# inside SQLite, so a copy taken while the lane is claiming cannot capture a
# half-written page. The copy is opened and checked before the previous one is
# rotated, so a "backup" that cannot be opened is never allowed to replace a
# backup that could.
set -uo pipefail

DB="${MESH_QUEUE_DB_PATH:-/opt/padiem/mesh-queue/queue.sqlite3}"
DIR="${MESH_QUEUE_BACKUP_DIR:-/opt/padiem/backups/mesh-queue}"
KEEP="${MESH_QUEUE_BACKUP_KEEP:-7}"
STAMP=$(date -u +%Y%m%d-%H%M%S)
OUT="$DIR/queue-$STAMP.sqlite"

umask 077
mkdir -p "$DIR"
python3 - "$DB" "$OUT" <<'PY'
import sqlite3, sys
source, target = sys.argv[1], sys.argv[2]
connection = sqlite3.connect("file:%s?mode=ro" % source, uri=True)
try:
    connection.execute("VACUUM INTO ?", (target,))
finally:
    connection.close()
PY
if [ ! -s "$OUT" ]; then
  echo "MESH_QUEUE_BACKUP=FAILED reason=no-file"; exit 1
fi

python3 - "$OUT" <<'PY'
import sqlite3, sys
check = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
try:
    if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("MESH_QUEUE_BACKUP=FAILED reason=integrity")
    rows = {name: check.execute("SELECT COUNT(*) FROM %s" % name).fetchone()[0]
            for name in ("oracle_mesh_dispatch", "pc_device_links",
                        "pc_pairing_codes", "mesh_device_presence")}
finally:
    check.close()
print("MESH_QUEUE_BACKUP=OK file=%s rows=%s" % (sys.argv[1].split("/")[-1], rows))
PY
[ $? -eq 0 ] || exit 1

ls -1t "$DIR"/queue-*.sqlite 2>/dev/null | tail -n "+$((KEEP + 1))" | while read -r old; do
  rm -f "$old"
done
ls -1 "$DIR"/queue-*.sqlite 2>/dev/null | wc -l | sed 's/^/MESH_QUEUE_BACKUP_KEPT=/'
