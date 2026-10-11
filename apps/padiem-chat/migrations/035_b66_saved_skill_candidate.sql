-- B66 #3186 — durable account-bound Saved Quote Skill *candidate* (customer approval request).
-- Source migration only. Applying this migration to any environment is a separate release action.
-- Padiem signed auth / Control Plane identity remains authoritative for user and tenant.
--
-- A candidate is an approval *request*, never a Saved Quote Skill. Only a trusted
-- operator review may turn a pending candidate into an approved artifact, and only
-- through the existing #3301 b66_saved_quote_skill store (separate table).
--
-- Raw source quotation bytes, renderer HTML, model/provider payloads and credentials
-- are never stored here. Only the bounded, already-validated candidate envelope.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS b66_saved_skill_candidate (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    client_ref TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    skill_fingerprint TEXT NOT NULL,
    candidate_digest TEXT NOT NULL,
    candidate_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
    decision_by TEXT,
    decision_ref TEXT,
    decision_at TEXT,
    rejection_reason TEXT,
    saved_skill_id TEXT,
    skill_version INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, workspace_id, client_ref)
);

CREATE INDEX IF NOT EXISTS idx_b66_saved_skill_candidate_owner_status
ON b66_saved_skill_candidate (user_id, workspace_id, status, updated_at DESC);

-- One open request per identical submitted content. The digest covers the whole
-- candidate envelope (including the display name), so a renamed candidate is a
-- genuinely new request rather than a silent overwrite or a merged duplicate.
CREATE UNIQUE INDEX IF NOT EXISTS idx_b66_saved_skill_candidate_open_digest
ON b66_saved_skill_candidate (user_id, workspace_id, candidate_digest)
WHERE status = 'pending';
