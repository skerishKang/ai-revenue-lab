# B14 OpenCode Go five-model protocol adapters — 2026-10-12 KST

## Source patch

- `apps/korean-ai-platform/app/pilot/opencode_go_wire.py` defines only the five exact owner-approved OpenCode Go model IDs and the correct native route for each. The same documented upstream is never rerouted silently to a different protocol or a different provider.
- LongCat 2.5 Preview Free and Step 5 Preview Free → `/chat/completions`, Muse Spark 1.3 Contributor and GPT 6 Luna → `/responses`, Claude Haiku 5.5 → `/messages` (Anthropic `x-api-key` and `anthropic-version`).
- Uses provider-approved base origin only: `https://opencode.ai/zen/go/v1`. `User-Agent: padiem-claw-coding-agent/1.0` and a **required trusted stable session ID** in `x-opencode-session`. Rejects missing session IDs; does not use ephemeral B14 request IDs in their place.
- Auth uses only the existing server-owned `PADIEM_OPENCODE_API_KEY` Worker Secrets Store binding. No secret value or account data in source, tests, logs, PR, or docs.
- Completed responses and SSE streams are parsed and normalized to B14's existing result contracts; errors and empty responses fail closed.
- The B14 public completed/stream adapter delegates only `provider_id == opencode-go` to the dedicated wire implementation. All other provider paths remain unchanged.
- The last preflight **requires the owner-enabled model AND owner-enabled provider** in the canonical B14 registry. Both are still disabled by owner-approved PR #4421. This patch **does not** activate models, release coding traffic to general members, or set product tiers.

## Evidence and open work

- MockTransport tests verify exact 5 model IDs, correct request shape/path and auth headers, missing-session refusal, enabled-gate refusal without reading credentials, 3 completed envelopes, 3 SSE streams, and secret-safe upstream errors.
- Existing B14 generic route regression tests scope to **enabled** legacy models. The owner model metadata remains source-controlled; no customer picker model is enabled.
- B14 local suite: **1,385 PASS** (2026-10-12).
- **Not yet completed:** Server-authenticated Claw conversation/session mapping into `session_id` (caller cannot supply a fabricated ID), live provider test with the actual Go account subscription and model-specific quota; ZansLab's exact GPT 6 Luna model ID from the account; Muse Contributor opt-in & geographic/data training restrictions; admin activation and owner-controlled Pro/Max tier assignments. These remain on [issue #4416](https://github.com/skerishKang/ai-revenue-lab/issues/4416).
- Do not claim the six models answer successfully from the production customer UI until real model calls are evidenced and permissioned.

Official: https://docs.opencode.ai/docs/go/
