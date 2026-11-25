#!/usr/bin/env bash
# Reuse a self-hosted Chat QA environment keyed by the locked dependency hash.
# Hosted runners keep the existing per-job setup; this script only runs when
# runner.environment == 'self-hosted'.
set -euo pipefail

repo_root="${GITHUB_WORKSPACE:-$(pwd)}"
lock="${repo_root}/apps/padiem-chat/uv.lock"
test -f "$lock"
hash="$(sha256sum "$lock" | cut -d' ' -f1)"
cache_root="${HOME}/.cache/b62-qa/${hash}"
venv="${cache_root}/venv"
browsers="${cache_root}/ms-playwright"
marker="${cache_root}/ready"

# Two runner processes share this host and can hit the same cold cache.
# Serialize creation so a concurrent sync cannot leave a half-written venv.
exec 9>"${cache_root}.lock"
flock -x 9
if [[ -f "$marker" && -x "${venv}/bin/python" && -d "$browsers" ]] \
   && grep -qx "$hash" "$marker"; then
  echo "B62_QA_ENV_REUSE=YES HASH=${hash:0:12}"
else
  echo "B62_QA_ENV_REUSE=NO HASH=${hash:0:12}"
  mkdir -p "$cache_root"
  rm -rf "$venv"
  UV_PROJECT_ENVIRONMENT="$venv" uv sync --locked --project "${repo_root}/apps/padiem-chat" --extra dev
  # The Chat uv.lock does not pin Playwright; the workflow installs it pinned.
  uv pip install --python "${venv}/bin/python" 'playwright==1.55.0'
  PLAYWRIGHT_BROWSERS_PATH="$browsers" UV_PROJECT_ENVIRONMENT="$venv" \
    uv run --project "${repo_root}/apps/padiem-chat" --locked --no-sync \
    python -m playwright install --only-shell chromium
  printf '%s\n' "$hash" > "$marker"
fi

{
  echo "UV_PROJECT_ENVIRONMENT=${venv}"
  # The shared environment is already locked and installed; concurrent jobs
  # must not re-sync it while another job is using it.
  echo "UV_NO_SYNC=1"
  echo "PLAYWRIGHT_BROWSERS_PATH=${browsers}"
  echo "B62_QA_ENV_HASH=${hash}"
} >> "${GITHUB_ENV}"
echo 'B62_QA_PREP_REUSE=PASS'
