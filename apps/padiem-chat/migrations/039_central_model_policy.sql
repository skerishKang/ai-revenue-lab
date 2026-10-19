-- #4453 / S2: common model policy authority. Schema ONLY, no rollout.
-- Apply via separately approved D1 migration gate against canonical PADIEM_CHAT_DB.
-- No migration automatically creates global admins or activates any model.
-- This is independent from legacy B66 membership & grants tables.
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS central_model_policy_state (
  workspace_id TEXT PRIMARY KEY CHECK(length(workspace_id) BETWEEN 1 AND 128),
  revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0),
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS central_model_policy_rules (
  workspace_id TEXT NOT NULL REFERENCES central_model_policy_state(workspace_id),
  product TEXT NOT NULL CHECK(product IN ('central','chat','claw','b66','b14-router')),
  tier TEXT NOT NULL CHECK(tier IN ('FREE','PLUS','PRO','MAX')),
  model_id TEXT NOT NULL CHECK(length(model_id) BETWEEN 1 AND 256),
  action TEXT NOT NULL CHECK(action IN ('allow','block')),
  PRIMARY KEY(workspace_id, product, tier, model_id)
);
CREATE INDEX IF NOT EXISTS idx_central_model_policy_rules_scope
  ON central_model_policy_rules(workspace_id,product,tier);

CREATE TABLE IF NOT EXISTS central_model_policy_nonces (
  workspace_id TEXT NOT NULL REFERENCES central_model_policy_state(workspace_id),
  nonce TEXT NOT NULL CHECK(length(nonce)=32),
  revision INTEGER NOT NULL CHECK(revision>0),
  PRIMARY KEY(workspace_id,nonce)
);

CREATE TABLE IF NOT EXISTS central_model_policy_history (
  workspace_id TEXT NOT NULL REFERENCES central_model_policy_state(workspace_id),
  revision INTEGER NOT NULL CHECK(revision>0),
  rules_json TEXT NOT NULL CHECK(json_valid(rules_json)),
  PRIMARY KEY(workspace_id,revision)
);

CREATE TABLE IF NOT EXISTS central_model_policy_audit (
  workspace_id TEXT NOT NULL REFERENCES central_model_policy_state(workspace_id),
  revision INTEGER NOT NULL CHECK(revision>0),
  actor_user_id TEXT NOT NULL CHECK(length(actor_user_id)=36),
  operation TEXT NOT NULL CHECK(operation IN ('apply','rollback')),
  changed_at TEXT NOT NULL,
  diff_json TEXT NOT NULL CHECK(json_valid(diff_json)),
  PRIMARY KEY(workspace_id,revision)
);
-- Intentionally no INSERT for policy rows, no enabled default, no B14 flags,
-- no runtime policy activation, and no automatic legacy B66 migration.
