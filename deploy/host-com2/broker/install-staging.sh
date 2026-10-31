#!/usr/bin/env bash
set -euo pipefail
umask 077
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source_root=$(cd -- "$here/../../.." && pwd)
apply=0
while (($#)); do
  case "$1" in
    --apply) apply=1; shift ;;
    --dry-run) apply=0; shift ;;
    --source-root) source_root=${2:?}; shift 2 ;;
    *) echo 'BROKER_STAGING_INSTALL=INVALID_ARGUMENT' >&2; exit 2 ;;
  esac
done
app=/opt/padiem/broker-staging
data=/mnt/d/padiem/broker-staging
unit=padiem-broker-staging.service
user=padiem-broker-staging
if (( ! apply )); then
  printf '%s\n' 'BROKER_STAGING_INSTALL=DRY_RUN' "APP_ROOT=$app" "DATA_ROOT=$data" 'START_SERVICE=NO' 'ENABLE_SERVICE=NO'
  exit 0
fi
fail() { echo "BROKER_STAGING_INSTALL=$1" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail ROOT_REQUIRED
for required in apps/padiem-broker/storage.py apps/padiem-broker/deploy/requirements.txt packages/padiem-control-plane/com2_identity_entrypoint.py apps/padiem-identity/authority_factory.py; do
  [[ -e "$source_root/$required" ]] || fail SOURCE_MISSING
done
mountpoint -q /mnt/d || fail HDD_NOT_MOUNTED
systemctl is-active --quiet "$unit" && fail STOP_STAGING_BEFORE_UPDATE
install -d -m 0755 "$app"
getent passwd "$user" >/dev/null || useradd --system --user-group --home-dir "$app" --shell /usr/sbin/nologin "$user"
install -d -m 0700 -o "$user" -g "$user" "$data"
if [[ ! -x "$app/venv/bin/python" ]]; then (umask 022; python3 -m venv "$app/venv"); fi
"$app/venv/bin/python" -m pip --isolated install --index-url https://pypi.org/simple --disable-pip-version-check --require-hashes -r "$source_root/apps/padiem-broker/deploy/requirements.txt"
ln -sfn "$source_root/packages/padiem-control-plane" "$app/src"
install -m 0644 "$source_root/apps/padiem-broker/service.py" "$app/service.py"
install -m 0644 "$source_root/apps/padiem-broker/storage.py" "$app/storage.py"
install -m 0644 "$source_root/apps/padiem-broker/pc_offer_asgi.py" "$app/pc_offer_asgi.py"
install -m 0644 "$here/check_config.py" "$app/check_config.py"
if [[ ! -e "$app/.env" ]]; then install -m 0600 "$here/broker.env.example" "$app/.env"; fi
chown root:root "$app/.env"
chmod 0600 "$app/.env"
sed -i 's/\r$//' "$app/.env"
# Verify the separately provisioned pepper as the service user before registering the unit.
set -a
source "$app/.env"
set +a
runuser -u "$user" -m -- "$app/venv/bin/python" "$app/check_config.py" --pepper-only >/dev/null || fail PEPPER_NOT_READY
install -m 0644 "$here/$unit" "/etc/systemd/system/$unit"
for action in start stop status; do install -m 0755 "$here/$action-staging.sh" "$app/$action-staging.sh"; done
systemctl daemon-reload
printf '%s\n' 'BROKER_STAGING_INSTALL=PASS' 'START_SERVICE=NO' 'ENABLE_SERVICE=NO'
