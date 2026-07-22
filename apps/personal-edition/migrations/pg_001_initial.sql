-- PostgreSQL migration: initial schema parity with SQLite 001–004
--
-- This migration creates the same logical schema as the SQLite migrations
-- 001_initial.sql, 002_participant_token_hash_unique.sql,
-- 003_benchmark_pilot_ops.sql, and 004_upgrade_pilot_ops.py, adapted for
-- PostgreSQL semantics.
--
-- Key SQLite → PostgreSQL transformations:
--
--   INTEGER PRIMARY KEY  →  TEXT PRIMARY KEY
--     (SQLite uses INTEGER PRIMARY KEY as rowid alias; our IDs are
--      UUID strings, so TEXT PRIMARY KEY is the correct parity.)
--
--   AUTOINCREMENT        →  (not used; IDs are application-generated UUIDs)
--
--   BOOLEAN (stored as INTEGER 0/1)  →  INTEGER 0/1
--     (SQLite has no native BOOLEAN; CHECK(... IN (0,1)) is used.
--      PostgreSQL retains this exactly for strict application code parity.)
--
--   TEXT timestamps      →  TEXT
--     (Application generates ISO-8601 strings; stored as TEXT for
--      cross-backend parity.  No implicit timezone conversion.)
--
--   CHECK(... IN (0, 1))  →  CHECK(... IN (0, 1))
--     (Preserved as-is for semantic parity.)
--
--   foreign key behavior  →  REFERENCES ... ON DELETE NO ACTION
--     (SQLite default is NO ACTION; PostgreSQL default is also NO ACTION,
--      but we state it explicitly for clarity.)
--
--   UNIQUE(col) inline   →  UNIQUE (col) table constraint
--     (PostgreSQL supports both inline and table-level UNIQUE; we use
--      table-level for consistency with the SQLite DDL.)
--
--   CREATE INDEX IF NOT EXISTS  →  CREATE INDEX IF NOT EXISTS
--     (PostgreSQL supports IF NOT EXISTS for indexes.)
--
--   schema_migrations table  →  separate metadata table with
--     version, checksum, applied_at columns.
--
-- Transaction boundary: this migration runs inside a single explicit
-- transaction (managed by apply_pg_migrations).  If any statement fails,
-- the entire transaction is rolled back.



-- ============================================================
-- participants
-- ============================================================
CREATE TABLE IF NOT EXISTS participants (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    access_token_hash TEXT NOT NULL,
    preferred_language TEXT NOT NULL DEFAULT 'ko',
    tone_preference TEXT NOT NULL DEFAULT 'calm_editorial',
    length_preference TEXT NOT NULL DEFAULT 'standard',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_participants_access_token_hash
    ON participants(access_token_hash);

-- ============================================================
-- inputs
-- ============================================================
CREATE TABLE IF NOT EXISTS inputs (
    id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL REFERENCES participants(id) ON DELETE NO ACTION,
    sequence_number INTEGER NOT NULL,
    raw_text TEXT NOT NULL,
    normalized_text TEXT,
    consent_confirmed INTEGER NOT NULL DEFAULT 0 CHECK(consent_confirmed IN (0, 1)),
    submitted_at TEXT NOT NULL,
    deleted_at TEXT,
    UNIQUE(participant_id, sequence_number)
);

-- ============================================================
-- editions
-- ============================================================
CREATE TABLE IF NOT EXISTS editions (
    id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL REFERENCES participants(id) ON DELETE NO ACTION,
    edition_number INTEGER NOT NULL,
    prior_edition_id TEXT REFERENCES editions(id) ON DELETE NO ACTION,
    input_id TEXT REFERENCES inputs(id) ON DELETE NO ACTION,
    generation_status TEXT NOT NULL DEFAULT 'pending_review',
    structured_content TEXT,
    rendered_title TEXT,
    drafted_at TEXT,
    reviewed_at TEXT,
    published_at TEXT,
    human_correction_minutes REAL CHECK(human_correction_minutes IS NULL OR human_correction_minutes >= 0),
    reviewer_notes TEXT,
    publication_state TEXT NOT NULL DEFAULT 'pending',
    UNIQUE(participant_id, edition_number)
);

-- ============================================================
-- feedback
-- ============================================================
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL REFERENCES participants(id) ON DELETE NO ACTION,
    edition_id TEXT NOT NULL REFERENCES editions(id) ON DELETE NO ACTION,
    direction_choices TEXT NOT NULL,
    selected_section_id TEXT,
    free_text TEXT,
    submitted_at TEXT NOT NULL,
    applied_to_next_edition INTEGER NOT NULL DEFAULT 0 CHECK(applied_to_next_edition IN (0, 1))
);

-- ============================================================
-- generation_runs
-- ============================================================
CREATE TABLE IF NOT EXISTS generation_runs (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    advertised_model TEXT NOT NULL,
    verified_upstream_status TEXT,
    cost_class TEXT NOT NULL DEFAULT 'free',
    prompt_version TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    latency_seconds REAL CHECK(latency_seconds IS NULL OR latency_seconds >= 0),
    success INTEGER NOT NULL DEFAULT 0 CHECK(success IN (0, 1)),
    validation_status TEXT,
    input_tokens INTEGER CHECK(input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK(output_tokens IS NULL OR output_tokens >= 0),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
    error_category TEXT,
    error_message TEXT,
    human_correction_minutes REAL CHECK(human_correction_minutes IS NULL OR human_correction_minutes >= 0)
);

-- ============================================================
-- benchmark_runs
-- ============================================================
CREATE TABLE IF NOT EXISTS benchmark_runs (
    id TEXT PRIMARY KEY,
    benchmark_name TEXT NOT NULL,
    fixture_name TEXT NOT NULL,
    run_index INTEGER NOT NULL,
    run_group TEXT NOT NULL DEFAULT 'full_pipeline',
    provider TEXT NOT NULL,
    advertised_model TEXT NOT NULL,
    task_type TEXT NOT NULL,
    prompt_version TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    latency_seconds REAL CHECK(latency_seconds IS NULL OR latency_seconds >= 0),
    success INTEGER NOT NULL DEFAULT 0 CHECK(success IN (0, 1)),
    failure_category TEXT CHECK(failure_category IS NULL OR failure_category IN ('provider', 'model_quality')),
    error_category TEXT,
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
    input_tokens INTEGER CHECK(input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK(output_tokens IS NULL OR output_tokens >= 0),
    total_tokens INTEGER CHECK(total_tokens IS NULL OR total_tokens >= 0),
    validation_result TEXT,
    synthetic_result_ref TEXT,
    human_correction_minutes REAL CHECK(human_correction_minutes IS NULL OR human_correction_minutes >= 0),
    is_provider_failure INTEGER NOT NULL DEFAULT 0 CHECK(is_provider_failure IN (0, 1)),
    is_model_quality_failure INTEGER NOT NULL DEFAULT 0 CHECK(is_model_quality_failure IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_benchmark_runs_fixture ON benchmark_runs(fixture_name);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_task ON benchmark_runs(task_type);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_benchmark ON benchmark_runs(benchmark_name);

-- ============================================================
-- pilot_ops_records
-- ============================================================
CREATE TABLE IF NOT EXISTS pilot_ops_records (
    record_id TEXT PRIMARY KEY,
    record_type TEXT NOT NULL CHECK(record_type IN (
        'benchmark_run', 'pilot_run', 'pilot_evidence',
        'payment_evidence', 'correction', 'deletion_request',
        'deletion_completion'
    )),
    participant_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pilot_ops_records_participant ON pilot_ops_records(participant_id);
CREATE INDEX IF NOT EXISTS idx_pilot_ops_records_type ON pilot_ops_records(record_type);
