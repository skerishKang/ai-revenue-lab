#!/usr/bin/env bash
# Installs the PC queue backup script and its units. Never starts or enables
# anything, and never touches the queue database — the timer fires the script
# and the script itself reads the queue read-only (VACUUM INTO).
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
apply=0
while (($#)); do
  case "$1" in
    --apply) apply=1; shift ;;
    --dry-run) apply=0; shift ;;
    *) echo 'MESH_QUEUE_BACKUP_INSTALL=INVALID_ARGUMENT' >&2; exit 2 ;;
  esac
done
app=/opt/padiem/mesh-queue
unit=padiem-mesh-queue-backup.service
if (( ! apply )); then
  printf '%s\n' 'MESH_QUEUE_BACKUP_INSTALL=DRY_RUN' "APP_ROOT=$app" "SCRIPT=$app/backup.sh" \
    "UNIT=/etc/systemd/system/$unit" 'START_SERVICE=NO' 'ENABLE_SERVICE=NO' 'DB_TOUCHED=NO'
  exit 0
fi
fail() { echo "MESH_QUEUE_BACKUP_INSTALL=$1" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || fail ROOT_REQUIRED
# The script runs as the queue's own account; it must already exist on the
# host that runs the queue lane (this kit never creates accounts).
id padiem-mesh >/dev/null 2>&1 || fail QUEUE_ACCOUNT_MISSING
for required in "$here/backup.sh" "$here/$unit" "$here/padiem-mesh-queue-backup.timer"; do
  [[ -s "$required" ]] || fail SOURCE_MISSING
done
bash -n "$here/backup.sh" || fail BACKUP_SCRIPT_SYNTAX
install -d -m 0755 "$app"
install -o padiem-mesh -g padiem-mesh -m 0755 "$here/backup.sh" "$app/backup.sh"
install -m 0644 "$here/$unit" "/etc/systemd/system/$unit"
install -m 0644 "$here/padiem-mesh-queue-backup.timer" /etc/systemd/system/padiem-mesh-queue-backup.timer
systemctl daemon-reload
printf '%s\n' 'MESH_QUEUE_BACKUP_INSTALL=PASS' 'START_SERVICE=NO' 'ENABLE_SERVICE=NO' 'DB_TOUCHED=NO'
