-- The verified subject's Chat account link, reused across logins.
-- Keys come only from signature-verified tokens; no credential is stored.
-- Disposed of by the same revision fence as auth_validation_cache, so any
-- account-link mutation, session revocation or logout drops these rows too.
CREATE TABLE IF NOT EXISTS auth_account_link_cache (
  owner_id TEXT PRIMARY KEY,
  product_user_id TEXT NOT NULL,
  valid_until REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_account_link_user
  ON auth_account_link_cache(product_user_id);
CREATE INDEX IF NOT EXISTS idx_auth_account_link_expiry
  ON auth_account_link_cache(valid_until);
