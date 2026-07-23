-- PostgreSQL migration: durable generation-request idempotency with
-- ownership and lease lifecycle.
--
-- Parity with SQLite 005_generation_requests.sql.  A generation request is
-- claimed atomically by idempotency_key before any edition is produced; the
-- claim INSERT uses ON CONFLICT (idempotency_key) DO NOTHING and the caller
-- inspects rowcount, so a re-submitted idempotency_key never creates a second
-- edition.
--
-- Ownership: participant_id + input_id are verified on every claim attempt.
-- Lease: claim_token + lease_expires_at enable expired-lease reclaim.
-- Failure: claimed -> failed transition with failure_category and failed_at.
--
-- Transaction boundary: this migration runs inside a single explicit
-- transaction (managed by apply_pg_migrations).  If any statement fails, the
-- entire transaction is rolled back.

CREATE TABLE IF NOT EXISTS generation_requests (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL,
    participant_id TEXT NOT NULL REFERENCES participants(id) ON DELETE NO ACTION,
    input_id TEXT NOT NULL REFERENCES inputs(id) ON DELETE NO ACTION,
    edition_id TEXT REFERENCES editions(id) ON DELETE NO ACTION,
    status TEXT NOT NULL DEFAULT 'claimed',
    claim_token TEXT NOT NULL,
    lease_expires_at TEXT,
    failed_at TEXT,
    failure_category TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (idempotency_key),
    CHECK (status IN ('claimed', 'completed', 'failed')),
    CHECK (
        (status = 'completed' AND edition_id IS NOT NULL AND completed_at IS NOT NULL)
        OR (status = 'claimed' AND edition_id IS NULL AND completed_at IS NULL)
        OR (status = 'failed' AND edition_id IS NULL AND failed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_generation_requests_participant
    ON generation_requests(participant_id);

CREATE INDEX IF NOT EXISTS idx_generation_requests_status_lease
    ON generation_requests(status, lease_expires_at);
