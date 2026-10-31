#!/usr/bin/env bash
# Installs the WSL-side boot self-check. Never starts or enables; Windows-side
# task registration and the enable step are Qoder steps (see the runbook).
set -euo pipefail
umask 077
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
apply=0
while (($#)); do
  case "$1" in
    --apply) apply=1; shift ;;
    --dry-run) apply=0; shift ;;
    *) echo 'BOOT_RECOVERY_INSTALL=INVALID_ARGUMENT' >&2; exit 2 ;;
  esac
done
app=/opt/padiem/boot-recovery
unit=padiem-boot-recovery.service
if (( ! apply )); then
  printf '%s\n' 'BOOT_RECOVERY_INSTALL=DRY_RUN' "APP_ROOT=$app" "UNIT=$unit" 'START_SERVICE=NO' 'ENABLE_SERVICE=NO' 'WINDOWS_TASK_CHANGE=NO'
  exit 0
fi
fail() { echo "BOOT_RECOVERY_INSTALL=$1" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || fail ROOT_REQUIRED
[[ -f "$here/wsl/boot_recovery.py" ]] || fail SOURCE_MISSING
if systemctl is-active --quiet "$unit"; then fail STOP_UNIT_BEFORE_UPDATE; fi
install -d -m 0755 "$app"
install -m 0755 "$here/wsl/boot_recovery.py" "$app/boot_recovery.py"
install -m 0755 "$here/wsl/boot-recovery.sh" "$app/boot-recovery.sh"
if [[ ! -e "$app/.env" ]]; then install -m 0600 "$here/wsl/boot-recovery.env.example" "$app/.env"; fi
chmod 0600 "$app/.env"
if [[ ! -e "$app/units.json" ]]; then install -m 0644 "$here/wsl/units.json.example" "$app/units.json"; fi
install -d -m 0700 /var/lib/padiem/boot-recovery
if ! /usr/bin/python3 "$app/boot_recovery.py" check --wait-seconds 0 >/dev/null 2>&1; then
  # A failing check at install time is information, not an install error; the
  # report itself is kept for Qoder.
  echo 'BOOT_RECOVERY_INSTALL_PRECHECK=FAIL (see /var/lib/padiem/boot-recovery/last.json)'
fi
install -m 0644 "$here/wsl/$unit" "/etc/systemd/system/$unit"
systemctl daemon-reload
printf '%s\n' 'BOOT_RECOVERY_INSTALL=PASS' 'START_SERVICE=NO' 'ENABLE_SERVICE=YES_REQUIRED_BY_QODER' 'WINDOWS_TASK_CHANGE=NO'
