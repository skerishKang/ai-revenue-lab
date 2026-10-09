# ExLab / Experiential Labs — Qwen3.8 Flash Next Uncensored

**Owner selected 2026-10-10. Source registration only; no Production activation or customer content sent.**

## Exact technical integration

- **Public B14 ID:** `experiential/qwen3.8-flash-next-uncensored` (not a B.AI Qwen model).
- **Official upstream model slug:** `qwen3.8-flash-next-uncensored`.
- **OpenAI-compatible API origin:** `https://api.experientiallabs.ai/v1`; `POST /chat/completions`, `Authorization: Bearer` with the server-owned key.
- **Existing Secrets Store binding name:** `PADIEM_EXLAB_API_KEY`, already present in Worker and Wrangler declarations. This change neither fetches nor modifies the secret value. Secret binding existence is **not** evidence the deployed Worker has a working key.
- **Provider:** `experiential`, installed from canonical `apps/korean-ai-platform/app/pilot/b14_models.json`, **not** from the retired `register_experiential_provider()` Python code.
- **Official public model detail** `GET https://api.experientiallabs.ai/api/models/qwen3.8-flash-next-uncensored` HTTP200 (2026-10-10): model `active`, **262,144** context, **65,536** advertised maximum output, text in/out, tool calling and reasoning. Two model-specific Experiential Cloud provider entries report `active`.
- Advertised reasoning values: **low / medium / xhigh**, default xhigh according to the public provider detail. Current B14 generic Chat adapter does **not** map provider-specific reasoning effort and globally accepts explicit `max_tokens` at most 4096; this PR does **not** pretend to support 65,536 output or model-specific reasoning controls.
- Public promotional listing has shown a zero-dollar introductory price; no immutable free entitlement or future charge is established. **No free capability** and **no numerical price** are asserted in the canonical JSON. B14 `plus/pro/max` groups remain empty.
- Previously retired `experiential/gpt-5.6-luna` and `b-ai/qwen3.8-flash` remain unregistered. The Owner's StepFun 3.7 and Inkling Small exclusions are unchanged.

## Data retention conflict — explicit release blocker

The vendor publishes two **not-yet-reconciled** statements:
1. Exact public `GET /api/models/<slug>` reports `retention=zdr_all_rungs` and `zero_data_retention=true` for both provider entries.
2. General **Data controls** documentation says models **marked uncensored** require prompt and response retention even when the account setting is off. The unauthenticated model detail does not independently expose the authenticated `uncensored` flag on `GET /v1/models`.

The model name containing "Uncensored" alone cannot establish that the special retention flag is set. Conversely, public route-level ZDR metadata alone is insufficient to supersede an explicit vendor policy. **Do not send real customer quotations, Drive documents, personal data, legal matters or internal business content until this discrepancy is formally resolved.** Do not store, copy or expose the key as part of verification.

### Fail-closed source gates

- Manual B14 routing rejects this exact model in live mode with `model_data_policy_pending` and `upstream_called=false`.
- Provider JSON and SSE streaming reject the exact model ID or a masked ID paired with the ExLab upstream slug **before reading the key or issuing HTTP**.
- Automatic scorer and manually requested fallback candidates exclude the pending ExLab route. It cannot silently replace an Owner-selected model.
- No release switch was added. A **separate reviewed change** is required to remove these guards after the Owner has approved the confirmed data handling policy.
- The model is visible in B14's source catalog as **registered, not executable**, so user-facing activation must wait until both this policy review and a B14 deployed canary have passed.

## Technical acceptance and evidence

- Current canonical source: 10 model IDs, 7 platform providers; manual-only ExLab model; historical nine remain unchanged.
- Mocked network-free tests pin exact upstream `/v1/chat/completions`, provider identity and key binding, refusal before live HTTP/secret read, no automatic fallback, and separate B.AI/ExLab identities.
- A public catalog GET is **not** a credential-backed provider completion. The Secret Store value and ExLab `GET /v1/models` authenticated eligibility **remain unverified**.
- Next gated steps: validate secret **presence** without exposing its value; obtain authenticated model `uncensored`/data policy evidence or direct vendor confirmation; obtain explicit Owner decision on data retention; implement reviewed release gate; run **one synthetic**, manually selected, no-retry live B14 canary, then synthetic QKR-001..010 strict grading with latency/usage and fail-closed 429/504 evidence; only then decide customer activation and Plus-group membership.
- **No Production deploy**, no external model POST, no customer data, no credential mutation, no B66 feature work in this change.

## Official sources

- <https://platform.experientiallabs.ai/docs/authentication>
- <https://platform.experientiallabs.ai/docs/openai-compatibility>
- <https://platform.experientiallabs.ai/docs/models>
- <https://platform.experientiallabs.ai/docs/data-controls>
- <https://api.experientiallabs.ai/api/models/qwen3.8-flash-next-uncensored>
