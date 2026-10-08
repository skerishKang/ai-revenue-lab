-- #3782 CONTRACT ONLY. Apply ONLY in a SEPARATE authenticated HUMAN P01
-- owner service database, NEVER via Engine's production D1 migrations.
-- The owner MUST authenticate user's login and persist exact continuation/action.
-- Engine only reads via independent service binding.
-- SOURCE_ONLY, OWNER_WRITER_WIRED=NO, PRODUCTION_APPLY=NO.
CREATE TABLE IF NOT EXISTS padiem_browser_control_owner_p01_decisions (
  app_id TEXT NOT NULL,
  continuation_ref TEXT NOT NULL,
  pause_id TEXT NOT NULL,
  owner_subject_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  invocation_sha256 TEXT NOT NULL CHECK (length(invocation_sha256) = 64),
  original_request_fingerprint TEXT NOT NULL CHECK (length(original_request_fingerprint) = 64),
  original_admission_decision_id TEXT NOT NULL,
  decision_id TEXT NOT NULL UNIQUE,
  authority_ref TEXT NOT NULL,
  evidence_ref TEXT NOT NULL,
  decided_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT DEFAULT NULL,
  outcome TEXT NOT NULL CHECK (outcome = 'approved'),
  authenticated_owner_session_ref TEXT NOT NULL,
  PRIMARY KEY (app_id, continuation_ref),
  CHECK (length(authenticated_owner_session_ref) > 0),
  CHECK (expires_at > decided_at)
);
