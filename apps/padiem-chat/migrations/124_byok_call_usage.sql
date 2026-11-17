CREATE TABLE IF NOT EXISTS byok_call_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    user_id TEXT NOT NULL,
    conversation_id TEXT,
    turn_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    credential_slot TEXT NOT NULL,
    is_byok INTEGER NOT NULL DEFAULT 1 CHECK (is_byok = 1),
    success INTEGER NOT NULL CHECK (success IN (0, 1)),
    error_code TEXT,
    duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    char_count INTEGER NOT NULL CHECK (char_count >= 0),
    cap_decision TEXT NOT NULL CHECK (cap_decision IN ('allowed', 'denied', 'not_evaluated'))
);

CREATE INDEX IF NOT EXISTS idx_byok_call_usage_user_created
    ON byok_call_usage(user_id, created_at);
