#!/usr/bin/env bash
# Stages the COM2 P01 Engine package and unit (CTO decision 2026-10-31: Linux,
# loopback 8811). Written for the authorized COM2 operator, never by CI.
#
# It never starts, enables, restarts or reloads the service (daemon-reload only
# with --reload), never touches the Windows 18731 release, and never edits the
# Chat host's environment — the Chat-side origin belongs to deploy/host-com2/chat.
#
#   bash install.sh              print decisions, write nothing (default)
#   bash install.sh --dry-run    same
#   bash install.sh --apply      stage unit, helper scripts and an env stub
#   bash install.sh --apply --reload   also systemctl daemon-reload (no start)
set -euo pipefail
umask 077

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source_root=$(cd -- "$here/../../.." && pwd)
app=/opt/padiem/p01
unit=padiem-p01.service
unit_target=/etc/systemd/system/$unit
apply=0
reload=0

while (($#)); do
  case "$1" in
    --apply) apply=1; shift ;;
    --dry-run) apply=0; shift ;;
    --reload) reload=1; shift ;;
    --source-root) source_root=${2:?source root required}; shift 2 ;;
    *) echo 'P01_COM2_INSTALL=INVALID_ARGUMENT' >&2; exit 2 ;;
  esac
done

if (( ! apply )); then
  printf '%s\n' \
    'P01_COM2_INSTALL=DRY_RUN' \
    "APP_ROOT=$app" \
    "UNIT=$unit_target" \
    'BIND=127.0.0.1' \
    'PORT=8811' \
    'START_SERVICE=NO' \
    'ENABLE_SERVICE=NO' \
    'TUNNEL_CHANGE=NO' \
    'CHAT_ENV_CHANGE=NO'
  exit 0
fi

fail() { echo "P01_COM2_INSTALL=$1" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || fail ROOT_REQUIRED
command -v systemctl >/dev/null 2>&1 || fail SYSTEMD_MISSING
[[ -d "$app" ]] || fail APP_ROOT_MISSING
# Refuse an incomplete source before replacing any existing release.
[[ -f "$source_root/apps/padiem-ai-engine/asgi.py" ]] || fail ASGI_ENTRY_MISSING
for item in app clients ingress migrations asgi.py worker.py worker_identity.py; do
  [[ -e "$source_root/apps/padiem-ai-engine/$item" ]] || fail SOURCE_MISSING
done
# Replacing code while the service is active would change a live process.
if systemctl is-active --quiet "$unit"; then fail STOP_P01_BEFORE_UPDATE; fi
[[ -x "$app/venv/bin/python" ]] || fail VENV_PYTHON_MISSING
if [[ -e "$unit_target" ]] && ! cmp -s "$here/padiem-p01.service.example" "$unit_target"; then
  # A foreign unit is the operator's decision, not something to overwrite.
  fail FOREIGN_UNIT_TARGET
fi

bash "$here/stage_code.sh" "$source_root" "$app"
[[ -f "$app/app/asgi.py" ]] || fail ASGI_ENTRY_MISSING

if ! getent passwd padiem-p01 >/dev/null; then
  useradd --system --user-group --home-dir "$app" --shell /usr/sbin/nologin padiem-p01
fi
install -d -o root -g root -m 0700 "$app/env"
install -d -o padiem-p01 -g padiem-p01 -m 0700 "$app/data" "$app/logs"
install -o root -g root -m 0644 "$here/check_config.py" "$app/check_config.py"
install -o root -g root -m 0755 "$here/health.py" "$app/health.py"
install -o root -g root -m 0755 "$here/start.sh" "$app/start.sh"
install -o root -g root -m 0755 "$here/stop.sh" "$app/stop.sh"
install -o root -g root -m 0755 "$here/status.sh" "$app/status.sh"
if [[ ! -e "$app/env/p01.env" ]]; then
  install -o root -g root -m 0600 "$here/p01.env.example" "$app/env/p01.env"
fi
install -o root -g root -m 0644 "$here/padiem-p01.service.example" "$unit_target"

if (( reload )); then
  systemctl daemon-reload
fi

# State is reported, never changed.
printf '%s\n' \
  'P01_COM2_INSTALL=STAGED' \
  "UNIT=$unit_target" \
  "UNIT_STATE=$(systemctl is-enabled "$unit" 2>/dev/null || echo unknown)" \
  "UNIT_ACTIVE=$(systemctl is-active "$unit" 2>/dev/null || echo unknown)" \
  'START_SERVICE=NO' \
  'ENABLE_SERVICE=NO' \
  'CREDENTIAL_WRITTEN=NO' \
  'CHAT_ENV_CHANGE=NO'
