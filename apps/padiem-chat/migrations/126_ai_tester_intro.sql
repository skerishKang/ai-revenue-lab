-- #7690 stage 1: short intro for AI honorary member accounts only.
-- Human users never have a row here and never have these fields collected.
CREATE TABLE IF NOT EXISTS ai_tester_intro (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    age_band TEXT,
    job TEXT,
    device TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
