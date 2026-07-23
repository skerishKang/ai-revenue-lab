-- Migration 007: Phase 2A corrective hardening (additive only).
--
-- Adds:
--  * invite_credentials.bound_reader_id  — pre-provisioned reader bound to the
--    invite before login. Login reuses this reader; it never creates one.
--  * invite_credentials.expires_at / revoked_at — invite expiry and revocation.
--  * reader_sessions.revoked_at / admin_sessions.revoked_at — explicit session
--    revocation in addition to absolute expires_at.
--  * review_decisions — immutable editorial decision audit (approve/reject),
--    including normalized rejection reason and before/after review state.
--
-- No existing column is altered or dropped. No existing migration is modified.

ALTER TABLE invite_credentials
    ADD COLUMN bound_reader_id TEXT REFERENCES readers(id);

ALTER TABLE invite_credentials ADD COLUMN expires_at TEXT;

ALTER TABLE invite_credentials ADD COLUMN revoked_at TEXT;

ALTER TABLE reader_sessions ADD COLUMN revoked_at TEXT;

ALTER TABLE admin_sessions ADD COLUMN revoked_at TEXT;

CREATE TABLE IF NOT EXISTS review_decisions (
    id TEXT PRIMARY KEY,
    branch_id TEXT NOT NULL REFERENCES branches(id),
    episode_id TEXT NOT NULL REFERENCES episodes(id),
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    rejection_reason TEXT,
    decided_at TEXT NOT NULL,
    actor_type TEXT NOT NULL DEFAULT 'admin',
    prior_state TEXT NOT NULL,
    new_state TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_review_decisions_branch
    ON review_decisions(branch_id);

CREATE INDEX IF NOT EXISTS idx_review_decisions_episode
    ON review_decisions(episode_id);

PRAGMA user_version = 7;
