-- Branch generation requests (idempotency + leasing), rejoin requests, and
-- editorial review decisions.

CREATE TABLE IF NOT EXISTS branch_generation_requests (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL,
    reader_id TEXT NOT NULL REFERENCES readers (id),
    reader_choice_id TEXT NOT NULL REFERENCES reader_choices (id),
    prior_episode_id TEXT NOT NULL REFERENCES episodes (id),
    canon_checkpoint_id TEXT NOT NULL REFERENCES canon_checkpoints (id),
    world_id TEXT NOT NULL REFERENCES worlds (id),
    branch_episode_id TEXT REFERENCES episodes (id),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'completed', 'failed')),
    error_message TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    operation_type TEXT NOT NULL DEFAULT 'personal_branch',
    attempt_number INTEGER NOT NULL DEFAULT 1 CHECK (attempt_number >= 1),
    pending_lease_at TEXT,
    updated_at TEXT,
    UNIQUE (idempotency_key)
);

CREATE TABLE IF NOT EXISTS rejoin_requests (
    id TEXT PRIMARY KEY,
    branch_id TEXT NOT NULL REFERENCES branches (id),
    target_checkpoint_id TEXT NOT NULL REFERENCES canon_checkpoints (id),
    status TEXT NOT NULL DEFAULT 'pending',
    rejection_reason TEXT,
    unresolved_consequences_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rejoin_requests_v2 (
    id TEXT PRIMARY KEY,
    branch_id TEXT NOT NULL REFERENCES branches (id),
    target_checkpoint_id TEXT NOT NULL REFERENCES canon_checkpoints (id),
    target_snapshot_id TEXT NOT NULL REFERENCES canon_snapshots (id),
    derived_consequences_json TEXT NOT NULL DEFAULT '[]',
    explanation TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'completed')),
    rejection_reason TEXT,
    validated_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (branch_id, target_checkpoint_id)
);

CREATE TABLE IF NOT EXISTS review_decisions (
    id TEXT PRIMARY KEY,
    branch_id TEXT NOT NULL REFERENCES branches (id),
    episode_id TEXT NOT NULL REFERENCES episodes (id),
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    rejection_reason TEXT,
    decided_at TEXT NOT NULL,
    actor_type TEXT NOT NULL DEFAULT 'admin',
    prior_state TEXT NOT NULL,
    new_state TEXT NOT NULL
);
