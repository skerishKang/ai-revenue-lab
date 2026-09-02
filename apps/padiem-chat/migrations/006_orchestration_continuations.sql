-- B62 product-local orchestration snapshot/audit state.
-- The Engine remains continuation authority; these rows only bind browser intent
-- to the exact server-sent Engine request and authenticated B62 user.

CREATE TABLE IF NOT EXISTS orchestration_continuations (
  continuation_ref TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  pause_id TEXT NOT NULL,
  request_json TEXT NOT NULL,
  user_text TEXT NOT NULL,
  conversation_id TEXT,
  expires_at TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('active','resuming','resumed','completed','denied','cancelled','expired')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orchestration_continuations_user_state
  ON orchestration_continuations(user_id, state, updated_at DESC);

CREATE TABLE IF NOT EXISTS orchestration_decisions (
  decision_id TEXT PRIMARY KEY,
  continuation_ref TEXT NOT NULL,
  user_id TEXT NOT NULL,
  pause_id TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('approved','denied')),
  authority_ref TEXT NOT NULL,
  evidence_ref TEXT NOT NULL UNIQUE,
  decided_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (continuation_ref) REFERENCES orchestration_continuations(continuation_ref) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_orchestration_decisions_continuation
  ON orchestration_decisions(continuation_ref, decided_at DESC);
