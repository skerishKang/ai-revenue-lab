#!/usr/bin/env bash
# Installs the uniform auto-restart drop-in for COM2 services (#4953 A).
# DRY-RUN by default. It never starts, restarts, stops or enables a unit; a
# drop-in takes effect on that unit's next (re)start, and a running service
# keeps its current policy until then.
set -euo pipefail
umask 022
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
apply=0
while (($#)); do
  case "$1" in
    --apply) apply=1; shift ;;
    --dry-run) apply=0; shift ;;
    *) echo 'RESTART_POLICY=INVALID_ARGUMENT' >&2; exit 2 ;;
  esac
done
dropin=padiem-restart.conf
units_file=$here/units.txt
[[ -f "$units_file" ]] || { echo 'RESTART_POLICY=FAIL reason=units_missing' >&2; exit 3; }

mapfile -t units < <(grep -vE '^\s*(#|$)' "$units_file")
(( ${#units[@]} > 0 )) || { echo 'RESTART_POLICY=FAIL reason=units_empty' >&2; exit 3; }

if (( ! apply )); then
  printf '%s\n' 'RESTART_POLICY=DRY_RUN' "DROP_IN=$here/10-padiem-restart.conf"
  for unit in "${units[@]}"; do
    printf 'UNIT=%s TARGET=/etc/systemd/system/%s.d/%s\n' "$unit" "$unit" "$dropin"
  done
  printf '%s\n' 'START_SERVICE=NO' 'RESTART_SERVICE=NO' 'ENABLE_SERVICE=NO'
  exit 0
fi

[[ ${EUID} -eq 0 ]] || { echo 'RESTART_POLICY=FAIL reason=root_required' >&2; exit 3; }
applied=0
skipped=0
for unit in "${units[@]}"; do
  if ! systemctl cat "$unit" >/dev/null 2>&1; then
    echo "UNIT=$unit SKIPPED_MISSING"
    skipped=$((skipped + 1))
    continue
  fi
  target_dir="/etc/systemd/system/$unit.d"
  install -d -m 0755 "$target_dir"
  install -m 0644 "$here/10-padiem-restart.conf" "$target_dir/$dropin"
  echo "UNIT=$unit APPLIED"
  applied=$((applied + 1))
done
if (( applied > 0 )); then
  systemctl daemon-reload
fi
printf 'RESTART_POLICY=PASS APPLIED=%d SKIPPED=%d\n' "$applied" "$skipped"
printf '%s\n' 'START_SERVICE=NO' 'RESTART_SERVICE=NO' 'ENABLE_SERVICE=NO'
echo 'VERIFY=systemctl show -p Restart -p RestartUSec <unit>'
