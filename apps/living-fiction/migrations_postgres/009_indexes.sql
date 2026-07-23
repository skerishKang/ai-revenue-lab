-- Secondary indexes (mirror the SQLite index set). The inline UNIQUE
-- constraints in the table definitions already back the uniqueness rules; these
-- are the additional lookup indexes the queries rely on.

CREATE INDEX IF NOT EXISTS idx_admin_sessions_token
    ON admin_sessions (token_digest);

CREATE INDEX IF NOT EXISTS idx_branch_gen_req_binding
    ON branch_generation_requests (
        reader_id, reader_choice_id, prior_episode_id,
        canon_checkpoint_id, world_id, operation_type
    );

CREATE INDEX IF NOT EXISTS idx_branch_gen_req_status
    ON branch_generation_requests (status);

CREATE INDEX IF NOT EXISTS idx_branch_gen_req_updated
    ON branch_generation_requests (updated_at);

CREATE INDEX IF NOT EXISTS idx_branch_gen_requests_key
    ON branch_generation_requests (idempotency_key);

CREATE INDEX IF NOT EXISTS idx_branches_reader_id
    ON branches (reader_id);

CREATE INDEX IF NOT EXISTS idx_choices_reader_id
    ON reader_choices (reader_id);

CREATE INDEX IF NOT EXISTS idx_episodes_reader_id
    ON episodes (reader_id);

CREATE INDEX IF NOT EXISTS idx_gen_attempts_provider
    ON generation_attempts (provider);

CREATE INDEX IF NOT EXISTS idx_gen_attempts_run_id
    ON generation_attempts (generation_run_id);

CREATE INDEX IF NOT EXISTS idx_gen_req_lease
    ON branch_generation_requests (pending_lease_at);

CREATE INDEX IF NOT EXISTS idx_gen_req_status
    ON branch_generation_requests (status);

CREATE INDEX IF NOT EXISTS idx_invite_credentials_digest
    ON invite_credentials (code_digest);

CREATE INDEX IF NOT EXISTS idx_reader_choices_anon
    ON reader_choices (anonymized_principal_id);

-- One choice per reader per canon episode (stronger than the table-level
-- UNIQUE(reader_id, canon_episode_id, choice_text)).
CREATE UNIQUE INDEX IF NOT EXISTS idx_reader_choices_one_per_canon
    ON reader_choices (reader_id, canon_episode_id);

CREATE INDEX IF NOT EXISTS idx_reader_deletion_audit_reader
    ON reader_deletion_audit (reader_id);

CREATE INDEX IF NOT EXISTS idx_reader_sessions_token
    ON reader_sessions (token_digest);

CREATE INDEX IF NOT EXISTS idx_rejoin_requests_v2_branch
    ON rejoin_requests_v2 (branch_id);

CREATE INDEX IF NOT EXISTS idx_review_decisions_branch
    ON review_decisions (branch_id);

CREATE INDEX IF NOT EXISTS idx_review_decisions_episode
    ON review_decisions (episode_id);
