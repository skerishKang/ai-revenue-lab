# Central Model Admin S3 — guarded D1 persistence (2026-10-12 KST)

## Scope and completed production foundation
- Repository: `skerishKang/ai-revenue-lab`; tracking issue #4453 (parent #4428).
- Canonical Cloudflare D1: `padiem-chat-db`, account verified by operator tooling. No second model registry.
- On 2026-10-12 KST the existing production D1 was exported to a **local operator-only backup** outside the repository before applying migration 039. The export checksum was recorded in the issue. Never commit/share this backup (it contains production records).
- Migration `039_central_model_policy.sql` applied successfully; readback confirms exactly five `central_model_policy_*` tables. This migration performs no model assignment or legacy B66 mutation.

## Server authority
- Google OAuth session identity -> `D1CentralModelAdminAuthorizer` -> exact verified Google subject and canonical `usr_` ID -> globally allowlisted trusted Worker email setting.
- B66-local admin status never authorizes central model writes.
- Independent server-only hex-encoded 32-byte HMAC key in the Worker binding `PADIEM_CENTRAL_MODEL_POLICY_SIGNING_KEY`. No key means write routes return 503; no implicit default key or request-supplied key.
- Browser origin MUST equal the server-configured public base origin on every mutation.
- Workspace is fixed server-side to `padiem-global` and cannot be selected in a browser request.
- API responses use no-store, bounded JSON requests; only B14 trusted registered/ready metadata can be used for new positive grants.
- Signed preview receipts bind actor, workspace, scope, revision, full diff, operation, one-use nonce and five-minute expiry. The D1 batch CAS check enforces concurrency and replays; atomic history and audit follow each accepted write.

## New S3 API — stored policy only
- `POST /api/admin/models/change-preview`: body `{"model_id":"<B14 route>", "targets":[{"product_id":"chat","tier":"PRO","action":"allow"}]}`. Returns prior/new diffs and a short-lived receipt; NO WRITE.
- `POST /api/admin/models/change-apply`: body `{"confirmation_receipt":"<signed token>"}`. Re-verifies current Google admin and B14 availability, commits one D1 revision transaction, audits, consumes receipt.
- `GET /api/admin/models/audit`: most recent 30 events, global-admin-only.
- `POST /api/admin/models/rollback-preview`: body `{"target_revision":0}` signs a bounded diff back to a previous state; same apply route commits an independently audited new revision.
- Existing S0 `POST /api/admin/models/preview` remains a nonpersistent legacy preview contract; no feature bypass.
- The UI exposes commit only after valid signed preview and a separate confirmation. History/rollback remain collapsed.

## Explicitly *not* activated
D1 policy persistence is **not runtime model authorization**. The response says `runtime_enforced:false`, and B14 / Chat / Claw / B66 / Router continue existing authorization until separate product-specific dispatch adapters and exact live E2E acceptance have passed. Do not label a D1 rule as successful model invocation or replace a user's selected model. B14 route registry/credentials and B66 legacy membership are unchanged.

## Operations, verification and rollback
1. Before any Worker code deployment: verify exact PR HEAD CI, the global-admin settings and migration applied. Deploy only via existing official B62 workflow with exact main SHA.
2. After deployment: verify `/health`, the static page, unauthenticated 401 on central routes, global-admin authentication, signed-preview/confirm/replay/rollback and D1 revision/audit readback. **Do not create sample production allows** to run QA; use read-only and authorized operator-driven deliberate changes.
3. On code regression: roll back Worker to last confirmed working version using established deployment process. On policy mistake: use signed rollback-preview/confirm to commit a new revision; do not mutate history/audit rows.
4. The pre-039 database export exists only for catastrophic recovery. Never import a full historical SQL backup into a populated production DB without a separate recovery assessment, because it would overwrite newer customer data.

## Outstanding blockers before closing #4453
- Real privileged browser-session E2E for the selected Google owner account.
- Prove actual Chat, Claw, B66 and Router request-dispatch policy enforcement at exact model/tier and distinguish B14 credential/provider errors.
- Confirm one-owner multiple-tier authorized grants against B14 live catalog and product feature permissions; do not silently migrate existing B66 grants.
