-- #3933 independent Engine D1 WRITE ToolInvocation; NEVER widen READ app.
-- Provision before enabling separate Engine WRITE Core/Owner flags.
CREATE TABLE IF NOT EXISTS padiem_web_quote_write_tool_continuations (
  app_id TEXT NOT NULL CHECK(app_id='padiem-web-xlsx-write-p01'),
  continuation_ref TEXT NOT NULL,
  pause_id TEXT NOT NULL UNIQUE,
  pause_json TEXT NOT NULL,
  canonical_agent_id TEXT NOT NULL,
  canonical_tool_id TEXT NOT NULL,
  invocation_json TEXT NOT NULL,
  invocation_sha256 TEXT NOT NULL CHECK(length(invocation_sha256)=64),
  state TEXT NOT NULL CHECK(state IN ('active','claimed','consumed','expired')),
  claim_token TEXT,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  PRIMARY KEY(app_id,continuation_ref)
);
CREATE INDEX IF NOT EXISTS idx_web_quote_write_tool_expiry
  ON padiem_web_quote_write_tool_continuations(state,expires_at);
