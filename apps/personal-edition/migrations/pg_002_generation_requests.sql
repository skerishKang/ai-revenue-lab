-- PostgreSQL migration: durable generation-request idempotency
--
-- Parity with SQLite 005_generation_requests.sql.  A generation request is
-- claimed atomically by idempotency_key before any edition is produced; the
-- claim INSERT uses ON CONFLICT (idempotency_key) DO NOTHING and the caller
-- inspects rowcount, so a re-submitted idempotency_key never creates a second
-- edition.
--
-- Transaction boundary: this migration runs inside a single explicit
-- transaction (managed by apply_pg_migrations).  If any statement fails, the
-- entire transaction is rolled back.

CREATE TABLE IF NOT EXISTS generation_requests (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL,
    participant_id TEXT NOT NULL REFERENCES participants(id) ON DELETE NO ACTION,
    input_id TEXT,
    edition_id TEXT,
    status TEXT NOT NULL DEFAULT 'claimed',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_generation_requests_participant
    ON generation_requests(participant_id);
