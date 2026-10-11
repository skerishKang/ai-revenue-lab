# B66 #3396 — D1 migration 028, schema-first production rollout

**Status:** source-only rollout gate; no customer-row writes or production deployment in this PR.

## Boundary

- Implemented B66 guided resume remains in Draft PR #4201 until production schema is proven.
- Migration 028 adds only `b66_guided_draft`, one authenticated `(user_id, workspace_id)` slot, without touching existing `b66_quote_history` rows.
- Draft/account authority is server-derived. Do not query, export or modify customers' in-progress quotations to verify the schema.
- 027 is reserved by another Draft PR and is intentionally not applied here.
- No Secrets changes, paid model calls, PDF renderer, Sol 4–100-item scope, or customer document bytes.

## Dispatch protocol (after gate is merged into main)

Workflow: `.github/workflows/b62-b66-d1-migration-028-gate.yml`.

1. Fetch the latest **exact main SHA**. Do not use a stale SHA, Draft PR SHA, or detached branch.
2. Dispatch mode `cloudflare_readonly` with that SHA. This resolves the actual `padiem-chat` Worker `PADIEM_CHAT_DB` binding, runs SQLite schema metadata only, and classifies: `MISSING`, `EXACT`, `DRIFT`. `DRIFT` is a hard stop; do not override.
3. Only when source-contract and read-only verification have passed, dispatch mode `apply_migration_028` with the same current main SHA and exact confirmation `APPLY_B62_B66_D1_MIGRATION_028_FROM_EXACT_MAIN`. The GitHub `production` environment protects mutation, and the job repeats main-SHA/binding/schema checks before applying.
4. If `MISSING`, execute only the pinned additive `028_b66_guided_draft.sql` table creation. If already `EXACT`, do nothing. Verify `EXACT` after either path. No application row SELECT/UPDATE/INSERT/DELETE.
5. Do not mark rollout successful merely because the SQL/API returned HTTP 200: require the post-schema classifier and successful workflow conclusion.

## Activation after schema is exact

- Merge-forward Draft PR #4201 onto current main; re-run exact-head CI including GitGuardian; never bypass failures.
- Deploy server API and Pages static/Worker bridge through existing governed release path. Verify served versions; do not assume main merge itself reaches Production.
- Use dedicated synthetic, non-customer account sessions: A in browser 1 enters a partial 1–3-item guided quote; fresh browser 2 under same account restores exact question step, items and tax flag; account B and independent workspace must not access; finish A's quote and confirm stale draft is not reopened.
- Delete only the synthetic test state by authenticated `DELETE /api/b66/guided-draft` while signed in as the exact test owner. Confirm absence. No blanket SQL cleanup.
- Record exact served SHA, schema readback, API status, step/item equality, cross-browser evidence, isolated owner checks and cleanup in #3396. Close only after real operational PASS.

## Safe failure / rollback

- A `DRIFT` or unverified parent `users` table prevents mutation; credentials, identifiers and actual customer rows must not be logged.
- If a partial deployment fails, **do not DROP** the new table in Production: disable or roll back only the newly deployed guided UI/API path with the existing release controls; retain the additive empty table until a reviewed recovery is approved.
- A failed live probe does not justify changing the existing B66 1–3-item MVP or any older D1 row.
