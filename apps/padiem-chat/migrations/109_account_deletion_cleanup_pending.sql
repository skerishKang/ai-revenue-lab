-- #7557: account deletion work that lives outside this database.
--
-- The deletion batch removes the account's rows atomically, but its stored
-- objects (R2), its Google connector grants and its COM2 file-lane directory
-- are external. Each of those is written here IN THE SAME BATCH that deletes
-- the rows, so the work survives the rows that indexed it. A finished item is
-- deleted; a failed one stays and is retried by the next pass (the request
-- itself first, then the daily purge run). Nothing here can be used to sign
-- in or to read the deleted data back: kind + target name only what to erase.
CREATE TABLE IF NOT EXISTS account_deletion_cleanup_pending (
  item_id TEXT NOT NULL PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('r2_key', 'r2_prefix', 'google_workspace', 'file_lane')),
  target TEXT NOT NULL CHECK (length(target) BETWEEN 1 AND 1024),
  created_at TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  last_attempt_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_account_deletion_cleanup_pending_created
  ON account_deletion_cleanup_pending (created_at);
