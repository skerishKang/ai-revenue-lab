-- #5318 PADIEM AI model call records (slice A: storage).
-- Additive, idempotent (IF NOT EXISTS). Migrations 001-066 are not modified.
-- Records one row per actual provider call: provider, model, time, outcome,
-- retry/fallback, token counts and estimated cost. This is SEPARATE from the
-- usage/quota ledger (D1UsageCounterStore) which tracks abuse-rate limits only;
-- this ledger is the audit/observability/cost authority. No customer prompt or
-- completion text is stored here.
CREATE TABLE IF NOT EXISTS model_call_records (
  id TEXT NOT NULL PRIMARY KEY,
  product TEXT NOT NULL CHECK (product IN ('chat','claw','b66','engine','b14_api','other')),
  user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  provider_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  called_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('success','error','timeout')),
  retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
  fallback_used INTEGER NOT NULL DEFAULT 0 CHECK (fallback_used IN (0,1)),
  input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
  output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
  reasoning_tokens INTEGER NOT NULL DEFAULT 0 CHECK (reasoning_tokens >= 0),
  cached_tokens INTEGER NOT NULL DEFAULT 0 CHECK (cached_tokens >= 0),
  cost_usd REAL NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
  cost_krw REAL NOT NULL DEFAULT 0 CHECK (cost_krw >= 0),
  error_code TEXT,
  conversation_id TEXT,
  duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_model_call_records_recent
  ON model_call_records(called_at DESC);

CREATE INDEX IF NOT EXISTS idx_model_call_records_product_time
  ON model_call_records(product, called_at DESC);

CREATE INDEX IF NOT EXISTS idx_model_call_records_provider_model
  ON model_call_records(provider_id, model_id, called_at DESC);

CREATE INDEX IF NOT EXISTS idx_model_call_records_user
  ON model_call_records(user_id, called_at DESC);