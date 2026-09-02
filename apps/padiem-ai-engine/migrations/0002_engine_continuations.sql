-- Durable identity-bound approval continuation state for Padiem AI Engine.
-- Source migration only; applying it to any environment is a separate release action.

CREATE TABLE IF NOT EXISTS padiem_engine_continuations (
  app_id TEXT NOT NULL,
  continuation_ref TEXT NOT NULL,
  pause_json TEXT NOT NULL,
  execution_identity_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('active','claimed','cancelling','consumed','cancelled','expired')),
  claim_token TEXT,
  cancel_reason TEXT,
  cancel_event_fingerprint TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  PRIMARY KEY (app_id, continuation_ref)
);

CREATE INDEX IF NOT EXISTS idx_padiem_engine_continuations_expiry
  ON padiem_engine_continuations (state, expires_at);
