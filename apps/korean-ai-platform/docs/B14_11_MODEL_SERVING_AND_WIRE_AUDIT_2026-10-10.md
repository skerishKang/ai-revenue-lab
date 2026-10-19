# B14 canonical 11-model serving evidence and wire audit (2026-10-10)

Issue: [#3977](https://github.com/skerishKang/ai-revenue-lab/issues/3977). Baseline: latest `main` at audit start `c234011684b16c8d18ad6b3c4224442d1f0392e2`. **This is a code-source and simulated-wire audit, NOT a live provider test or production certification.**

## Evidence and semantic boundaries

The authoritative registry is `app/pilot/b14_models.json`, not historic evaluation models. `model_serving_evidence.py` attaches first-party official model metadata and Owner-observed Google quota history; `model_native_parameters.py` has a narrow exact-ID optional-field allowlist. `context_window=0` below means **UNKNOWN**. `context_window` is catalog metadata and not proof of the deployed provider's accepted input length. No registered model has a demonstrated serving-provider maximum output in the current evidence source. Do not infer current free status from the existence of a registered key or historical promotion.

| Exact registered B14 ID | Serving provider | Catalog context tokens | Catalog input capabilities | Native optional overrides currently documented in B14 | Manufacturer card max output | Serving API max output |
|---|---|---:|---|---|---|---|
| `agnes-ai/agnes-3.0-flash` | Agnes AI | UNKNOWN | chat, coding | UNKNOWN | UNKNOWN | UNKNOWN |
| `atria/Atria-Dawn-Preview` | Atria | UNKNOWN | chat | `reasoning_effort=low/medium/high` | UNKNOWN | UNKNOWN |
| `google/gemini-3.1-flash-lite` | Google AI Studio | 1,048,576 | chat, coding, image | `reasoning_effort=minimal/low/medium/high` | 65,536 | UNKNOWN |
| `google/gemini-3.5-flash-lite` | Google AI Studio | 1,048,576 | chat, coding, image | `reasoning_effort=minimal/low/medium/high` | 65,536 | UNKNOWN |
| `google/gemma-4-26b-a4b-it` | Google AI Studio | 262,144 | chat, image | UNKNOWN | UNKNOWN | UNKNOWN |
| `google/gemma-4-31b-it` | Google AI Studio | 262,144 | chat | UNKNOWN | UNKNOWN | UNKNOWN |
| `inception/mercury-2.5` | Inception | UNKNOWN | chat | UNKNOWN | UNKNOWN | UNKNOWN |
| `poolside/laguna-s-2.1` | Poolside | 1,000,000 | chat, coding, long_context | UNKNOWN | UNKNOWN | UNKNOWN |
| `sensenova/sensenova-6.8-flash-lite` | SenseNova | 256,000 | chat, coding | `top_p,top_k,min_p,presence_penalty,repetition_penalty` | UNKNOWN | UNKNOWN |
| `experiential/qwen3.8-flash-next-uncensored` | Experiential Labs | 262,144 | chat, coding | UNKNOWN | UNKNOWN | UNKNOWN |
| `kira/qwen3.8-flash-free` | Kira AI | 1,000,000 | chat | UNKNOWN | UNKNOWN | UNKNOWN |

The capability names and context sizes above are copied from the **internal registry**; treat them as internal catalog claims rather than newly independently revalidated vendor capabilities. Official Google model IDs and URLs: [Gemini 3.1 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite), [Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite), [Google-hosted Gemma](https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api), and [OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai). Native option evidence currently also references [SenseNova 6.8 API](https://github.com/OpenSenseNova/SenseNova6.8/blob/main/API.md). Other supplier-specific provenance/variant classifications remain **UNKNOWN** in `model_serving_evidence.py`, even if registry source descriptors refer to prior studies.

## Separate Google AI Studio account quota observation

On **2026-10-09**, Owner observed these **Free-tier project** figures. These are not hardcoded live rate limits, current remaining quota, or general vendor guarantees.

| Exact Google model | RPM | Input TPM | RPD |
|---|---:|---:|---:|
| `google/gemini-3.1-flash-lite` | 15 | 250,000 | 500 |
| `google/gemini-3.5-flash-lite` | 15 | 250,000 | 500 |
| `google/gemma-4-26b-a4b-it` | 30 | 16,000 | 14,400 |
| `google/gemma-4-31b-it` | 30 | 16,000 | 14,400 |

Reconfirm currently assigned quotas and remaining usage in the [AI Studio dashboard](https://aistudio.google.com/rate-limit); use Google's [rate-limit guide](https://ai.google.dev/gemini-api/docs/rate-limits) for the three separate dimensions. Output-card maxima, input TPM, requests/day, and explicitly requested `max_tokens` are different quantities.

## Request path and validation

The Gateway preserves omitted `temperature` and `max_tokens` as `None`; both completed and SSE platform adapters omit those keys from outbound JSON. Explicit native options are validated by exact registered model against the fail-closed allowlist; unsupported options raise an error. Model ID, upstream model, serving origin and provider are distinct identities. No automatic model substitution was added.

`tests/test_3977_eleven_model_wire_parity.py` exercises **all 11** exact ID/provider/upstream tuples using synthetic `httpx.MockTransport`, with no real credential, upstream POST, deployment, or billed usage. It checks exact model selection, absence of implicit sampling/output/reasoning fields, non-stream/SSE response format parity, and the rule that HTTP 200 with empty user-visible text fails rather than passing.

## Remaining acceptance gaps

- **Official evidence**: exact served-variant provenance and per-field support for the other seven models, vendor-specific accepted `max_tokens`, and independent API-serving maximum output/context evidence for all 11.
- **Rate limits**: non-Google RPM/input-TPM/RPD and current quota/balance UNKNOWN; historic Owner Google snapshot must not be used as automatic throttling configuration.
- **Live proof**: no approved paid POSTs, no new Secrets access, no Production deployment or actual Engine/Claw end-to-end quality proof. Mock HTTP 200 never substitutes for live-provider acceptance.
- **Status interpretation**: a transient provider 429 or timeout/504 is not an intelligence score; a 200 with empty text is not a correct answer. Track live/production acceptance in [#3554](https://github.com/skerishKang/ai-revenue-lab/issues/3554).
