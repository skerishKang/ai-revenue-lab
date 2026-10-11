-- B66 #3402 — private account-bound quotation logo/stamp assets.
-- Source migration only. Applying this migration to any environment is a separate release action.
-- Asset bytes live only in private R2; this table stores bounded metadata.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS b66_quote_asset (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    asset_kind TEXT NOT NULL CHECK (asset_kind IN ('logo', 'stamp')),
    media_type TEXT NOT NULL CHECK (media_type IN ('image/png', 'image/jpeg', 'image/webp')),
    object_key TEXT NOT NULL UNIQUE,
    byte_length INTEGER NOT NULL CHECK (byte_length >= 1 AND byte_length <= 262144),
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('approved', 'disabled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_b66_quote_asset_owner_workspace_status
ON b66_quote_asset (user_id, workspace_id, status, updated_at DESC);
