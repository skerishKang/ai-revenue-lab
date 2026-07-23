-- Migration 005: web reader/admin sessions and invite credentials.
-- Phase 2A visual vertical slice.
-- Adds tables for invite credential digests, reader sessions, and admin
-- sessions. No plaintext invite codes or raw session tokens are stored.

CREATE TABLE IF NOT EXISTS invite_credentials (
    id TEXT PRIMARY KEY,
    code_digest TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    used_by_reader_id TEXT REFERENCES readers(id),
    used_at TEXT
);

CREATE TABLE IF NOT EXISTS reader_sessions (
    id TEXT PRIMARY KEY,
    reader_id TEXT NOT NULL REFERENCES readers(id),
    token_digest TEXT NOT NULL UNIQUE,
    csrf_token_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_sessions (
    id TEXT PRIMARY KEY,
    token_digest TEXT NOT NULL UNIQUE,
    csrf_token_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reader_sessions_token ON reader_sessions(token_digest);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_token ON admin_sessions(token_digest);
CREATE INDEX IF NOT EXISTS idx_invite_credentials_digest ON invite_credentials(code_digest);
