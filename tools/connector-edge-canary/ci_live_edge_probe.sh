#!/usr/bin/env bash
# #4139 ONE scoped live Cloudflare Python runtime proof. No customer data.
# Only the unique ephemeral canary is created/deleted; never change padiem-chat,
# any existing Worker, DNS, bindings, secrets, D1, R2 or enrollment flags.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ "${GITHUB_ACTIONS:-}" != "true"
   || "${GITHUB_REPOSITORY:-}" != "skerishKang/ai-revenue-lab"
   || "${GITHUB_EVENT_NAME:-}" != "pull_request"
   || "${GITHUB_HEAD_REF:-}" != "central/4139-claw-connect-integration-261013"
   || "${PADIEM_CONNECTOR_TEMP_CANARY_ENABLED:-}" != "explicitly-scoped" ]]; then
  echo 'CONNECTOR_CANARY_CI_SCOPE=REFUSED' >&2
  exit 2
fi
if [[ -z "${CLOUDFLARE_API_TOKEN:-}" || -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]]; then
  echo 'CONNECTOR_CANARY_CF_AUTH=UNAVAILABLE' >&2
  exit 2
fi

NAME="padiem-conn-py-e-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
if [[ ! "$NAME" =~ ^padiem-conn-py-e-[0-9]{8,14}-[0-9]{1,3}$ ]]; then
  echo 'CONNECTOR_CANARY_NAME=REFUSED' >&2
  exit 2
fi
CONFIG=".cf-live-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}.toml"
LOG="$(mktemp)"
DELETED=0
STARTED=0
cleanup() {
  code=$?
  trap - EXIT
  set +e
  if [[ "$STARTED" == "1" ]]; then
    # Independently controlled name; never use a variable from a remote page.
    for attempt in 1 2 3; do
      uv run pywrangler delete --config "$CONFIG" --name "$NAME" --force >"$LOG" 2>&1
      delete_code=$?
      uv run pywrangler deployments list --config "$CONFIG" --name "$NAME" >"$LOG" 2>&1
      if grep -Fq 'does not exist on your account' "$LOG"; then
        DELETED=1
        break
      fi
      if [[ "$delete_code" == 0 ]]; then
        sleep 2
      fi
    done
    if [[ "$DELETED" == 1 ]]; then
      echo 'CONNECTOR_CANARY_CLOUDFLARE_CLEANUP=CONFIRMED_NO_SCRIPT'
    else
      echo 'CONNECTOR_CANARY_CLOUDFLARE_CLEANUP=UNVERIFIED' >&2
      code=1
    fi
  fi
  rm -f -- "$CONFIG" "$LOG"
  exit "$code"
}
trap cleanup EXIT

cat >"$CONFIG" <<EOF
name = "$NAME"
main = "worker.py"
compatibility_date = "2026-10-13"
compatibility_flags = ["python_workers"]
workers_dev = true
preview_urls = false
EOF
# No account_id stored on disk. Cloudflare token+account passed as masked
# GitHub Secrets by the workflow, and used by pywrangler only.
if grep -Eq 'service|secret|durable|r2_|d1_|route' "$CONFIG"; then
  echo 'CONNECTOR_CANARY_BINDING_CONTRACT=REFUSED' >&2
  exit 2
fi

# Existing SOURCE-only Python Worker and external SDK; never legacy flag.
uv run pywrangler sync --force >"$LOG" 2>&1
test -f python_modules/workers/__init__.py

STARTED=1
if ! uv run pywrangler deploy --config "$CONFIG" >"$LOG" 2>&1; then
  echo 'CONNECTOR_CANARY_EDGE_DEPLOY=FAIL' >&2
  exit 1
fi
echo 'CONNECTOR_CANARY_EDGE_DEPLOY=EPHEMERAL_PASS'

BASE="https://${NAME}.padiem.workers.dev"
status=""
health=""
for attempt in $(seq 1 12); do
  status="$(curl -sS --max-time 8 -o "$LOG" -w '%{http_code}' \
      "$BASE/__padiem_canary/tls" || true)"
  health="$(cat "$LOG")"
  if [[ "$status" == 200 && "$health" == TLS_OK ]]; then
    break
  fi
  sleep 2
done
if [[ "$status" != 200 || "$health" != TLS_OK ]]; then
  echo 'CONNECTOR_CANARY_EDGE_TLS=NOT_PROVEN' >&2
  if [[ "$status" =~ ^[0-9]{3}$ ]]; then
    echo "CONNECTOR_CANARY_EDGE_HTTP_STATUS=$status" >&2
  else
    echo "CONNECTOR_CANARY_EDGE_HTTP_STATUS=TRANSPORT_ERROR" >&2
  fi
  # The only accepted detailed diagnostics are synthetic constant markers
  # emitted by OUR canary; never print an arbitrary upstream response body.
  case "$health" in
    CF_UNAVAILABLE|TLS_VERSION_UNAVAILABLE|TLS_UNACCEPTED|TLS_METADATA_ERROR)
      echo "CONNECTOR_CANARY_EDGE_TLS_BOUNDED_REASON=$health" >&2 ;;
    *)
      echo 'CONNECTOR_CANARY_EDGE_TLS_BOUNDED_REASON=UNRECOGNIZED_RESPONSE' >&2 ;;
  esac
  exit 1
fi
echo 'CONNECTOR_CANARY_EDGE_TLS=PASS'

nonupgrade="$(curl -sS --max-time 8 -o /dev/null -w '%{http_code}' \
    "$BASE/__padiem_canary/wss" || true)"
if [[ "$nonupgrade" != 426 ]]; then
  echo "CONNECTOR_CANARY_EDGE_NONUPGRADE=FAIL code=$nonupgrade" >&2
  exit 1
fi
echo 'CONNECTOR_CANARY_EDGE_NONUPGRADE_426=PASS'

PADIEM_EDGE_CANARY_NAME="$NAME" node ci_live_edge_ws_client.mjs
echo 'CONNECTOR_CANARY_PYTHON_EDGE_WSS_101_AND_FRAMES=PASS'
echo 'CONNECTOR_CANARY_REAL_DEVICE_AUTH=NOT_TESTED'
