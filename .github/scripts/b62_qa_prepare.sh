#!/usr/bin/env bash
# Self-hosted browser QA preparation: share only external Playwright browsers.
# Repository packages are always installed by each job into its own checkout
# venv, so one PR's source can never leak into another PR's test environment.
set -euo pipefail

version='1.55.0'
base="${HOME}/.cache/b62-qa"
mkdir -p "$base"
browsers="${base}/ms-playwright-${version}"
lock="${base}/ms-playwright-${version}.lock"

exec 9>"$lock"
flock -x 9
if [[ -d "$browsers" ]]; then
  echo "B62_QA_BROWSER_REUSE=YES VERSION=${version}"
else
  echo "B62_QA_BROWSER_REUSE=NO VERSION=${version}"
  PLAYWRIGHT_BROWSERS_PATH="$browsers" \
    uvx --from "playwright==${version}" playwright install --only-shell chromium
fi

{
  echo "PLAYWRIGHT_BROWSERS_PATH=${browsers}"
  echo "B62_QA_BROWSER_VERSION=${version}"
} >> "${GITHUB_ENV}"
echo 'B62_QA_PREP_REUSE=PASS'
