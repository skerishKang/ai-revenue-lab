-- #4428: central per-product/tier primary and fallback routes. Schema ONLY.
-- Apply via separately approved D1 migration gate against canonical PADIEM_CHAT_DB.
-- No row is inserted here: an absent row preserves the historical static route.
-- B14 remains the catalog/credential/execution authority; this table never
-- registers, activates or authorizes a provider.
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS central_model_route_state (
  workspace_id TEXT PRIMARY KEY CHECK(length(workspace_id) BETWEEN 1 AND 128),
  revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0),
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS central_model_tier_routes (
  workspace_id TEXT NOT NULL REFERENCES central_model_route_state(workspace_id),
  product TEXT NOT NULL CHECK(product IN ('chat','claw','b66')),
  tier TEXT NOT NULL CHECK(tier IN ('FREE','PLUS','PRO','MAX')),
  primary_model_id TEXT NOT NULL CHECK(length(primary_model_id) BETWEEN 1 AND 256),
  fallback_model_id TEXT CHECK(fallback_model_id IS NULL OR length(fallback_model_id) BETWEEN 1 AND 256),
  enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
  PRIMARY KEY(workspace_id,product,tier),
  CHECK(fallback_model_id IS NULL OR fallback_model_id <> primary_model_id)
);

CREATE TABLE IF NOT EXISTS central_model_route_nonces (
  workspace_id TEXT NOT NULL REFERENCES central_model_route_state(workspace_id),
  nonce TEXT NOT NULL CHECK(length(nonce)=32),
  revision INTEGER NOT NULL CHECK(revision>0),
  PRIMARY KEY(workspace_id,nonce)
);

CREATE TABLE IF NOT EXISTS central_model_route_history (
  workspace_id TEXT NOT NULL REFERENCES central_model_route_state(workspace_id),
  revision INTEGER NOT NULL CHECK(revision>0),
  routes_json TEXT NOT NULL CHECK(json_valid(routes_json)),
  PRIMARY KEY(workspace_id,revision)
);

CREATE TABLE IF NOT EXISTS central_model_route_audit (
  workspace_id TEXT NOT NULL REFERENCES central_model_route_state(workspace_id),
  revision INTEGER NOT NULL CHECK(revision>0),
  actor_user_id TEXT NOT NULL CHECK(length(actor_user_id)=36),
  operation TEXT NOT NULL CHECK(operation IN ('apply','rollback')),
  changed_at TEXT NOT NULL,
  diff_json TEXT NOT NULL CHECK(json_valid(diff_json)),
  PRIMARY KEY(workspace_id,revision)
);
