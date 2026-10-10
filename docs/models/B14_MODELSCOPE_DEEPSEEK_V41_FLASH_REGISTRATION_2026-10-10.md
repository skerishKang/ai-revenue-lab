# ModelScope — DeepSeek V4.1 Flash (B14 model #12) — 2026-10-10

**Scope:** one-time registration of a new ModelScope Provider, then ordinary JSON-only onboarding for future ModelScope models. [Issue #4176](https://github.com/skerishKang/ai-revenue-lab/issues/4176).

## Exact authority and source

| Field | Value | Evidence / limitations |
| --- | --- | --- |
| Serving platform | ModelScope API-Inference | https://www.modelscope.cn/models/deepseek-ai/DeepSeek-V4.1-Flash |
| B14 model ID | `modelscope/deepseek-ai/DeepSeek-V4.1-Flash` | Local unambiguous exact manual route |
| ModelScope upstream ID | `deepseek-ai/DeepSeek-V4.1-Flash` | **Case-sensitive** ModelScope full namespace |
| Serving base URL | `https://api-inference.modelscope.cn/v1` | ModelScope's published OpenAI-compatible API-Inference endpoint |
| Route | `POST /chat/completions` | Existing generic B14 provider adapter |
| Credential binding | `PADIEM_MODELSCOPE_API_KEY` | Separate ModelScope token; **not** the vendor DeepSeek API token |
| Security | `platform_secret`, HTTPS-only fixed host `api-inference.modelscope.cn` | Missing binding fails closed; redirect disabled; no key re-use |
| Known capabilities | `chat` | Image input, function calling, streaming *real service* not independently certified; streaming has only offline wire contract |
| ModelScope serving context | UNKNOWN (`context_window=0`) | Manufacturer model card's max is not hosted API's verified limit |
| Billing | UNKNOWN (`null` in price fields, no `free` tag) | Free trial is not permanent commercial free price |
| Daily quota | OWNER_EXPECTATION: **100+ requests/day** | **Not yet measured for this account/model/date**; consult actual ModelScope account page |
| Product availability | Source only until official release | No automatic fallback, no new Plus/Pro/Max assignment |

**Important:** The manufacturer DeepSeek API directly uses `https://api.deepseek.com` + model `deepseek-flash`. **Do not substitute that origin or model ID for ModelScope.** They are different billable accounts and contracts. DeepSeek's [September 2026 release note](https://api-docs.deepseek.com/news/news260910/) only identifies the manufacturer model, not ModelScope quotas.

**ModelScope official community API reference:** https://community.modelscope.cn/675262372db35d1195183bdb.html (2024-12-06; API-Inference base URL, free trial, SDK Token). It stated an account-wide **2,000 requests/day at publication**, but this is **historical, not verified as a current daily or per-model quota**. That same announcement warns that free API-Inference is aimed at developer exploration and should not be used as a high-concurrency, SLA-guaranteed production business API without a commercial provider agreement. Do not silently promote this endpoint into customer production readiness. **Owner account limits and allowed commercial use need independent confirmation.**

## Actual source changes (one first-provider-onboarding PR)

- Only existing `apps/korean-ai-platform/app/pilot/b14_models.json` is canonical; append new provider `modelscope`, append one model, preserve existing 11 model IDs and three empty groups.
- `apps/korean-ai-platform/worker.py` permits ONLY the name `PADIEM_MODELSCOPE_API_KEY` from Worker bindings; `wrangler.toml` projects the **same preexisting Secrets Store name** (Charliekant default store ID) as metadata. The name was found in an authenticated **read-only store list** on 2026-10-10. Neither the credential value nor any other provider's value was read or changed.
- Existing B14 `platform.py` generic adapter handles JSON and SSE, provider-specific 401/429, bounded timeouts and response sanitization. No new gateway, hardcoded native reasoning/sampling level, model fallback or routing default.
- MockTransport contracts check correct ModelScope URL and exact upstream, one synthetic client request, missing-secret no-egress, independent credential isolation, normal/stream body omission, 429 behavior.
- Prior parameter-provenance tests that had hardcoded `11` are updated to iterate **any future append-only registered model count**, not to re-run giant suites every model.

## Minimal completion path and bounds

1. Source-only new Provider PR, focused tests and exact-head CI; **no model request** needed to register code.
2. Before a customer-facing Production release, verify ModelScope ToS/current quota/commercial authorization and credential binding readiness. Do not fetch or print the token. Obtain explicit separate Owner release approval, then official exact-main B14 deploy and GET-only **12/12 canonical model parity**. Do not automatically run official deploy from a PR.
3. For transport acceptance, a **single separately Owner-approved potentially quota-consuming ModelScope text-only hello** (attempt 1, retries 0, external fallback 0, provider/model exact, no raw sensitive logs) is sufficient. Do **not** require 10 synthetic QKR tests, 100% PDF, Drive, Claw or Sol validation for basic model registration.
4. If quota or terms fail, keep `PRODUCTION_READY=NO` and the linked issue open. A secret-name existence check is **not** a completed login or a successful API response.

**At initial source stage:** API calls 0, Secrets value reads/writes 0, Production mutations 0; no actual model accuracy ranking, availability SLA or 100+ per-day guarantee.
