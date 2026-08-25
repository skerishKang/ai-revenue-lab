CREATE TABLE IF NOT EXISTS saved_outputs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    conversation_id TEXT,
    project_id TEXT,
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 100),
    content_text TEXT NOT NULL CHECK(length(content_text) BETWEEN 1 AND 32000),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_saved_outputs_user_updated
    ON saved_outputs(user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saved_outputs_conversation
    ON saved_outputs(user_id, conversation_id)
    WHERE conversation_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_saved_outputs_project
    ON saved_outputs(user_id, project_id)
    WHERE project_id IS NOT NULL;
