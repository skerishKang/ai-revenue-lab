#!/usr/bin/env bash
# Trusted, root-installed runner content. Executed as unprivileged user inside
# offline/read-only Docker; the GitHub checkout is an untrusted read-only mount.
set -euo pipefail
export HOME=/tmp XDG_CACHE_HOME=/tmp/cache PYTHONPYCACHEPREFIX=/tmp/pycache
export PYTHONPATH=/work/packages/padiem-ai-core:/work/packages/padiem-control-plane:/work/apps/padiem-ai-engine/clients/python:/work/apps/korean-ai-code-agent
cmp -s /opt/apps/padiem-chat/uv.lock /work/apps/padiem-chat/uv.lock || { echo CI_5210_LOCK_DRIFT; exit 42; }
for p in packages/padiem-ai-core packages/padiem-control-plane apps/padiem-ai-engine/clients/python apps/korean-ai-code-agent; do
  cmp -s "/opt/$p/pyproject.toml" "/work/$p/pyproject.toml" || { echo CI_5210_METADATA_DRIFT; exit 42; }
done
python - <<'PY'
import padiem_ai_core
assert padiem_ai_core.__file__.startswith('/work/packages/padiem-ai-core/'), padiem_ai_core.__file__
print('CI_5210_CHECKOUT_IMPORT_PASS')
PY
export PADIEM_CHAT_RUNTIME_MODE=mock PADIEM_CHAT_LIVE_ENABLED=false PADIEM_CHAT_WEB_PROVIDER=off
export B62_STRUCTURED_QA_BASE_URL=http://127.0.0.1:8774
export B62_STRUCTURED_QA_OUT_DIR=/tmp/b62-structured-answer-browser-qa
cd /work/apps/padiem-chat
python -m pytest -p no:cacheprovider -q tests/test_rich_responses.py tests/test_browser_streaming_rich_integration.py
uvicorn app.main:app --host 127.0.0.1 --port 8774 >/tmp/structured-server.log 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true' EXIT
for i in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:8774/health >/dev/null; then break; fi
  sleep 1
done
curl --fail --silent http://127.0.0.1:8774/health >/dev/null
python ../../.github/scripts/b62_structured_answer_browser_qa.py
echo CI_5210_CHECKOUT_OVERLAY_PASS
