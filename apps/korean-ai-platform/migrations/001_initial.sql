-- Korean AI Platform (Business 14) initial product-local schema.
-- Product-owned SQLite. No JSON aggregate blobs: workflow state, cost, verdict,
-- changed files, tests, findings, timeline are queryable relational rows with
-- constraints. Forward-only; extend by adding new migration files.

CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    instruction TEXT NOT NULL,
    project_id TEXT NOT NULL,
    worker_model_id TEXT NOT NULL,
    validator_model_id TEXT NOT NULL,
    cost_limit_krw REAL NOT NULL CHECK (cost_limit_krw >= 0),
    external_policy TEXT NOT NULL CHECK (external_policy IN ('allow', 'restrict')),
    branch_mode TEXT NOT NULL CHECK (branch_mode IN ('auto', 'manual')),
    status TEXT NOT NULL CHECK (status IN ('ready', 'running', 'awaiting_approval', 'completed', 'rework', 'rejected')),
    created_at TEXT NOT NULL,
    rework_count INTEGER NOT NULL DEFAULT 0 CHECK (rework_count >= 0),
    approver TEXT,
    commit_sha TEXT,
    branch_name TEXT,
    completed_at TEXT,
    rejected_reason TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE task_allowed_paths (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    path TEXT NOT NULL,
    PRIMARY KEY (task_id, position)
);

CREATE TABLE task_denied_paths (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    path TEXT NOT NULL,
    PRIMARY KEY (task_id, position)
);

CREATE TABLE task_rework_reasons (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    reason TEXT NOT NULL,
    PRIMARY KEY (task_id, position)
);

CREATE TABLE task_runs (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    run_number INTEGER NOT NULL CHECK (run_number >= 1),
    plan_text TEXT NOT NULL DEFAULT '',
    worker_claim TEXT NOT NULL DEFAULT '',
    verdict TEXT NOT NULL CHECK (verdict IN ('approve', 'caution', 'reject')),
    cost_total_krw REAL NOT NULL DEFAULT 0 CHECK (cost_total_krw >= 0),
    over_budget INTEGER NOT NULL DEFAULT 0 CHECK (over_budget IN (0, 1)),
    created_at TEXT NOT NULL,
    PRIMARY KEY (task_id, run_number)
);

CREATE TABLE run_steps (
    task_id TEXT NOT NULL,
    run_number INTEGER NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'done', 'warning', 'failed')),
    detail TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (task_id, run_number, position),
    FOREIGN KEY (task_id, run_number) REFERENCES task_runs(task_id, run_number) ON DELETE CASCADE
);

CREATE TABLE run_changed_files (
    task_id TEXT NOT NULL,
    run_number INTEGER NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    path TEXT NOT NULL,
    additions INTEGER NOT NULL CHECK (additions >= 0),
    deletions INTEGER NOT NULL CHECK (deletions >= 0),
    language TEXT NOT NULL DEFAULT '',
    diff TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (task_id, run_number, position),
    FOREIGN KEY (task_id, run_number) REFERENCES task_runs(task_id, run_number) ON DELETE CASCADE
);

CREATE TABLE run_test_summaries (
    task_id TEXT NOT NULL,
    run_number INTEGER NOT NULL,
    command TEXT NOT NULL DEFAULT '',
    total INTEGER NOT NULL CHECK (total >= 0),
    passed INTEGER NOT NULL CHECK (passed >= 0),
    failed INTEGER NOT NULL CHECK (failed >= 0),
    skipped INTEGER NOT NULL CHECK (skipped >= 0),
    PRIMARY KEY (task_id, run_number),
    FOREIGN KEY (task_id, run_number) REFERENCES task_runs(task_id, run_number) ON DELETE CASCADE
);

CREATE TABLE run_test_results (
    task_id TEXT NOT NULL,
    run_number INTEGER NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (task_id, run_number, position),
    FOREIGN KEY (task_id, run_number) REFERENCES task_runs(task_id, run_number) ON DELETE CASCADE
);

CREATE TABLE run_findings (
    task_id TEXT NOT NULL,
    run_number INTEGER NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    level TEXT NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (task_id, run_number, position),
    FOREIGN KEY (task_id, run_number) REFERENCES task_runs(task_id, run_number) ON DELETE CASCADE
);

CREATE TABLE run_path_violations (
    task_id TEXT NOT NULL,
    run_number INTEGER NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    text TEXT NOT NULL,
    PRIMARY KEY (task_id, run_number, position),
    FOREIGN KEY (task_id, run_number) REFERENCES task_runs(task_id, run_number) ON DELETE CASCADE
);

CREATE TABLE run_security_notes (
    task_id TEXT NOT NULL,
    run_number INTEGER NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    text TEXT NOT NULL,
    PRIMARY KEY (task_id, run_number, position),
    FOREIGN KEY (task_id, run_number) REFERENCES task_runs(task_id, run_number) ON DELETE CASCADE
);

CREATE TABLE run_cost_lines (
    task_id TEXT NOT NULL,
    run_number INTEGER NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    model_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    role TEXT NOT NULL,
    tokens_in INTEGER NOT NULL CHECK (tokens_in >= 0),
    tokens_out INTEGER NOT NULL CHECK (tokens_out >= 0),
    krw REAL NOT NULL CHECK (krw >= 0),
    PRIMARY KEY (task_id, run_number, position),
    FOREIGN KEY (task_id, run_number) REFERENCES task_runs(task_id, run_number) ON DELETE CASCADE
);

CREATE TABLE run_timeline (
    task_id TEXT NOT NULL,
    run_number INTEGER NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    at TEXT NOT NULL,
    label TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (task_id, run_number, position),
    FOREIGN KEY (task_id, run_number) REFERENCES task_runs(task_id, run_number) ON DELETE CASCADE
);

CREATE TABLE security_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    domestic_first INTEGER NOT NULL DEFAULT 1 CHECK (domestic_first IN (0, 1)),
    allow_external INTEGER NOT NULL DEFAULT 1 CHECK (allow_external IN (0, 1)),
    block_on_secret INTEGER NOT NULL DEFAULT 1 CHECK (block_on_secret IN (0, 1)),
    project_cost_limit_krw REAL NOT NULL DEFAULT 10000 CHECK (project_cost_limit_krw >= 0),
    block_push_without_approval INTEGER NOT NULL DEFAULT 1 CHECK (block_push_without_approval = 1),
    updated_at TEXT NOT NULL
);

CREATE TABLE byok_registrations (
    model_id TEXT PRIMARY KEY,
    registered INTEGER NOT NULL DEFAULT 0 CHECK (registered IN (0, 1)),
    updated_at TEXT NOT NULL
);

CREATE TABLE task_id_sequence (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    next_value INTEGER NOT NULL CHECK (next_value >= 0)
);

CREATE TABLE seed_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    seeded INTEGER NOT NULL DEFAULT 0 CHECK (seeded IN (0, 1)),
    seeded_at TEXT
);

-- Initial singleton rows. Task IDs start at t-101 (matches the in-memory
-- Store counter). block_push_without_approval is seeded true and constrained
-- to always be true.
INSERT INTO task_id_sequence (id, next_value) VALUES (1, 101);
INSERT INTO security_settings (id, domestic_first, allow_external, block_on_secret, project_cost_limit_krw, block_push_without_approval, updated_at)
VALUES (1, 1, 1, 1, 10000, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
