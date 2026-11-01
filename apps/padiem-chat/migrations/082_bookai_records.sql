-- BookAI record sync v1 (#6446): signed PADIEM subject is the tenant boundary.
-- Common-login subjects need no corresponding Chat users row.
-- updated_at is the client's Unix timestamp in milliseconds; deleted rows are
-- retained as tombstones so devices that were offline receive the deletion.
CREATE TABLE IF NOT EXISTS bookai_records (
    subject TEXT NOT NULL,
    record_id TEXT NOT NULL,
    book_id TEXT NOT NULL,
    locator TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('progress', 'note', 'highlight', 'ai_chat')),
    payload TEXT NOT NULL CHECK (json_valid(payload) AND json_type(payload) = 'object'),
    updated_at INTEGER NOT NULL CHECK (typeof(updated_at) = 'integer' AND updated_at >= 0),
    deleted INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0, 1)),
    PRIMARY KEY (subject, record_id)
);

CREATE INDEX IF NOT EXISTS idx_bookai_records_subject_updated
    ON bookai_records (subject, updated_at, record_id);
