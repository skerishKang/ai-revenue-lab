-- #3782 source-only: canonical Engine-verified browser.control approval receipts.
-- This DOES NOT issue an approval or add an Engine/Worker route.
-- Schema application to D1 is a separate owner-authorized action.
-- Receipts are inert unless the canonical Engine continuation is CONSUMED.
CREATE TABLE IF NOT EXISTS padiem_engine_browser_control_p01_receipts (
  app_id TEXT NOT NULL,
  continuation_ref TEXT NOT NULL,
  pause_id TEXT NOT NULL,
  decision_id TEXT NOT NULL,
  evidence_ref TEXT NOT NULL,
  authority_ref TEXT NOT NULL,
  run_id TEXT NOT NULL,
  invocation_sha256 TEXT NOT NULL,
  approved_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  PRIMARY KEY (app_id, continuation_ref),
  UNIQUE (app_id, decision_id),
  FOREIGN KEY (app_id, continuation_ref)
    REFERENCES padiem_engine_continuations (app_id, continuation_ref)
);
CREATE INDEX IF NOT EXISTS idx_padiem_engine_browser_control_p01_receipts_expiry
  ON padiem_engine_browser_control_p01_receipts (expires_at, revoked_at);
