-- Chat-local journal. No queue dispatch grants or operations are added.
CREATE TABLE IF NOT EXISTS pc_helper_maintenance_jobs (
  claim_token TEXT PRIMARY KEY,
  device_id TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  registration_sha256 TEXT NOT NULL,
  release_sha256 TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('refresh','install')),
  created_at TEXT NOT NULL,
  deadline TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('reserved','queued','terminal')),
  run_id TEXT,
  dispatch_id TEXT,
  receipt_at TEXT,
  outcome TEXT,
  proof TEXT,
  notified INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS pc_helper_maintenance_jobs_pending
  ON pc_helper_maintenance_jobs(status,notified,created_at);
