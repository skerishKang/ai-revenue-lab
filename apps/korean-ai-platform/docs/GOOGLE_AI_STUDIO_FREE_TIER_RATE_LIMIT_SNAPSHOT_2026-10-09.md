# Google AI Studio Free-tier model quota snapshot — 2026-10-09 (#3977)

## Authority and scope

These numbers were **observed in the Owner's Google AI Studio project on 2026-10-09** and passed to CENTRAL. They are **not** an immutable Google promise, an output token budget, a currently remaining quota, or a live vendor-acceptance result. For the active project/tier, re-check the [Google AI Studio Rate Limit dashboard](https://aistudio.google.com/rate-limit).

| Exact B14 model | RPM | Input TPM | RPD | Snapshot |
| --- | ---: | ---: | ---: | --- |
| `google/gemini-3.1-flash-lite` | 15 | 250,000 | 500 | Owner-observed 2026-10-09 |
| `google/gemini-3.5-flash-lite` | 15 | 250,000 | 500 | Owner-observed 2026-10-09 |
| `google/gemma-4-26b-a4b-it` | 30 | 16,000 | 14,400 | Owner-observed 2026-10-09 |
| `google/gemma-4-31b-it` | 30 | 16,000 | 14,400 | Owner-observed 2026-10-09 |

RPM = requests per minute. Input TPM = **input** tokens per minute; not output-token cap. RPD = requests per day.

## Contract separation — never conflate

1. **Original manufacturer model spec**: Gemini 3.1/3.5 Flash-Lite manufacturer max output = 65,536 tokens (official model cards).
2. **Exact Google AI Studio serving quota**: observed RPM, input TPM, RPD above, subject to project/tier/model revision. Google states API limits are applied per **project**, not per key; model-specific quotas exist. RPD resets at **midnight Pacific time**, not midnight in Korea.
3. **Serving model's max output tokens**: **UNKNOWN until separately evidenced**, even where the manufacturer card states 65,536.
4. **Product-requested `max_tokens`**: its own explicitly chosen budget; do not substitute output max, input TPM, RPD, or a hardcoded 4,096 cap.
5. **Remaining usage**: not measured in this source-only work. Do not calculate remaining RPD without live usage authority.

Source of general quota semantics: [Google Gemini API Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits). Source of **these four exact numeric quotas**: Owner's 2026-10-09 Google AI Studio dashboard report, **not** Google's evergreen documentation.

## Implementation

Read-only typed metadata: `app/pilot/model_serving_evidence.py::GoogleAIStudioFreeTierSnapshot`. It is attached only to exact first-party Google model IDs with the official Google serving origin and unchanged upstream model code. Third-party variants and the other seven B14 registered models stay `None` (unknown quota).

**No production limiter, automatic fallback, billing activation, API-key access, requests or model-scoring behavior is introduced by this snapshot.** 429 errors indicate quota/capacity/availability rather than model answer quality. Before shipping a quota-aware dispatcher, obtain current per-project limit and usage evidence and authorize that *separately*.
