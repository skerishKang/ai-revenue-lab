-- 117: operator replies, the sender's unread marker, and the AI-tester flag.
-- The feedback body remains private; replies are bounded and owner-scoped in SQL.
ALTER TABLE users ADD COLUMN ai_tester INTEGER NOT NULL DEFAULT 0 CHECK(ai_tester IN (0,1));
ALTER TABLE product_feedback ADD COLUMN ops_reply_read_at TEXT;

CREATE TABLE IF NOT EXISTS product_feedback_reply (
    id TEXT PRIMARY KEY,
    feedback_id TEXT NOT NULL REFERENCES product_feedback(id) ON DELETE CASCADE,
    side TEXT NOT NULL CHECK(side IN ('ops','user')),
    body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 4000),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS product_feedback_reply_thread
    ON product_feedback_reply(feedback_id, created_at, id);
CREATE INDEX IF NOT EXISTS product_feedback_reply_unread
    ON product_feedback_reply(feedback_id, side, created_at);