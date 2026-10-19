-- PADIEM CLAW GitHub App user-to-server OAuth (private owner-scoped authority).
-- All provider access and refresh tokens are sealed with AES-GCM before D1 storage.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS claw_github_oauth_states (
 state_sha256 TEXT PRIMARY KEY,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 session_sha256 TEXT NOT NULL,
 pkce_verifier TEXT NOT NULL,
 expires_at INTEGER NOT NULL,
 created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claw_github_oauth_states_expiry ON claw_github_oauth_states(expires_at);
CREATE TABLE IF NOT EXISTS claw_github_connections (
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 github_user_id INTEGER NOT NULL,
 github_login TEXT NOT NULL,
 installation_id INTEGER NOT NULL,
 sealed_credential TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
 access_expires_at INTEGER NOT NULL,
 refresh_expires_at INTEGER NOT NULL,
 created_at INTEGER NOT NULL,
 updated_at INTEGER NOT NULL
);
