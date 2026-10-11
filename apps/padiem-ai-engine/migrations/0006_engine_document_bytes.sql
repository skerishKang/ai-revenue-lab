-- #2741 (E8C-B): canonical Engine-owned document byte retention schema for
-- the CloudflareD1DocumentByteStore SQL contract (doc_* namespace). Source
-- migration only; applying it to any environment is a separate release
-- action (D1 provision gate). No Worker route, no composition wiring and no
-- admission activation live here; the ENGINE_DOCUMENT_STORE alias in
-- wrangler.toml only declares the repo-owned binding.

CREATE TABLE IF NOT EXISTS padiem_engine_document_bytes (
  document_ref TEXT NOT NULL,
  app_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  media_type TEXT NOT NULL CHECK (media_type IN (
    'text/plain',
    'text/markdown',
    'text/csv',
    'application/json',
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/hwp+zip'
  )),
  name TEXT NOT NULL CHECK (length(name) > 0 AND length(name) <= 120),
  byte_size INTEGER NOT NULL CHECK (byte_size > 0 AND byte_size <= 2097152),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  terminal INTEGER NOT NULL DEFAULT 0 CHECK (terminal IN (0, 1)),
  payload_base64 TEXT NOT NULL CHECK (length(payload_base64) <= 2796208),
  PRIMARY KEY (document_ref)
);

CREATE INDEX IF NOT EXISTS idx_padiem_engine_document_bytes_expires_at
  ON padiem_engine_document_bytes (expires_at);

CREATE INDEX IF NOT EXISTS idx_padiem_engine_document_bytes_scope
  ON padiem_engine_document_bytes (app_id, tenant_id, subject_id);
