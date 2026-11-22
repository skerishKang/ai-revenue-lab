#!/usr/bin/env bash
# Playwright 1.55 has no Ubuntu 26.04 headless shell download entry.
set -euo pipefail
source /etc/os-release
if [[ "$ID" == ubuntu && "$VERSION_ID" == 26.04 && "$(uname -m)" == x86_64 ]]; then
  echo 'PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64' >> "$GITHUB_ENV"
  echo 'Playwright: Ubuntu 26.04 x64 uses the Ubuntu 24.04 browser build'
fi
