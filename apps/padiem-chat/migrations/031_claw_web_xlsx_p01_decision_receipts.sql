-- #3580: one owner-scoped, irreversible dispatch attempt per P01 pause.
-- No browser-minted Engine continuation, and no implied processing authority.
CREATE TABLE IF NOT EXISTS claw_web_xlsx_p01_decision_receipts (
  request_ref TEXT PRIMARY KEY,
  selection_ref TEXT NOT NULL,
  user_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
  pause_id TEXT NOT NULL UNIQUE,
  outcome TEXT NOT NULL CHECK(outcome IN ('approve','deny')),
  state TEXT NOT NULL CHECK(state IN ('dispatching','denied','confirmed')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(request_ref) REFERENCES claw_web_xlsx_p01_requests(request_ref)
);
CREATE INDEX IF NOT EXISTS idx_web_xlsx_p01_decision_owner
  ON claw_web_xlsx_p01_decision_receipts(user_id,workspace_id,selection_ref);
