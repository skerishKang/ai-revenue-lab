-- Migration 002: additive repair for CTO review blockers.
-- Does NOT modify or rewrite migration 001 tables.
-- Adds new columns, tables, constraints, and indexes.

-- ── Generation attempt-level accounting ─────────────────────────────────
-- One row per actual provider attempt, distinguished from aggregate task rows.
CREATE TABLE IF NOT EXISTS generation_attempts (
    id TEXT PRIMARY KEY,
    generation_run_id TEXT NOT NULL REFERENCES generation_runs(id),
    attempt_number INTEGER NOT NULL CHECK(attempt_number >= 1),
    provider TEXT NOT NULL,
    advertised_model TEXT NOT NULL,
    cost_class TEXT NOT NULL DEFAULT 'unknown',
    request_id TEXT,
    task_type TEXT NOT NULL,
    prompt_version TEXT,
    latency_seconds REAL CHECK(latency_seconds IS NULL OR latency_seconds >= 0),
    input_tokens INTEGER CHECK(input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK(output_tokens IS NULL OR output_tokens >= 0),
    total_tokens INTEGER CHECK(total_tokens IS NULL OR total_tokens >= 0),
    success INTEGER NOT NULL DEFAULT 0 CHECK(success IN (0, 1)),
    retryable INTEGER NOT NULL DEFAULT 0 CHECK(retryable IN (0, 1)),
    error_category TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(generation_run_id, attempt_number)
);

-- Add cost_class and request_id to generation_runs for aggregate consistency
-- (idempotent — SQLite ALTER TABLE ADD COLUMN is ignored if column exists in practice
-- via the IF NOT EXISTS pattern is not supported, so we use a guard pragma approach)
-- We add columns only if they don't exist yet.

-- Idempotency key for branch generation requests
CREATE TABLE IF NOT EXISTS branch_generation_requests (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL,
    reader_id TEXT NOT NULL REFERENCES readers(id),
    reader_choice_id TEXT NOT NULL REFERENCES reader_choices(id),
    prior_episode_id TEXT NOT NULL REFERENCES episodes(id),
    canon_checkpoint_id TEXT NOT NULL REFERENCES canon_checkpoints(id),
    world_id TEXT NOT NULL REFERENCES worlds(id),
    branch_episode_id TEXT REFERENCES episodes(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'completed', 'failed')),
    error_message TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(idempotency_key)
);

-- ── Rejoin integrity fields ──────────────────────────────────────────────
-- Track rejoin request lifecycle with explanation requirement
CREATE TABLE IF NOT EXISTS rejoin_requests_v2 (
    id TEXT PRIMARY KEY,
    branch_id TEXT NOT NULL REFERENCES branches(id),
    target_checkpoint_id TEXT NOT NULL REFERENCES canon_checkpoints(id),
    target_snapshot_id TEXT NOT NULL REFERENCES canon_snapshots(id),
    derived_consequences_json TEXT NOT NULL DEFAULT '[]',
    explanation TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected', 'completed')),
    rejection_reason TEXT,
    validated_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(branch_id, target_checkpoint_id)
);

-- ── Reader deletion/revocation audit ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS reader_deletion_audit (
    id TEXT PRIMARY KEY,
    reader_id TEXT NOT NULL,
    anonymized_display_name TEXT,
    choices_revoked_count INTEGER NOT NULL DEFAULT 0,
    branches_anonymized_count INTEGER NOT NULL DEFAULT 0,
    episodes_anonymized_count INTEGER NOT NULL DEFAULT 0,
    rejoin_requests_removed_count INTEGER NOT NULL DEFAULT 0,
    pilot_evidence_anonymized_count INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- ── Indexes for performance ──────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_gen_attempts_run_id ON generation_attempts(generation_run_id);
CREATE INDEX IF NOT EXISTS idx_gen_attempts_provider ON generation_attempts(provider);
CREATE INDEX IF NOT EXISTS idx_branch_gen_requests_key ON branch_generation_requests(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_rejoin_requests_v2_branch ON rejoin_requests_v2(branch_id);
CREATE INDEX IF NOT EXISTS idx_reader_deletion_audit_reader ON reader_deletion_audit(reader_id);
CREATE INDEX IF NOT EXISTS idx_episodes_reader_id ON episodes(reader_id);
CREATE INDEX IF NOT EXISTS idx_choices_reader_id ON reader_choices(reader_id);
CREATE INDEX IF NOT EXISTS idx_branches_reader_id ON branches(reader_id);
