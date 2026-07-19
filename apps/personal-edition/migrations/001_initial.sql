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

CREATE TABLE IF NOT EXISTS inputs (
    id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL REFERENCES participants(id),
    sequence_number INTEGER NOT NULL,
    raw_text TEXT NOT NULL,
    normalized_text TEXT,
    consent_confirmed INTEGER NOT NULL DEFAULT 0 CHECK(consent_confirmed IN (0, 1)),
    submitted_at TEXT NOT NULL,
    deleted_at TEXT,
    UNIQUE(participant_id, sequence_number)
);

CREATE TABLE IF NOT EXISTS editions (
    id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL REFERENCES participants(id),
    edition_number INTEGER NOT NULL,
    prior_edition_id TEXT REFERENCES editions(id),
    input_id TEXT REFERENCES inputs(id),
    generation_status TEXT NOT NULL DEFAULT 'pending_review',
    structured_content TEXT,
    rendered_title TEXT,
    drafted_at TEXT,
    reviewed_at TEXT,
    published_at TEXT,
    human_correction_minutes REAL,
    reviewer_notes TEXT,
    publication_state TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL REFERENCES participants(id),
    edition_id TEXT NOT NULL REFERENCES editions(id),
    direction_choices TEXT NOT NULL,
    selected_section_id TEXT,
    free_text TEXT,
    submitted_at TEXT NOT NULL,
    applied_to_next_edition INTEGER NOT NULL DEFAULT 0
);

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
