-- B66 #3301 — durable account-bound Saved Quote Skill persistence.
-- Source migration only. Applying this migration to any environment is a separate release action.
-- Existing Padiem auth / Control Plane identity remains authoritative.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS b66_saved_quote_skill (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    skill_fingerprint TEXT NOT NULL,
    skill_version INTEGER NOT NULL CHECK (skill_version >= 1),
    skill_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('approved', 'disabled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, workspace_id, skill_id, skill_version)
);

CREATE INDEX IF NOT EXISTS idx_b66_saved_quote_skill_owner_workspace_status
ON b66_saved_quote_skill (user_id, workspace_id, status, updated_at DESC);
