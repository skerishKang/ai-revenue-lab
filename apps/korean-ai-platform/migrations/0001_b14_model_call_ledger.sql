-- B14 model call ledger (#5318)
--
-- Applied to the B14 ledger D1 database by the D1 provision gate. Application
-- code never creates or mutates this schema at request time, and declaring the
-- binding in wrangler.toml is not the same act as applying this file.
--
-- One row per logical B14 request, plus one row per candidate the gateway
-- considered. The parent row is the unit of consumption: tokens and cost are
-- stored there so that a fallback chain is counted once, while the child rows
-- keep each physical attempt (including the ones that failed) visible instead
-- of letting the eventual success overwrite them.
--
-- There is deliberately no prompt, response, header, cookie, IP address or
-- credential column. Identity arrives as opaque references and email-shaped
-- values are refused by the contract before a row is ever built.

CREATE TABLE IF NOT EXISTS b14_model_call (
  log_id                 TEXT PRIMARY KEY CHECK (length(log_id) BETWEEN 8 AND 64),
  request_id             TEXT NOT NULL CHECK (length(request_id) BETWEEN 1 AND 128),
  endpoint               TEXT CHECK (endpoint IS NULL OR length(endpoint) <= 96),
  product                TEXT NOT NULL CHECK (product IN ('chat','claw','b66','engine','api','unknown')),
  origin_source          TEXT NOT NULL CHECK (origin_source IN ('b14_observed','caller_declared','unknown')),
  origin_request_id      TEXT CHECK (origin_request_id IS NULL OR length(origin_request_id) <= 128),
  subject_ref            TEXT CHECK (subject_ref IS NULL OR length(subject_ref) <= 128),
  tenant_ref             TEXT CHECK (tenant_ref IS NULL OR length(tenant_ref) <= 128),
  membership_tier        TEXT CHECK (membership_tier IS NULL OR length(membership_tier) <= 32),
  client_app             TEXT CHECK (client_app IS NULL OR length(client_app) <= 64),
  client_version         TEXT CHECK (client_version IS NULL OR length(client_version) <= 48),
  session_ref            TEXT CHECK (session_ref IS NULL OR length(session_ref) <= 128),
  requested_model_id     TEXT CHECK (requested_model_id IS NULL OR length(requested_model_id) <= 128),
  selected_model_id      TEXT CHECK (selected_model_id IS NULL OR length(selected_model_id) <= 128),
  selected_provider      TEXT CHECK (selected_provider IS NULL OR length(selected_provider) <= 64),
  selected_upstream_model TEXT CHECK (selected_upstream_model IS NULL OR length(selected_upstream_model) <= 128),
  selected_route_id      TEXT CHECK (selected_route_id IS NULL OR length(selected_route_id) <= 128),
  actual_response_model  TEXT CHECK (actual_response_model IS NULL OR length(actual_response_model) <= 128),
  route_mode             TEXT CHECK (route_mode IS NULL OR length(route_mode) <= 16),
  streaming              INTEGER NOT NULL DEFAULT 0 CHECK (streaming IN (0, 1)),
  protocol               TEXT NOT NULL CHECK (protocol IN ('responses','messages','chat/completions','native','unknown')),
  outcome                TEXT NOT NULL CHECK (outcome IN ('success','error','aborted')),
  http_status            INTEGER CHECK (http_status IS NULL OR (http_status >= 100 AND http_status <= 599)),
  error_code             TEXT CHECK (error_code IS NULL OR length(error_code) <= 64),
  finish_reason          TEXT CHECK (finish_reason IS NULL OR length(finish_reason) <= 48),
  started_at             TEXT CHECK (started_at IS NULL OR length(started_at) <= 32),
  finished_at            TEXT CHECK (finished_at IS NULL OR length(finished_at) <= 32),
  elapsed_ms             INTEGER CHECK (elapsed_ms IS NULL OR elapsed_ms >= 0),
  latency_source         TEXT NOT NULL CHECK (latency_source IN ('measured','unknown')),
  ttft_ms                INTEGER CHECK (ttft_ms IS NULL OR ttft_ms >= 0),
  attempt_count          INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 32),
  fallback_used          INTEGER NOT NULL DEFAULT 0 CHECK (fallback_used IN (0, 1)),
  fallback_depth         INTEGER NOT NULL DEFAULT 0 CHECK (fallback_depth BETWEEN 0 AND 32),
  -- NULL with token_source='missing' means the provider reported nothing.
  -- A stored zero here would later read as "this call cost nothing".
  prompt_tokens          INTEGER CHECK (prompt_tokens IS NULL OR prompt_tokens >= 0),
  completion_tokens      INTEGER CHECK (completion_tokens IS NULL OR completion_tokens >= 0),
  total_tokens           INTEGER CHECK (total_tokens IS NULL OR total_tokens >= 0),
  reasoning_tokens       INTEGER CHECK (reasoning_tokens IS NULL OR reasoning_tokens >= 0),
  token_source           TEXT NOT NULL CHECK (token_source IN ('measured','missing')),
  -- Catalog price snapshot applied to measured tokens; never an invoice.
  estimated_usd          REAL CHECK (estimated_usd IS NULL OR estimated_usd >= 0),
  estimated_krw          REAL CHECK (estimated_krw IS NULL OR estimated_krw >= 0),
  cost_basis             TEXT NOT NULL CHECK (cost_basis IN ('configured_snapshot','known_free','unknown')),
  currency               TEXT NOT NULL DEFAULT 'USD' CHECK (length(currency) <= 8)
);

CREATE TABLE IF NOT EXISTS b14_model_call_attempt (
  log_id                 TEXT NOT NULL REFERENCES b14_model_call(log_id) ON DELETE CASCADE,
  attempt_index          INTEGER NOT NULL CHECK (attempt_index BETWEEN 0 AND 32),
  provider               TEXT CHECK (provider IS NULL OR length(provider) <= 64),
  model_id               TEXT CHECK (model_id IS NULL OR length(model_id) <= 128),
  upstream_model         TEXT CHECK (upstream_model IS NULL OR length(upstream_model) <= 128),
  route_id               TEXT CHECK (route_id IS NULL OR length(route_id) <= 128),
  outcome                TEXT NOT NULL CHECK (outcome IN ('success','error','aborted')),
  error_code             TEXT CHECK (error_code IS NULL OR length(error_code) <= 64),
  retry_index            INTEGER NOT NULL DEFAULT 0 CHECK (retry_index >= 0),
  actual_response_model  TEXT CHECK (actual_response_model IS NULL OR length(actual_response_model) <= 128),
  finish_reason          TEXT CHECK (finish_reason IS NULL OR length(finish_reason) <= 48),
  provider_request_id    TEXT CHECK (provider_request_id IS NULL OR length(provider_request_id) <= 128),
  started_at             TEXT CHECK (started_at IS NULL OR length(started_at) <= 32),
  finished_at            TEXT CHECK (finished_at IS NULL OR length(finished_at) <= 32),
  elapsed_ms             INTEGER CHECK (elapsed_ms IS NULL OR elapsed_ms >= 0),
  latency_source         TEXT NOT NULL CHECK (latency_source IN ('measured','unknown')),
  prompt_tokens          INTEGER CHECK (prompt_tokens IS NULL OR prompt_tokens >= 0),
  completion_tokens      INTEGER CHECK (completion_tokens IS NULL OR completion_tokens >= 0),
  total_tokens           INTEGER CHECK (total_tokens IS NULL OR total_tokens >= 0),
  reasoning_tokens       INTEGER CHECK (reasoning_tokens IS NULL OR reasoning_tokens >= 0),
  token_source           TEXT NOT NULL CHECK (token_source IN ('measured','missing')),
  estimated_usd          REAL CHECK (estimated_usd IS NULL OR estimated_usd >= 0),
  estimated_krw          REAL CHECK (estimated_krw IS NULL OR estimated_krw >= 0),
  cost_basis             TEXT NOT NULL CHECK (cost_basis IN ('configured_snapshot','known_free','unknown')),
  endpoint               TEXT CHECK (endpoint IS NULL OR length(endpoint) <= 96),
  protocol               TEXT NOT NULL CHECK (protocol IN ('responses','messages','chat/completions','native','unknown')),
  -- 0 marks a candidate the gateway skipped without dispatching it. It is
  -- routing evidence, not a provider call, and is excluded from call counts.
  dispatched             INTEGER NOT NULL DEFAULT 1 CHECK (dispatched IN (0, 1)),
  PRIMARY KEY (log_id, attempt_index)
);

-- The dashboard's default read is a time-ordered list, then a filter sweep.
CREATE INDEX IF NOT EXISTS b14_model_call_started ON b14_model_call (started_at);
CREATE INDEX IF NOT EXISTS b14_model_call_request ON b14_model_call (request_id);
CREATE INDEX IF NOT EXISTS b14_model_call_outcome ON b14_model_call (outcome, started_at);
CREATE INDEX IF NOT EXISTS b14_model_call_model ON b14_model_call (selected_model_id, started_at);
CREATE INDEX IF NOT EXISTS b14_model_call_product ON b14_model_call (product, started_at);
CREATE INDEX IF NOT EXISTS b14_model_call_subject ON b14_model_call (subject_ref, started_at);
CREATE INDEX IF NOT EXISTS b14_model_call_attempt_log ON b14_model_call_attempt (log_id, attempt_index);
