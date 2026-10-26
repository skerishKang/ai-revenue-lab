-- #5573 limits 3/3: preserve rows/receipt grants and raise XLSX selection to 10MiB.
-- Source migration only; applying to any environment needs separate release approval.
-- Preserve the referencing receipt rows while rebuilding the parent CHECK. This
-- works with foreign_keys=ON inside a D1-style transaction, without disabling it.
PRAGMA defer_foreign_keys=ON;
CREATE TABLE claw_web_xlsx_receipts_limits_backup AS
SELECT * FROM claw_web_xlsx_quote_edit_receipts;
DELETE FROM claw_web_xlsx_quote_edit_receipts;
CREATE TABLE claw_web_xlsx_selections_limits_next (
    selection_ref TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL CHECK (length(source_sha256)=64),
    filename TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 10485760),
    status TEXT NOT NULL DEFAULT 'source_selected_p01_not_started'
      CHECK (status = 'source_selected_p01_not_started'),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

INSERT INTO claw_web_xlsx_selections_limits_next
SELECT * FROM claw_web_xlsx_selections;
DROP TABLE claw_web_xlsx_selections;
ALTER TABLE claw_web_xlsx_selections_limits_next RENAME TO claw_web_xlsx_selections;
CREATE INDEX idx_claw_web_xlsx_selections_owner
ON claw_web_xlsx_selections (user_id, workspace_id, expires_at, created_at);
INSERT INTO claw_web_xlsx_quote_edit_receipts
SELECT * FROM claw_web_xlsx_receipts_limits_backup;
DROP TABLE claw_web_xlsx_receipts_limits_backup;
