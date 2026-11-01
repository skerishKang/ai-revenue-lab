-- Owner-scoped PC file delegation, on the existing Chat/COM2 database.
-- No row means the existing behavior. Disabled rules remain in the document
-- so turning a rule off never silently restores an automatic allow.
CREATE TABLE IF NOT EXISTS padiem_pc_delegations (
    user_id TEXT NOT NULL PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    settings_json TEXT NOT NULL CHECK (json_valid(settings_json)),
    updated_at TEXT NOT NULL
);
