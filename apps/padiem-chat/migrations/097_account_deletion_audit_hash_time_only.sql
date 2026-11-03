-- Compact account-deletion retention to the approved hash + timestamp only.
-- Keep the newest deletion time for each subject hash; discard random row IDs.
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS account_deletion_audit_compact (
    user_id_hash TEXT PRIMARY KEY,
    deleted_at TEXT NOT NULL
);
INSERT INTO account_deletion_audit_compact (user_id_hash, deleted_at)
SELECT user_id_hash, MAX(deleted_at)
FROM account_deletion_audit
GROUP BY user_id_hash
ON CONFLICT(user_id_hash) DO UPDATE SET deleted_at=excluded.deleted_at;
DROP TABLE account_deletion_audit;
ALTER TABLE account_deletion_audit_compact RENAME TO account_deletion_audit;
CREATE INDEX IF NOT EXISTS idx_account_deletion_audit_deleted_at
    ON account_deletion_audit (deleted_at);
COMMIT;
