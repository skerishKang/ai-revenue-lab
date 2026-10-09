# B14 -> B66 current approved-model evaluation protocol (2026-10-09)

Status: SOURCE-ONLY PROCESS CONTRACT. No credentials provisioned here, no model/provider called, and no customer tier, Production, Auto or fallback approved. Source selection: apps/korean-ai-platform/app/pilot/b14_models.json on current main.

## Purpose: what to benchmark

B66 has two separate tasks. Never use the quality of an AI-generated HTML or PDF as the grade for REPEATED quotation generation.

**Onboard once:** a document-capable development/analysis model interprets an existing source document and helps build a source-derived reusable quotation Skill. Independently certify structure, font, branding/logo/stamp, source reproduction and mutation. Sol 6.1 previously built a certified CGI source-derived renderer, but that provenance does not automatically make Sol the default repeat-request inference model.

**Repeat many times:** user message -> optional model-based extraction of NEW recipient, quote facts, item names, specifications, quantity, unit price and corrections -> user confirmation if ambiguous -> B66 QuoteDraft -> QuoteCore computes totals, discount/tax and validation -> assigned Saved Quote Skill -> certified deterministic PDF generator. If the user enters all structured fields directly, SKIP model inference. No repeated layout analysis, HTML reconstruction or document certification.

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

## Stage 2. Rendering quality is assessed separately

Certified source-derived template fidelity belongs to B66 #3180/#3542/#3595 and multipage development #3839. Existing CGI Sol reference is certified only for a single A4 page of 1-3 rows; the final B66 product requires arbitrary practical item counts and dynamic pages. The chosen repeat-interpretation model does NOT create PDF pages; the existing renderer/compiler executes deterministic code. For exact quote data, compare B66 HTML preview, QuoteCore values, downloadable PDF, page count, confidential source text and visual fidelity. Never classify PDF-code execution as an AI model's inference score.

## Release boundaries

A new live evaluation requires Owner-approved provider credentials, explicit authorized exact-model selection, served-version/preflight gates and bounded synthetic prompts. This document does not authorize running the nine models or any Production POST now. Keep the historic five-candidate benchmark for offline research only, and reject Motif/Luna/all-five in all paths that can send a live request. Preserve the five Owner exclusions when editing models, workflows, B66 or Claw.
