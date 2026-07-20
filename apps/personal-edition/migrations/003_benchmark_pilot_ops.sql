-- Phase 5A: Benchmark runs and pilot operations tables
-- These tables support the runtime benchmark runner and manual pilot operations.

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

CREATE TABLE IF NOT EXISTS pilot_ops_records (
    id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL,
    record_type TEXT NOT NULL CHECK(record_type IN (
        'invitation', 'sample_edition', 'offer', 'payment_evidence',
        'correction', 'engagement', 'costs', 'revenue',
        'deletion_request', 'deletion_completion'
    )),
    edition_id TEXT,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pilot_ops_records_participant ON pilot_ops_records(participant_id);
CREATE INDEX IF NOT EXISTS idx_pilot_ops_records_type ON pilot_ops_records(record_type);
