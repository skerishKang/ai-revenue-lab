CREATE TABLE IF NOT EXISTS storymemory_sync_records (
  user_id TEXT NOT NULL,
  record_type TEXT NOT NULL CHECK (record_type IN ('progress', 'annotation', 'note', 'bookmark')),
  record_id TEXT NOT NULL,
  data_json TEXT,
  client_updated_at INTEGER NOT NULL,
  device_id TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK (revision > 0),
  is_deleted INTEGER NOT NULL DEFAULT 0 CHECK (is_deleted IN (0, 1)),
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, record_type, record_id)
);

CREATE INDEX IF NOT EXISTS storymemory_sync_records_user_type
  ON storymemory_sync_records (user_id, record_type, updated_at);

CREATE TABLE IF NOT EXISTS storymemory_sync_preferences (
  user_id TEXT NOT NULL,
  device_id TEXT NOT NULL,
  scopes_json TEXT NOT NULL,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, device_id)
);

CREATE TABLE IF NOT EXISTS storymemory_sync_delete_receipts (
  service_id TEXT PRIMARY KEY,
  operation_id TEXT NOT NULL UNIQUE,
  account_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'complete')),
  created_at INTEGER NOT NULL,
  completed_at INTEGER
);
