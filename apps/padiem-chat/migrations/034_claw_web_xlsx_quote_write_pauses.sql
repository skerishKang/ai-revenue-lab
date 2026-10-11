-- Durable owner-scoped Core WRITE pause. 032 is edit proposal,
-- 033 is owner decision. Neither alone authorizes an XLSX mutation.
CREATE TABLE IF NOT EXISTS claw_web_xlsx_quote_write_pauses (
 selection_ref TEXT PRIMARY KEY,
 user_id TEXT NOT NULL, workspace_id TEXT NOT NULL, run_id TEXT NOT NULL,
 source_document_id TEXT NOT NULL, source_sha256 TEXT NOT NULL,
 workcopy_document_id TEXT NOT NULL, edit_sha256 TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('dispatching','waiting_p01')),
 pause_id TEXT UNIQUE, continuation_ref TEXT UNIQUE,
 pause_expires_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 CHECK((status='dispatching' AND pause_id IS NULL AND continuation_ref IS NULL)
    OR (status='waiting_p01' AND pause_id IS NOT NULL AND continuation_ref IS NOT NULL
        AND pause_expires_at IS NOT NULL)),
 FOREIGN KEY(selection_ref) REFERENCES claw_web_xlsx_quote_edit_receipts(selection_ref)
);
