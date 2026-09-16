-- Padiem Chat Business 62 — migration 012 permanent password authentication.
--
-- Fully additive by design. Existing users and every existing ownership/FK table
-- remain untouched. The legacy users.auth_provider CHECK remains Google-only;
-- password accounts receive a compatibility users row while password_credentials
-- is the authoritative product-local marker for the password authentication method.
-- Canonical identity authority receives auth_provider='password' separately.

CREATE TABLE IF NOT EXISTS password_credentials (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (failed_attempts BETWEEN 0 AND 100),
    locked_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_password_credentials_username
    ON password_credentials(username COLLATE NOCASE);
