-- B62 Phase 11: bounded persistent text documents for Projects.
-- Original binary files are intentionally not stored in this phase.

CREATE TABLE IF NOT EXISTS project_files (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE NO ACTION,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE NO ACTION,
    name TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK(media_type IN (
        'text/plain', 'text/markdown', 'text/csv', 'application/json'
    )),
    content_text TEXT NOT NULL,
    content_chars INTEGER NOT NULL CHECK(content_chars > 0 AND content_chars <= 40000),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_project_files_owner_project
    ON project_files(user_id, project_id, created_at);

CREATE INDEX IF NOT EXISTS idx_project_files_project_updated
    ON project_files(project_id, updated_at DESC);
