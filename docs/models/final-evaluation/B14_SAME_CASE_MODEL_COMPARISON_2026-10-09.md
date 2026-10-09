# B14 model quality and availability — 2026-10-09 same-case re-evaluation

**Status:** COMPLETED_BOUNDED_MEASUREMENT / RECOMMENDATION_ONLY — no routing/default/model registry change, no production deployment.

## 1. Exact experimental conditions

- Actual production B14 `POST /api/pilot/v1/chat/completions`, 3 explicit model IDs; source and strict scoring pinned to `main` SHA `de447841f0df4b3ddf0cdc50ac6fc4ff467f5f83` (scoring corpus and normalizer unchanged through report base merge).
- Same **QKR-001..010** fixed synthetic Korean quote corpus, same refreshed verbatim-item-name extraction prompt `PROMPT_HEADER`, **actual newline** separating context and user prompt; `temperature=0`, `max_tokens=3500` for every test.
- Exactly **one HTTP POST per model per case**, no retry, no fallback, no re-routed model. Model ID and upstream model checked against Production GET catalog before running; response metadata validates selected model and upstream, attempt_count=1, fallback_used=false.
- Each model's 10 requests made sequentially; outputs graded through unchanged `grade_case` / canonical B66 `quote-extraction.js` strict field/item normalization. Successful HTTP with absent/incomplete content is **not** accuracy PASS. HTTP504 is availability failure, **not** a fabricated wrong answer.
- An earlier first Mercury run used a **literal backslash-n** between header and case and `max_tokens=1800/2400`; it had **5/10 strict / 8/10 HTTP200**, but **is excluded from comparable scores** because input serialization and output budget differ. Raw metadata retained locally, not silently overwritten.
- This is an n=10 smoke per model, not an account-wide reliability/SLA estimate. Existing earlier Gemini minimal/medium 10/10 and SenseNova 10/10 results remain valid as *separate historical samples* with different model settings.

## 2. Fresh Production B14 comparison (V2, uniform prompt and budget)

| Model (exact manual choice) | Requested | HTTP200 | Strict quote PASS / all attempts | Correct / completed response | HTTP504 | Median of HTTP200 requests |
|---|---:|---:|---:|---:|---:|---:|
| `inception/mercury-2.5` | 10 | **10/10** | **9/10** | 9/10 | **0** | **3.87s** |
| `google/gemini-3.5-flash-lite` | 10 | **7/10** | **7/10** | 7/7 | **3** | **6.55s** |
| `sensenova/sensenova-6.8-flash-lite` | 10 | **7/10** | **7/10** | 7/7 | **3** | **6.77s** |

**Mercury QKR-008 is the single strict FAIL in the valid V2 round.** All 12 item names, recipient, project and issue date passed; **nine quantity/unit-price item field checks failed**, so accuracy is 9/10 despite 10/10 HTTP200. It is not the old whitespace-only name error.

**Gemini and SenseNova**: all seven responses that completed scored strict PASS (7/7 conditional accuracy); each had three `HTTP504/upstream_timeout` outcomes in this sample. This does not establish the failing provider-specific phase or erase earlier 10/10 successful rounds.

## 3. Case-by-case result matrix

| Case | Mercury 2.5 | Gemini 3.5 Flash Lite | SenseNova 6.8 Flash Lite |
|---|---|---|---|
| QKR-001 | PASS | PASS | HTTP504 |
| QKR-002 | PASS | HTTP504 | PASS |
| QKR-003 | PASS | PASS | PASS |
| QKR-004 | PASS | PASS | PASS |
| QKR-005 | PASS | PASS | HTTP504 |
| QKR-006 | PASS | PASS | PASS |
| QKR-007 | PASS | PASS | PASS |
| QKR-008 | FAIL | PASS | HTTP504 |
| QKR-009 | PASS | HTTP504 | PASS |
| QKR-010 | PASS | HTTP504 | PASS |

## 4. Atria Dawn Preview reasoning effort and streaming (DIRECT PROVIDER ONLY)

Atria official documentation: <https://api.atria-asi.ai/docs> and its documented OpenAI/Codex client config describe direct Chat Completions, SSE and low/medium/high reasoning profiles. Tested **`https://api.atria-asi.ai/v1/chat/completions`** using the locally authorized Atria key, exact `Atria-Dawn-Preview`, `stream=true`, `temperature=0`, `max_tokens=3500`, identical synthetic QKR-001 and only one call for each level. No API key values or raw response body saved to Git.

| Explicit `reasoning_effort` | Provider HTTP | Stream `[DONE]` | Strict QKR-001 | Total time | First text delta |
|---|---:|---|---|---:|---:|
| `low` | 200 | YES | **PASS** | **22.17s** | 17.33s |
| `medium` | 200 | YES | **PASS** | **24.31s** | 19.97s |
| `high` | 200 | YES | **PASS** | **43.92s** | 37.70s |

- **Observed low > medium > high speed ranking (faster is better)** for this one quote; all three gave the same strict PASS. Higher effort did **not** improve the single-case result; this cannot prove higher effort has no value on harder prompts.
- Prior direct Atria `reasoning_effort=none` produced HTTP422; do not label `none` as a supported UI mode. Current official SDK examples describe low/medium/high, but API mode availability should always be verified by actual provider response.
- This is **DIRECT Atria API** proof, *not* confirmation that live B14 generic gateway forwards `reasoning_effort`. The B14 platform adapter's supported request payload currently forwards model/messages/temperature/max_tokens, not this option. B14 normal Atria QKR-001 had HTTP504; its separate streaming-preview returned one PASS after ~50.64s in a different run.
- For a user-facing reasoning toggle, add provider-specific opt-in only after gateway allowlist, live B14 pass-through, exact-mode response, latency and cancellation tests. Do not globally force a mode or silently switch providers.

## 5. CTO model application recommendation (no automatic selection)

1. **Complex Korean quote extraction — Mercury 2.5 is the best candidate in this new sampled round**: 9/10 strict and 10/10 HTTP200, ~3.87s median. Still requires strict Quantity/UnitPrice confirmation on multi-line QKR-008 and customer PDF owner tests; not a certified final model.
2. **Short conversational/minimal tasks — Gemini 3.5 Flash Lite remains a candidate**, based on prior separately documented minimal-reasoning results; its **current default-mode quote path** experienced 3/10 504s, so do not claim current unrestricted reliability or silently auto-select it.
3. **SenseNova — alternative manually selected candidate**. This run showed 7/10 due to three 504s but all completed quotes were correct; historical `reasoning=none` benchmark performed better. Re-evaluate configured reasoning modes and gateway timeout separately.
4. **Atria Dawn — advanced research/agent and optional deliberate streaming**, not the default synchronous quote path at its observed 22–44s direct latency. The explicit direct low setting is an interesting speed candidate; the current B14 reasoning-control path is not certified.
5. **Agnes 3.0 Flash — `ERROR_B14_HTTP429 / DEFERRED`** (#3913), unchanged. Do not auto-fallback into it.

**User-facing model choice remains manual**. This report gives recommended defaults only; it does not modify the B14 registry, route semantics, provider keys, model ordering, WAF, Worker or any B66 product code.

## 6. Remaining validation before production-grade model certification

- Separate B14 HTTP504 provider-phase provenance from 10-second client/gateway timing; one synthetic no-retry canary per model and exact model ID after any code or route change.
- Isolate Mercury QKR-008 quantity/unit-price mistakes without altering source item names or customer-confirmed amounts. Consider explicit numeric consistency questions rather than ungrounded automatic correction.
- Full 10-case repetition or wider statistically useful samples per model/settings; small single rounds cannot establish persistent model rankings.
- If requested: compare Atria direct low/medium/high on diverse complex prompts and implement **explicit user-controlled** B14 pass-through after source/security tests.

**Evidence locality:** `E:\b14-modelcompare-20261009` contains 3 V2 strict-metadata 10-case JSON files and Atria direct reasoning metadata. Earlier Mercury non-comparable V1 metadata retained separately. No secrets, customer data, raw answers, or customer PDFs included in Git.
