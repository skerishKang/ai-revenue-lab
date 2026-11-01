-- MCP credentials are owner/device-bound authentication only. Existing PC
-- pairing, folder grants, admission and the common Engine harness remain the
-- execution authorities. No plaintext bearer token is persisted.
CREATE TABLE IF NOT EXISTS padiem_mcp_tokens (
    id TEXT NOT NULL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL,
    name TEXT NOT NULL,
    token_sha256 TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_mcp_tokens_owner ON padiem_mcp_tokens(user_id,created_at DESC);

-- A first-party decision for immutable exact tool material. Consumption is a
-- single conditional UPDATE before dispatch; it cannot authorize a replay or
-- change grants. This is not an Engine pause/continuation store.
CREATE TABLE IF NOT EXISTS padiem_mcp_approvals (
    id TEXT NOT NULL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_id TEXT NOT NULL REFERENCES padiem_mcp_tokens(id),
    device_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL CHECK(json_valid(arguments_json)),
    request_digest TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','approved','denied','consumed')),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    decided_at TEXT,
    consumed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_mcp_approvals_owner ON padiem_mcp_approvals(user_id,status,created_at);

-- Audit metadata deliberately excludes bearer credentials, file content and
-- tool output. Exact material is correlated by digest; owner UI alone reads
-- the approval request containing material awaiting the user's decision.
CREATE TABLE IF NOT EXISTS padiem_mcp_audit (
    id TEXT NOT NULL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_id TEXT NOT NULL REFERENCES padiem_mcp_tokens(id),
    device_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    status TEXT NOT NULL,
    approval_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mcp_audit_owner ON padiem_mcp_audit(user_id,created_at DESC);
