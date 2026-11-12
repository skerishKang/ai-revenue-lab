-- #7604: the shared-login finish joins the account-cleanup pending rows as its
-- own kind. When the common account is deleted but the shared-login complete
-- call fails, the withdrawal records this work here and the cleanup lanes
-- retry it (prepare → complete).
--
-- The kind column's CHECK cannot be altered in place, so the table is rebuilt:
-- every existing row (kind, target, attempt count, timestamps) is carried over
-- unchanged. Additive in effect — no existing kind is removed, no row edited.
CREATE TABLE IF NOT EXISTS account_deletion_cleanup_pending_v113 (
  item_id TEXT NOT NULL PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('r2_key', 'r2_prefix', 'google_workspace', 'file_lane', 'shared_account_complete')),
  target TEXT NOT NULL CHECK (length(target) BETWEEN 1 AND 1024),
  created_at TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  last_attempt_at TEXT
);
INSERT INTO account_deletion_cleanup_pending_v113
  (item_id, kind, target, created_at, attempts, last_attempt_at)
SELECT item_id, kind, target, created_at, attempts, last_attempt_at
  FROM account_deletion_cleanup_pending;
DROP TABLE account_deletion_cleanup_pending;
ALTER TABLE account_deletion_cleanup_pending_v113 RENAME TO account_deletion_cleanup_pending;
DROP INDEX IF EXISTS idx_account_deletion_cleanup_pending_created;
CREATE INDEX IF NOT EXISTS idx_account_deletion_cleanup_pending_created
  ON account_deletion_cleanup_pending (created_at);
