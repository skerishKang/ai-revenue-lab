-- #3580: owner-scoped P01 Engine pause dispatch receipts, not approval.
-- Reservation is one-shot per selection; uncertain dispatch is never retried.
CREATE TABLE IF NOT EXISTS claw_web_xlsx_p01_requests (
    request_ref TEXT PRIMARY KEY,
    selection_ref TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
    status TEXT NOT NULL CHECK(status IN ('dispatching','waiting_p01')),
    engine_run_id TEXT,
    continuation_ref TEXT,
    pause_id TEXT,
    pause_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claw_web_xlsx_p01_owner
  ON claw_web_xlsx_p01_requests(user_id,workspace_id,run_id);
