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

# Stage the reviewed B66 authorities into this Worker project so
# pywrangler can bundle them without committing duplicate implementations.
B66_EXTRACTION_SOURCE="../b66-quote-adapter/app/extraction_routing.py"
B66_EXTRACTION_STAGED="app/b66_extraction_routing.py"
B66_INTAKE_SOURCE="../b66-quote-adapter/app/file_intake.py"
B66_INTAKE_STAGED="app/b66_file_intake.py"
CORE_SOURCE="../../packages/padiem-ai-core/padiem_ai_core"
CORE_STAGED="padiem_ai_core"
# #6828: the private-registry switch imports padiem_control_plane.models_registry at
# boot. The bundle and the host tree resolve it the same way: a package directory
# beside the app, not a host PYTHONPATH.
CONTROL_PLANE_SOURCE="../../packages/padiem-control-plane/padiem_control_plane"
CONTROL_PLANE_STAGED="padiem_control_plane"
cleanup_b66_stage() {
    rm -f "${B66_EXTRACTION_STAGED}" "${B66_INTAKE_STAGED}"
    rm -rf "${CORE_STAGED}" "${CONTROL_PLANE_STAGED}"
}
trap cleanup_b66_stage EXIT
test -f "${B66_EXTRACTION_SOURCE}"
test -f "${B66_INTAKE_SOURCE}"
for module in document_semantics.py document_normalization.py document_parser_boundary.py pc_work_metrics.py conversation_bounds.py evidence_blocks.py; do
    test -f "${CORE_SOURCE}/${module}"
done
cp "${B66_EXTRACTION_SOURCE}" "${B66_EXTRACTION_STAGED}"
cp "${B66_INTAKE_SOURCE}" "${B66_INTAKE_STAGED}"
mkdir -p "${CORE_STAGED}"
printf '%s\n' '"""Deployment-staged package shell for canonical Core parser modules."""' > "${CORE_STAGED}/__init__.py"
for module in document_semantics.py document_normalization.py document_parser_boundary.py pc_work_metrics.py conversation_bounds.py evidence_blocks.py; do
    cp "${CORE_SOURCE}/${module}" "${CORE_STAGED}/${module}"
done
test -f "${CONTROL_PLANE_SOURCE}/models_registry.py"
rm -rf "${CONTROL_PLANE_STAGED}"
cp -R "${CONTROL_PLANE_SOURCE}" "${CONTROL_PLANE_STAGED}"
find "${CONTROL_PLANE_STAGED}" -name '__pycache__' -type d -prune -exec rm -rf {} +
echo "B66_EXTRACTION_AUTHORITY_STAGED=YES"
echo "B66_FILE_INTAKE_AUTHORITY_STAGED=YES"
echo "B66_CORE_PARSER_BOUNDARY_STAGED=YES"

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
