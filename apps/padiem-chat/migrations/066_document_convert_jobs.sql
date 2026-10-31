-- #5568 PDF to Markdown utility — additive, owner-scoped work ledger.
-- Converted Markdown and the original PDF bytes live in the signed-in owner's own
-- R2 workspace objects; this ledger stores names, bounds, status and the bounded
-- verification report only. No customer document content is stored in D1.
-- Idempotent (IF NOT EXISTS). Migrations 001-065 are not modified by this change.
CREATE TABLE IF NOT EXISTS document_convert_jobs (
  id TEXT NOT NULL PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  mode TEXT NOT NULL CHECK (mode IN ('fast','verify')),
  status TEXT NOT NULL CHECK (status IN ('queued','working','reviewed','done','failed')),
  item_count INTEGER NOT NULL DEFAULT 0 CHECK (item_count >= 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_document_convert_jobs_recent
  ON document_convert_jobs(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS document_convert_items (
  id TEXT NOT NULL PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES document_convert_jobs(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
  status TEXT NOT NULL CHECK (status IN ('queued','working','reviewed','done','failed')),
  page_count INTEGER NOT NULL DEFAULT 0 CHECK (page_count >= 0),
  character_count INTEGER NOT NULL DEFAULT 0 CHECK (character_count >= 0),
  original_key TEXT NOT NULL,
  markdown_key TEXT,
  report_json TEXT,
  error_code TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (status <> 'done' OR markdown_key IS NOT NULL),
  -- The bounded verification report is the only JSON this ledger holds, and the
  -- store truncates it to the same ceiling rather than letting a row grow.
  CHECK (report_json IS NULL OR length(report_json) <= 12000)
);

CREATE INDEX IF NOT EXISTS idx_document_convert_items_job
  ON document_convert_items(job_id, created_at);

CREATE INDEX IF NOT EXISTS idx_document_convert_items_recent
  ON document_convert_items(user_id, updated_at DESC);
