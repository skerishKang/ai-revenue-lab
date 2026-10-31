-- #5882 PR-E: the stored text ceiling of project_files was an arbitrary 40,000
-- characters (migrations 003 / 068 / 069 declared `CHECK(content_chars <= 40000)`).
-- 40,000 characters is not a platform limit. The platform limit is D1's per-row
-- size (~2 MB), and one Korean character costs 3 UTF-8 bytes, so a character
-- ceiling refused bodies that D1 would hold without complaint: 40,000 Korean
-- characters is only ~117 KB of the ~2 MB a row may occupy.
--
-- The ceiling now measures the bytes D1 actually limits:
--     CHECK(length(CAST(content_text AS BLOB)) <= 2097152)
-- 2,097,152 bytes = 2 MiB, D1's documented per-row limit. That is the physical
-- bound, not a product cap: no row that fits D1 is refused here.
--
-- `content_chars` keeps its semantic floor — > 0 for a text-bearing media type,
-- >= 0 for an image original that carries no text (the #5728 case) — and loses
-- the arbitrary upper bound.
--
-- SQLite cannot alter a CHECK in place, so this is the same rebuild migration
-- 068 and 069 already used: new table with the widened CHECK, copy the rows,
-- drop, rename, re-index. `country` (added by 075) is carried through.

CREATE TABLE project_files_rebuilt_077 (
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
            AND content_chars >= 0)
        OR
        (media_type NOT IN ('image/png', 'image/jpeg', 'image/webp')
            AND content_chars > 0)
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT 'kr',
    CHECK(length(CAST(content_text AS BLOB)) <= 2097152)
);

INSERT INTO project_files_rebuilt_077
    (id, project_id, user_id, name, media_type, content_text, content_chars,
     created_at, updated_at, country)
SELECT id, project_id, user_id, name, media_type, content_text, content_chars,
       created_at, updated_at, country
FROM project_files;

DROP TABLE project_files;

ALTER TABLE project_files_rebuilt_077 RENAME TO project_files;

CREATE INDEX IF NOT EXISTS idx_project_files_owner_project
    ON project_files(user_id, project_id, created_at);

CREATE INDEX IF NOT EXISTS idx_project_files_project_updated
    ON project_files(project_id, updated_at DESC);
