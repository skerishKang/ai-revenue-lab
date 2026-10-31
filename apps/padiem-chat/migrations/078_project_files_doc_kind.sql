-- #5731 (A안): 저장된 글의 '종류'와 덮어쓰기 이전 본문.
--
-- The util tools (축사·SNS·회의·활동집) all stored their text as ordinary
-- project files, so the only thing telling one tool's writing from another's
-- was the file name. A list could therefore only filter by name prefix, and a
-- speech list showed meeting records.
--
-- `doc_kind` is the marker the save itself leaves: speech / sns / meeting /
-- book. An empty value is not an error — it is every row stored before this
-- migration, and the screen groups those under 기타 instead of hiding them.
--
-- `doc_version_of` points at the file a row was displaced from when the owner
-- chose to overwrite. Overwriting never destroys text: the previous body is
-- written as its own project file (same channel, same owner/project scope) and
-- only links back here. Null means "this row is a current document".
--
-- Both are additive column adds. No table is rebuilt and no row is rewritten:
-- every existing file keeps its id, its bytes and its timestamps, and picks up
-- the documented defaults ('' and NULL).

ALTER TABLE project_files ADD COLUMN doc_kind TEXT NOT NULL DEFAULT '';
ALTER TABLE project_files ADD COLUMN doc_version_of TEXT;

CREATE INDEX IF NOT EXISTS idx_project_files_kind
    ON project_files(user_id, project_id, doc_kind, created_at);
