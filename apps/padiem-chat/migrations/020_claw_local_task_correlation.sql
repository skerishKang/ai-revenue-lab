CREATE TABLE IF NOT EXISTS claw_local_task_correlation (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    tool_request_ref TEXT NOT NULL,
    request_id TEXT NOT NULL,
    revision_ref TEXT NOT NULL,
    evidence_ref TEXT,
    request_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_claw_local_task_correlation_user_run
ON claw_local_task_correlation (user_id, run_id);
