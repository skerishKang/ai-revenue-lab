-- #6695 PR-4 — the install URL carries the account, not just the pairing code.
--
-- Before this, an install link was a bare base URL plus a one-time code the
-- person typed, or a downloaded file whose trailer held the derived install
-- tag. Nothing in the bytes that reach a PC said which account it was for, so
-- MeshCentral's own join check was the only thing standing between one
-- account's installer and another account's server (`ignoreagenthashcheck`
-- lets any binary that knows the mesh id join). The Chat layer now issues a
-- per-account install token alongside the pairing code and binds the two, so
-- a pairing claim can be refused when the token that came in was revoked,
-- expired, or was minted for a different account.
--
-- Only the hash is stored. The token itself travels to the PC inside the
-- install URL and is never readable back from the server: a leaked database
-- row must not be an install credential. One token per pairing code, so the
-- token's lifetime is the code's lifetime; `expires_at` is a column, not a
-- cron, and revocation is a stamp rather than a delete because a refused
-- claim wants to say *why* it was refused.
--
-- Additive only. No existing table is rebuilt or rewritten, and a link that
-- predates this table reads exactly as it did before: a pairing code with no
-- token row is a legacy code and is claimed the way it always was.
CREATE TABLE IF NOT EXISTS pc_install_tokens (
  token_id TEXT PRIMARY KEY CHECK(length(token_id) BETWEEN 1 AND 64),
  token_sha256 TEXT NOT NULL UNIQUE CHECK(length(token_sha256) = 64),
  -- The pairing code this token was minted with. One code, one token.
  code_id TEXT NOT NULL UNIQUE CHECK(length(code_id) BETWEEN 1 AND 64),
  user_id TEXT NOT NULL CHECK(length(user_id) BETWEEN 1 AND 256),
  issued_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  CHECK(expires_at > issued_at)
);

CREATE INDEX IF NOT EXISTS idx_pc_install_tokens_user
ON pc_install_tokens (user_id);
