-- B66 deterministic CGI Guided question/answer history (#4657 follow-up).
-- Private owner/workspace scoped; independent of B66 AI model conversation history.
-- Retained when the in-progress #028 Guided slot is cleared on quote completion.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS b66_guided_transcript (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  messages_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, workspace_id, conversation_id)
);
CREATE INDEX IF NOT EXISTS idx_b66_guided_transcript_recent
  ON b66_guided_transcript(user_id, workspace_id, updated_at DESC);
