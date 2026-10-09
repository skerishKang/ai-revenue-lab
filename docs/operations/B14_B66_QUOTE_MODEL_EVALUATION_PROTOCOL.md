# B14 -> B66 current approved-model evaluation protocol (2026-10-09)

Status: CURRENT B66 EXTRACTION EVALUATION PROCEDURE. Current source registry: apps/korean-ai-platform/app/pilot/b14_models.json. 2026-10-09 live results are recorded in [B14 model selection and evaluation standard](B14_MODEL_SELECTION_AND_EVALUATION_STANDARD_2026-10-09.md). This text is an evaluation protocol, not a release decision.

## Purpose: what to benchmark

This protocol evaluates **one optional operation only: B14 interpretation of new free-form quotation facts**. It does not benchmark source-template engineering, an AI-designed page, or a PDF-producing model. Its stage boundaries are defined once in the
[B66 canonical stage-ownership table](../products/b66/README.md#stage-ownership--one-canonical-answer-for-sol-b14-and-final-pdf); model identity/permissions remain governed by the [Owner model policy §0A](MODEL_CHANGE_OWNER_APPROVAL_POLICY.md).

**Initial source onboarding (not this benchmark):** Sol 6.1 was a development/analysis and source-reproduction implementation tool for the previously certified CGI template. Independently certify the document-derived structure, fonts, branding/logo/stamp, mutations and layout. That engineering provenance does not establish a repeat-request Sol route or make Sol a production PDF generator.

**Customer repeats (this benchmark covers the interpretation step only):** when the customer uses natural language, one explicitly selected and permitted B14 model may extract new recipient, item name, specification, quantity, unit price and corrections. The user confirms ambiguity. When the customer has entered complete structured facts, **skip inference entirely**. In either case, QuoteDraft -> QuoteCore -> approved Saved Quote Skill -> deterministic renderer -> PDF. **B14 does not draw the PDF, Sol is not invoked per repeat, and neither model calculates totals/tax or recreates layout.** The actual PDF is rendered without model calls using the previously certified template. Never grade an AI-generated HTML/PDF as the quality of this interpretation task.

## Stage 0. Selection and authority

1. Fresh-read exact-main B14 canonical JSON. The command below must return current nine IDs. Any Owner-approved future addition/removal changes the JSON and passes model-registration gates before being evaluable.
2. List of names from Kilo CLI, web search, provider dashboard, historical issue or synthetic fixture is DISCOVERY ONLY. It never authorizes testing or silently changes a provider. Do not treat a free alias as interchangeable with the direct API.
3. The current Laguna route is Poolside direct: model ID poolside/laguna-s-2.1, upstream poolside/laguna-s-2.1, HTTPS origin https://inference.poolside.ai/v1. It requires an actual direct Poolside API credential for a live trial. Kilo Laguna aliases are retired, even if the CLI advertises them.
4. Other Owner-excluded models: B.AI Qwen, Motif 3, GPT-5.6 Luna, NVIDIA Nemotron. An old evaluation script fixture containing those names is historical test evidence, NOT runtime authority. StepFun #3835 is a separate Draft, not among the current nine.
5. The nine models are registered, not automatically API-ready. Plus/Pro/Max groups are empty; a registration entry cannot imply pricing, a selected user plan, a paid fallback or a customer release.

Read-only commands from the repository root:

    python .github/scripts/b14_owner_evaluation_registry.py --list
    python .github/scripts/b14_owner_evaluation_registry.py --check poolside/laguna-s-2.1
    python .github/scripts/b14_owner_evaluation_registry.py --legacy-check motif

The third must reject the excluded selector with exit code 2. The source gate does not read secrets or invoke the provider. Under the historic comparative benchmark workflow, only surviving legacy selectors agnes/mercury/atria remain dispatch choices, and its actual live path executes this guard before any provider POST. The separate current-nine read-only selector does NOT authorize a new live batch.

## Stage 1. Evaluating the nine for repeat quote interpretation

Use an identical, synthetic Korean request corpus, identical schema, deterministic max-output/time budget and exactly one user-selected model per attempt. Do not transfer model IDs between providers; if a direct provider credential is missing or response unavailable, classify the candidate NOT_TESTED / UNAVAILABLE with the exact failure type. No hidden retry, automatic substitute, or fallback.

Test dimensions (with golden expected structured QuoteDraft records, not model-made PDF):

- Direct single-line quote with recipient, item name, quantity and unit price.
- Multi-line quotes with varied names, counts and units, including more than three line items; no arbitrary truncation.
- Korean edit/correction ("10개가 아니라 12개") overwrites the intended field only.
- Explicitly distinguish a price per item from a stated overall total; do not fabricate omitted unit prices.
- Missing/contradictory information must produce a clarification-needed result, not invented numbers.
- Numeric parsing (comma-separated won, Korean units such as 만 원, zero/large values) with unit price preserved.
- Korean business names and invoice dates faithfully copied, no leakage of previous customer's saved-template facts.
- Defensive behavior when unrelated text tries to override model routing/QuoteCore rules.
- Output exactly the documented QuoteDraft field schema; no model-assigned PDF renderer, invented taxes or price calculation.

**Scoring**: report per-field exact match (recipient, item name, quantity, unit price), item count/ordering, correction application, unknown/clarification correctness, instruction adherence and JSON/schema validity. A rejected, timed-out or rate-limited request is an availability failure (NOT a 0% reasoning score). Record model ID + exact provider/upstream, credentials-present boolean only, request count, successful responses, latency and safe hashes. Keep any raw customer payloads and API keys out of logs and artifacts. Source-only tests and legacy six-case benchmark are NOT evidence of nine-model quote performance.

Before customers use any candidate: inspect genuine successful responses, confirm no silent fallback and schema parity with QuoteCore. Only Owner may designate a default or approve release. Rankings must be based on real comparable live data, not intuition.

## 2026-10-09 executable ten-case Korean quote extraction benchmark

- Golden synthetic fixture: `.github/fixtures/b66_quote_interpret_v1.json` (10 prompts covering single/multiple item rows up to 12, corrections, missing unit prices, total-vs-unit-price ambiguity, Korean amounts, zero cost, date, and untrusted text).
- Read-only model/GET preflight and offline scoring implementation: `.github/scripts/b66_quote_model_benchmark.py`. It reads the **current exact nine-model central JSON**, then uses the **real B66 `quote-extraction.js` normalizer** to score recipient company, project, issue date, ordered items, quantities and unit prices. It never sends an inference POST, computes a total, recreates a template or executes paid fallback.
- Tests: `.github/tests/test_b66_quote_model_benchmark.py`; PR/main automated job `.github/workflows/b66-quote-model-benchmark.yml` is **OFFLINE ONLY**. Imported responses are explicitly labeled `IMPORTED_RESPONSE_NOT_ATTESTED_LIVE` and cannot produce a purported verified live model ranking.
- Historical blocker resolved: first GET showed 11 served IDs against nine canonical IDs. B14 #3842 packaging/deployment was fixed, and later GET preflight returned 9/9 MATCH. The earlier drift is no longer the current blocker.
- 2026-10-09 actual live evaluation completed: nine models times three QKR prompts = 27 requests, plus two finalists times seven additional QKR prompts = 14 requests, 41 total. Poolside direct 7/10 correct (HTTP200 9/10); Gemini 3.1 Flash-Lite 7/10 (HTTP200 10/10); Gemini 3.5 Flash-Lite and SenseNova 6.8 2/3 each; Agnes and Mercury 1/3 each; Atria and both Gemma 0/3 due to timeouts. See [#2676](https://github.com/skerishKang/ai-revenue-lab/issues/2676) and the current evaluation standard for exact per-case status. No score implies customer PDF readiness.

Offline commands from the repository root:

    python .github/scripts/b66_quote_model_benchmark.py --list
    python .github/scripts/b66_quote_model_benchmark.py --preflight-live-get
    python .github/scripts/b66_quote_model_benchmark.py --model agnes-ai/agnes-3.0-flash --prompt QKR-001
    python -m pytest .github/tests/test_b66_quote_model_benchmark.py -q
## Stage 2. Rendering quality is assessed separately

Certified source-derived template fidelity belongs to B66 #3180/#3542/#3595 and multipage development #3839. Existing CGI Sol reference is certified only for a single A4 page of 1-3 rows; the final B66 product requires arbitrary practical item counts and dynamic pages. The chosen repeat-interpretation model does NOT create PDF pages; the existing renderer/compiler executes deterministic code. For exact quote data, compare B66 HTML preview, QuoteCore values, downloadable PDF, page count, confidential source text and visual fidelity. Never classify PDF-code execution as an AI model's inference score.

## Release boundaries

Further live evaluation uses an explicitly selected allowed model ID, current served/source preflight, bounded identical QKR input and direct usage/status evidence. Score field accuracy separately from 429/504 availability. PDF layout and customer E2E remain separately assessed by B66. For actual evaluation findings see [current selection standard](B14_MODEL_SELECTION_AND_EVALUATION_STANDARD_2026-10-09.md).
