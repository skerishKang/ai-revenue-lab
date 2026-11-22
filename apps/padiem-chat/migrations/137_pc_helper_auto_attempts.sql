CREATE TABLE IF NOT EXISTS pc_helper_auto_attempts (
  device_id TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  stopped INTEGER NOT NULL DEFAULT 0,
  last_reason TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (device_id, source_sha256)
);
