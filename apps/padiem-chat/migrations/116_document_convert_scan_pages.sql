-- #5568 S3: per-page sub-work for one document conversion.
--
-- One row per page of an item that went through the scan path. D1 keeps only
-- bounded state, counters and a pointer: the page's own text stays in R2, and
-- the pointer is cleared when the page image is removed. A page that finished
-- is never read again, so a host restart resumes at the first unfinished page.
--
-- status:
--   pending        not started, or put back after a restart
--   working        claimed by one run
--   ok             read in full
--   partial_length output budget ran out; the text that exists is kept
--   failed         no usable text; the page keeps the base conversion's notice
CREATE TABLE IF NOT EXISTS document_convert_scan_pages (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('text', 'scan')),
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'working', 'ok', 'partial_length', 'failed')
    ),
    attempts INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER,
    reasoning_tokens INTEGER,
    completion_tokens INTEGER,
    seconds REAL,
    error_code TEXT,
    markdown_key TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (item_id, page_number)
);

CREATE INDEX IF NOT EXISTS idx_document_convert_scan_pages_item
    ON document_convert_scan_pages (item_id, page_number);

-- The daily page ceiling counts pages that actually finished today for one
-- owner, across every document, so an unfinished page is never charged twice
-- and a resumed page is not charged again.
CREATE INDEX IF NOT EXISTS idx_document_convert_scan_pages_daily
    ON document_convert_scan_pages (user_id, completed_at);
