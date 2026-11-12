-- #7543 S07: one Claw execute per Idempotency-Key across worker processes.
-- The first request inserts a pending row (the claim). When it finishes it
-- stores its reply in the same row for 60 seconds, so a duplicate that reached
-- another worker process replays the same bytes instead of executing again.
-- Rows are owner-scoped, removed by the next claim once they expire, and
-- deleted with the account. Only signed-in requests write here.
CREATE TABLE IF NOT EXISTS claw_execute_receipts (
  user_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  claim_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('pending', 'done')),
  status_code INTEGER,
  headers_json TEXT,
  response_body TEXT,
  created_at_ms INTEGER NOT NULL,
  expires_at_ms INTEGER NOT NULL,
  PRIMARY KEY (user_id, idempotency_key),
  CHECK (
    (state = 'pending' AND status_code IS NULL AND response_body IS NULL)
    OR (state = 'done' AND status_code IS NOT NULL AND response_body IS NOT NULL)
  )
);
CREATE INDEX IF NOT EXISTS idx_claw_execute_receipts_expires
  ON claw_execute_receipts (expires_at_ms);
