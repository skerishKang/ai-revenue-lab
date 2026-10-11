#!/usr/bin/env bash
# #3989: all six original Worker dry-runs, full pytest, one Ubuntu runner.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
: "$RUNNER_TEMP"
scratch="$(mktemp -d "$RUNNER_TEMP/control-plane-ci-3989.XXXXXX")"
tests_pid=''
packages_pid=''
cleanup() {
  if [[ -n "$tests_pid" ]]; then kill "$tests_pid" 2>/dev/null || :; fi
  if [[ -n "$packages_pid" ]]; then kill "$packages_pid" 2>/dev/null || :; fi
  rm -rf "$scratch"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Copy exact reviewed source to isolate generated config and packaging writes.
cp -a "$repo_root/packages/padiem-control-plane" "$scratch/padiem-control-plane"
work="$scratch/padiem-control-plane"
test ! -e "$work/wrangler.jsonc"

(
  cd "$repo_root/packages/padiem-control-plane"
  pytest -q
) > "$scratch/tests.log" 2>&1 &
tests_pid=$!

(
  cd "$work"
  config='wrangler.jsonc'
  run_package() {
    local source_config="$1" output_name="$2" secrets_file="$3"
    test ! -e "$config"
    cp "$source_config" "$config"
    if [[ -n "$secrets_file" ]]; then
      uvx --from 'workers-py>=1.17.1,<2' pywrangler deploy \
        --secrets-file "$secrets_file" --dry-run \
        --outdir "$scratch/$output_name"
    else
      uvx --from 'workers-py>=1.17.1,<2' pywrangler deploy \
        --dry-run --outdir "$scratch/$output_name"
    fi
    rm -f "$config"
    test -d "$scratch/$output_name"
  }

  broker_secrets="$scratch/b54-local-agent-ci-secrets.env"
  printf 'LOCAL_AGENT_BROKER_PEPPER=%s\n' "$(python -c 'import secrets; print(secrets.token_hex(32))')" > "$broker_secrets"
  chmod 600 "$broker_secrets"
  run_package wrangler.local-agent-broker.jsonc b54-state-dry-run "$broker_secrets"
  run_package wrangler.local-agent-broker-edge.jsonc b54-edge-dry-run ''
  echo 'LOCAL_AGENT_WORKER_PACKAGING_PREFLIGHT=PASS'
  echo 'PRODUCTION_MUTATION=NO'

  oauth_secrets="$scratch/b54-google-oauth-ci-secrets.env"
  python - <<'PY' > "$oauth_secrets"
import base64
import secrets
def key():
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('ascii').rstrip('=')
print(f'GOOGLE_CONNECT_TICKET_KEY={key()}')
print(f'GOOGLE_OAUTH_SEAL_KEY={key()}')
print('GOOGLE_OAUTH_CLIENT_SECRET=ci-only-placeholder-not-production')
PY
  chmod 600 "$oauth_secrets"
  run_package wrangler.google-oauth.jsonc b54-google-oauth-state-dry-run "$oauth_secrets"
  run_package wrangler.google-oauth-edge.jsonc b54-google-oauth-edge-dry-run ''
  echo 'GOOGLE_OAUTH_WORKER_PACKAGING_PREFLIGHT=PASS'
  echo 'PUBLIC_HOSTNAME_CONFIGURED=NO'
  echo 'PRODUCTION_MUTATION=NO'

  identity_secrets="$scratch/control-plane-identity-ci-secrets.env"
  python - <<'PY' > "$identity_secrets"
import base64
import secrets
def key():
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('ascii').rstrip('=')
print(f'CONTROL_PLANE_IDENTITY_LOOKUP_KEY={key()}')
print(f'GOOGLE_CONNECT_TICKET_KEY={key()}')
PY
  chmod 600 "$identity_secrets"
  run_package wrangler.identity-authority.jsonc control-plane-identity-dry-run "$identity_secrets"
  echo 'CONTROL_PLANE_IDENTITY_WORKER_PACKAGING_PREFLIGHT=PASS'
  echo 'SERVER_OWNED_CONNECTOR_CONTEXT=YES'
  echo 'CLIENT_ACTOR_ACCOUNT_WORKSPACE_AUTHORITY=NO'
  echo 'PROVIDER_SUBJECT_PERSISTED=NO'
  echo 'PUBLIC_ROUTE_CONFIGURED=NO'
  echo 'PRODUCTION_MUTATION=NO'

  run_package wrangler.engine-admission-authority.jsonc control-plane-engine-admission-dry-run ''
  echo 'CONTROL_PLANE_ENGINE_ADMISSION_WORKER_PACKAGING_PREFLIGHT=PASS'
  echo 'PRIVATE_SERVICE_BINDING_RPC=YES'
  echo 'PUBLIC_ROUTE_CONFIGURED=NO'
  echo 'PRODUCTION_MUTATION=NO'
) > "$scratch/packaging.log" 2>&1 &
packages_pid=$!

tests_status=0
packages_status=0
wait "$tests_pid" || tests_status=$?
wait "$packages_pid" || packages_status=$?
echo '=== Full Control Plane pytest (unabridged log) ==='
cat "$scratch/tests.log"
echo '=== All six Worker dry-runs (unabridged log) ==='
cat "$scratch/packaging.log"
printf 'CONTROL_PLANE_TEST_EXIT=%s\n' "$tests_status"
printf 'CONTROL_PLANE_PACKAGING_EXIT=%s\n' "$packages_status"
if [[ "$tests_status" -ne 0 || "$packages_status" -ne 0 ]]; then
  echo 'CONTROL_PLANE_CI_OVERLAP=FAIL' >&2
  exit 1
fi
for output in \
  b54-state-dry-run b54-edge-dry-run \
  b54-google-oauth-state-dry-run b54-google-oauth-edge-dry-run \
  control-plane-identity-dry-run control-plane-engine-admission-dry-run; do
  test -d "$scratch/$output"
done
echo 'CONTROL_PLANE_CI_OVERLAP=PASS'
