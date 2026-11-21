-- #8204: immutable release snapshots and administrator-controlled rollout.
CREATE TABLE IF NOT EXISTS pc_helper_rollout (
  singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
  revision INTEGER NOT NULL CHECK(revision >= 1),
  plan_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pc_helper_rollout_outcomes (
  device_id TEXT NOT NULL,
  release_sha256 TEXT NOT NULL CHECK(length(release_sha256) = 64),
  outcome TEXT NOT NULL CHECK(outcome IN ('updated','failed','rollback')),
  received_at TEXT NOT NULL,
  PRIMARY KEY(device_id, release_sha256)
);
