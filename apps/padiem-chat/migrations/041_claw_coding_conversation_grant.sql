-- #3933 S1: B54-only durable first-turn conversation reservation/correlation.
--
-- Additive only. This SOURCE file is reviewed but NEVER applied by this slice:
-- no worker, test harness, or route applies migrations at runtime, and CENTRAL
-- owns any future production apply decision (#4522 chain). The table is a
-- reservation/execution-idempotency record, never a standalone entitlement or
-- approval, and never a second conversation authority:
--
-- * the grant row binds one server-minted conversation reference to the
--   canonical (product, owner, subject, tenant, route scope) BEFORE dispatch;
-- * only a guarded compare-and-set claim (reserved -> active) authorizes a
--   dispatch; a read of the row never does;
-- * only ONE live (reserved/active, unexpired) grant may exist per
--   (user, correlation) — enforced by the partial unique index below, which is
--   the atomic arbiter for concurrent reserves. Terminal rows
--   (completed/failed/revoked) are history and never block a fresh reserve.
--
-- No ALTER, no DROP, no new conversation/message/run authority. The existing
-- `conversations` (user-scoped read model) and `claw_run_history` tables are
-- untouched.

CREATE TABLE IF NOT EXISTS claw_coding_conversation_grant (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    product_id TEXT NOT NULL CHECK (product_id = 'b54-padiem-claw'),
    route_scope TEXT NOT NULL,
    conversation_ref TEXT NOT NULL,
    correlation_key TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('reserved', 'active', 'completed', 'failed', 'revoked')),
    run_ref TEXT,
    saved_conversation_id TEXT,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    claimed_at TEXT,
    completed_at TEXT
);

-- Exactly one LIVE grant per (user, correlation). Terminal rows are exempt so
-- a finished or dead grant never blocks the next legitimate reserve.
CREATE UNIQUE INDEX IF NOT EXISTS idx_coding_grant_live_claim
    ON claw_coding_conversation_grant (user_id, correlation_key)
    WHERE state IN ('reserved', 'active');

CREATE INDEX IF NOT EXISTS idx_coding_grant_user_state_expiry
    ON claw_coding_conversation_grant (user_id, state, expires_at);
