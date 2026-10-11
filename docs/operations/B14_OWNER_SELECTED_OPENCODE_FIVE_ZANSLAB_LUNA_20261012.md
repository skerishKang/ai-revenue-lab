# B14 owner-selected OpenCode Go five-model roster and ZansLab Luna — 2026-10-12 KST

## Owner's exact model choices

Only the following **five OpenCode Go models**, plus **one ZansLab GPT 6 Luna**, are within this intake. Do not add any other provider model, infer a default model, auto-route, or assign plan tiers in source. Owner can assign tiers using the admin UI separately.

| Provider | Exact ID in B14 (when executable) | Exact upstream model ID | Required upstream API | Owner's future tier |
| --- | --- | --- | --- | --- |
| OpenCode Go | `opencode-go/longcat-2.5-preview-free` | `longcat-2.5-preview-free` | `/chat/completions` | Pro |
| OpenCode Go | `opencode-go/step-5-preview-free` | `step-5-preview-free` | `/chat/completions` | Pro |
| OpenCode Go | `opencode-go/muse-spark-1.3-contributor` | `muse-spark-1.3-contributor` | `/responses` | Pro |
| OpenCode Go | `opencode-go/gpt-6-luna` | `gpt-6-luna` | `/responses` | Max |
| OpenCode Go | `opencode-go/claude-haiku-5-5` | `claude-haiku-5-5` | `/messages` (Anthropic) | Max |
| ZansLab | **Not yet registered — exact account route unverified** | Owner requests GPT 6 Luna only | ZansLab advertises `/v1/chat/completions` but exact model ID must be confirmed from its authenticated catalog | Owner has not assigned tier |

The same underlying GPT 6 Luna offered by different providers is **two distinct routed models** with separate credentials, provider-origin restrictions, readiness, usage and accounting. Do not alias Go Luna to ZansLab Luna.

## Canonical source decisions

- Only the five **exact Go IDs** are added to `apps/korean-ai-platform/app/pilot/b14_models.json`, with `enabled=false`; provider remains disabled, and the account's existing secret binding is preserved. No existing models are changed. Only two owner-identified temporary free offers have zero current prices and the `free` capability, not a permanent pricing guarantee.
- No executable ZansLab ID is invented or registered without a response from the account-specific ZansLab model catalog or verified provider documentation. ZansLab provider remains disabled.
- The B14 generic provider adapter currently uses `/chat/completions`. Turning on the Responses/Messages models without building a wire-specific adapter would create incorrect live API requests. This source-only intake **does not enable live model invocation** or change the customer-visible catalog.
- OpenCode Go's own service contract expects genuine coding agent traffic with a recognizable User-Agent and **stable** `x-opencode-session` per conversation. Implement session provenance through the approved authenticated client, never an arbitrary user-provided upstream URL or unrelated account key. Avoid presenting it as a generic public proxy to thousands of members.
- Muse Spark 1.3 Contributor permits model training on prompts/completions and is subject to permitted regions; it must not silently receive private legal/customer/business content. Explicit product routing and data-use disclosure required before use.
- LongCat 2.5 Preview Free and Step 5 Preview Free are free **for a limited time** only. Detect expiration/429/402, never silently charge fallback to balance or automatically substitute another model.
- Owner suggested Pro for LongCat, Step and Muse and Max for Luna and Claude, but `groups.plus`, `groups.pro`, and `groups.max` are **intentionally unchanged**. No auto-tier assignments.

## Acceptance criteria to activate in a separate code PR

1. Wire-specific Chat Completions, Responses, and Anthropic Messages adapters, with completed + SSE parity, clear usage, real response-model identity, bounded parser frames, and fail-closed unknown protocol.
2. Stable conversation session header and explicit coding-agent permission, no credential disclosure and no cross-provider key reuse.
3. Authenticate/verify ZansLab's Luna exact upstream model ID; create **one** distinct `zanslab/` model row; validate direct completed+stream model identity. Do not assume the OpenCode Go ID is the ZansLab ID.
4. Tests against MockTransport, exact-head B14 CI, scoped real-owner-provider smoke where permitted, and guarded B14 served-version deployment before any model `enabled=true`.
5. Existing admin model ON/OFF and group assignment after actual endpoints are ready. No product-wide default mutation.

Source reference: https://docs.opencode.ai/docs/go/ (official exact IDs, endpoints, pricing and data handling); https://zanslab.id/documentation (documented generic endpoint), https://zanslab.id/models (dynamic public catalog).

**Progress:** 5 Go models registered **inactive**. ZansLab Luna targeted but exact ID pending. No provider calls, member exposure, model plan assignments, or Production model activation claimed.
