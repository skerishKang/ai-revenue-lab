#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'BROKER_STAGING_STOP=ROOT_REQUIRED' >&2; exit 1; }
systemctl stop padiem-broker-staging.service
echo 'BROKER_STAGING_STOP=PASS'
