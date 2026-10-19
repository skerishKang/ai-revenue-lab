-- #3933 one-shot, owner-specific WEB-FIRST XLSX quote EDIT/WRITE decision.
-- A confirmed READ or workcopy is NEVER a write grant. The Engine must
-- independently verify exactly this D1 dispatching receipt/ToolRuntime pause.
CREATE TABLE IF NOT EXISTS claw_web_xlsx_quote_edit_receipts (
  selection_ref TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  source_document_id TEXT NOT NULL,
  source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
  workcopy_document_id TEXT NOT NULL,
  edit_sha256 TEXT NOT NULL CHECK(length(edit_sha256)=64),
  school_name TEXT NOT NULL,
  supply_amount INTEGER NOT NULL CHECK(supply_amount>0 AND supply_amount<=999999999999),
  state TEXT NOT NULL CHECK(state IN ('dispatching','confirmed')),
  revision_document_id TEXT,
  revision_sha256 TEXT CHECK(revision_sha256 IS NULL OR length(revision_sha256)=64),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK((state='dispatching' AND revision_document_id IS NULL AND revision_sha256 IS NULL)
      OR (state='confirmed' AND revision_document_id IS NOT NULL AND revision_sha256 IS NOT NULL)),
  FOREIGN KEY(selection_ref) REFERENCES claw_web_xlsx_selections(selection_ref)
);
CREATE INDEX IF NOT EXISTS idx_claw_web_xlsx_quote_edit_owner
  ON claw_web_xlsx_quote_edit_receipts(user_id,workspace_id,selection_ref);
