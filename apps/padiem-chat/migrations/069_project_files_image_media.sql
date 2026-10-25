-- #5728: the SNS composition photos persist through the project_files table
-- as OPAQUE ORIGINALS — media_type is the uploaded image type and the record
-- carries no text (content_chars = 0). Migration 068's rebuilt CHECK neither
-- lists the image media types nor allows a zero-length text body, so every
-- image insert fails with sqlite3.IntegrityError on any D1 that runs the
-- shipped schema — the same schema-only trap #5115/#5763 documented for the
-- extracted text documents, and one the in-memory store tests cannot see.
--
-- SQLite cannot alter a CHECK in place, so this is the standard rebuild:
-- new table with the widened CHECK, copy the rows, drop, rename, re-index.
-- The content_chars floor stays > 0 for every text-bearing media type and
-- relaxes to >= 0 only for the three image originals.

CREATE TABLE project_files_rebuilt_069 (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE NO ACTION,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE NO ACTION,
    name TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK(media_type IN (
        'text/plain', 'text/markdown', 'text/csv', 'application/json',
        'extracted/pdf', 'extracted/docx',
        'image/png', 'image/jpeg', 'image/webp'
    )),
    content_text TEXT NOT NULL,
    content_chars INTEGER NOT NULL CHECK(
        (media_type IN ('image/png', 'image/jpeg', 'image/webp')
            AND content_chars >= 0 AND content_chars <= 40000)
        OR
        (media_type NOT IN ('image/png', 'image/jpeg', 'image/webp')
            AND content_chars > 0 AND content_chars <= 40000)
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO project_files_rebuilt_069
    (id, project_id, user_id, name, media_type, content_text, content_chars, created_at, updated_at)
SELECT id, project_id, user_id, name, media_type, content_text, content_chars, created_at, updated_at
FROM project_files;

DROP TABLE project_files;

ALTER TABLE project_files_rebuilt_069 RENAME TO project_files;

CREATE INDEX IF NOT EXISTS idx_project_files_owner_project
    ON project_files(user_id, project_id, created_at);

CREATE INDEX IF NOT EXISTS idx_project_files_project_updated
    ON project_files(project_id, updated_at DESC);
