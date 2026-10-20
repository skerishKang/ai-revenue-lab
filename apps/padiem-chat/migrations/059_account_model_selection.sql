-- #5222: the last AI tier an account explicitly selected.
--
-- This row is a UI preference only. It never grants model access: the server
-- re-verifies the member grade and the administrator gate on every read and on
-- every model request, and the browser can never name another account because
-- the row is always scoped to the signed session's canonical user id.
--
-- Fully additive: no existing table is altered, renamed or dropped.
CREATE TABLE IF NOT EXISTS padiem_account_model_selections (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    tier TEXT NOT NULL CHECK (tier IN ('free', 'plus', 'pro', 'max', 'admin')),
    updated_at TEXT NOT NULL
);
