-- Padiem Chat Business 62 — Phase 10 Projects
-- Apply after 001_auth_history.sql.

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    instructions TEXT NOT NULL DEFAULT '' CHECK (length(instructions) <= 1800),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_projects_user_updated
    ON projects(user_id, updated_at DESC);

ALTER TABLE conversations
    ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_conversations_user_project_updated
    ON conversations(user_id, project_id, updated_at DESC);
