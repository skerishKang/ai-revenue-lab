# B62 owner-restored long conversation context — 2026-10-12

Scope: active B62 completed and streaming chat gap tracked under umbrella issue #4379. Prior Claw storage PR #4431 is already deployed.

## Change and authority

- On existing signed-in conversation, verify D1 user ownership/project binding before loading full history from D1HistoryStore.get_conversation_model_context (private R2 for long messages).
- Ignore all untrusted browser-provided earlier turns, including clipped 8k UI previews and forged assistant turns. Append only the newly submitted browser user message to server-owned full prior messages in both completed and SSE chat.
- New conversations, anonymous Chat, display history, model entitlements, provider OFF, P01, quotas, projects, attachment rules and quote schema are unchanged.
- Missing legacy originals produce explicit HTTP 409 conversation_context_incomplete before model or quota dispatch. Combined history beyond 5.5MB UTF-8 transport capacity produces explicit HTTP 413 model_context_transport_limit. No silent model context truncation.
- Full private R2 is retrieved only after the owner D1 record is verified. Anonymous calls never load it.

## Validation and release

- Test file: apps/padiem-chat/tests/test_4379_b62_owner_model_context.py. Completed and streaming routes, original full text, forged past turn ignored, legacy preview refusal, cross-owner no private R2 reads, oversized context refusal all covered.
- Local focused 67 PASS including authentication/history, project, streaming, document tests. No live vendor inference.
- Release: exact-head green CI, canonical Cloudflare readonly gate, B62 only production code deploy exact-main, binding/served secret preservation and smoke. Engine and B14 do not require redeploy because this PR changes B62 only.
- Excluded: retired B66 extraction_routing 32000-character symbol is in a HOLD module whose request builders all refuse model calls. Do not silently reactivate an old provider or alter quote schema bounds.
- Historical preview-only messages cannot be reconstructed; users must resupply originals.
