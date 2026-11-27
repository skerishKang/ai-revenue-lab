-- One durable cadence cursor per Chat instance; CAS decides which worker wins.
-- The OS process lock is retained separately for full-round mutual exclusion.
CREATE TABLE IF NOT EXISTS pc_helper_maintenance_rounds (
  cadence_seconds INTEGER PRIMARY KEY CHECK (cadence_seconds IN (60,900)),
  window_id INTEGER NOT NULL,
  round_id TEXT NOT NULL,
  last_round_at TEXT NOT NULL,
  lease_expires_at TEXT NOT NULL,
  completed_at TEXT
);
