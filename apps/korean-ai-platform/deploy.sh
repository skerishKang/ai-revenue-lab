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
