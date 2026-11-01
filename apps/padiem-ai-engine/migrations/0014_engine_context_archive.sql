-- #6460 5-1: owner-scoped originals for compacted PC conversation context.
-- A summary keeps only source ids; the original role/content of every removed
-- turn or tool result stays here and is readable through claw.pc.recall_context.
-- Source migration only; applying it to an environment is a separate release
-- action (D1/LocalSqlite migration gate). No Worker route provisions schema.
CREATE TABLE IF NOT EXISTS padiem_engine_context_archive_v1 (
    owner_scope TEXT NOT NULL,
    source_id TEXT NOT NULL,
    message_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (owner_scope, source_id)
);

CREATE INDEX IF NOT EXISTS idx_engine_context_archive_owner
    ON padiem_engine_context_archive_v1(owner_scope);
