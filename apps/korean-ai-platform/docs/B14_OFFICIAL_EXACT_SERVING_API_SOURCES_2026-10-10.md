# B14 serving-provider exact-route official evidence — 2026-10-10

Issue [#3977](https://github.com/skerishKang/ai-revenue-lab/issues/3977); continuation of [#4115](https://github.com/skerishKang/ai-revenue-lab/pull/4115) and [#4119](https://github.com/skerishKang/ai-revenue-lab/pull/4119).

## Interpretation rules

This document reports publicly verifiable *serving-provider* claims. A manufacturer/model card, the currently registered platform route, the actual provider API contract, product request budget and live account's remaining quota are distinct. Official advertised output-parameter ceiling does **not** prove the API can successfully generate a non-empty completion that long. This change is **read-only metadata** with no vendor POST, key access, credential changes, runtime routing or auto model selection.

The new `ServingModelEvidence.verified_serving_api` field is attached only on an exact `(model_id, provider_id, upstream_model, base_origin)` match; renamed upstreams or altered hosts fail closed. Existing `provenance_status` for all seven non-Google registrations remains **UNKNOWN**, since a model being listed by a serving provider does not prove its underlying base model, training lineage or fork status.

## Direct original serving sources, not inferred upstream equivalents

| Exact B14 model / serving provider | Primary source and what it actually proves | Still UNKNOWN |
|---|---|---|
| `atria/Atria-Dawn-Preview` / Atria | [Atria's own API docs](https://api.atria-asi.ai/docs): `https://api.atria-asi.ai/v1/chat/completions`; exact case-sensitive `Atria-Dawn-Preview` ID; **256,000 context tokens**; text-only input; Chat Completions request `max_tokens` / `max_completion_tokens` **accept 1–65,536** | Guaranteed single-answer length, independently measured serving max generated tokens, current quota, underlying model-variant lineage |
| `sensenova/sensenova-6.8-flash-lite` / SenseNova | [OpenSenseNova international/China regional guide](https://github.com/OpenSenseNova/SenseNova-Skills/blob/main/INSTALL.md): international `https://token.sensenova.ai/v1` is **correct**, China mainland uses distinct `https://token.sensenova.cn/v1`; same exact model ID, regional keys not interchangeable. [Vendor request documentation](https://github.com/OpenSenseNova/SenseNova6.8/blob/main/API.md) details optional sampling and SSE output | Account RPM/TPM/RPD, served max output, differences among regional endpoints beyond documented contract. **Do not replace .ai with .cn** |
| `poolside/laguna-s-2.1` / Poolside | [Poolside official models page](https://www.poolside.ai/models) explicitly shows `https://inference.poolside.ai/v1` and `poolside/laguna-s-2.1`; promotion described as **free for a limited time** | **Hosted** context/output maxima, continuing free plan. Example's **131,072** refers to a *local/self-hosted* Docker inference display and must NOT replace hosted context metadata |
| `inception/mercury-2.5` / Inception | [Inception official models page](https://www.inceptionlabs.ai/models): exact `mercury-2.5` POST to `https://api.inceptionlabs.ai/v1/chat/completions`; advertises **260K** context (preserved as a label, not silently converted to an exact token count). Also lists trial-token offer | Exact integer context limit, API max output, current free trial balance. Trial allotment does not imply zero-cost permanent usage |

## The remaining three of seven non-Google IDs

- `agnes-ai/agnes-3.0-flash`: official open-weight **Preview** model information cannot automatically establish the distinct production/API serving checkpoint or its limits. Exact serving API output and provider-specific supported options remain UNKNOWN.
- `experiential/qwen3.8-flash-next-uncensored`: previous recorded vendor-model GET and registry tuple remain intact, but up-to-date publicly verifiable exact-fork specification is still insufficient here. Never inherit original Qwen native overrides without vendor evidence.
- `kira/qwen3.8-flash-free`: recorded historical HTTP 200 and a time-limited free promotion do not certify unlimited free requests, native options or hosted token output ceilings.

For Google four exact registered IDs, retain [Google AI Studio historical Owner-observed Free tier snapshot](GOOGLE_AI_STUDIO_FREE_TIER_RATE_LIMIT_SNAPSHOT_2026-10-09.md): RPM/input TPM/RPD values observed on 2026-10-09 are **not a live balance**; two original Gemini cards each state 65,536 manufacturer maximum output but the actual serving API output acceptance remains UNKNOWN in B14 evidence.

## Scope, safeguards and required next proof

Metadata only; no changes to `b14_models.json`, Gateway, Core, product UI, request dispatcher or Production. The newly documented Atria API request limit **does not change** the shared Core's conservative explicit output request ceiling of 4096 and is **not** automatically sent on omitted requests. Test for spoofed hosts/upstream aliases, no inherited limits, source-date preservation and existing Google snapshots.

Before any claim of full model support, collect authorized exact-provider API evidence for non-stream/SSE with *nonempty answer*, supported explicit parameters, token usage, finish reason, error classification and actual account availability, then validate Engine/Claw integration under [#3554](https://github.com/skerishKang/ai-revenue-lab/issues/3554). Never score HTTP429/504 infrastructure failure as zero model intelligence.
