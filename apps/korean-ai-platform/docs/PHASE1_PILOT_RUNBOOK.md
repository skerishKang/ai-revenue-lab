# Phase 1: BYOK Gateway Pilot — Runbook

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BUSINESS14_PILOT_PROVIDER_ID` | No | `pilot-openai-compat` | Provider identifier for metadata |
| `BUSINESS14_PILOT_BASE_URL` | **Yes** | `""` | Upstream API base URL (https:// only) |
| `BUSINESS14_PILOT_MODEL_ID` | **Yes** | `""` | Business 14 model ID for this pilot |
| `BUSINESS14_PILOT_UPSTREAM_MODEL` | No | `""` | Upstream model name (defaults to model_id) |
| `BUSINESS14_PILOT_TIMEOUT_SECONDS` | No | `30` | Upstream request timeout |

## Local Setup

```bash
cd apps/korean-ai-platform

# Configure pilot (example with dummy URL for testing)
export BUSINESS14_PILOT_BASE_URL="https://api.openai.com"
export BUSINESS14_PILOT_MODEL_ID="gpt-4o-mini"

# Run the app
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

# Test:
#   curl http://127.0.0.1:8000/api/pilot/health
#   curl http://127.0.0.1:8000/api/pilot/models
```

## Testing with Fake Transport (No Real Key Required)

All Phase 1 tests use `httpx.MockTransport` — no external network calls:

```bash
cd apps/korean-ai-platform
.venv/bin/python -m pytest tests/test_pilot.py -v
```

## Optional Live Smoke Test

Only runs when explicitly enabled:

```bash
export BUSINESS14_ENABLE_LIVE_SMOKE=1
export BUSINESS14_PILOT_BASE_URL="https://api.openai.com"
export BUSINESS14_PILOT_MODEL_ID="gpt-4o-mini"

# Run specific smoke test
.venv/bin/python -m pytest tests/ -k "live_smoke" -v
```

**Never paste a real API key into the shell command.** Use environment variables or a
`.env` file that is *.gitignore*'d.

Do not include the actual API key in:
- Shell history
- Command output
- Screenshots
- Bug reports
- Git commits

## Failure Investigation Order

1. **Health check**: `GET /api/pilot/health`
   - `status: "ok"` → configured correctly
   - `status: "not_configured"` → missing `BUSINESS14_PILOT_BASE_URL` or `_MODEL_ID`

2. **Model list**: `GET /api/pilot/models`
   - Returns 0 models → not configured

3. **Test with curl** (use a real key):
   ```bash
   curl -X POST http://localhost:8000/api/pilot/v1/chat/completions \
     -H "Content-Type: application/json" \
     -H "X-Business14-Provider-Key: sk-real-key-here" \
     -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Hello"}]}'
   ```

4. **Check app logs** for `pilot_error` or `pilot_request` entries

## Secret Exposure Incident Response

If an API key is accidentally exposed:

1. Revoke the compromised key at the provider immediately
2. Check git history for the key — if committed, rotate and remove from history
3. Check shell history files
4. Check application logs for key leakage (should not happen — verify redaction)
5. Document the incident

## Current Limitations

- Only one upstream provider supported
- No automatic failover
- No rate limiting at gateway
- No encrypted key storage (keys are memory-only per request)
- Streaming not supported
