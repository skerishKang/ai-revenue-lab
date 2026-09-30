#!/usr/bin/env bash
#
# Build + deploy script for ai-revenue-korean-ai-platform Worker.
#
# Usage:
#   ./deploy.sh [--dry-run]
#
# This script is the single source of truth for Workers Builds.
# It produces a bundle under the free 3 MiB limit.
#
set -euo pipefail

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "[DRY RUN]"
fi

cd "$(dirname "$0")"

echo "==> uv sync --frozen"
uv sync --frozen

# Stage the single reviewed #3212 B66 extraction authority into this Worker
# project so pywrangler can bundle it without committing a duplicate copy.
B66_AUTHORITY_SOURCE="../b66-quote-adapter/app/extraction_routing.py"
B66_STAGED_MODULE="b66_extraction_routing.py"
cleanup_b66_stage() {
    rm -f "${B66_STAGED_MODULE}"
}
trap cleanup_b66_stage EXIT
test -f "${B66_AUTHORITY_SOURCE}"
cp "${B66_AUTHORITY_SOURCE}" "${B66_STAGED_MODULE}"
echo "B66_EXTRACTION_AUTHORITY_STAGED=YES"

echo "==> pywrangler sync"
uv run pywrangler sync --force

echo "==> Removing pywrangler-generated venvs (not needed at runtime)"
rm -rf .venv .venv-workers

echo "==> Deploying"
if $DRY_RUN; then
    npx wrangler deploy --dry-run --name ai-revenue-korean-ai-platform
else
    npx wrangler deploy --name ai-revenue-korean-ai-platform
fi
