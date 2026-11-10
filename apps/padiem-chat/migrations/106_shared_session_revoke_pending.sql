-- #7078: durable retry marker for padiem-auth session revocation.
-- A password change/reset revokes the user's shared-login sessions best-effort.
-- When that call fails, this row makes the next login/refresh/change retry it
-- without failing the credential change itself.
CREATE TABLE IF NOT EXISTS shared_session_revoke_pending (
  user_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0
);
