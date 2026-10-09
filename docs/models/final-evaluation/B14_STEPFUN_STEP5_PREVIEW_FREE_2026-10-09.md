# StepFun Step 5 Preview Free — 2026-10-09 bounded model evaluation

**Verdict: DIRECT_KILO_FREE_QKR_10/10_PASS / ZERO_429_IN_THIS_SAMPLE / B14_REGISTRATION_NOT_DONE / CUSTOMER_READY_UNPROVEN.**

## Current canonical availability and pricing

- Read-only direct Kilo Gateway `GET https://api.kilo.ai/api/gateway/models`: HTTP200, 401 catalog models at query time. The **exact free upstream** `stepfun/step-5-preview-free` was present with prompt=0, completion=0 and advertised context window 1,000,000 tokens.
- The distinct `stepfun/step-5-preview` catalog entry was **paid** (nonzero input and output prices). **No POST was addressed to this paid route**, no authorization or credit-bearing API key was sent. Kilo's public documentation describes anonymous access to free models and an IP-based free-model limit, but dynamic rate limits and provider admission may vary.
- All direct anonymous free-route responses included `model=stepfun/step-5-preview` and `provider=StepFun`; this is the **underlying model name reported by the Gateway**, not evidence of a paid POST or permission to silently substitute a model. The request, free catalog route, no-key condition and exact response-model distinction are preserved separately.
- B14's deployed **nine-model** canonical registry does **not** include the proposed manual ID `kilo/stepfun/step-5-preview-free`. Therefore this direct provider/Gateway trial is not B14 production routing proof, and it is not a worker secret/config deployment.

## Live synthetic QKR quote extraction — 10-case fixed corpus

- Actual direct `POST https://api.kilo.ai/api/gateway/chat/completions`, with `model=stepfun/step-5-preview-free`, 1 request for each QKR-001..010, temp=0, max_tokens=3500. Same existing QKR benchmark corpus/prompt and strict B66 normalization/grade machinery used for the Mercury/Gemini/SenseNova B14 comparisons. No retry, no fallback, no saved raw provider answer or original customer data.

| Metric | Bounded result |
|---|---:|
| Requested quote cases | 10 |
| Gateway HTTP200 | **10/10** |
| Strict QKR field/item PASS | **10/10** |
| HTTP429 / HTTP504 | **0 / 0** |
| Normal response latency median | **4.05 s** |
| Fastest / slowest | **3.53 / 10.78 s** |
| QKR-008 12 original item names/qty/prices | **PASS** |

### Case-by-case evidence

| Case | HTTP | Strict QKR | Total response |
|---|---:|---|---:|
| QKR-001 | 200 | **PASS** | 3.62s |
| QKR-002 | 200 | **PASS** | 5.22s |
| QKR-003 | 200 | **PASS** | 3.98s |
| QKR-004 | 200 | **PASS** | 3.98s |
| QKR-005 | 200 | **PASS** | 3.59s |
| QKR-006 | 200 | **PASS** | 3.53s |
| QKR-007 | 200 | **PASS** | 4.11s |
| QKR-008 | 200 | **PASS** | 7.89s |
| QKR-009 | 200 | **PASS** | 10.78s |
| QKR-010 | 200 | **PASS** | 4.98s |

## Historical 429, identity and comparison boundaries

- Earlier historical **Draft PR #3835** attempted a *different ten-task suite* (quote implementation, money math, HTML, Python). The free route returned **HTTP429 10/10, no provider answer**. That score is **UNASSESSABLE**, never 0/10 quality. Today's exact free route did not return a 429 on ten QKR extraction tasks; this does **not** explain why the prior admission failed and does not guarantee continuous uptime.
- The first isolated test request today returned HTTP200 but could not be graded initially because the Gateway echoed the underlying `stepfun/step-5-preview` rather than the requested free-route string. A second short metadata-only diagnostic confirmed the same underlying name from an **anonymous, no-key free-ID POST**. Only after explicitly allowing that documented observed identity **without changing request routing** was a fresh full ten-case QKR round conducted. Those two separate diagnostic requests are **not included** in the ten-case quality table.
- Recent [B14 same-case comparison](B14_SAME_CASE_MODEL_COMPARISON_2026-10-09.md), PR #3944: Mercury 9/10 strict, 10/10 HTTP200, median 3.87s; Gemini 3.5 Flash Lite 7/10 strict and SenseNova 6.8 Flash Lite 7/10 strict, both 3 HTTP504 and medians 6.55s/6.77s. **This StepFun trial is direct Kilo gateway**, not B14 Worker, so the samples differ by routing, timing, provider admission and possibly limits. It would be inaccurate to announce StepFun as the new B14 production winner yet.
- Kilo public free catalog exposes `reasoning` and `include_reasoning` for the free Step 5 route, but **not `reasoning_effort`**. No direct low/medium/high passthrough or PDF was tested. Do not assume compatibility with Atria/Gemini effort controls.

## CTO owner-facing next gate

1. **Model candidate state: EVALUATION_PASS / RECOMMENDED_FOR_B14_MANUAL_ONBOARDING**, not CUSTOMER_READY, DEFAULT or AUTO. Keep the owner as the chooser, preserve the exact free route and no silent paid substitution.
2. Rebuild historical **stacked Draft #3835** against fresh current `main` as a separate narrowly scoped registration change, not a blind merge of the old 20-file stack. Validate the canonical nine-to-ten model JSON contract, free URL identity, no auth/paid fallback, and owner-controlled manual model selection.
3. Run a **bounded single-message live B14 Worker exact-model canary** only after source + registry CI, explicit deployment gate and free-route readiness checks. Repeat ten-case B14 run if canary matches the free route. Long-term rate reliability, Atria-style reasoning, B66 quote construction/PDF remain separate evidence gates.
4. Retain 429 history; on any future 429 stop free-route trial and record whether it is Kilo IP hourly cap or provider-level exhaustion if response metadata proves the origin. No automatic paid promotion.

## External documentation

- <https://kilo.ai/docs/gateway/api-reference> — public Gateway /models and error codes.
- <https://kilo.ai/docs/getting-started/using-kilo-for-free> — free model volatility, authenticated/anonymous free usage.
- <https://github.com/Kilo-Org/kilocode/blob/main/packages/kilo-docs/pages/gateway/usage-and-billing.md> — free model requests rate-limited per IP, HTTP429 policy.
- <https://platform.stepfun.com/> — Step 5 Preview upstream model family.

**Reproducibility:** `E:\b14-stepfun-free-check-v2-20261009.py` and metadata `E:\b14-stepfun-free-20261009-V2-evidence.json` remain local. Repo includes only sanitized per-case metadata in `evidence/STEPFUN_STEP5_FREE_2026-10-09_METADATA.json`. This report does not alter B66 implementation, B14 registry, Worker, customer data, provider keys or production routing.
