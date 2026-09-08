-- WO-10 PR-C2 (D28): OAuth connector grant references (no credential material).
-- Source migration only; applying it to any environment is a separate release action.

CREATE TABLE IF NOT EXISTS padiem_engine_connector_grants (
  app_id TEXT NOT NULL,
  canonical_agent_id TEXT NOT NULL,
  connector_id TEXT NOT NULL,
  binding_ref TEXT NOT NULL,
  actor_ref TEXT NOT NULL,
  granted_scopes_json TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (app_id, connector_id)
);

CREATE INDEX IF NOT EXISTS idx_padiem_engine_connector_grants_active
  ON padiem_engine_connector_grants (connector_id, active);
