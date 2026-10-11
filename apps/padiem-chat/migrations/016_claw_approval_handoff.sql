-- #2956: owner-scoped approval handoff context under the existing claw history owner.
--
-- Additive only. Same D1 history persistence owner as the existing Claw history.
-- This is NOT an Engine continuation store: it never mints continuation_ref or
-- pause_id, never owns resume/cancel state, and never verifies approval
-- decisions. It only preserves the bounded server-derived P01 request context
-- so a later canonical Engine resume can be reconstructed without the browser
-- re-supplying authority fields.
--
-- owner + run_id correlation is immutable (UNIQUE). Exact replay is idempotent;
-- a conflicting continuation_ref / pause_id / trusted request identity fails
-- closed at the store boundary. Cross-owner and cross-workspace reads never
-- disclose existence.

CREATE TABLE IF NOT EXISTS claw_approval_handoff (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    workspace_id TEXT,
    conversation_id TEXT,
    continuation_ref TEXT NOT NULL,
    pause_id TEXT NOT NULL,
    pause_expires_at TEXT NOT NULL,
    trusted_request_json TEXT NOT NULL,
    trusted_request_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_claw_approval_handoff_user_workspace
ON claw_approval_handoff (user_id, workspace_id, created_at DESC);
