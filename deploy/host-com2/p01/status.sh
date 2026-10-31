#!/usr/bin/env bash
# Read-only P01 status: unit state, listener, loopback health. No root needed.
set -euo pipefail
app=/opt/padiem/p01
unit=padiem-p01.service

echo "P01_COM2_UNIT=$(systemctl is-active "$unit" 2>/dev/null || true)"
echo "P01_COM2_ENABLED=$(systemctl is-enabled "$unit" 2>/dev/null || true)"
if command -v ss >/dev/null 2>&1; then
  if ss -ltn 2>/dev/null | grep -qE '[:.]8811[[:space:]]'; then
    echo 'P01_COM2_LISTENER=127.0.0.1:8811'
  else
    echo 'P01_COM2_LISTENER=none'
  fi
else
  echo 'P01_COM2_LISTENER=unknown reason=ss_missing'
fi
systemctl --no-pager --full status "$unit" 2>/dev/null | sed -n '1,12p' || true
if [[ -x "$app/venv/bin/python" && -f "$app/health.py" ]]; then
  "$app/venv/bin/python" "$app/health.py" || true
else
  echo 'P01_COM2_HEALTH=UNKNOWN reason=app_not_installed'
fi
