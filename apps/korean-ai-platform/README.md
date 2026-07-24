# Korean AI Platform — Business 14

## Overview

A Korean AI API Provider concept demo and BYOK (Bring Your Own Key) gateway pilot.

### Phase 0: AI API Provider Mock Demo

- 8-model catalog (GPT-4o, Claude, Gemini, HyperCLOVA X, Kanana, VARCO LLM, Ko-Open 32B, Llama-Ko 70B)
- Model detail, playground, API keys demo, docs, usage, pricing
- Korean-language UI with routing modes (cheapest, fastest, korean-first, domestic-first)

### Phase 1: BYOK Gateway Pilot

- Single-provider OpenAI-compatible BYOK gateway
- Request-scoped provider key forwarding (keys never stored or logged)
- Server-configured endpoint allowlist with SSRF protection
- Non-streaming chat completions with validation and redaction

### Phase 2: Multi-Provider BYOK Model Routing Pilot

- Server-configured multi-provider registry via `BUSINESS14_PROVIDER_REGISTRY_JSON`
- Deterministic model-to-provider routing (one model → one provider)
- Key isolation across providers (Provider A key never sent to Provider B)
- Aggregated model catalog from all registered providers
- Multi-provider health and model listing API
- Legacy Phase 1 single-provider compatibility (when registry is not set)

## Environment Variables

### Phase 1 Legacy (single provider)

```bash
BUSINESS14_PILOT_PROVIDER_ID=my-provider
BUSINESS14_PILOT_BASE_URL=https://api.provider.example.com/v1
BUSINESS14_PILOT_MODEL_ID=my-model
BUSINESS14_PILOT_UPSTREAM_MODEL=upstream-model-name
BUSINESS14_PILOT_TIMEOUT_SECONDS=30
```

### Phase 2 Multi-Provider Registry

```bash
BUSINESS14_PROVIDER_REGISTRY_JSON='[
  {
    "provider_id": "provider-a",
    "display_name": "Provider A",
    "base_url": "https://api.provider-a.example.com",
    "timeout_seconds": 30,
    "models": [
      {
        "model_id": "model-a-v1",
        "upstream_model": "upstream-a",
        "display_name": "Model A",
        "enabled": true
      }
    ]
  }
]'
```

**Note:** When `BUSINESS14_PROVIDER_REGISTRY_JSON` is set and valid, multi-provider mode is used. Legacy env vars are ignored when registry is set. Invalid registry JSON causes a `registry_invalid` error — no silent fallback to legacy mode.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/pilot/health` | Provider configuration summary |
| GET | `/api/pilot/models` | Aggregated model catalog |
| POST | `/api/pilot/v1/chat/completions` | BYOK chat completions |

### Key Delivery

- Provider key is sent via `X-Business14-Provider-Key` request header
- Keys are never persisted, logged, or returned in responses
- Each request uses a single model; the key is forwarded to the mapped provider only

## Cost

BYOK has no Business 14 billing. Actual usage costs depend on the connected provider's contract. Pilot response metadata shows `estimated_krw: null` (unknown).

## Security Boundary

- Provider endpoints are server-configured only (no user-submitted URLs)
- Redirects disabled, timeouts enforced, URL credential rejection
- Secret redaction on all log output
- Request ID tracking for all errors
- No streaming, tool calling, or image input support

## Testing

```bash
cd apps/korean-ai-platform
python -m pytest -q
```

All tests use `httpx.MockTransport` — no external network calls.

## Documentation

- [Phase 2 Charter](docs/PHASE2_MULTI_PROVIDER_CHARTER.md)
- [Phase 2 Routing Contract](docs/PHASE2_ROUTING_CONTRACT.md)
- [Phase 2 Pilot Runbook](docs/PHASE2_PILOT_RUNBOOK.md)
