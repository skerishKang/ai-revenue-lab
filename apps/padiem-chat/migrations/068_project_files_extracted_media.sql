-- #5115: widen the project_files media_type CHECK for extracted documents.
--
-- The binary project-file upload path (POST /api/projects/{id}/files with
-- application/octet-stream) parses a PDF/DOCX through the Core authority and
-- stores the EXTRACTED TEXT with media_type 'extracted/pdf' /
-- 'extracted/docx' (app/project_files.py: _extracted_media_type and the
-- create_file extracted/ branch). Migration 003's CHECK only allowed the four
-- text media types, so every binary upload failed the INSERT with
-- sqlite3.IntegrityError -> HTTP 503 on any D1 that runs the shipped schema
-- — the COM2 native runtime measured it live against the published
-- generation copy (2026-10-23), and the repo's binary-upload tests never saw
-- it because they run on in-memory fakes without the schema.
--
-- SQLite cannot alter a CHECK in place, so this is the standard rebuild:
-- new table with the widened CHECK, copy the rows, drop, rename, re-index.

CREATE TABLE project_files_rebuilt_068 (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE NO ACTION,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE NO ACTION,
    name TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK(media_type IN (
        'text/plain', 'text/markdown', 'text/csv', 'application/json',
        'extracted/pdf', 'extracted/docx'
    )),
    content_text TEXT NOT NULL,
    content_chars INTEGER NOT NULL CHECK(content_chars > 0 AND content_chars <= 40000),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO project_files_rebuilt_068
    (id, project_id, user_id, name, media_type, content_text, content_chars, created_at, updated_at)
SELECT id, project_id, user_id, name, media_type, content_text, content_chars, created_at, updated_at
FROM project_files;

DROP TABLE project_files;

ALTER TABLE project_files_rebuilt_068 RENAME TO project_files;

CREATE INDEX IF NOT EXISTS idx_project_files_owner_project
    ON project_files(user_id, project_id, created_at);

CREATE INDEX IF NOT EXISTS idx_project_files_project_updated
    ON project_files(project_id, updated_at DESC);
