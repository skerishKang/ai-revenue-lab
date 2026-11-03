-- MCP OAuth 2.1 web-connector support.
--
-- The existing personal access token table stays the one credential row shape.
-- An OAuth grant is the same owner/device-bound row with kind='oauth', a
-- short-lived access hash, a rotating refresh hash and the client/resource
-- binding used for audience checks. Only hashes are stored.
--
-- Additive: existing PAT rows keep kind='pat' and NULL expiry/refresh/client
-- columns and authenticate exactly as before.
ALTER TABLE padiem_mcp_tokens ADD COLUMN kind TEXT NOT NULL DEFAULT 'pat';
ALTER TABLE padiem_mcp_tokens ADD COLUMN expires_at TEXT;
ALTER TABLE padiem_mcp_tokens ADD COLUMN refresh_token_sha256 TEXT;
ALTER TABLE padiem_mcp_tokens ADD COLUMN refresh_expires_at TEXT;
ALTER TABLE padiem_mcp_tokens ADD COLUMN client_id TEXT;
ALTER TABLE padiem_mcp_tokens ADD COLUMN scope TEXT;
ALTER TABLE padiem_mcp_tokens ADD COLUMN resource TEXT;

CREATE INDEX IF NOT EXISTS idx_mcp_tokens_refresh ON padiem_mcp_tokens(refresh_token_sha256);
CREATE INDEX IF NOT EXISTS idx_mcp_tokens_client ON padiem_mcp_tokens(client_id);

-- Dynamic Client Registration / pre-registered public and confidential clients.
-- A public client has no secret; its PKCE verifier is the proof at the token
-- endpoint. A confidential client stores only the SHA-256 of its secret.
CREATE TABLE IF NOT EXISTS padiem_mcp_oauth_clients (
    client_id TEXT NOT NULL PRIMARY KEY,
    client_secret_sha256 TEXT,
    client_name TEXT NOT NULL,
    redirect_uris_json TEXT NOT NULL CHECK(json_valid(redirect_uris_json)),
    token_endpoint_auth_method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);

-- One-time authorization codes. The code string is never stored; the SHA-256
-- is the primary key. Consumption is one conditional UPDATE so a second
-- exchange cannot reuse the code or race another exchange.
CREATE TABLE IF NOT EXISTS padiem_mcp_oauth_codes (
    code_sha256 TEXT NOT NULL PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES padiem_mcp_oauth_clients(client_id),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    code_challenge_method TEXT NOT NULL,
    scope TEXT NOT NULL,
    resource TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_mcp_oauth_codes_user ON padiem_mcp_oauth_codes(user_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_mcp_oauth_codes_client ON padiem_mcp_oauth_codes(client_id);
