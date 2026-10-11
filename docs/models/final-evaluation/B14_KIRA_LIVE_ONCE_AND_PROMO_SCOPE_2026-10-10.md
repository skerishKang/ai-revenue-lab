# B14 Kira exact-model live single-call proof and promotion-vs-subscription scope — 2026-10-10

**Owner-approved one-call result: B14 Production `CONNECTIVITY_PASS`**. Evidence [#3554](https://github.com/skerishKang/ai-revenue-lab/issues/3554#issuecomment-6095979271). This is **not** a claim of permanent free pricing, actual zero billing, latest deployed SHA or complete Engine/Claw/B66/PDF E2E.

## Current official exact model and account billing distinction

- Exact B14 registered ID: `kira/qwen3.8-flash-free`. Serving provider Kira, upstream `qwen3.8-flash-free`, origin `https://kiraai.vn/api/v1`; existing Worker credential alias unchanged.
- [Official exact-model page](https://kiraai.vn/models/qwen3.8-flash-free/): showed **FREE**, **0 charged per token in the published *limited* promotional window**, and a visible countdown; additionally advertised 1,000,000 input context and 131,072 output tokens, neither independently stress-tested. As of 2026-10-10, an independent public GET on the authorized desktop confirmed **HTTP200, exact upstream slug, free/no-token-cost marker and promotion-end countdown** immediately before the one B14 POST. The displayed remaining countdown is dynamic; do **not** convert it to a permanent price or precise contract expiry without account/vendor confirmation.
- [Kira official subscription billing policy](https://kiraai.vn/billing/) says **membership-included tokens apply only to `kira-` prefixed model slugs**; partner models use separate wallet/model-by-model rates outside special promotions. This B14 upstream does **not** have the `kira-` prefix. Owner reports a **paid Kira account that replenishes 10,000,000 tokens daily**, but **the refill's eligibility for this exact served model is UNKNOWN**. Public promotional price is a separate basis for performing this small call.
- The Owner's Kira account payment/usage ledger was not accessed, therefore **actual monetary charge and amount deducted = UNKNOWN** even with the public $0 promotional listing. No stored values/keys/creds exported.

## Existing Production B14 single-call observation

| Field | Value |
|---|---|
| KST | **2026-10-10 18:08**, new single call |
| Source/Production GET preflight | **11/11 registry identities MATCH**, no extra/missing/changed upstream/provider; GET does not attest exact deployed git SHA |
| API | Existing `ai-revenue-korean-ai-platform.charliekant.workers.dev/api/pilot/v1/chat/completions` |
| B14 selected / serving model | `kira/qwen3.8-flash-free` / `qwen3.8-flash-free` |
| Request | One synthetic Korean literal `OK` instruction, `stream=false`; `max_tokens=1024` is an explicit **diagnostic request budget**, not a manufacturer/serving output cap |
| Request routing | `business14.allow_paid=true`, `max_attempts=1`, `max_retries=0`, `allow_external_fallback=false`; temperature and native controls omitted |
| Observed response | **HTTP200**, **7,781 ms**, nonempty literal `OK`, visible length 2, `finish_reason=stop` |
| Exact model attribution | selected model, selected upstream and actual provider response upstream **MATCH**; `route_mode=manual`, `fallback_used=false`, `attempt_count=1` |
| Reported usage | prompt **1,934**, completion **103**, total **2,037** tokens — do not infer visible word/token conversion or undisclosed billing |
| Failed/repeated provider calls | **0 additional calls, 0 retries, 0 alternate model calls**; no ExLab request |
| Secrets/deployment | Existing Worker binding used internally; **0 credentials read or changed by tester**, **0 deployments** |

Sanitized evidence stored **outside repo** on authorized desktop at `E:\\b14-3554-kira-once-20261010-safe-evidence.json`; atomic private one-shot lock `E:\\b14-3554-kira-once-20261010.lock` prevents accidental replay. No raw response, prompt, key, invoice, or personal billing details checked in.

## Certification limits and next gate

**PASS** only: authenticated actual B14 production path accepted manually selected exact Kira model, provider answered text and returned model/attempt/usage metadata. The prior direct Kira HTTP200 observation and this separate B14 call are two distinct dates/tests. **NOT PASSED/NOT TESTED:** specific applicability of the daily Owner refill, billing ledger, permanent free tier, provider 1,000,000/131,072 full token lengths, model-specific reasoning/native options, model-quality benchmark, SSE, customer quotation and exact final Sol-native PDF, Engine/Claw integration, currently deployed source SHA.

Next step needs **new distinct Owner approval** for any additional potentially charged call; do not infer blanket approval from this exact one-shot. `ExLab` current restriction suspected → **HOLD/no calls**. `SenseNova` prior one-shot Production **PASS** (separately [recorded](B14_3554_OWNER_QUOTA_AND_LIVE_PROBE_GATE_2026-10-10.md)); no repeated smoke tests.
