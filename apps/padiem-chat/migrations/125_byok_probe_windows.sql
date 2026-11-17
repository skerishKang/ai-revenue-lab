-- #7543 S37: per-owner BYOK probe budget in the shared D1 database.
-- Only the owner id, the fixed window start (epoch seconds) and a count are
-- stored. No provider key, key fragment, request body or log text is persisted.
CREATE TABLE IF NOT EXISTS byok_probe_windows (
    user_id TEXT NOT NULL,
    window_start INTEGER NOT NULL DEFAULT 0,
    count INTEGER NOT NULL,
    PRIMARY KEY (user_id, window_start)
);
