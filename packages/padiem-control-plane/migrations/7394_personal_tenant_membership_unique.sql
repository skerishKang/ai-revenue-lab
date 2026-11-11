-- #7394 item 2 — PROPOSAL ONLY. NOT APPLIED.
--
-- The runtime fix is the atomic `ensure_personal_tenant_membership` RPC in
-- `identity_authority_durable.py`. This partial unique index is a
-- defense-in-depth backstop for old Chat instances during rollout: a second
-- active personal-tenant OWNER row for the same subject is refused by SQLite.
--
-- The identity authority is a Durable Object. Its schema is applied by
-- `identity_authority_durable.py`, not by this file, so this migration is
-- intentionally not wired into any runtime path.
--
-- Precheck (read-only) before any application. Resolve every duplicate first;
-- creating the index fails while duplicates exist.
--
--   SELECT canonical_subject_id, COUNT(*) AS active_owners
--   FROM canonical_tenant_membership
--   WHERE state = 'active' AND role = 'owner'
--   GROUP BY canonical_subject_id
--   HAVING COUNT(*) > 1;
--
-- Current schema note: a personal tenant is the only tenant a subject owns,
-- and it is created with role='owner'. If a future feature lets one subject
-- own several tenants, add an explicit `personal` marker and scope the index
-- to that marker instead of role='owner'.

CREATE UNIQUE INDEX IF NOT EXISTS idx_canonical_tenant_membership_active_owner
ON canonical_tenant_membership(canonical_subject_id)
WHERE state = 'active' AND role = 'owner';
