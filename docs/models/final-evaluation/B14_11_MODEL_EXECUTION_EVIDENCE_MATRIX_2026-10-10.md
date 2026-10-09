# B14 #3554 — 11-model live execution and Engine/Claw acceptance evidence matrix

**Snapshot:** 2026-10-10 KST, source main `7f0fc71f6cd1e9d86274b5190f22ea5b4c239d61`, canonical `apps/korean-ai-platform/app/pilot/b14_models.json` = 11 models / 8 providers. Authoritative test outcome source is [B14 Owner evaluation priority ledger](B14_OWNER_EVALUATION_PRIORITY_2026-10-10.md) and [issue #3554](https://github.com/skerishKang/ai-revenue-lab/issues/3554). This file is a **source/read-only inventory**, not a new model scoring exercise or real-provider call.

## 1. Strictly separated evidence states

- `REGISTERED`: exact model ID and provider/upstream tuple are present in canonical source (all 11). **Not** evidence that served Production currently matches the latest source or that a secret is valid.
- `BASIC_HTTP`: latest owner-ledger summary of a single synthetic prompt and response status, not an independently rerun 11-model benchmark.
- `STREAM`: only independently documented stream completion; otherwise `NOT_VERIFIED` even if basic HTTP 200 occurred.
- `ENGINE_CLAW_E2E`: requires authenticated user-selected model → Engine → B14 exact model request → actual upstream completion → render, with stable correlation and no substitution/fallback. **No complete per-model result verified here**.
- `QUOTE_PDF_E2E`: requires customer quotation input → selected exact model extraction → canonical template → actual PDF preview/output with source preservation. **No per-model end-to-end result verified here**.

| # | Exact canonical model ID | Latest independently reported B14 availability evidence | Current interpretation | Engine/Claw E2E | Quotation/PDF E2E |
|---:|---|---|---|---|---|
| 1 | `agnes-ai/agnes-3.0-flash` | HTTP 429 repeatedly | DEFERRED / no response-completion proof | NOT_VERIFIED | NOT_VERIFIED |
| 2 | `atria/Atria-Dawn-Preview` | A separate live SSE HTTP 200 completion was observed; HTTP 504 also observed | DEFERRED / intermittent availability | NOT_VERIFIED | NOT_VERIFIED |
| 3 | `google/gemini-3.1-flash-lite` | Simple synthetic text prompt HTTP 200 with body | No quote/PDF E2E acceptance | NOT_VERIFIED | NOT_VERIFIED |
| 4 | `google/gemini-3.5-flash-lite` | Simple synthetic text prompt HTTP 200 with body | No quote/PDF E2E acceptance | NOT_VERIFIED | NOT_VERIFIED |
| 5 | `google/gemma-4-26b-a4b-it` | Simple synthetic text prompt HTTP 200 with body | No quote/PDF E2E acceptance | NOT_VERIFIED | NOT_VERIFIED |
| 6 | `google/gemma-4-31b-it` | HTTP 504 observed on same basic operational check | Availability unresolved; no quality score from 504 | NOT_VERIFIED | NOT_VERIFIED |
| 7 | `inception/mercury-2.5` | Simple synthetic text prompt HTTP 200 with body | No quote/PDF E2E acceptance | NOT_VERIFIED | NOT_VERIFIED |
| 8 | `poolside/laguna-s-2.1` | Simple synthetic text prompt HTTP 200 with body (direct Poolside provider) | Direct Poolside admission != broad owner/customer authorization | NOT_VERIFIED | NOT_VERIFIED |
| 9 | `sensenova/sensenova-6.8-flash-lite` | Simple synthetic text prompt HTTP 200 with body | No quote/PDF E2E acceptance | NOT_VERIFIED | NOT_VERIFIED |
| 10 | `experiential/qwen3.8-flash-next-uncensored` | Provider HTTP 429 observed | Owner HOLD; no new calls by this review | NOT_VERIFIED | NOT_VERIFIED |
| 11 | `kira/qwen3.8-flash-free` | Registered in canonical source; no comparable live scored response verified in owner priority ledger | NO COMPARABLE EVIDENCE YET | NOT_VERIFIED | NOT_VERIFIED |

**Caveats:** The six simple-prompt HTTP 200 observations are historical evidence snapshots from the owner ledger, not our live rerun. Atria's one SSE completion does not negate independent HTTP 504. Agnes/ExLab HTTP 429 and Gemma 4 31B HTTP 504 are availability failures, **not zero-score quality grades**. Kira Qwen is registered without comparable completed evaluation evidence. Direct Poolside is distinct from the excluded Kilo Poolside Laguna route, and registration does not confer broad user authorization.

## 2. CENTRAL-owned acceptance order (#3554)

1. **Source/contract**: compare fresh current-main 11/8 registry with observed served B14 /models metadata using already authorized read-only evidence. Preserve exact model identity and provider/upstream tuple; record `NOT_CHECKED` if served observations cannot be read.
2. **Offline**: B14 nonstream/stream fail-closed contract for canonical tuples and Owner-excluded spoofed identities (#3789). Verify no accidental auto/fallback and that errors retain exact selected model/correlation IDs.
3. **Shared-path handoff**: LOCAL1's [#3977](https://github.com/skerishKang/ai-revenue-lab/issues/3977) owns optional model-native parameter transport through shared Core; B62/Claw source belongs to its product teams. CENTRAL validates their delivered contracts but does not overwrite shared worktrees.
4. **Actual model responses**: only execute specific real-provider requests within the Owner's existing exact-model, permitted-key, bounded-call and cost authorization; otherwise record `NOT_AUTHORIZED` / `NOT_TESTED`. Never implement retry, fallback or paid-provider switching just to obtain a success.
5. **E2E acceptance**: per-model JSON + SSE + representative Korean business document, Engine/Claw user session and result rendering; store request attempts, HTTP/error class, server-observed model ID, source SHA and authorization chain, **never secret values or raw customer documents**.

## 3. Status definitions and remaining work

- `SOURCE_CONTRACT`: ongoing; existing guarded source tests, incremental #3789 exact-tuple and stream negative coverage.
- `B14_SERVING_CATALOG_PARITY`: not reverified at this snapshot; past production deployment reports do not establish today's exact head as served.
- `MODEL_PARAMETER_TRANSPORT`: depends on LOCAL1-owned #3977 acceptance; no assumption of completion from B14-side changes.
- `PROVIDER_LIVE_PER_MODEL`, `CLAW_ENGINE_PER_MODEL`, `CUSTOMER_QUOTE_PDF_PER_MODEL`: **OPEN / NOT_VERIFIED** except narrowly documented independent historical probes.
- `OWNER_MODEL_SELECTION_CHANGED`: NO. `B14_ROUTE_DEFAULT_CHANGED`: NO. `AUTOMATIC_FALLBACK`: NO. `SECRET_STORE_MUTATION`: NO. `PRODUCTION_DEPLOYMENT`: NO.

A passing registry CI, synthetic regression or simple model response never closes #3554 by itself. Keep #3554 OPEN until actual per-route evidence and consumer E2E acceptance are recorded, even if neighboring product owners completed their own PRs.
