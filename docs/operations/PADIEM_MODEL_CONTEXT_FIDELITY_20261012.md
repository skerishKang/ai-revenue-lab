# Model-native conversation and reference fidelity — 2026-10-12

Owner issue: #4379. Scope: B62 Padiem Chat / Padiem Claw / shared Core.

## Behavior

1. D1 messages.content remains the bounded 8,000-character **UI preview**, visibly labeled if incomplete. The private PADIEM_WORKSPACE_FILES R2 binding stores exact normalized UTF-8 long model messages under server-minted canonical conversation/message keys. There is no new browser-controlled key, public URL, new credential, D1 schema migration, or model router.
2. Claw general follow-ups authorize the conversation against D1 user_id before any R2 access and reconstruct model context from full server-persisted bytes. Missing, tampered, or legacy preview-only messages fail closed before quota/provider dispatch. Browser history API continues returning previews only.
3. Owner deletion of a conversation cleans associated R2 long-text objects after D1 deletion. Project deletion uses ON DELETE SET NULL, so it must not delete surviving conversation context.
4. B62 document/project-file/combined reference context assembly preserves normalized source by default. Explicitly bounded presentation excerpts retain their legacy behavior. The B14 client and Core eliminate arbitrary 14k/16k/32k model-context limits. The 5.5MB UTF-8 byte safety envelope remains below the existing 6MB model HTTP request boundary, and is not a provider token limit.
5. Grounding source count, provenance, allowed file types, auth, P01 approvals, quotas and entitlement, completed output memory limits and admin model OFF remain intact.

## Limitations and operational gates

- Previously saved preview-only long messages cannot be reconstructed. They cause an explicit refused follow-up instead of silently losing context. The user must resupply the original or start a fresh thread.
- Existing B66 structured quote bounds and Claw manual executable-task limits are unchanged.
- Account-deletion and orphan-R2 lifecycle maintenance need a separate retention review. Tests cover owner conversation deletion.
- Local tests are provider-free. No successful Cloudflare R2 integration or production model E2E is claimed.
- B62 production release must preserve the existing private R2 and D1 bindings and pass exact-head CI/served readback. B54 Engine deployment must separately preserve its six critical bindings. No blind deploy or secret modification.
- Open Draft PR #3988 overlaps b14_client.py and execution_runtime.py. Its owner must rebase/reconcile against this PR before merging #3988.

## Rollback

Restore a previously verified immutable B62 Worker version using the canonical gate if any authenticated real-world post-release checks fail. Do not automatically purge R2 text keys. Never silently downgrade full context to truncated previews.
