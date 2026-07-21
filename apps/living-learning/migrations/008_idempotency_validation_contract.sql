-- Migration 008: Concurrent idempotency validation contract
-- Replaces simple SELECT-INSERT with atomic claim/complete/fail pattern

PRAGMA foreign_keys=OFF;

-- 1. Create new idempotency_requests table with proper lifecycle
CREATE TABLE IF NOT EXISTS idempotency_requests (
    id TEXT PRIMARY KEY,
    key_value TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    learner_id TEXT NOT NULL DEFAULT '',
    resource_id TEXT NOT NULL DEFAULT '',
    request_fingerprint TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'failed')),
    result_json TEXT DEFAULT NULL,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    lease_expires_at TEXT DEFAULT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_idempotency_key_op_resource
    ON idempotency_requests(key_value, operation_type, resource_id);

-- 2. Migrate existing data from idempotency_keys if table exists
INSERT OR IGNORE INTO idempotency_requests
    (id, key_value, operation_type, learner_id, resource_id, request_fingerprint, status, result_json, attempt_number, created_at)
SELECT
    'idem_' || substr(hex(randomblob(16)), 1, 32),
    key_value,
    'lesson_generation',
    COALESCE(lesson_id, ''),
    COALESCE(lesson_id, ''),
    key_value,
    'completed',
    result,
    1,
    created_at
FROM idempotency_keys
WHERE key_value IS NOT NULL;

-- 3. Drop old idempotency_keys table
DROP TABLE IF EXISTS idempotency_keys;

-- 4. Add validation_result column to generation_runs if not exists
CREATE TABLE IF NOT EXISTS generation_runs_new (
    id TEXT PRIMARY KEY,
    attempt_group_id TEXT NOT NULL DEFAULT '',
    attempt_number INTEGER NOT NULL DEFAULT 1,
    request_id TEXT,
    task_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    advertised_model TEXT,
    cost_class TEXT DEFAULT 'free',
    prompt_version TEXT,
    latency_ms REAL DEFAULT 0,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    success INTEGER NOT NULL DEFAULT 0,
    validation_result TEXT DEFAULT 'pending',
    error_category TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    lesson_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO generation_runs_new
    (id, attempt_group_id, attempt_number, request_id, task_type, provider, advertised_model, cost_class,
     prompt_version, latency_ms, prompt_tokens, completion_tokens, success, error_category, error_message, lesson_id, created_at)
SELECT
    id,
    COALESCE(request_id, id),
    1,
    request_id,
    task_type,
    provider,
    advertised_model,
    cost_class,
    prompt_version,
    latency_ms,
    prompt_tokens,
    completion_tokens,
    success,
    COALESCE(error_category, ''),
    COALESCE(error_message, ''),
    lesson_id,
    created_at
FROM generation_runs;

DROP TABLE generation_runs;
ALTER TABLE generation_runs_new RENAME TO generation_runs;

PRAGMA foreign_keys=ON;
