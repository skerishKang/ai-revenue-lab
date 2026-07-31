-- Migration 009: portal-ready identity boundary, provider accounting, and
-- atomic idempotency lifecycle. ADDITIVE ONLY — does not modify migrations
-- 001..008. Rebuilds idempotency_requests to widen the status domain and make
-- the operation key globally unique; adds accounting columns to
-- generation_runs; creates adaptation_decisions, external_identities and
-- product_memberships.

PRAGMA foreign_keys=OFF;

-- ---------------------------------------------------------------------------
-- 1. Idempotency lifecycle: widen status domain + global UNIQUE operation key.
--    The operation key (key_value) is now a canonical hash over the full
--    OperationIdentity, so it must be globally unique: the same operation key
--    can never refer to two different operations.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS idempotency_requests_new (
    id TEXT PRIMARY KEY,
    key_value TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    learner_id TEXT NOT NULL DEFAULT '',
    resource_id TEXT NOT NULL DEFAULT '',
    request_fingerprint TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'completed', 'failed_retryable', 'failed_terminal')),
    result_json TEXT DEFAULT NULL,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    lease_expires_at TEXT DEFAULT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO idempotency_requests_new
    (id, key_value, operation_type, learner_id, resource_id, request_fingerprint,
     status, result_json, attempt_number, lease_expires_at, created_at, updated_at)
SELECT
    id, key_value, operation_type, learner_id, resource_id, request_fingerprint,
    CASE status WHEN 'failed' THEN 'failed_retryable' ELSE status END,
    result_json, attempt_number, lease_expires_at, created_at, updated_at
FROM idempotency_requests;

DROP TABLE idempotency_requests;
ALTER TABLE idempotency_requests_new RENAME TO idempotency_requests;

CREATE UNIQUE INDEX IF NOT EXISTS ux_idempotency_operation_key
    ON idempotency_requests(key_value);
CREATE INDEX IF NOT EXISTS idx_idempotency_learner
    ON idempotency_requests(learner_id);

-- ---------------------------------------------------------------------------
-- 2. Provider accounting columns on generation_runs (additive ALTERs).
--    Tokens are nullable because some providers do not report usage; a NULL
--    means "not provided", distinct from 0.
-- ---------------------------------------------------------------------------
ALTER TABLE generation_runs ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE generation_runs ADD COLUMN provider_call_count INTEGER NOT NULL DEFAULT 1;
ALTER TABLE generation_runs ADD COLUMN latency_ms_total REAL NOT NULL DEFAULT 0;
ALTER TABLE generation_runs ADD COLUMN input_tokens_total INTEGER;
ALTER TABLE generation_runs ADD COLUMN output_tokens_total INTEGER;
ALTER TABLE generation_runs ADD COLUMN started_at TEXT;
ALTER TABLE generation_runs ADD COLUMN completed_at TEXT;

-- Backfill totals from the per-attempt columns so existing rows stay coherent.
UPDATE generation_runs
SET latency_ms_total = COALESCE(latency_ms, 0),
    input_tokens_total = prompt_tokens,
    output_tokens_total = completion_tokens,
    provider_call_count = 1,
    retry_count = COALESCE(attempt_number, 1) - 1
WHERE latency_ms_total IS NULL OR latency_ms_total = 0;

CREATE INDEX IF NOT EXISTS idx_generation_runs_attempt_group
    ON generation_runs(attempt_group_id);

-- ---------------------------------------------------------------------------
-- 3. Adaptation decisions: rebuild the legacy 001 table (lesson_id/feedback_id/
--    plan-json blob) into an independent, auditable record of every material
--    change, keyed by (learner, prior lesson, next lesson, signal, dimension).
--    Existing rows (if any) are migrated; the legacy table is empty in practice
--    because no prior code path wrote to it.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS adaptation_decisions_new (
    id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL,
    prior_lesson_id TEXT NOT NULL,
    next_lesson_id TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    signal_reference_id TEXT NOT NULL DEFAULT '',
    dimension TEXT NOT NULL,
    before_value TEXT NOT NULL DEFAULT '',
    after_value TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (learner_id) REFERENCES learners(id),
    FOREIGN KEY (prior_lesson_id) REFERENCES lessons(id),
    FOREIGN KEY (next_lesson_id) REFERENCES lessons(id)
);

INSERT OR IGNORE INTO adaptation_decisions_new
    (id, learner_id, prior_lesson_id, next_lesson_id, signal_type,
     signal_reference_id, dimension, before_value, after_value, reason, created_at)
SELECT
    a.id,
    COALESCE(l.learner_id, ''),
    COALESCE(l.prior_lesson_id, ''),
    a.lesson_id,
    'feedback',
    COALESCE(a.feedback_id, ''),
    'adaptation',
    COALESCE(a.original_lesson_plan_json, ''),
    COALESCE(a.adapted_lesson_plan_json, ''),
    'migrated from legacy adaptation_decisions',
    a.created_at
FROM adaptation_decisions a
LEFT JOIN lessons l ON l.id = a.lesson_id;

DROP TABLE adaptation_decisions;
ALTER TABLE adaptation_decisions_new RENAME TO adaptation_decisions;

CREATE INDEX IF NOT EXISTS idx_adaptation_learner
    ON adaptation_decisions(learner_id);
CREATE INDEX IF NOT EXISTS idx_adaptation_next_lesson
    ON adaptation_decisions(next_lesson_id);

-- ---------------------------------------------------------------------------
-- 4. Portal-ready identity boundary.
--    external_identities maps a verified external identity (provider+issuer+
--    subject) to a product-local record. product_memberships grants a role on
--    the product, optionally linked to a learner. Firebase authentication
--    alone never grants access: a row in both tables with active status and
--    the correct role is required.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS external_identities (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    issuer TEXT NOT NULL,
    subject TEXT NOT NULL,
    email TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'revoked')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_external_identities_provider_issuer_subject
    ON external_identities(provider, issuer, subject);

CREATE TABLE IF NOT EXISTS product_memberships (
    id TEXT PRIMARY KEY,
    external_identity_id TEXT NOT NULL,
    role TEXT NOT NULL
        CHECK (role IN ('learner', 'operator', 'reviewer')),
    learner_id TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'revoked')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    revoked_at TEXT,
    FOREIGN KEY (external_identity_id) REFERENCES external_identities(id),
    FOREIGN KEY (learner_id) REFERENCES learners(id)
);

CREATE INDEX IF NOT EXISTS idx_memberships_identity
    ON product_memberships(external_identity_id);
CREATE INDEX IF NOT EXISTS idx_memberships_learner
    ON product_memberships(learner_id);

PRAGMA foreign_keys=ON;
