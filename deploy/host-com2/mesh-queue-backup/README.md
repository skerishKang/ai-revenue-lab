# mesh-queue-backup kit — one verified daily copy of the PC queue database

The script the #5881 PC dispatch queue relies on (`/opt/padiem/mesh-queue/backup.sh`,
`padiem-mesh-queue-backup.service` + `.timer`, OnCalendar 04:35) existed only on
the COM2 host. The 2026-11-02..04 restore/relink window left that script absent
for three scheduled runs (systemd 203/EXEC), which in turn made the offsite
uploader fail closed with `REASON=backup_stale`. This kit puts the script and
its units under version control so a queue reinstall or restore lays them down
together with the code.

## Files

| File | Purpose |
| --- | --- |
| `backup.sh` | the host script, verbatim: `VACUUM INTO` snapshot, integrity check, 7-copy rotation; configuration comes only from `MESH_QUEUE_DB_PATH` / `MESH_QUEUE_BACKUP_DIR` / `MESH_QUEUE_BACKUP_KEEP` |
| `padiem-mesh-queue-backup.service` | oneshot, `User=padiem-mesh`, runs the script |
| `padiem-mesh-queue-backup.timer` | `OnCalendar=04:35`, `Persistent=true`, ±180 s jitter |
| `install.sh` | dry-run by default; `--apply` copies script (0755, padiem-mesh) + units and reloads systemd — never starts or enables, never touches the database |

No secrets: the script and units carry only the three environment variable
names above; the database itself is read through SQLite read-only mode.

## Restore / reinstall checklist (the line that was missing)

**백업 스크립트 존재와 실행 권한 확인** — after any queue restore, relink or
reinstall, verify before the 04:35 timer fires:

```bash
test -x /opt/padiem/mesh-queue/backup.sh && echo OK || \
  bash deploy/host-com2/mesh-queue-backup/install.sh --apply
```

2026-11-02..04 lesson: a relink that restores `queue.sqlite3` but not this
script leaves the queue without a backup for days, and the offsite uploader
correctly refuses to ship a stale one.
