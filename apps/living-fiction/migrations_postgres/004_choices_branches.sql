-- Reader choices (one per reader/canon episode) and branches.

CREATE TABLE IF NOT EXISTS reader_choices (
    id TEXT PRIMARY KEY,
    reader_id TEXT NOT NULL REFERENCES readers (id),
    canon_episode_id TEXT NOT NULL REFERENCES episodes (id),
    choice_text TEXT NOT NULL,
    comment TEXT,
    submitted_at TEXT NOT NULL,
    applied_to_branch_id TEXT REFERENCES episodes (id),
    applied_at TEXT,
    anonymized_principal_id TEXT DEFAULT NULL,
    is_anonymized SMALLINT DEFAULT 0,
    UNIQUE (reader_id, canon_episode_id, choice_text)
);

CREATE TABLE IF NOT EXISTS branches (
    id TEXT PRIMARY KEY,
    reader_id TEXT NOT NULL REFERENCES readers (id),
    canon_checkpoint_id TEXT NOT NULL REFERENCES canon_checkpoints (id),
    prior_episode_id TEXT NOT NULL REFERENCES episodes (id),
    branch_episode_id TEXT NOT NULL REFERENCES episodes (id),
    reader_choice_id TEXT NOT NULL REFERENCES reader_choices (id),
    divergence_state_json TEXT,
    branch_only_facts_json TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    rejoin_checkpoint_id TEXT REFERENCES canon_checkpoints (id),
    rejoin_explanation TEXT,
    rejoined_at TEXT,
    created_at TEXT NOT NULL,
    anonymized_at TEXT,
    UNIQUE (reader_id, canon_checkpoint_id, reader_choice_id)
);
