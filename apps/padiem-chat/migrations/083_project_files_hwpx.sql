-- Preserve every project row and index while admitting extracted HWPX.
CREATE TABLE project_files_rebuilt_083 (
 id TEXT PRIMARY KEY,
 project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE NO ACTION,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE NO ACTION,
 name TEXT NOT NULL,
 media_type TEXT NOT NULL CHECK(media_type IN (
  'text/plain','text/markdown','text/csv','application/json',
  'extracted/pdf','extracted/docx','extracted/hwpx',
  'image/png','image/jpeg','image/webp'
 )),
 content_text TEXT NOT NULL,
 content_chars INTEGER NOT NULL CHECK(
  (media_type IN ('image/png','image/jpeg','image/webp') AND content_chars >= 0)
  OR (media_type NOT IN ('image/png','image/jpeg','image/webp') AND content_chars > 0)
 ),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 country TEXT NOT NULL DEFAULT 'kr',
 doc_kind TEXT NOT NULL DEFAULT '',
 doc_version_of TEXT,
 CHECK(length(CAST(content_text AS BLOB)) <= 2097152)
);
INSERT INTO project_files_rebuilt_083
 (id,project_id,user_id,name,media_type,content_text,content_chars,created_at,updated_at,country,doc_kind,doc_version_of)
SELECT id,project_id,user_id,name,media_type,content_text,content_chars,created_at,updated_at,country,doc_kind,doc_version_of FROM project_files;
DROP TABLE project_files;
ALTER TABLE project_files_rebuilt_083 RENAME TO project_files;
CREATE INDEX IF NOT EXISTS idx_project_files_owner_project ON project_files(user_id,project_id,created_at);
CREATE INDEX IF NOT EXISTS idx_project_files_project_updated ON project_files(project_id,updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_project_files_kind ON project_files(user_id,project_id,doc_kind,created_at);
