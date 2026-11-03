#!/usr/bin/env bash
set -euo pipefail
bash /opt/padiem/com2-deploy/ops/deploy/host-com2/cron/install-cron.sh --profile production --schedule '*-*-* 18:00:00' --dry-run
