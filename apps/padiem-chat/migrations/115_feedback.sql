-- Private product feedback; no external delivery or conversation association.
CREATE TABLE IF NOT EXISTS product_feedback (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL CHECK(length(body) >= 1),
    screen_json TEXT,
    status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','reviewing','fixed','deferred')),
    created_day TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    fixed_version INTEGER NOT NULL DEFAULT 0 CHECK(fixed_version >= 0),
    read_version INTEGER NOT NULL DEFAULT 0 CHECK(read_version >= 0 AND read_version <= fixed_version)
);
CREATE INDEX IF NOT EXISTS product_feedback_owner_day ON product_feedback(user_id, created_day);
CREATE INDEX IF NOT EXISTS product_feedback_owner_list ON product_feedback(user_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS product_feedback_status_list ON product_feedback(status, created_at DESC, id DESC);
