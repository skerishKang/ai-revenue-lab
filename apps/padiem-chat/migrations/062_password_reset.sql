-- Padiem Chat Business 62 - migration 062: lost-password self-service reset (#5441).
--
-- Additive only. No existing table is altered, dropped or rewritten, so the
-- account rows, the #5118 role rows and every other account-owned record stay
-- exactly as they were.
--
-- A reset token is stored as a keyed digest only. The raw token exists in the
-- recipient's mailbox and in the request that redeems it; it is never stored,
-- never logged and never written to an audit row.
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_digest TEXT NOT NULL UNIQUE,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    revoked_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user
    ON password_reset_tokens (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expiry
    ON password_reset_tokens (expires_at);

-- The audit ledger of the reset lifecycle. It records who asked, when, and
-- what the server decided. The identifier is a keyed digest, never a raw
-- email address, so the ledger never becomes an account directory.
CREATE TABLE IF NOT EXISTS password_reset_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL CHECK (
        event IN (
            'requested',
            'issued',
            'delivered',
            'delivery_failed',
            'consumed',
            'rejected',
            'expired'
        )
    ),
    user_id TEXT,
    identifier_digest TEXT NOT NULL,
    reason_code TEXT,
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_password_reset_audit_identifier
    ON password_reset_audit (identifier_digest, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_password_reset_audit_occurred
    ON password_reset_audit (occurred_at);
CREATE INDEX IF NOT EXISTS idx_password_reset_audit_user
    ON password_reset_audit (user_id, occurred_at DESC);
