#!/usr/bin/env bash
# Starts the COM2 P01 Engine unit only. Never enables it, never reloads it,
# never touches the Windows 18731 release or any tunnel.
set -euo pipefail
app=/opt/padiem/p01
unit=padiem-p01.service
fail() { echo "P01_COM2_START=$1" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || fail ROOT_REQUIRED
[[ -f "/etc/systemd/system/$unit" ]] || fail UNIT_NOT_INSTALLED
[[ -f "$app/env/p01.env" ]] || fail ENV_MISSING
[[ -x "$app/venv/bin/python" ]] || fail VENV_PYTHON_MISSING
if systemctl is-active --quiet "$unit"; then
  echo 'P01_COM2_START=ALREADY_ACTIVE PORT=8811'
  exit 0
fi
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -qE '[:.]8811[[:space:]]'; then
  fail PORT_8811_IN_USE
fi

set -a
# shellcheck disable=SC1091
source "$app/env/p01.env"
set +a
runuser -u padiem-p01 -m -- "$app/venv/bin/python" "$app/check_config.py" \
  --app-root "$app" >/dev/null || fail CONFIG_NOT_READY

systemctl start "$unit"
if ! systemctl is-active --quiet "$unit"; then
  systemctl --no-pager --full status "$unit" >&2 || true
  fail NOT_ACTIVE
fi
for _ in $(seq 1 30); do
  if "$app/venv/bin/python" "$app/health.py" >/dev/null 2>&1; then
    "$app/venv/bin/python" "$app/health.py"
    echo 'P01_COM2_START=PASS PORT=8811'
    exit 0
  fi
  sleep 2
done
"$app/venv/bin/python" "$app/health.py" || fail HEALTH_FAILED
echo 'P01_COM2_START=PASS PORT=8811'
