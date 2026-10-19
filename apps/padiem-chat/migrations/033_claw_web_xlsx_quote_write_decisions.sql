-- #3933 Hark WRITE owner decision is distinct from original READ approval.
-- The B62 one-shot write request (032) is not independent authorization.
-- This row must bind an actual paused Engine WRITE ToolInvocation + user act.
CREATE TABLE IF NOT EXISTS claw_web_xlsx_quote_write_decisions (
  selection_ref TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  source_document_id TEXT NOT NULL,
  source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
  workcopy_document_id TEXT NOT NULL,
  edit_sha256 TEXT NOT NULL CHECK(length(edit_sha256)=64),
  pause_id TEXT NOT NULL UNIQUE,
  continuation_ref TEXT NOT NULL UNIQUE,
  outcome TEXT NOT NULL CHECK(outcome IN ('approve','deny')),
  state TEXT NOT NULL CHECK(state IN ('dispatching','confirmed','denied')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(selection_ref)
    REFERENCES claw_web_xlsx_quote_edit_receipts(selection_ref)
);
CREATE INDEX IF NOT EXISTS idx_web_quote_write_decision_owner
  ON claw_web_xlsx_quote_write_decisions(user_id,workspace_id,selection_ref);
