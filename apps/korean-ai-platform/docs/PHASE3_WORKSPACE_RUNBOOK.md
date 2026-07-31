# Phase 3: Workspace Pilot Runbook

## Environment Variables

Phase 3 reuses Phase 2 configuration. No new environment variables.

### Multi-Provider Registry (Phase 2)

```bash
export BUSINESS14_PROVIDER_REGISTRY_JSON='[
  {
    "provider_id": "my-provider",
    "display_name": "My Provider",
    "base_url": "https://api.my-provider.example",
    "timeout_seconds": 30,
    "models": [
      {
        "model_id": "my-model",
        "upstream_model": "upstream-model-name",
        "display_name": "My Model",
        "enabled": true
      }
    ]
  }
]'
```

### Legacy Single-Provider (Phase 1 Compat)

```bash
export BUSINESS14_PILOT_BASE_URL="https://api.openai.com"
export BUSINESS14_PILOT_MODEL_ID="gpt-4o"
export BUSINESS14_PILOT_PROVIDER_ID="openai"
export BUSINESS14_PILOT_UPSTREAM_MODEL="gpt-4o"
export BUSINESS14_PILOT_TIMEOUT_SECONDS=30
```

## Local Run

```bash
cd apps/korean-ai-platform
pip install -e .
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/workspace

## Testing

```bash
cd apps/korean-ai-platform

# Run all tests (Phases 0-3)
pytest -q

# Run only Phase 3 workspace tests
pytest tests/test_workspace_phase3.py -q

# Run with warning-strict (targeted)
pytest -W error::Warning -W ignore::starlette.exceptions.StarletteDeprecationWarning -q

# Compile check
compileall -q app tests

# Import smoke
python -c "from app.main import app; print(app.title)"
```

## Test Structure

```
tests/
├── test_pilot.py              # Phase 0 + Phase 1 tests (preserved origin/main)
├── test_pilot_phase2.py       # Phase 2 registry/routing/key-isolation
└── test_workspace_phase3.py   # Phase 3 workspace/locale/multi-turn/key-safety/XSS
```

## Clean Runtime Install

Verify no dev dependencies are required for production:

```bash
rm -rf /tmp/business14-phase3-runtime
python -m venv /tmp/business14-phase3-runtime
/tmp/business14-phase3-runtime/bin/python -m pip install .
/tmp/business14-phase3-runtime/bin/python -c "from app.main import app; print(app.title)"
```

## Key Provisioning (for testing)

Phase 3 does NOT store keys. During testing, provide a key via header:

```bash
curl -X POST http://localhost:8000/workspace/api/chat \
  -H "Content-Type: application/json" \
  -H "X-Business14-Provider-Key: sk-your-real-key" \
  -d '{"model":"my-model","messages":[{"role":"user","content":"안녕하세요"}],"temperature":0.2,"max_tokens":512}'
```

## Failure Modes

### Registry Invalid

Symptom: Workspace shows "Provider registry 설정이 올바르지 않습니다."
Action: Check `BUSINESS14_PROVIDER_REGISTRY_JSON` syntax and structure.

### Model Not Found

Symptom: "선택한 모델을 찾을 수 없습니다."
Action: Verify the model ID exists in the registry and is `enabled: true`.

### Provider Auth Failed (401)

Symptom: "Provider 인증에 실패했습니다."
Action: Check the API key entered in the workspace. It must be a real, active key.

### Rate Limited (429)

Symptom: "Provider rate limit에 도달했습니다."
Action: Wait and retry. The key is valid but quota exceeded.

### Timeout (504)

Symptom: "Provider 요청 시간이 초과되었습니다."
Action: Check network connectivity and provider status. Increase `timeout_seconds`.

## Security Incident Response

If a credential is exposed in logs or responses:

1. Record the incident details (time, request ID, affected endpoint)
2. Rotate the affected Provider API key immediately
3. Check `BUSINESS14_PROVIDER_REGISTRY_JSON` was not captured
4. Verify no other credentials are exposed
5. Document the root cause

## Known Limitations

- No server-side conversation persistence
- No streaming
- No DNS rebinding protection
- No CSP/SRI headers
- Mobile overflow only manually verified
- No automated browser tests (environment-limited)
