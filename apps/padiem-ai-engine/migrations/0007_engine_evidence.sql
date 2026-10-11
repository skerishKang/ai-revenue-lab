-- #2954 ([E9][A6-Document]): canonical Engine evidence retention schema for
-- the CloudflareD1EvidenceStoragePort SQL contract. Source migration only;
-- applying it to any environment is a separate release action (D1 provision
-- gate). No Worker route provisions schema; the ENGINE_EVIDENCE_STORE alias
-- in wrangler.toml only declares the repo-owned binding.

CREATE TABLE IF NOT EXISTS padiem_engine_evidence (
  evidence_id TEXT NOT NULL CHECK (length(evidence_id) >= 16 AND length(evidence_id) <= 64),
  document_json TEXT NOT NULL CHECK (length(document_json) <= 2000000),
  retention_json TEXT NOT NULL CHECK (length(retention_json) <= 2000000),
  created_at TEXT NOT NULL,
  PRIMARY KEY (evidence_id)
);

CREATE INDEX IF NOT EXISTS idx_padiem_engine_evidence_created_at
  ON padiem_engine_evidence (created_at);
