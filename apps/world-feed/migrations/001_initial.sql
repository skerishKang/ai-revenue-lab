-- World Feed Phase 1 MVP — initial schema (version 001)
-- All data is synthetic. No live crawling, no personal identifiers.

CREATE TABLE IF NOT EXISTS sources (
    source_id            TEXT PRIMARY KEY,
    country              TEXT NOT NULL,
    locality             TEXT NOT NULL,
    original_language    TEXT NOT NULL,
    source_tier          TEXT NOT NULL,
    publisher_name       TEXT NOT NULL,
    organization_type    TEXT NOT NULL,
    canonical_url        TEXT NOT NULL,
    publication_timestamp TEXT NOT NULL,
    access_timestamp     TEXT NOT NULL,
    title                TEXT NOT NULL,
    text_extract         TEXT NOT NULL,
    category             TEXT NOT NULL,
    media_rights_state   TEXT NOT NULL,
    source_state         TEXT NOT NULL,
    conflict_penalty     REAL NOT NULL DEFAULT 0.0,
    canonical_key        TEXT NOT NULL,
    checksum             TEXT NOT NULL,
    synthetic_flag       INTEGER NOT NULL DEFAULT 1,
    reviewer_notes       TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sources_canonical_key ON sources (canonical_key);
CREATE INDEX IF NOT EXISTS idx_sources_state ON sources (source_state);

CREATE TABLE IF NOT EXISTS canonical_events (
    id                       TEXT PRIMARY KEY,
    canonical_key           TEXT UNIQUE NOT NULL,
    country                 TEXT NOT NULL,
    locality                TEXT NOT NULL,
    title_original          TEXT NOT NULL,
    title_localized         TEXT NOT NULL,
    category                TEXT NOT NULL,
    start_date              TEXT,
    end_date                TEXT,
    organizer               TEXT NOT NULL DEFAULT '',
    status                  TEXT NOT NULL,
    uncertainty_note        TEXT,
    source_ids              TEXT NOT NULL DEFAULT '[]',
    conflicting_source_ids  TEXT NOT NULL DEFAULT '[]',
    eligible                INTEGER NOT NULL DEFAULT 1,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_status ON canonical_events (status);
CREATE INDEX IF NOT EXISTS idx_events_eligible ON canonical_events (eligible);

CREATE TABLE IF NOT EXISTS readers (
    reader_id     TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    language      TEXT NOT NULL,
    preferences   TEXT NOT NULL DEFAULT '{}',
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    id                TEXT PRIMARY KEY,
    reader_id         TEXT NOT NULL,
    prior_brief_id    TEXT,
    idempotency_key   TEXT UNIQUE NOT NULL,
    action            TEXT NOT NULL,
    detail            TEXT NOT NULL DEFAULT '',
    applied_to_brief_id TEXT,
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feedback_reader ON feedback (reader_id);
CREATE INDEX IF NOT EXISTS idx_feedback_idem ON feedback (idempotency_key);

CREATE TABLE IF NOT EXISTS briefs (
    id                  TEXT PRIMARY KEY,
    brief_number        TEXT UNIQUE NOT NULL,
    reader_id           TEXT NOT NULL,
    language            TEXT NOT NULL,
    generation_run_id   TEXT NOT NULL,
    sequence            TEXT NOT NULL,
    status              TEXT NOT NULL,
    title               TEXT NOT NULL,
    deck                TEXT NOT NULL,
    body_json           TEXT NOT NULL,
    selected_event_ids  TEXT NOT NULL DEFAULT '[]',
    feedback_id         TEXT,
    validation_status   TEXT NOT NULL DEFAULT 'pending',
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_briefs_reader ON briefs (reader_id);
CREATE INDEX IF NOT EXISTS idx_briefs_reader_seq ON briefs (reader_id, sequence);

CREATE TABLE IF NOT EXISTS generation_runs (
    id                TEXT PRIMARY KEY,
    task_type         TEXT NOT NULL,
    provider          TEXT NOT NULL,
    advertised_model  TEXT NOT NULL,
    cost_class        TEXT NOT NULL DEFAULT 'free',
    prompt_version    TEXT,
    started_at        TEXT NOT NULL,
    completed_at      TEXT,
    latency_seconds   REAL,
    success           INTEGER NOT NULL DEFAULT 0,
    validation_status TEXT,
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    total_tokens      INTEGER,
    retry_count       INTEGER NOT NULL DEFAULT 0,
    error_category    TEXT,
    error_message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_task ON generation_runs (task_type);

CREATE TABLE IF NOT EXISTS pilot_evidence (
    id              TEXT PRIMARY KEY,
    reader_id       TEXT NOT NULL,
    brief_id        TEXT NOT NULL,
    evidence_type   TEXT NOT NULL,
    anonymous_token TEXT NOT NULL,
    detail          TEXT NOT NULL DEFAULT '',
    recorded_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_reader ON pilot_evidence (reader_id);
