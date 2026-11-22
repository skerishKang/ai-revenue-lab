-- #8204: one fixed-source registration attempt per PC and source release.
CREATE TABLE IF NOT EXISTS pc_helper_registration (
  device_id TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  actor_user_id TEXT NOT NULL,
  attempt_id TEXT NOT NULL,
  dispatch_id TEXT,
  reason TEXT,
  requested_at TEXT NOT NULL,
  PRIMARY KEY(device_id, source_sha256)
);
