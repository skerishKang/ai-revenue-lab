#!/usr/bin/env bash
# Install the pc_read latency monitor on COM2 (WSL). Run from the repository:
#   bash deploy/host-com2/pc-read-metrics/install.sh
# It copies the probe and cycle script under /opt/padiem/pc-read-metrics,
# installs the systemd service+timer and enables the 30-minute schedule.
# It never prints, creates or rewrites token values: comp1.token and
# paths.json must already exist under /opt/padiem/com2-secrets/pc-read-metrics.
# comp2.token is optional: when it is absent the timer still measures COM1 and
# skips COM2 only (the probe logs PC_READ_METRICS WARN device=comp2
# reason=token_missing to the journal). Place the token and re-run this script
# to start measuring COM2. See the 비공개 운영 기록(거버넌스 폴더, 같은 상대
# 경로), PC_READ_LATENCY_MONITOR_261109.md.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../.." && pwd)
secret_dir=/opt/padiem/com2-secrets/pc-read-metrics
target=/opt/padiem/pc-read-metrics

if [ "$(id -u)" != "0" ]; then
  echo "install: must run as root (wsl.exe -d Ubuntu -u root --exec bash)" >&2
  exit 2
fi
for required in comp1.token paths.json; do
  if [ ! -s "$secret_dir/$required" ]; then
    echo "install: missing $secret_dir/$required (place it yourself; values are never handled by this script)" >&2
    exit 3
  fi
done
if [ ! -s "$secret_dir/comp2.token" ]; then
  echo "install: $secret_dir/comp2.token missing; the timer will measure COM1 and skip COM2 only (place it and re-run to include COM2)" >&2
fi
chmod 700 "$secret_dir"
chmod 600 "$secret_dir"/*.token "$secret_dir/paths.json"

mkdir -p "$target" /var/lib/padiem-pc-read-metrics
install -m 755 "$repo/scripts/ops/pc_read_measure.py" "$target/pc_read_measure.py"
install -m 755 "$here/run_cycle.sh" "$target/run_cycle.sh"

install -m 644 "$here/padiem-pc-read-metrics.service" /etc/systemd/system/padiem-pc-read-metrics.service
install -m 644 "$here/padiem-pc-read-metrics.timer" /etc/systemd/system/padiem-pc-read-metrics.timer
systemctl daemon-reload
systemctl enable --now padiem-pc-read-metrics.timer

echo "install: probe installed at $target/pc_read_measure.py"
echo "install: store at /var/lib/padiem-pc-read-metrics/metrics.jsonl (7-day retention)"
systemctl list-timers padiem-pc-read-metrics.timer --no-pager | head -3
