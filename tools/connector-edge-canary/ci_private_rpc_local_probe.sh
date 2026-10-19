#!/usr/bin/env bash
# #4139: Real local Workerd multi-Worker Python RPC. No Cloudflare token or
# deploy. NEVER point any of these service bindings to existing Workers.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
PRIMARY=".ci-rpc-gateway.toml"
IDENTITY=".ci-rpc-identity.toml"
BROKER=".ci-rpc-broker.toml"
LOG="$(mktemp)"
REPLY="$(mktemp)"
SERVER_PID=""
cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -f -- "$PRIMARY" "$IDENTITY" "$BROKER" "$LOG" "$REPLY"
}
trap cleanup EXIT

# Explicitly local. No production route, token, D1/DO, secret or remote: true.
cat > "$PRIMARY" <<'EOF'
name = "padiem-local-4139-test-only-gateway"
main = "rpc_gateway_fixture.py"
compatibility_date = "2026-10-13"
compatibility_flags = ["python_workers"]
workers_dev = false
preview_urls = false

[[services]]
binding = "IDENTITY_AUTHORITY_SERVICE"
service = "padiem-local-4139-test-only-identity"

[[services]]
binding = "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"
service = "padiem-local-4139-test-only-broker"
EOF
cat > "$IDENTITY" <<'EOF'
name = "padiem-local-4139-test-only-identity"
main = "rpc_identity_fixture.py"
compatibility_date = "2026-10-13"
compatibility_flags = ["python_workers"]
workers_dev = false
preview_urls = false
EOF
cat > "$BROKER" <<'EOF'
name = "padiem-local-4139-test-only-broker"
main = "rpc_broker_fixture.py"
compatibility_date = "2026-10-13"
compatibility_flags = ["python_workers"]
workers_dev = false
preview_urls = false
EOF

python - <<'PY'
import tomllib
from pathlib import Path
a=tomllib.loads(Path(".ci-rpc-gateway.toml").read_text())
i=tomllib.loads(Path(".ci-rpc-identity.toml").read_text())
b=tomllib.loads(Path(".ci-rpc-broker.toml").read_text())
assert [x["binding"] for x in a["services"]] == [
    "IDENTITY_AUTHORITY_SERVICE", "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"
]
assert [x["service"] for x in a["services"]] == [i["name"], b["name"]]
for obj in (a, i, b):
    assert obj["name"].startswith("padiem-local-4139-test-only-")
    assert obj["workers_dev"] is False and obj["preview_urls"] is False
    assert obj["compatibility_flags"] == ["python_workers"]
    for key in ("account_id", "routes", "vars", "durable_objects",
                "d1_databases", "r2_buckets", "secrets", "env"):
        assert key not in obj, key
print("CONNECTOR_CANARY_PRIVATE_RPC_BINDINGS_LOCAL_ONLY=PASS")
PY

# Wrangler -c multi-config launches three real Python Workers in one workerd.
# Every Worker is a separate entrypoint, never a Python in-process fake.
uv run pywrangler dev -c "$PRIMARY" -c "$IDENTITY" -c "$BROKER" \
  --port 8812 --inspector-port 9261 >"$LOG" 2>&1 &
SERVER_PID="$!"

SUCCESS=0
for try_no in $(seq 1 90); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "CONNECTOR_CANARY_PRIVATE_RPC_WORKER_EARLY_EXIT=FAIL" >&2
    tail -n 40 "$LOG" >&2
    exit 1
  fi
  code="$(curl -sS --max-time 3 -o "$REPLY" -w '%{http_code}' \
    http://127.0.0.1:8812/__padiem_canary/private-rpc 2>/dev/null || true)"
  body="$(cat "$REPLY")"
  if [[ "$code" == 200 && "$body" == LOCAL_RPC_3_IDENTITY_5_BROKER_ALL_DENIED ]]; then
    SUCCESS=1
    break
  fi
  if [[ "$code" == 503 ]]; then
    echo "CONNECTOR_CANARY_PRIVATE_RPC_DENIED_OR_INCOMPATIBLE=HOLD" >&2
    tail -n 30 "$LOG" >&2
    exit 1
  fi
  sleep 1
done
if [[ "$SUCCESS" != 1 ]]; then
  echo "CONNECTOR_CANARY_PRIVATE_RPC_READINESS=FAIL" >&2
  tail -n 40 "$LOG" >&2
  exit 1
fi
echo "CONNECTOR_CANARY_REAL_WORKER_SERVICE_RPC_3_IDENTITY_5_BROKER=PASS"
echo "CONNECTOR_CANARY_ALL_ENROLLMENT_RPC_RESULTS=DENIED"
echo "CONNECTOR_CANARY_PRODUCTION_RPC_SOURCE_PARITY=NOT_ATTESTED"
echo "CONNECTOR_CANARY_CLOUDFLARE_ACCOUNT_MUTATION=0"
