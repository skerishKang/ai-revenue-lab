-- B66 #3405 — durable account/workspace-bound quotation history (Slice A: server authority).
-- Source migration only. Applying this migration to any environment is a separate release action.
-- Padiem signed auth / Control Plane identity remains authoritative for user and tenant.
--
-- A record is a *normalized QuoteDraft snapshot*, never a calculation authority:
-- computed totals are not persisted as trusted values and QuoteCore recalculates on load.
-- Raw source spreadsheet/PDF bytes, renderer HTML, model/provider payloads and credentials
-- are never stored here.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS b66_quote_history (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    quote_no TEXT,
    issue_date TEXT,
    saved_skill_id TEXT,
    skill_fingerprint TEXT,
    snapshot_json TEXT NOT NULL,
    sender_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_b66_quote_history_owner_workspace_updated
ON b66_quote_history (user_id, workspace_id, updated_at DESC);
