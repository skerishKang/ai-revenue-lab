#!/usr/bin/env bash
set -euo pipefail
echo "IDENTITY_STAGING_UNIT=$(systemctl is-active padiem-identity-staging.service 2>/dev/null || true)"
systemctl --no-pager --full status padiem-identity-staging.service 2>/dev/null | sed -n '1,12p' || true
