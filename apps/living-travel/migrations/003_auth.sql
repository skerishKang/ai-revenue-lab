-- Phase 2: Auth and session tables

CREATE TABLE IF NOT EXISTS operator_sessions (
    id TEXT PRIMARY KEY,
    session_token TEXT NOT NULL UNIQUE,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS traveler_tokens (
    id TEXT PRIMARY KEY,
    traveler_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    rotated_at TEXT,
    FOREIGN KEY (traveler_id) REFERENCES travelers(id)
);

CREATE TABLE IF NOT EXISTS traveler_sessions (
    id TEXT PRIMARY KEY,
    traveler_id TEXT NOT NULL,
    session_token TEXT NOT NULL UNIQUE,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (traveler_id) REFERENCES travelers(id)
);

CREATE INDEX IF NOT EXISTS idx_traveler_tokens_traveler ON traveler_tokens(traveler_id);
CREATE INDEX IF NOT EXISTS idx_traveler_tokens_hash ON traveler_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_traveler_sessions_traveler ON traveler_sessions(traveler_id);
CREATE INDEX IF NOT EXISTS idx_operator_sessions_token ON operator_sessions(session_token);
