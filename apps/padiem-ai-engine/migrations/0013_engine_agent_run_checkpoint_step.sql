-- #4379: the durable Agent run row must not cap the checkpoint step.
-- The 0..64 CHECK duplicated the Python step ceiling, so a long run that
-- passed 64 steps would fail its checkpoint write even though the runtime
-- itself allows it. The table is recreated with the step count unbounded.
-- Source migration only; applying it to any environment is a separate release
-- action (D1 provision gate). No Worker route provisions schema.
--
-- The copy is idempotent: re-running it refreshes the widened table from the
-- current rows instead of failing on a duplicate primary key.
PRAGMA foreign_keys=OFF;

CREATE TABLE IF NOT EXISTS padiem_engine_agent_runs_v1_widened (
    run_id TEXT PRIMARY KEY,
    owner_scope TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL CHECK(length(request_fingerprint)=64),
    worker_id TEXT NOT NULL,
    epoch INTEGER NOT NULL CHECK(epoch>=1),
    status TEXT NOT NULL CHECK(status IN
        ('running','paused','awaiting_approval','completed','failed','cancelled','needs_review')),
    lease_until REAL NOT NULL,
    heartbeat_at REAL NOT NULL,
    checkpoint_step INTEGER NOT NULL DEFAULT 0 CHECK(checkpoint_step>=0),
    side_effect_uncertain INTEGER NOT NULL DEFAULT 0 CHECK(side_effect_uncertain IN (0,1))
);

DELETE FROM padiem_engine_agent_runs_v1_widened;

INSERT INTO padiem_engine_agent_runs_v1_widened (
    run_id, owner_scope, request_fingerprint, worker_id, epoch, status,
    lease_until, heartbeat_at, checkpoint_step, side_effect_uncertain
)
SELECT run_id, owner_scope, request_fingerprint, worker_id, epoch, status,
       lease_until, heartbeat_at, checkpoint_step, side_effect_uncertain
FROM padiem_engine_agent_runs_v1;

DROP TABLE IF EXISTS padiem_engine_agent_runs_v1;

ALTER TABLE padiem_engine_agent_runs_v1_widened
    RENAME TO padiem_engine_agent_runs_v1;

CREATE INDEX IF NOT EXISTS idx_engine_agent_runs_owner
    ON padiem_engine_agent_runs_v1(owner_scope,status);
CREATE INDEX IF NOT EXISTS idx_engine_agent_runs_expiry
    ON padiem_engine_agent_runs_v1(status,lease_until);

PRAGMA foreign_keys=ON;
