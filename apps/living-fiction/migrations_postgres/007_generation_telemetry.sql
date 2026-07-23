-- Generation telemetry: runs and per-attempt records.

CREATE TABLE IF NOT EXISTS generation_runs (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    advertised_model TEXT NOT NULL,
    cost_class TEXT NOT NULL DEFAULT 'free',
    prompt_version TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    latency_seconds DOUBLE PRECISION
        CHECK (latency_seconds IS NULL OR latency_seconds >= 0),
    success SMALLINT NOT NULL DEFAULT 0 CHECK (success IN (0, 1)),
    validation_status TEXT,
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    error_category TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generation_attempts (
    id TEXT PRIMARY KEY,
    generation_run_id TEXT NOT NULL REFERENCES generation_runs (id),
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    provider TEXT NOT NULL,
    advertised_model TEXT NOT NULL,
    cost_class TEXT NOT NULL DEFAULT 'unknown',
    request_id TEXT,
    task_type TEXT NOT NULL,
    prompt_version TEXT,
    latency_seconds DOUBLE PRECISION
        CHECK (latency_seconds IS NULL OR latency_seconds >= 0),
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    total_tokens INTEGER CHECK (total_tokens IS NULL OR total_tokens >= 0),
    success SMALLINT NOT NULL DEFAULT 0 CHECK (success IN (0, 1)),
    retryable SMALLINT NOT NULL DEFAULT 0 CHECK (retryable IN (0, 1)),
    error_category TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (generation_run_id, attempt_number)
);
