#!/usr/bin/env bash
# Installs only the padiem-broker package/units. Never starts or enables.
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
    *) echo 'BROKER_INSTALL=INVALID_ARGUMENT' >&2; exit 2 ;;
  esac
done
app=/opt/padiem/broker
data=/mnt/d/padiem/broker
unit=padiem-broker.service
if (( ! apply )); then
  printf '%s\n' 'BROKER_INSTALL=DRY_RUN' "APP_ROOT=$app" "DATA_ROOT=$data" "UNIT=$unit" 'START_SERVICE=NO' 'ENABLE_SERVICE=NO' 'TUNNEL_CHANGE=NO'
  exit 0
fi
fail() { echo "BROKER_INSTALL=$1" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || fail ROOT_REQUIRED
for required in \
  apps/padiem-broker/service.py \
  apps/padiem-broker/storage.py \
  packages/padiem-control-plane/local_agent_broker_worker.py \
  packages/padiem-control-plane/internal_rpc_ingress.py \
  packages/padiem-control-plane/padiem_control_plane; do
  [[ -e "$source_root/$required" ]] || fail SOURCE_MISSING
done
mountpoint -q /mnt/d || fail HDD_NOT_MOUNTED
if systemctl is-active --quiet "$unit"; then fail STOP_BROKER_BEFORE_UPDATE; fi
install -d -m 0755 "$app"
if ! getent passwd padiem-broker >/dev/null; then
  useradd --system --user-group --home-dir "$app" --shell /usr/sbin/nologin padiem-broker
fi
install -d -m 0700 -o padiem-broker -g padiem-broker "$data"
if [[ ! -x "$app/venv/bin/python" ]]; then (umask 022; python3 -m venv "$app/venv"); fi
(umask 022; "$app/venv/bin/python" -m pip --isolated install --index-url https://pypi.org/simple --disable-pip-version-check --require-hashes -r "$here/requirements.txt")
install -m 0644 "$source_root/apps/padiem-broker/service.py" "$app/service.py"
install -m 0644 "$source_root/apps/padiem-broker/storage.py" "$app/storage.py"
# Single-source modules: the service imports THIS checkout's broker code, not a copy.
ln -sfn "$source_root/packages/padiem-control-plane" "$app/src"
install -m 0644 "$here/check_config.py" "$app/check_config.py"
install -m 0755 "$here/health.py" "$app/health.py"
install -m 0700 "$here/backup.py" "$app/backup.py"
install -m 0700 "$here/provision_secrets.sh" "$app/provision_secrets.sh"
if [[ ! -e "$app/.env" ]]; then install -m 0600 "$here/.env.example" "$app/.env"; fi
chown root:root "$app/.env"
chmod 0600 "$app/.env"
if ! runuser -u padiem-broker -- env "PADIEM_BROKER_DB_PATH=$data/broker.sqlite3" "$app/venv/bin/python" -c \
  "import os, pathlib, tempfile, uvicorn, starlette; fd, name=tempfile.mkstemp(dir=os.path.dirname(os.environ['PADIEM_BROKER_DB_PATH'])); os.close(fd); pathlib.Path(name).unlink()" >/dev/null 2>&1; then
  fail RUNTIME_OR_HDD_PERMISSION_FAILED
fi
if ! (cd "$app" && runuser -u padiem-broker -- env PYTHONPATH="$app:$app/src" "$app/venv/bin/python" -c \
  "import storage, service; from internal_rpc_ingress import handle_internal_rpc"); then
  fail SERVICE_IMPORT_FAILED
fi
for unit_file in padiem-broker.service padiem-broker-health.service padiem-broker-health.timer padiem-broker-backup.service padiem-broker-backup.timer; do
  install -m 0644 "$here/$unit_file" "/etc/systemd/system/$unit_file"
done
systemctl daemon-reload
printf '%s\n' 'BROKER_INSTALL=PASS' 'START_SERVICE=NO' 'ENABLE_SERVICE=NO' 'TUNNEL_CHANGE=NO'
