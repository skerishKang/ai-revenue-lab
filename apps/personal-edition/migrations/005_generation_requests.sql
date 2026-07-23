-- Durable generation-request idempotency.
--
-- A generation request is claimed atomically by idempotency_key before any
-- edition is produced.  Re-submitting the same idempotency_key (double-click,
-- network retry) does not create a second edition: the claim INSERT uses
-- ON CONFLICT (idempotency_key) DO NOTHING and the caller inspects rowcount.
CREATE TABLE IF NOT EXISTS generation_requests (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL,
    participant_id TEXT NOT NULL REFERENCES participants(id),
    input_id TEXT,
    edition_id TEXT,
    status TEXT NOT NULL DEFAULT 'claimed',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_generation_requests_participant
    ON generation_requests(participant_id);
