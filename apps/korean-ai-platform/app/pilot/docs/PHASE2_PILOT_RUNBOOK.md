# Phase 2: Multi-Provider BYOK Pilot — Runbook

## Environment Variables

### Multi-Provider Mode

BUSINESS14_PROVIDER_REGISTRY_JSON: Provider registry JSON string

### Legacy Single-Provider Mode (Phase 1 Compat)

BUSINESS14_PILOT_PROVIDER_ID=pilot-openai-compat
BUSINESS14_PILOT_BASE_URL=https://...
BUSINESS14_PILOT_MODEL_ID=my-model
BUSINESS14_PILOT_UPSTREAM_MODEL=upstream-model
BUSINESS14_PILOT_TIMEOUT_SECONDS=30

## Local Run

```bash
cd apps/korean-ai-platform
.venv/bin/uvicorn app.main:app --reload
```

## Testing

```bash
.venv/bin/python -m pytest -q
```

## Fake Transport Testing

All tests use httpx.MockTransport — no external network calls.
Provider-specific fake transports verify correct routing:
- Provider A transport: receives Model A requests
- Provider B transport: receives Model B requests
- Authorization header verification for key isolation

## Troubleshooting

| Symptom | Check |
|---------|-------|
| registry_invalid | BUSINESS14_PROVIDER_REGISTRY_JSON JSON 형식, 중복 ID, URL scheme 확인 |
| model_not_found | 요청한 model_id가 registry에 존재하고 enabled=true인지 확인 |
| key isolation | 각 요청의 X-Business14-Provider-Key가 올바른 Provider에 전달되는지 MockTransport로 확인 |

## Known Limitations

- Single upstream model per Business 14 model ID
- No DNS rebinding protection (endpoint is server-configured, not user-supplied)
- No automatic failover or load balancing
- No streaming or tool calling
