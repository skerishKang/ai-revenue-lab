# Korean AI Platform — Business 14

## Overview

Business 14는 한국 시장에서 여러 국내·해외 AI Provider와 모델을 하나의 인터페이스로 이용할 수 있도록 만드는 한국형 AI Provider 플랫폼이다.

이 프로젝트의 출발점은 한국 사용자·기업·기관이 사용할 수 있는 독립적인 한국 중심 AI Provider 계층이 부족하다는 문제다. 따라서 제품의 기준 시장과 기본 사용자 경험은 한국이며, 해외 Provider 연동은 한국 사용자가 더 쉽게 활용하기 위한 수단으로 다룬다.

### Product and Language Policy

- 1차 목표 시장: 대한민국
- 제품 문구와 UX의 원본 언어: 한국어(`ko-KR`)
- 모든 Business 14 Phase와 화면의 기본 UI 언어: 한국어
- 최초 접속, 저장된 locale 없음, 잘못된 locale 값: 한국어로 fallback
- 영어: 사용자가 명시적으로 선택할 수 있는 보조 locale
- 신규 기능, 용어, 도움말, 검증 오류, 정책·보안·비용 설명: 한국어를 먼저 완성
- 영어 번역이 없는 문구: 한국어로 fallback
- 모든 신규 문구의 한·영 동시 완성은 기본 개발·병합 조건이 아님
- API 필드명, 코드 예제, Provider·모델 고유명 등 기술 표준은 영어를 유지할 수 있으나 사용자 설명과 기본 탐색은 한국어
- Korea-first 정책은 개인 사용 편의가 아니라 Business 14 전체의 제품시장 결정

정식 전체 정책: [Business 14 Product Language Policy](docs/BUSINESS14_LANGUAGE_POLICY.md)

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
- Korean-first product copy; English localization expansion is deferred unless required for the pilot

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

- [Business 14 Product Language Policy](docs/BUSINESS14_LANGUAGE_POLICY.md)
- [API Provider Phase 0 Charter](docs/API_PROVIDER_PHASE0_CHARTER.md)
- [Business 14 Decision Log](docs/BUSINESS14_DECISION_LOG.md)
- [Phase 2 Charter](docs/PHASE2_MULTI_PROVIDER_CHARTER.md)
- [Phase 2 Routing Contract](docs/PHASE2_ROUTING_CONTRACT.md)
- [Phase 2 Pilot Runbook](docs/PHASE2_PILOT_RUNBOOK.md)
