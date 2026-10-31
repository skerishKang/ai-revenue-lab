#!/usr/bin/env bash
# Install the COM2 connector watch. Run as root on COM2 (WSL2).
#
# Refuses while the unit is active: replacing a running watch silently would make the
# next verdict look like it came from code nobody reviewed.
set -euo pipefail

APP_DIR=/opt/padiem/connector-watch
UNIT=padiem-connector-watch.service
TIMER=padiem-connector-watch.timer
STATE_DIR=/var/lib/padiem-connector-watch
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if systemctl is-active --quiet "${UNIT}"; then
  echo "refusing: ${UNIT} is active; stop it first" >&2
  exit 1
fi

id -u padiem-connector-watch >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin padiem-connector-watch
install -d -m 0750 -o padiem-connector-watch -g padiem-connector-watch "${APP_DIR}" "${STATE_DIR}"
install -m 0755 "${HERE}/connector_watch_host.py" "${APP_DIR}/connector_watch_host.py"
# The lane verdicts live once, in the GitHub-side watch module, and are installed
# beside the host script so both read the queue the same way.
install -m 0755 "${HERE}/../../../.github/scripts/connector_lane_watch.py" "${APP_DIR}/connector_lane_watch.py"
if [ ! -f "${APP_DIR}/.env" ]; then
  install -m 0600 -o padiem-connector-watch -g padiem-connector-watch "${HERE}/connector-watch.env.example" "${APP_DIR}/.env"
  echo "wrote ${APP_DIR}/.env from the example: fill the notifier names, then run this again"
fi
install -m 0644 "${HERE}/${UNIT}" "/etc/systemd/system/${UNIT}"
install -m 0644 "${HERE}/${TIMER}" "/etc/systemd/system/${TIMER}"
systemctl daemon-reload
systemctl enable --now "${TIMER}"
echo "installed; first run: systemctl start ${UNIT} && journalctl -u ${UNIT} -n 20"
