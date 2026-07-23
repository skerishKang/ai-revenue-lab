-- Living Travel: Phase 1 schema (PostgreSQL)
-- Mirrors migrations/001_initial.sql with PostgreSQL syntax.
-- Timestamp columns stay TEXT (ISO-8601 strings) for parity with SQLite.

CREATE TABLE IF NOT EXISTS travelers (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    preferred_language TEXT NOT NULL DEFAULT 'ko',
    destination TEXT NOT NULL DEFAULT '',
    trip_duration_nights INTEGER NOT NULL DEFAULT 2,
    trip_context TEXT NOT NULL DEFAULT 'solo',
    budget_tendency TEXT NOT NULL DEFAULT 'moderate',
    pace_preference TEXT NOT NULL DEFAULT 'comfortable',
    interests TEXT NOT NULL DEFAULT '[]',
    exclusions TEXT NOT NULL DEFAULT '[]',
    tone_preference TEXT NOT NULL DEFAULT 'calm',
    length_preference TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    updated_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    publisher TEXT NOT NULL,
    source_type TEXT NOT NULL,
    original_language TEXT NOT NULL DEFAULT 'ko',
    publication_date TEXT NOT NULL DEFAULT '',
    access_date TEXT NOT NULL DEFAULT '',
    destination TEXT NOT NULL,
    locality TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    claims TEXT NOT NULL DEFAULT '[]',
    confidence TEXT NOT NULL DEFAULT 'approximate',
    state TEXT NOT NULL DEFAULT 'single_source',
    verification_notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
);

CREATE TABLE IF NOT EXISTS travel_inputs (
    id TEXT PRIMARY KEY,
    traveler_id TEXT NOT NULL REFERENCES travelers(id),
    sequence_number INTEGER NOT NULL,
    raw_text TEXT NOT NULL,
    destination TEXT NOT NULL,
    trip_duration_nights INTEGER NOT NULL DEFAULT 2,
    consent_confirmed INTEGER NOT NULL DEFAULT 0,
    submitted_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
);

CREATE TABLE IF NOT EXISTS editions (
    id TEXT PRIMARY KEY,
    traveler_id TEXT NOT NULL REFERENCES travelers(id),
    edition_number INTEGER NOT NULL,
    prior_edition_id TEXT,
    input_id TEXT,
    generation_status TEXT NOT NULL DEFAULT 'input_received',
    structured_content TEXT NOT NULL DEFAULT '{}',
    publication_state TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    updated_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    traveler_id TEXT NOT NULL REFERENCES travelers(id),
    edition_id TEXT NOT NULL REFERENCES editions(id),
    direction_choices TEXT NOT NULL DEFAULT '[]',
    selected_section_id TEXT NOT NULL DEFAULT '',
    free_text TEXT NOT NULL DEFAULT '',
    applied_to_next_edition INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
);

CREATE TABLE IF NOT EXISTS generation_runs (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    advertised_model TEXT NOT NULL DEFAULT '',
    cost_class TEXT NOT NULL DEFAULT 'free',
    prompt_version TEXT NOT NULL DEFAULT '',
    latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    error_category TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    edition_id TEXT NOT NULL DEFAULT '',
    success INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
);

CREATE TABLE IF NOT EXISTS pilot_evidence (
    id TEXT PRIMARY KEY,
    evidence_type TEXT NOT NULL,
    traveler_id TEXT NOT NULL,
    edition_id TEXT NOT NULL,
    offer_description TEXT NOT NULL,
    price_krw INTEGER NOT NULL DEFAULT 0,
    consent_recorded INTEGER NOT NULL DEFAULT 0,
    payment_evidence TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
);
