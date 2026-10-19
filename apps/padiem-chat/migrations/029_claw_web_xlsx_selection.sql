-- #3580 web-first: a selection of a stored XLSX is NOT a P01 approval.
-- No Engine continuation, file content, local path or Drive scope resides here.
CREATE TABLE IF NOT EXISTS claw_web_xlsx_selections (
    selection_ref TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL CHECK (length(source_sha256)=64),
    filename TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 1048576),
    status TEXT NOT NULL DEFAULT 'source_selected_p01_not_started'
      CHECK (status = 'source_selected_p01_not_started'),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claw_web_xlsx_selections_owner
ON claw_web_xlsx_selections (user_id, workspace_id, expires_at, created_at);
