# B14 OpenCode Go / ZansLab owner intake — 2026-10-12 KST

## Owner intent and exact scope

Owner identified two credentials in an existing **local private** API key text file: one OpenCode Go account (“padiemipu”) and one ZansLab gateway. Never copy, commit, print, hash in public output, or paste the actual key values into GitHub, Cloudflare deployment logs or documentation. This PR only registers **metadata with both providers disabled**.

| Provider ID | Trusted official base origin | Reserved Secrets Store binding | Status |
| --- | --- | --- | --- |
| `opencode-go` | `https://opencode.ai/zen/go/v1` | `PADIEM_OPENCODE_API_KEY` | registered; **disabled; account secret active and binding metadata prepared** |
| `zanslab` | `https://zanslab.id/v1` | `PADIEM_ZANSLAB_API_KEY` | registered; **disabled; account secret active and binding metadata prepared** |

## Critical execution boundaries

- OpenCode Go officially targets **coding-agent-style traffic**, requires a stable per-conversation session header (`x-opencode-session`) and proper User-Agent. It is **not approved here for general member chat, quote generation, mass proxying, or silent default/fallback**.
- Two exact OpenCode Go **Chat Completions** candidates (`deepseek-v4-flash`, `mimo-v2.5`) come from the provider's public model catalogue but are **NOT YET registered in the executable model catalog**, until the owner-confirmed account key is securely provisioned in Secrets Store and transport compatibility is tested. Do not misroute `gpt-5.6-luna` (Responses API), `muse-spark-1.2-contributor` (Responses API), or MiniMax/Qwen (Messages API) through the current generic chat-completions transport.
- ZansLab's own documentation describes OpenAI-style `/v1/chat/completions`, but an authenticated `GET /v1/models` response for the owner account was **not acquired**. Therefore no unverified model IDs or context windows/prices are inserted.
- Both Secrets Store entries are **confirmed active** in the existing Charliekant account Secrets Store (`f0b09ca04a7b43248154c773704a5616`). Do not use a different account's OpenCode Go credential.
- Both B14 Worker `secrets_store_secrets` metadata-only bindings now point to the exact preexisting secret names. Keep both providers disabled and expose no model until authenticated exact-model transport and product-specific use authorization are separately checked; run exact HEAD CI and a guarded production deploy before claiming served binding readiness. There is **no customer model enablement or tier assignment** in this change.

## References

- OpenCode Go: https://docs.opencode.ai/docs/go/
- OpenCode live public models: https://opencode.ai/zen/go/v1/models
- ZansLab integration: https://zanslab.id/documentation
- ZansLab public catalogue: https://zanslab.id/models
- Single canonical registration: `apps/korean-ai-platform/app/pilot/b14_models.json`

**Status:** source metadata and bindings prepared; both secret names confirmed active with `workers` scope. ZansLab exact model selection, OpenCode coding-session header support, live provider verification, and B14 Production deployment are outstanding.
## Owner key-account confirmation (2026-10-12)

Owner identified the OpenCode Go account credential as the local file entry **immediately after the specifically identified email label**; the entry occurs once and the next line has valid key shape. Neither the email address nor the key value is committed. Duplicate ZansLab records match exactly. Cloudflare provisioning via the remote secret workflow was attempted but blocked by a security check; **no secret value was created or updated**, and no live provider request was made.

## Cloudflare readback update (2026-10-12)

In the existing account store, the owner-provisioned entries were verified **active** with `workers` scope using a metadata-only Wrangler list. Exact stored names are `PADIEM_OPENCODE_API_KEY` (NOT the earlier provisional `PADIEM_OPENCODE_GO_API_KEY`) and `PADIEM_ZANSLAB_API_KEY`. Binding metadata is updated to these exact names. No key value was accessed or logged, and the disabled-provider gate remains in place.
