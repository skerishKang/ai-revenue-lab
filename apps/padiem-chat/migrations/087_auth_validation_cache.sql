-- Disposable, short-lived results of the existing identity authority.
-- No credentials or permission grants. Every key includes its verified owner.
CREATE TABLE IF NOT EXISTS auth_validation_cache (
  kind TEXT NOT NULL CHECK (kind IN ('legacy', 'shared')),
  owner_id TEXT NOT NULL,
  session_hash TEXT NOT NULL,
  product_user_id TEXT NOT NULL,
  valid_until REAL NOT NULL,
  PRIMARY KEY (kind, owner_id, session_hash)
);
CREATE INDEX IF NOT EXISTS idx_auth_validation_cache_user
  ON auth_validation_cache(product_user_id);
CREATE INDEX IF NOT EXISTS idx_auth_validation_cache_expiry
  ON auth_validation_cache(valid_until);

-- A mutation fence rejects a lookup started before any invalidation completed.
-- Existing entries for other sessions/users remain usable.
CREATE TABLE IF NOT EXISTS auth_validation_cache_revision (
  id INTEGER PRIMARY KEY CHECK (id=1),
  revision INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO auth_validation_cache_revision(id, revision) VALUES (1, 0);
