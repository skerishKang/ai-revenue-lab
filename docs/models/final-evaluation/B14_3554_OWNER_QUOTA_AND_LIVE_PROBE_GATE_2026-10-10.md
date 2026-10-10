# B14 #3554 — Owner account entitlement and bounded live-response verification gate

**Date:** 2026-10-10 KST. **Authority:** Owner's latest account observations and current `main` B14 canonical registry, 11 models / 8 serving providers. **Current status: SenseNova single Owner-approved live paid B14 call PASSED / Kira NOT CALLED / ExLab HOLD / NO PRODUCTION RELEASE.** Evaluation priority only, never automatic product routing.

## Current exact-provider live evidence — 2026-10-10 18:00 KST

**Verdict: SenseNova Production B14 exact-route single-request connectivity PASS, not full product E2E.** The Owner separately approved precisely one paid SenseNova request. It was actually executed once through the existing B14 Production Worker; this is a later event that supersedes the historical pre-approval `PAID_PROVIDER_CALL_APPROVAL=NOT_GIVEN` snapshot at the bottom of this document **for this one completed call only**. No broader paid-call, second-model or production-deployment approval is implied.

| Verified fact | Observed value |
|---|---|
| Preflight | Read-only canonical/Production `GET /api/pilot/models` comparison `MATCH` — 11/11 exact IDs with matching provider/upstream, zero preflight POST |
| Exact B14 route | `sensenova/sensenova-6.8-flash-lite` → `sensenova-6.8-flash-lite` |
| Existing Production API | `POST /api/pilot/v1/chat/completions` via `ai-revenue-korean-ai-platform.charliekant.workers.dev` |
| Paid POST request count | **1** (atomic local single-use execution lock; no repeat) |
| B14 request | Synthetic Korean literal-`OK` prompt; `stream=false`, `max_tokens=1024` (diagnostic request budget, not vendor max) |
| Retry / route guards | `allow_paid=true`, `max_attempts=1`, `max_retries=0`, `allow_external_fallback=false` |
| Explicit temperature/reasoning/native override fields | **Omitted** (native-parameter E2E remains untested) |
| HTTP / latency | **200 / 8,328 ms** |
| Nonempty answer / expected answer | **YES / `OK`** (2 visible characters), `finish_reason=stop` |
| Provider reported usage | prompt **98**, completion **287**, total **385** tokens |
| Route metadata | selected model and upstream and actual response model all **MATCH**; `route_mode=manual`; `attempt_count=1`; `fallback_used=false` |
| Source/served version | Production served commit SHA **NOT_ATTESTED** — registry parity does not prove current main code is deployed |
| Secrets / Production mutation | **0** secret value reads/changes, **0** deployment/config changes; Worker used existing credential binding |
| No additional paid tests | **Kira 0 calls, ExLab 0 calls** |

**Accounting caveat:** completion-token usage of 287 is the provider/B14 reported token count despite only two visible characters. It may include thinking tokens; no new inference about the billed reasoning/output split or total monetary charge. Retain only sanitized metadata; do not commit prompts, Authorization or raw provider responses.

**Local private sanitized evidence:** `E:\\b14-3554-sensenova-once-20261010-safe-evidence.json`; single-use lock `E:\\b14-3554-sensenova-once-20261010.lock`. Durable GitHub evidence: [issue #3554 success record](https://github.com/skerishKang/ai-revenue-lab/issues/3554#issuecomment-6095917323). **Do not rerun** this one-shot probe. New paid calls, current deployed SHA attestation, native SenseNova parameters, Claw/Engine, SSE, ten-case QKR or customer PDF E2E are independently gated.

## 1. Account plan, provider access and serving model are different dimensions

| Exact registered model | Account facts (Owner-reported 2026-10-10) | Model-specific proof missing | Gate |
|---|---|---|---|
| `sensenova/sensenova-6.8-flash-lite` | Paid account, ample credits. Exact remaining credit/value and per-model unit pricing **UNKNOWN** | Whether latest Core/Gateway parameters work on the currently deployed route; live rate limits and output budget | **FIRST COMPLETED** on 2026-10-10; further paid calls separately gated |
| `kira/qwen3.8-flash-free` | Paid Kira account; Owner reports **10,000,000 tokens refreshed daily**. Do **not** claim this is the quota for this particular model | [Kira official API subscriptions](https://kiraai.vn/) specify included subscription tokens **only for upstream IDs prefixed `kira-`**. This exact B14 *upstream* `qwen3.8-flash-free` is **not `kira-` prefixed**. Its promo admission, subscription applicability, partner wallet billing, actual available budget and RPM/RPD remain **UNKNOWN** | **SECOND**, confirm per-model charging/entitlement then seek separate paid-call approval |
| `experiential/qwen3.8-flash-next-uncensored` | Owner reports current access restriction is **suspected**, historical B14 HTTP429 seen | 429 class: hard quota vs rate window vs provider busy, reset time, account scope; promotion does not prove present admission | **HOLD: zero requests, zero retries**, resume only after independent account-side evidence or separate Owner authorization |

The `-free` suffix is the exact **model slug**, not a guarantee that an Owner's provider account or the model is free. No live account token number or sensitive balance should be committed. No dormant model becomes disabled, removed, automatically replaced, or zero-ranked.

## 2. Previously completed proof: do not repeat

- Kira direct Provider authenticated test on 2026-10-10 returned **HTTP200, `OK`, `finish_reason=stop`** in ~4.74 s, with returned usage from that historical request (see `B14_KIRA_QWEN38_FLASH_FREE_ONBOARDING_2026-10-10.md`). This was a **direct Kira test**, not a current B14/Engine/Claw Production confirmation.
- SenseNova 2026-10-09 B14 routing **10/10** completed Korean QKR cases and vendor-direct evaluations **10/10** plus four reasoning-mode batches. Those were historical settings; new Core native-field passthrough #4119 source merge and current served build were not proven by the earlier measurement.
- ExLab historical 429 is an **availability/entitlement**, not model reasoning, outcome. Additional 429-inducing calls are unnecessary now.

## 3. Proposed execution — each paid/live POST separately gated

1. **Read-only preparation (authorized now):** compare exact current `main` model IDs, Provider/origin, deployed Production SHA, route capability, key-binding *presence indicators only*, and account dashboard quota / billing scope without exposing keys or raw balances. This document does not authorize retrieving the secret contents or changing bindings.
2. **Separate Owner paid-provider-call approval required before any POST**, with exact provider, number of calls, max cost/exposure and execution environment. Default proposal: **one** SenseNova non-stream text completion, and **one** Kira completion later, after the subscription/model entitlement is confirmed. ExLab **zero**. Do not reuse an approval for unrelated Provider/model or Production deployment.
3. **Proposed bounded request** (not executed here): one synthetic Korean question asking for the literal answer `OK`, exact selected B14 ID, manual route, `max_attempts=1`, `max_retries=0`, `allow_external_fallback=false`. Explicit `max_tokens=1024` or lower only if confirmed sufficient and permitted by the active Core 4096 product compatibility ceiling. Omit `temperature`, `reasoning_effort` and provider-native options on first pass; do not invent defaults. This is a **bounded diagnostic setting**, not the model's official recommended default and may cause reasoning-budget exhaustion (classify separately). **No streaming and no PDF** on this initial connectivity request.
4. On an explicitly authorized single call, capture only sanitized evidence: `model_id`, `provider_id`, exact selected upstream, committed deployment HEAD, HTTP status, elapsed milliseconds, whether content is nonblank, `finish_reason`, public usage counts if returned, attempt count (=1), fallback used (=false), normalized error category. Preserve no raw Authorization, token/key, provider-controlled error body, internal billing identifiers or user content.
5. **Verdict:** HTTP200 + nonempty text + matching model identity + valid finish is **CONNECTIVITY_PASS only**; not a quality score, per-model maximum output proof, 10-case benchmark or customer production ready. HTTP200 with blank text is **EMPTY_ANSWER_FAIL**, possibly explicit budget exhaustion if finish indicates `length`. 429 = **RATE_LIMIT_OR_CAPACITY_UNCLASSIFIED** until provider/account evidence distinguishes quota and busy. 504/timeouts = **NETWORK_OR_GATEWAY_TIMEOUT**, not intelligence score. Auth 401/403 must fail closed. Never auto retry, expand tokens or switch models.
6. **Independent later approvals:** Live B14 route and Engine/Claw E2E, SSE, model-specific native option tests, Korean quotation QKR 10-case evaluation and **Production deployment** are separate from a direct vendor POST. A merge to main does not update Production; a previous success does not certify the current revision.

## 4. Historical pre-approval no-call snapshot (superseded for the one SenseNova test above)

```text
B14_OWNER_QUOTA_DATE=2026-10-10
MODEL_COUNT_CANONICAL=11
RETEST_PRIORITY_1=sensenova/sensenova-6.8-flash-lite
RETEST_PRIORITY_2=kira/qwen3.8-flash-free
RETEST_HOLD=experiential/qwen3.8-flash-next-uncensored
PAID_PROVIDER_CALL_APPROVAL=NOT_GIVEN
LIVE_PROVIDER_POST_EXECUTED=0
SECRETS_READ_OR_CHANGED=0
PRODUCTION_MUTATION=0
AUTO_FALLBACK=0
```

Reference owners: [#3554](https://github.com/skerishKang/ai-revenue-lab/issues/3554) (real response / E2E), [#2676](https://github.com/skerishKang/ai-revenue-lab/issues/2676) (model evaluation), [#3977](https://github.com/skerishKang/ai-revenue-lab/issues/3977) (serving exact provider metadata). Registered IDs and payer credentials are independent; protect account information.
