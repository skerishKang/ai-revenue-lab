# Atria Dawn Preview — Production SSE prestart 504 timeout-phase investigation (#3922)

2026-10-10: `/start.js` served version contains `start_atria_stream_preview` and `readAtriaPreview` (HTTP200). One **real synthetic manual exact Atria** SSE request to B14 `/api/pilot/v1/chat/completions/stream-preview` with 0 retries and no external fallback returned **HTTP504/upstream_timeout at ~11.23s, zero SSE frames**. Existing streaming UI source and deploy are present, but live SSE completion is not demonstrated. Prior QKR-001 one-shot streaming PASS ~50s is historical evidence and cannot override this result.

## Source-only follow-up
The generic provider adapter `platform.py` maps all `httpx.TimeoutException` subtypes to the same `UpstreamTimeout` HTTP504, losing whether **connect/read/write/pool** actually timed out. New `atria_timeout_diagnostics.py` logs **only** `atria_safe_timeout provider=atria phase=connect|read|write|pool|other mode=completed|stream` on this exact serving-provider route. No exception text, account, headers, user content, credentials, endpoint URLs, request IDs or timing-derived guesses. Existing HTTP504 and no-retry/no-fallback behavior unchanged.

New network-free `tests/test_atria_timeout_diagnostics.py` verifies all phases, live-adapter completed/SSE mapping, non-Atria suppression and safe logging. This is **diagnostic instrumentation, not a model timeout fix**.

## Required proof before #3922 can close
- Exact-head source CI PASS, canonical B14 deploy (only after approved source merge) and one no-retry synthetic Atria SSE canary.
- Inspect **only** safe timeout phase; if `connect`, investigate Worker→serving provider egress/TLS; if `read`, investigate provider time-to-first-byte/SSE heartbeat/limits; if outside httpx or `other`, inspect Worker budget and manual route timeout wrapper. Do not blindly increase common timeouts.
- Actually verify browser option+abort/incomplete handling and customer quote saved template→PDF E2E. Source mock/UI alone cannot close it.
- Exact-model selection, provider official native parameters, caller omission and Owner excluded routes remain unchanged. No secrets, worker WAF, pricing, auto fallback or API origin changes.
