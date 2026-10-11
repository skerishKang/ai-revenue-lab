-- #4194 Engine Agent/Task owner-scoped durable lease metadata.
-- Source only; production D1 migration must pass explicit provision gate.
-- No prompt, tool argument, credential, model answer, or approval stored.
-- Runtime MUST NOT create/migrate tables. B14 model timeout unchanged.

CREATE TABLE IF NOT EXISTS padiem_engine_agent_runs_v1 (
    run_id TEXT PRIMARY KEY,
    owner_scope TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL CHECK(length(request_fingerprint)=64),
    worker_id TEXT NOT NULL,
    epoch INTEGER NOT NULL CHECK(epoch>=1),
    status TEXT NOT NULL CHECK(status IN
        ('running','paused','awaiting_approval','completed','failed','cancelled','needs_review')),
    lease_until REAL NOT NULL,
    heartbeat_at REAL NOT NULL,
    checkpoint_step INTEGER NOT NULL DEFAULT 0 CHECK(checkpoint_step BETWEEN 0 AND 64),
    side_effect_uncertain INTEGER NOT NULL DEFAULT 0 CHECK(side_effect_uncertain IN (0,1))
);
CREATE INDEX IF NOT EXISTS idx_engine_agent_runs_owner
    ON padiem_engine_agent_runs_v1(owner_scope,status);
CREATE INDEX IF NOT EXISTS idx_engine_agent_runs_expiry
    ON padiem_engine_agent_runs_v1(status,lease_until);
