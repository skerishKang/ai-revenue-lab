-- Padiem Chat Business 62 — migration 012 permanent password authentication.
-- Preserves every existing Google user while widening the reviewed product
-- identity provider set to google + password and adding password credentials.
--
-- IMPORTANT: foreign_keys is disabled only for the bounded users-table rebuild.
-- The migration reenables it and performs foreign_key_check before completion.

PRAGMA foreign_keys = OFF;

BEGIN TRANSACTION;

CREATE TABLE users_012 (
    id TEXT PRIMARY KEY,
    auth_provider TEXT NOT NULL CHECK (auth_provider IN ('google', 'password')),
    provider_subject TEXT NOT NULL,
    email TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    picture_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (auth_provider, provider_subject)
);

INSERT INTO users_012 (
    id, auth_provider, provider_subject, email, display_name, picture_url, created_at, updated_at
)
SELECT
    id, auth_provider, provider_subject, email, display_name, picture_url, created_at, updated_at
FROM users;

DROP TABLE users;
ALTER TABLE users_012 RENAME TO users;

CREATE TABLE password_credentials (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (failed_attempts BETWEEN 0 AND 100),
    locked_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_password_credentials_username
    ON password_credentials(username COLLATE NOCASE);

COMMIT;

PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;
