#!/usr/bin/env bash
# Installs only the file-lane package/unit. Never starts/enables any service.
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
    *) echo 'FILE_LANE_INSTALL=INVALID_ARGUMENT' >&2; exit 2 ;;
  esac
done
app=/opt/padiem/file-lane
data=/mnt/d/padiem/file-lane
unit=padiem-file-lane.service
if (( ! apply )); then
  printf '%s\n' 'FILE_LANE_INSTALL=DRY_RUN' "APP_ROOT=$app" "DATA_ROOT=$data" "UNIT=$unit" 'START_SERVICE=NO' 'ENABLE_SERVICE=NO' 'TUNNEL_CHANGE=NO'
  exit 0
fi
fail() { echo "FILE_LANE_INSTALL=$1" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || fail ROOT_REQUIRED
[[ -f "$source_root/apps/padiem-file-lane/pyproject.toml" ]] || fail SOURCE_MISSING
mountpoint -q /mnt/d || fail HDD_NOT_MOUNTED
if systemctl is-active --quiet "$unit"; then fail STOP_FILE_LANE_BEFORE_UPDATE; fi
if ! command -v soffice >/dev/null 2>&1; then
  DEBIAN_FRONTEND=noninteractive apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends libreoffice-calc
fi
command -v soffice >/dev/null 2>&1 || fail LIBREOFFICE_UNAVAILABLE
install -d -m 0755 "$app"
if ! getent passwd padiem-file-lane >/dev/null; then
  useradd --system --user-group --home-dir "$app" --shell /usr/sbin/nologin padiem-file-lane
fi
install -d -m 0700 -o padiem-file-lane -g padiem-file-lane "$data"
if [[ ! -x "$app/venv/bin/python" ]]; then (umask 022; python3 -m venv "$app/venv"); fi
(umask 022; "$app/venv/bin/python" -m pip --isolated install --index-url https://pypi.org/simple --disable-pip-version-check --require-hashes -r "$here/requirements.txt")
(umask 022; "$app/venv/bin/python" -m pip --isolated install --index-url https://pypi.org/simple --disable-pip-version-check --no-deps "$source_root/packages/padiem-ai-core" "$source_root/apps/padiem-file-lane")
install -m 0644 "$here/check_config.py" "$app/check_config.py"
install -m 0755 "$here/health.py" "$app/health.py"
if [[ ! -e "$app/.env" ]]; then install -m 0600 "$here/.env.example" "$app/.env"; fi
chown root:root "$app/.env"
chmod 0600 "$app/.env"
# DrvFS/NTFS permissions are host-specific. Prove this service identity can
# create/remove a private probe, rather than claiming chmod alone is enough.
if ! runuser -u padiem-file-lane -- "$app/venv/bin/python" -c 'import os, pathlib, tempfile, padiem_file_lane, uvicorn, pypdf, openpyxl, padiem_ai_core; fd, name=tempfile.mkstemp(dir="/mnt/d/padiem/file-lane"); os.close(fd); pathlib.Path(name).unlink()' >/dev/null 2>&1; then
  fail RUNTIME_OR_HDD_PERMISSION_FAILED
fi
install -m 0644 "$here/$unit" "/etc/systemd/system/$unit"
systemctl daemon-reload
printf '%s\n' 'FILE_LANE_INSTALL=PASS' 'START_SERVICE=NO' 'ENABLE_SERVICE=NO' 'TUNNEL_CHANGE=NO'
