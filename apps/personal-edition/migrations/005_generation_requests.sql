-- Durable generation-request idempotency with ownership and lease lifecycle.
--
-- A generation request is claimed atomically by idempotency_key before any
-- edition is produced.  Re-submitting the same idempotency_key (double-click,
-- network retry) does not create a second edition: the claim INSERT uses
-- ON CONFLICT (idempotency_key) DO NOTHING and the caller inspects rowcount.
--
-- Ownership: participant_id + input_id are verified on every claim attempt;
-- a mismatch raises GenerationRequestOwnershipError.
--
-- Lease: each claim carries a claim_token and lease_expires_at.  An expired
-- lease allows the same owner to reclaim; a valid lease blocks re-claim.
--
-- Failure: a claimed request can transition to 'failed' (with failure_category
-- and failed_at).  The same owner may reclaim a failed request.
CREATE TABLE IF NOT EXISTS generation_requests (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL,
    participant_id TEXT NOT NULL REFERENCES participants(id),
    input_id TEXT NOT NULL REFERENCES inputs(id),
    edition_id TEXT REFERENCES editions(id),
    status TEXT NOT NULL DEFAULT 'claimed',
    claim_token TEXT NOT NULL,
    lease_expires_at TEXT,
    failed_at TEXT,
    failure_category TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(idempotency_key),
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
