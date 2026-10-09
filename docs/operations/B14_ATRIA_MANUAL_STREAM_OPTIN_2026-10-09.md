# B14 Atria Dawn Preview — explicit manual streaming opt-in

Status: **SOURCE_READY / DRAFT ONLY / NOT PRODUCTION DEPLOYED** (2026-10-09).

## Observed production problem

- Selected `atria/Atria-Dawn-Preview` canonical `POST /api/pilot/v1/chat/completions` QKR-001 returns **HTTP504 `upstream_timeout`** after **10,563 ms**.
- The same explicit model and prompt through `/api/pilot/v1/chat/completions/stream-preview` returns **HTTP200**, strict QKR-001 PASS in **50,640ms**, first delta **43,531ms**, one upstream attempt, no other model.
- The upstream Atria documentation supports `stream:true` SSE through Chat Completions. It does not establish why one nonstream call returned 504; no proof of a particular client/network connection phase.
- Direct Atria API also had a 50.3-second nonstream timeout, a 31.6-second streaming QKR-001 success, and a 65-second incomplete QKR-002 stream; **streaming is not proven always reliable**.

Sources: https://api.atria-asi.ai/docs ; prior B14 independent evaluation PR #3867.

## Implementation — no silent product promotion

- **Unselected by default**, explicitly labeled advanced option `Atria 수동 스트리밍 시험` on the B14 Start UI.
- Works only if **manual** `atria/Atria-Dawn-Preview` is selected **and external fallback is unchecked**. Violations fail before any network request.
- Requests the existing `/api/pilot/v1/chat/completions/stream-preview`, `stream:true`, `max_tokens=1800`, `max_attempts=1`, `max_retries=0`, `allow_external_fallback=false`; no arbitrary upstream/base URL or credential.
- Front-end buffers the bounded SSE response, verifies `[DONE]`, exact public/upstream model route, single attempt, manual mode, `fallback_used=false`, and displays assistant text only on fully completed success. Error frame, truncated SSE, invalid JSON, route/model drift fail closed. No partial text is treated as a complete quotation.
- Other providers, auto routing and users not opting in keep the **existing nonstream endpoint** unchanged.
- Fixes the B14 Start UI fallback checkbox **change-event state sync**; previously state reflected the initial value only, so unchecking in the UI did not alter the routed request. This is separately test-pinned.

## Acceptance and remaining risks

- Local tests: SSE parser happy, malformed, wrong route, wrong model, incomplete stream, error event, oversized frame, CRLF, plus existing streaming gateway tests.
- Source-only success does not prove full browser integration, customer UI deployment, or PDF. Do not change `stream-preview` into a general `/chat/completions` substitute without an additional release gate.
- B14 10K timeout is not currently proven to be a Cloudflare restriction. Do not globally increase timeouts, retry 504 blindly or disable WAF.
- Before deployment: owner review, exact-head GitHub CI and **browser acceptance** on served Worker (manual Atria, fallback off, advanced checkbox on; QKR-001; full SSE termination; request aborted/canceled; no 2nd upstream call).
- Requires separate approved deploy. Leave Production-live claim **false** until the opt-in is observed on the deployed UI.

No secrets, actual model response text, user-specific data or cost values are part of source.
