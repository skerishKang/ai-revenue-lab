#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'IDENTITY_STAGING_STOP=ROOT_REQUIRED' >&2; exit 1; }
systemctl stop padiem-identity-staging.service
echo 'IDENTITY_STAGING_STOP=PASS'
