# B14 -> B66 current approved-model evaluation protocol (2026-10-09)

> **CURRENT SOURCE AS OF 2026-10-10:** Owner-added ExLab
> `experiential/qwen3.8-flash-next-uncensored` is the tenth canonical B14
> model (seven providers), with existing `PADIEM_EXLAB_API_KEY` binding.
> Previous nine-model references below refer to historical benchmark cohorts,
> not the current registry. ExLab model is listed for manual selection but
> **live dispatch is explicitly blocked** until ExLab model data policy review
> and a separate release approval; no automatic fallback, customer activation,
> changed tiers or Production deployment. Old B.AI Qwen and ExLab Luna remain
> retired. See
> `docs/models/final-evaluation/B14_EXLAB_QWEN38_NEXT_UNCENSORED_2026-10-10.md`.


Status: SOURCE-ONLY PROCESS CONTRACT. No credentials provisioned here, no model/provider called, and no customer tier, Production, Auto or fallback approved. Source selection: apps/korean-ai-platform/app/pilot/b14_models.json on current main.

## Purpose: what to benchmark

This protocol evaluates **one optional operation only: B14 interpretation of new free-form quotation facts**. It does not benchmark source-template engineering, an AI-designed page, or a PDF-producing model. Its stage boundaries are defined once in the
[B66 canonical stage-ownership table](../products/b66/README.md#stage-ownership--one-canonical-answer-for-sol-b14-and-final-pdf); model identity/permissions remain governed by the [Owner model policy §0A](MODEL_CHANGE_OWNER_APPROVAL_POLICY.md).

**Initial source onboarding (not this benchmark):** Sol 6.1 was a development/analysis and source-reproduction implementation tool for the previously certified CGI template. Independently certify the document-derived structure, fonts, branding/logo/stamp, mutations and layout. That engineering provenance does not establish a repeat-request Sol route or make Sol a production PDF generator.

**Customer repeats (this benchmark covers the interpretation step only):** when the customer uses natural language, one explicitly selected and permitted B14 model may extract new recipient, item name, specification, quantity, unit price and corrections. The user confirms ambiguity. When the customer has entered complete structured facts, **skip inference entirely**. In either case, QuoteDraft -> QuoteCore -> approved Saved Quote Skill -> deterministic renderer -> PDF. **B14 does not draw the PDF, Sol is not invoked per repeat, and neither model calculates totals/tax or recreates layout.** The actual PDF is rendered without model calls using the previously certified template. Never grade an AI-generated HTML/PDF as the quality of this interpretation task.

## Stage 0. Selection and authority

1. Fresh-read exact-main B14 canonical JSON. The command below must return current nine IDs. Any Owner-approved future addition/removal changes the JSON and passes model-registration gates before being evaluable.
2. List of names from Kilo CLI, web search, provider dashboard, historical issue or synthetic fixture is DISCOVERY ONLY. It never authorizes testing or silently changes a provider. Do not treat a free alias as interchangeable with the direct API.
3. The current Laguna route is Poolside direct: model ID poolside/laguna-s-2.1, upstream poolside/laguna-s-2.1, HTTPS origin https://inference.poolside.ai/v1. It requires an actual direct Poolside API credential for a live trial. Kilo Laguna aliases are retired, even if the CLI advertises them.
4. Other Owner-excluded models: B.AI Qwen, Motif 3, GPT-5.6 Luna, NVIDIA Nemotron, and **StepFun Step 3.7 Flash (all direct/Kilo aliases)**. An old evaluation script fixture containing these names is historical test evidence, NOT runtime authority. StepFun **Step 5 Preview Free** (#3835 historical Draft, #3947 direct free evaluation) is a different candidate, not among the current nine.
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
- Read-only 2026-10-09 Production discovery: exact-main source catalog 9 models but served `GET /api/pilot/models` returned **11** entries, including the five Owner-deleted IDs and retired Space Bunny, while all four current Google registrations were absent. The read-only GET guard correctly returns `BLOCKED_REGISTRY_DRIFT`, exit 4, `live_post_count=0`. Release blocker: [#3842](https://github.com/skerishKang/ai-revenue-lab/issues/3842), including the Worker JSON packaging failure. This source-only benchmark does not remedy that deployment issue and MUST NOT silently score that stale Worker as the nine approved models.
- No locally provisioned direct provider credential bindings were found for the 6 registered providers on the test PC (presence checks only). **Actual inference quality per model: NOT TESTED**, not failed. After separately approved canonical B14 deployment and credential readiness, use one explicit owner-selected exact model at a time with bounded real inputs, no retry/fallback, and preserve measured availability and error codes independently of quality.

Offline commands from the repository root:

    python .github/scripts/b66_quote_model_benchmark.py --list
    python .github/scripts/b66_quote_model_benchmark.py --preflight-live-get
    python .github/scripts/b66_quote_model_benchmark.py --model agnes-ai/agnes-3.0-flash --prompt QKR-001
    python -m pytest .github/tests/test_b66_quote_model_benchmark.py -q
## Stage 2. Rendering quality is assessed separately

Certified source-derived template fidelity belongs to B66 #3180/#3542/#3595 and multipage development #3839. Existing CGI Sol reference is certified only for a single A4 page of 1-3 rows; the final B66 product requires arbitrary practical item counts and dynamic pages. The chosen repeat-interpretation model does NOT create PDF pages; the existing renderer/compiler executes deterministic code. For exact quote data, compare B66 HTML preview, QuoteCore values, downloadable PDF, page count, confidential source text and visual fidelity. Never classify PDF-code execution as an AI model's inference score.

## Release boundaries

A new live evaluation requires Owner-approved provider credentials, explicit authorized exact-model selection, served-version/preflight gates and bounded synthetic prompts. This document does not authorize running the nine models or any Production POST now. Keep the historic five-candidate benchmark for offline research only, and reject Motif/Luna/all-five in all paths that can send a live request. Preserve the five Owner exclusions when editing models, workflows, B66 or Claw.
