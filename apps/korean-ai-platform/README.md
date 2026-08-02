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

### Phase 3: Korean-First Session Workspace Pilot

- `GET /workspace` — Korean-first browser chat workspace
- Korean default UI; explicit English switch via `?lang=en` or cookie
- Accept-Language is ignored; missing/empty/invalid locale → Korean
- Multi-turn conversation in browser JS memory (no server persistence)
- Provider API key via password input + Apply button (key held in JS memory only)
- Key input value cleared immediately after capture
- Model change resets key and conversation (no cross-provider key/message leakage)
- `POST /api/pilot/v1/chat/completions` directly (no separate workspace proxy endpoint)
- Phase 2 multi-provider registry for model selection
- Estimated cost: always `확인 불가` (unknown) — actual billing by the connected Provider
- XSS-safe config injection via `application/json` script element
- `innerHTML` not used; `textContent` and `replaceChildren` for content rendering
- Page reload or tab close clears key and conversation

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/pilot/health` | Provider configuration summary |
| GET | `/api/pilot/models` | Aggregated model catalog |
| POST | `/api/pilot/v1/chat/completions` | BYOK chat completions |
| GET | `/workspace` | Korean-first session workspace UI |

### Key Delivery

- Provider key is sent via `X-Business14-Provider-Key` request header
- Keys are never persisted, logged, or returned in responses
- Each request uses a single model; the key is forwarded to the mapped provider only
- Workspace: key is captured via Apply button, held in JS memory, not stored in cookies/DOM/localStorage

## Cost

BYOK has no Business 14 billing. Actual usage costs depend on the connected provider's contract. Pilot response metadata shows `estimated_krw: null` (unknown). Workspace displays `확인 불가` (cannot be determined).

## Security Boundary

- Provider endpoints are server-configured only (no user-submitted URLs)
- Redirects disabled, timeouts enforced, URL credential rejection
- Secret redaction on all log output
- Request ID tracking for all errors
- No streaming, tool calling, or image input support
- Workspace: key in JS memory only, cleared on reload/tab-close/model-change
- Workspace: XSS-safe rendering (textContent, replaceChildren, no innerHTML)
- Workspace: config injected via `application/json` script element (not `|safe`)

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
- [Phase 3 Charter](docs/PHASE3_SESSION_WORKSPACE_CHARTER.md)
- [Phase 3 Security Contract](docs/PHASE3_SESSION_SECURITY_CONTRACT.md)
- [Phase 3 Workspace Runbook](docs/PHASE3_WORKSPACE_RUNBOOK.md)

## Alpha 1 — Owner-Tryable OpenRouter Gateway

Business 14 Alpha 1 lets an owner run the app locally with their own OpenRouter
API key, send Korean questions, and receive real model responses.

### Quick Start

```bash
cd apps/korean-ai-platform

# 1. Copy the example environment
cp .env.example .env

# 2. Edit .env — set your OpenRouter key and switch to live mode
#    B14_PROVIDER_MODE=live
#    OPENROUTER_API_KEY=sk-or-v1-...

# 3. Start with the documented command (loads .env; mock mode needs no key)
python3 -m uvicorn app.main:app --env-file .env --host 127.0.0.1 --port 8000
```

Visit `http://localhost:8000/workspace` — the Start screen shows the
prompt input, model selection, optimization options, and route preview.

### Run Commands

| Command | Description |
|---------|-------------|
| `python3 -m uvicorn app.main:app --env-file .env --host 127.0.0.1 --port 8000` | Documented owner start command (loads `.env`; mode comes from `B14_PROVIDER_MODE`) |
| `python3 -m app.pilot.catalog validate-model-catalog` | Check the configured catalog snapshot against the public OpenRouter Models API |
| `python3 -m app.pilot.smoke_live` | Run a single live smoke test with `openrouter/free` (only when a real key is present) |

### Mock Mode

- No API key required
- `B14_PROVIDER_MODE=mock` (default if unset)
- Returns canned responses labeled "모의 응답 · 실제 Provider 호출 없음"
- Zero upstream HTTP calls

### Live Mode

- Requires `OPENROUTER_API_KEY` in environment or `.env`
- `B14_PROVIDER_MODE=live`
- Makes real POST /chat/completions calls to `https://openrouter.ai/api/v1`
- API key is read from server env var only — never sent to browser, never logged
- Responses labeled "실제 Provider 응답"

### Security Boundary

- `OPENROUTER_API_KEY` is **only** read from server-side environment variables
- API key is **never** transmitted to the browser
- API key is **never** included in logs, exceptions, or responses
- API key is **never** passed as a query parameter
- Authorization is via `Authorization: Bearer` header only
- Redirects are disabled (`follow_redirects=False`)
- Exact host allow-list: `openrouter.ai` only
- Explicit connect/read/write/pool timeout bounds applied (10s/30s/10s/10s; no implicit total timeout)
- Success responses are streamed and aborted as soon as the 1 MB body cap is exceeded
- Upstream error body truncated to 500 characters
- `.env` is in `.gitignore`; `.env.example` has empty values only

### Router Core

- **Manual**: specific catalog model ID → single upstream call
- **Automatic**: `model: "b14/auto"` → deterministic selection by `optimize_for`
  (balanced / cost / latency / korean)
- **Fallback**: retries only on transport failure, timeout, HTTP 429, HTTP 5xx (up to `max_attempts`, default 3)
- **No fallback**: HTTP 400/401/403/404/409/422/any other 4xx, malformed request, malformed upstream response, oversize response, missing key, unsupported feature, unknown exceptions
- **No-safe-route**: returns `NO_SAFE_ROUTE` with zero upstream calls
- Resolve endpoint (`POST /api/pilot/router/resolve`) performs no upstream calls

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/pilot/health` | Health check (includes B14 provider mode + key availability) |
| GET | `/api/pilot/models` | Catalog models + existing BYOK models |
| POST | `/api/pilot/router/resolve` | Resolve route without upstream calls |
| POST | `/api/pilot/v1/chat/completions` | Chat completions (mock or live depending on mode) |

The chat completions response includes bounded `business14` metadata:

```json
{
  "route_mode": "auto",
  "selected_provider": "Google",
  "selected_model": "google/gemini-2.5-flash",
  "selected_upstream_model": "google/gemini-2.5-flash",
  "actual_response_model": "google/gemini-2.5-flash",
  "selected_route_id": "b14route_...",
  "reason_codes": ["optimize_for:balanced", "capabilities:chat"],
  "fallback_allowed": true,
  "fallback_used": false,
  "attempt_count": 1,
  "attempt_evidence": [
    {
      "attempt": 1,
      "model_id": "google/gemini-2.5-flash",
      "upstream_model": "google/gemini-2.5-flash",
      "provider": "Google",
      "outcome": "success",
      "error_code": null,
      "actual_response_model": "google/gemini-2.5-flash"
    }
  ],
  "route_evidence_status": "mock_no_upstream_call",
  "prompt_tokens": 0,
  "completion_tokens": 0,
  "total_tokens": 0,
  "estimated_usd": null,
  "estimated_krw": null,
  "cost_basis": "unknown",
  "request_id": "b14req_...",
  "provider_mode": "mock"
}
```

### Catalog

The Alpha catalog is a **configured snapshot** taken from the public
OpenRouter Models API (`GET https://openrouter.ai/api/v1/models`, no key
required). Prices are snapshot metadata, not a live invoice.

| Model ID | Provider | Notes |
|----------|----------|-------|
| `openrouter/free` | OpenRouter (free router) | Sends exactly `"model": "openrouter/free"`; actual free model preserved in `actual_response_model` |
| `google/gemini-2.5-flash` | Google | Snapshot-priced paid model |
| `deepseek/deepseek-chat` | DeepSeek | Snapshot-priced paid model |
| `mistralai/mistral-small-3.2-24b-instruct` | Mistral | Snapshot-priced paid model |
| `anthropic/claude-sonnet-4.5` | Anthropic | Snapshot-priced paid model |

Model IDs and snapshot prices are checked against the live OpenRouter Models API via:

```bash
python3 -m app.pilot.catalog validate-model-catalog
```

This command calls the public Models API; no API key or live provider mode
is required. Without network access it reports `SKIPPED` and the catalog
remains a configured snapshot.

### Limitations

- **No payment processing** — actual billing is between the user and OpenRouter
- **No platform credits** — no prepaid wallet or credit system
- **No persistent key vault** — key is read from env var per deployment
- **No merge/deploy** — this is an owner-tryable Alpha, not a production release
- Catalog model IDs and prices are a configured snapshot; use
  `validate-model-catalog` to check them against the live OpenRouter Models API
