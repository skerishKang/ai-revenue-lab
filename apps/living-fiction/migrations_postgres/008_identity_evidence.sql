-- Identity, sessions, deletion audit, and pilot evidence.
-- Invite codes and session tokens are stored ONLY as digests; no plaintext
-- credential ever lives in the schema.

CREATE TABLE IF NOT EXISTS invite_credentials (
    id TEXT PRIMARY KEY,
    code_digest TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    used_by_reader_id TEXT REFERENCES readers (id),
    used_at TEXT,
    bound_reader_id TEXT REFERENCES readers (id),
    expires_at TEXT,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS reader_sessions (
    id TEXT PRIMARY KEY,
    reader_id TEXT NOT NULL REFERENCES readers (id),
    token_digest TEXT NOT NULL UNIQUE,
    csrf_token_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS admin_sessions (
    id TEXT PRIMARY KEY,
    token_digest TEXT NOT NULL UNIQUE,
    csrf_token_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    last_seen_at TEXT
);

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
    created_at TEXT NOT NULL,
    deletion_event_id TEXT
);

CREATE TABLE IF NOT EXISTS pilot_evidence (
    id TEXT PRIMARY KEY,
    evidence_category TEXT NOT NULL,
    canon_episode_id TEXT REFERENCES episodes (id),
    branch_episode_id TEXT REFERENCES episodes (id),
    reader_id TEXT REFERENCES readers (id),
    evidence_data_json TEXT NOT NULL,
    privacy_safe SMALLINT NOT NULL DEFAULT 1 CHECK (privacy_safe IN (0, 1)),
    created_at TEXT NOT NULL,
    category_consent_obtained SMALLINT CHECK (category_consent_obtained IN (0, 1)),
    category_revenue_hypothesis SMALLINT CHECK (category_revenue_hypothesis IN (0, 1)),
    privacy_locked SMALLINT DEFAULT 0
);
