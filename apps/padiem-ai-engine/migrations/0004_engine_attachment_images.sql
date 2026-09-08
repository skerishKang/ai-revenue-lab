-- #2152 (A6 S2): canonical attachment-image byte retention schema for the
-- #2138 CloudflareD1ImageByteStore SQL contract. Source migration only;
-- applying it to any environment is a separate release action (provision gate).
-- No Worker binding, no composition wiring and no admission path live here.

CREATE TABLE IF NOT EXISTS padiem_engine_attachment_images (
  attachment_ref TEXT NOT NULL,
  app_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  media_type TEXT NOT NULL CHECK (media_type IN ('image/jpeg', 'image/png', 'image/webp')),
  byte_size INTEGER NOT NULL CHECK (byte_size > 0 AND byte_size <= 4194304),
  created_at TEXT NOT NULL,
  expires_at TEXT,
  terminal INTEGER NOT NULL DEFAULT 0 CHECK (terminal IN (0, 1)),
  payload_base64 TEXT NOT NULL CHECK (length(payload_base64) <= 5592412),
  PRIMARY KEY (attachment_ref)
);

CREATE INDEX IF NOT EXISTS idx_padiem_engine_attachment_images_expires_at
  ON padiem_engine_attachment_images (expires_at);

CREATE INDEX IF NOT EXISTS idx_padiem_engine_attachment_images_scope
  ON padiem_engine_attachment_images (app_id, tenant_id, subject_id);
