-- Padiem Chat Business 62 — Phase 9 auth/history
-- Apply to the dedicated PADIEM_CHAT_DB D1 database before enabling Google auth.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    auth_provider TEXT NOT NULL CHECK (auth_provider = 'google'),
    provider_subject TEXT NOT NULL,
    email TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    picture_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (auth_provider, provider_subject)
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 80),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_updated
    ON conversations(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sequence_number INTEGER NOT NULL CHECK (sequence_number >= 0),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 8000),
    created_at TEXT NOT NULL,
    UNIQUE (conversation_id, sequence_number)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_sequence
    ON messages(conversation_id, sequence_number ASC);
