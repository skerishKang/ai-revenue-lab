-- Migration 004: Final contract repair for idempotency CAS, reader deletion,
-- and evidence category schema.

-- Note: Migration runner wraps statements in BEGIN IMMEDIATE/COMMIT,
-- so no explicit transaction control here.

CREATE INDEX IF NOT EXISTS idx_gen_req_status ON branch_generation_requests(status);
CREATE INDEX IF NOT EXISTS idx_gen_req_lease ON branch_generation_requests(pending_lease_at);

ALTER TABLE reader_choices ADD COLUMN anonymized_principal_id TEXT DEFAULT NULL;
CREATE INDEX IF NOT EXISTS idx_reader_choices_anon ON reader_choices(anonymized_principal_id);

ALTER TABLE reader_choices ADD COLUMN is_anonymized INTEGER DEFAULT 0;

ALTER TABLE episodes ADD COLUMN is_reader_input_anonymized INTEGER DEFAULT 0;

ALTER TABLE pilot_evidence ADD COLUMN privacy_locked INTEGER DEFAULT 0;

PRAGMA user_version = 4;
