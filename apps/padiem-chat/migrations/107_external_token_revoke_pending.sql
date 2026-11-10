-- A password change/reset revokes the account's MCP personal tokens and
-- OAuth grants best-effort. When that fails, this row makes the next
-- login/refresh/change retry it without failing the credential change.
CREATE TABLE IF NOT EXISTS external_token_revoke_pending (
  user_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0
);
