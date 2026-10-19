-- #3929 Hark: owner/conversation/workspace-scoped durable Claw artifact index.
-- Production additive migration only, NOT implicitly applied by Worker runtime.
-- Raw provider location is private and must never be exposed in GET projection.
-- Intentionally no grant/secret/ref minting: registration is authorized only
-- after a completed, already owner/conv/workspace-bound Claw run.
CREATE TABLE IF NOT EXISTS claw_conversation_artifact_index (
    ordinal INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    workspace_ref TEXT NOT NULL,
    source_run_ref TEXT NOT NULL REFERENCES claw_run_history(run_id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK (
        media_type IN (
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/pdf'
        )
    ),
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 10485760),
    integrity_ref TEXT NOT NULL CHECK (length(integrity_ref) = 64),
    location_kind TEXT NOT NULL,
    location_ref TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claw_conversation_artifact_owner
ON claw_conversation_artifact_index (
    user_id, conversation_id, workspace_ref, ordinal DESC
);
