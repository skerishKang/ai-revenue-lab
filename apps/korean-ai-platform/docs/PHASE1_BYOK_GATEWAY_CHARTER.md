# Phase 1: BYOK Gateway Pilot — Charter

## Business Purpose

Phase 0 demonstrated the concept of a Korean AI API Provider with 8 mock models. Phase 1
converts that concept into a technical pilot: customers use their own AI Provider API keys
(OpenAI-compatible) while experiencing Business 14's unified request format, Korean UI, model
selection, request tracking, and estimated KRW cost display.

## Why BYOK First

- No provider reseller agreement required
- No Business 14 prepaid credit needed
- No GPU purchase required
- Customer uses their existing provider accounts
- Validates real Gateway technical feasibility
- Future expansion: unified credit, self-hosted inference

## Product Value

- Single Korean-language API experience
- Reduced documentation differences per provider
- Model switching via unified request format
- Provider/model display
- Estimated KRW cost
- Latency display
- Secure key forwarding (not stored)
- Request tracking (request ID)
- Korean technical support potential

## Supported Scope (Phase 1)

- Non-streaming chat completions only
- One configured OpenAI-compatible upstream provider
- Customer key via `X-Business14-Provider-Key` header
- Server-configured endpoint allowlist (no user-supplied URLs)
- Temperature, max_tokens support
- Model availability check

## Non-Goals (Phase 1)

- Streaming (`stream=true`)
- Tool calling / function calling
- Image input
- Arbitrary provider base URL (SSRF prevention)
- Automatic failover
- Production-grade rate limiting
- Multi-tenant authentication
- Long-term API key storage
- Actual billing / payment
- Business 14 credit sales
- Provider reseller agreement
- Self-hosted GPU inference
- Production SLA

## Relationship to Phase 0

- Phase 0 Mock Demo (`/playground`, 8 models, routing, docs) is **fully preserved**
- Phase 1 BYOK Gateway (`/pilot`, `/api/pilot/*`) is an **independent addition**
- The two mode `Mock Demo` and `BYOK Pilot` are visually and functionally separated
- Phase 0 models remain demo/concept — not actual integrations

## Future Expansion (Post-Phase 1)

- Streaming support
- Multiple upstream providers
- Customer key storage (encrypted, with consent)
- Usage-based credit system
- Self-hosted model inference
- Provider failover
- Rate limiting at gateway level
