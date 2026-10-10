-- B66 #3884 Slice 1 -- private account-bound customer template source custody.
-- Source migration only. Applying this migration to any environment is a separate release action.
-- Original template bytes live only in private R2; this table stores bounded metadata.
-- status='uploaded' only: upload alone never certifies a template. Analysis/approval
-- is a separate slice and its status transitions must not be introduced here.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS b66_template_source (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK (media_type IN (
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'text/csv')),
    original_filename TEXT NOT NULL,
    object_key TEXT NOT NULL UNIQUE,
    byte_length INTEGER NOT NULL CHECK (byte_length >= 1 AND byte_length <= 10485760),
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('uploaded', 'disabled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_b66_template_source_owner_workspace_status
ON b66_template_source (user_id, workspace_id, status, created_at DESC);
