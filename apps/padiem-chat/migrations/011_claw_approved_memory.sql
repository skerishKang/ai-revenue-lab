CREATE TABLE IF NOT EXISTS claw_approved_memory (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    name TEXT NOT NULL,
    note TEXT,
    source_channel TEXT,
    status TEXT NOT NULL DEFAULT 'approved',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claw_approved_memory_owner_workspace_created
ON claw_approved_memory (user_id, workspace_id, created_at DESC);
