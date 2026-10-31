#!/usr/bin/env bash
set -euo pipefail
echo "BROKER_STAGING_UNIT=$(systemctl is-active padiem-broker-staging.service 2>/dev/null || true)"
systemctl --no-pager --full status padiem-broker-staging.service 2>/dev/null | sed -n '1,12p' || true
