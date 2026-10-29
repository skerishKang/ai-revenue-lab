#!/usr/bin/env bash
# Installs only the offsite-backup package/units. Never starts or enables, and
# never creates or reads the encryption key — that is an operator step.
set -euo pipefail
umask 077
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source_root=$(cd -- "$here/../../.." && pwd)
apply=0
while (($#)); do
  case "$1" in
    --apply) apply=1; shift ;;
    --dry-run) apply=0; shift ;;
    --source-root) source_root=${2:?source root required}; shift 2 ;;
    *) echo 'OFFSITE_INSTALL=INVALID_ARGUMENT' >&2; exit 2 ;;
  esac
done
app=/opt/padiem/offsite-backup
unit=padiem-offsite-backup.service
if (( ! apply )); then
  printf '%s\n' 'OFFSITE_INSTALL=DRY_RUN' "APP_ROOT=$app" "UNIT=$unit" 'START_SERVICE=NO' 'ENABLE_SERVICE=NO' 'KEY_CREATED=NO' 'TUNNEL_CHANGE=NO'
  exit 0
fi
fail() { echo "OFFSITE_INSTALL=$1" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || fail ROOT_REQUIRED
for required in \
  deploy/host-com2/offsite-backup/offsite.py \
  scripts/ops/com2_backup.py \
  scripts/ops/com2_backup.py; do
  [[ -e "$source_root/$required" ]] || fail SOURCE_MISSING
done
[[ -s /etc/padiem/offsite-backup.key ]] || fail KEY_FILE_MISSING
[[ "$(stat -c %a /etc/padiem/offsite-backup.key 2>/dev/null || echo '')" == "600" ]] || fail KEY_FILE_NOT_0600
if systemctl is-active --quiet "$unit"; then fail STOP_SERVICE_BEFORE_UPDATE; fi
install -d -m 0755 "$app"
install -d -m 0700 /var/lib/padiem-offsite-backup
if [[ ! -x "$app/venv/bin/python" ]]; then (umask 022; python3 -m venv "$app/venv"); fi
(umask 022; "$app/venv/bin/python" -m pip --isolated install --index-url https://pypi.org/simple --disable-pip-version-check --require-hashes -r "$here/requirements.txt")
install -m 0755 "$here/offsite.py" "$app/offsite.py"
# Reuse the reviewed envelope helpers instead of a drifting copy.
ln -sfn "$source_root/scripts/ops/com2_backup.py" "$app/com2_backup.py"
if [[ ! -e /etc/padiem/offsite-backup.env ]]; then
  install -m 0600 "$here/offsite-backup.env.example" /etc/padiem/offsite-backup.env
fi
chown root:root /etc/padiem/offsite-backup.env
chmod 0600 /etc/padiem/offsite-backup.env
if ! "$app/venv/bin/python" -c \
  "import importlib.util, sys; sys.path.insert(0, '$app'); spec=importlib.util.spec_from_file_location('com2_backup_crypto', '$app/com2_backup.py'); m=importlib.util.module_from_spec(spec); sys.modules['com2_backup_crypto']=m; spec.loader.exec_module(m); m.parse_encryption_key('ab'*32)" >/dev/null 2>&1; then
  fail CRYPTO_IMPORT_FAILED
fi
install -m 0644 "$here/$unit" "/etc/systemd/system/$unit"
install -m 0644 "$here/padiem-offsite-backup.timer" /etc/systemd/system/padiem-offsite-backup.timer
systemctl daemon-reload
printf '%s\n' 'OFFSITE_INSTALL=PASS' 'START_SERVICE=NO' 'ENABLE_SERVICE=NO' 'KEY_CREATED=NO' 'TUNNEL_CHANGE=NO'
