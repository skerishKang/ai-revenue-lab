CREATE TABLE IF NOT EXISTS claw_run_history (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    run_id TEXT NOT NULL UNIQUE,
    channel TEXT NOT NULL,
    action TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_summary TEXT,
    artifact_document_id TEXT,
    artifact_filename TEXT,
    artifact_media_type TEXT
);

CREATE INDEX IF NOT EXISTS idx_claw_run_history_user_created
ON claw_run_history (user_id, created_at DESC);
