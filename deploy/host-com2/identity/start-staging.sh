#!/usr/bin/env bash
set -euo pipefail
app=/opt/padiem/identity-staging
unit=padiem-identity-staging.service
fail() { echo "IDENTITY_STAGING_START=$1" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail ROOT_REQUIRED
[[ -f "/etc/systemd/system/$unit" && -f "$app/.env" ]] || fail NOT_INSTALLED
command -v ss >/dev/null 2>&1 || fail SS_REQUIRED
systemctl is-active --quiet "$unit" && { echo 'IDENTITY_STAGING_START=ALREADY_ACTIVE'; exit 0; }
ss -ltn | grep -qE '[:.]8802[[:space:]]' && fail PORT_IN_USE
set -a
source "$app/.env"
set +a
runuser -u padiem-identity-staging -m -- "$app/venv/bin/python" "$app/check_config.py" >/dev/null || fail CONFIG_NOT_READY
systemctl start "$unit"
systemctl is-active --quiet "$unit" || fail NOT_ACTIVE
echo 'IDENTITY_STAGING_START=PASS PORT=8802'
