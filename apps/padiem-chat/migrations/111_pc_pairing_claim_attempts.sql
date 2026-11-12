-- #7563: a typed pairing code is a 12-character possession proof. The claim
-- surface counts its failures in the database (a deployment can run more than
-- one worker process), twice per failure: once for the node id the claim named
-- and once for the network the request came from. Both keys are opaque SHA-256
-- values; no raw node id or request address is stored here.
--
-- The window is a fixed ten-minute bucket. A success never resets a counter,
-- and the two rows are independent, so a saturated node counter never stops
-- the network counter from moving.
CREATE TABLE IF NOT EXISTS pc_pairing_claim_attempts (
  key_type TEXT NOT NULL CHECK(key_type IN ('node', 'source')),
  key_hash TEXT NOT NULL CHECK(length(key_hash) = 64),
  window_start TEXT NOT NULL CHECK(length(window_start) BETWEEN 20 AND 32),
  failure_count INTEGER NOT NULL DEFAULT 0 CHECK(failure_count >= 0),
  updated_at TEXT NOT NULL CHECK(length(updated_at) BETWEEN 20 AND 32),
  PRIMARY KEY (key_type, key_hash, window_start)
);

CREATE INDEX IF NOT EXISTS idx_pc_pairing_claim_attempts_window
ON pc_pairing_claim_attempts (window_start);
