-- Episodes (canon and personal-branch narrative units).

CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL REFERENCES worlds (id),
    episode_type TEXT NOT NULL CHECK (episode_type IN ('canon', 'personal_branch')),
    episode_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    synopsis TEXT NOT NULL,
    canon_snapshot_id TEXT REFERENCES canon_snapshots (id),
    canon_checkpoint_id TEXT REFERENCES canon_checkpoints (id),
    prior_episode_id TEXT REFERENCES episodes (id),
    reader_id TEXT REFERENCES readers (id),
    scene_list_json TEXT NOT NULL,
    character_ids_json TEXT NOT NULL,
    location_ids_json TEXT NOT NULL,
    prose_json TEXT NOT NULL,
    clue_refs_json TEXT,
    world_state_deltas_json TEXT,
    applied_reader_input_json TEXT,
    unresolved_threads_json TEXT,
    next_choice_options_json TEXT,
    content_classification TEXT NOT NULL DEFAULT 'adult',
    review_state TEXT NOT NULL DEFAULT 'pending_review',
    generation_run_id TEXT,
    created_at TEXT NOT NULL,
    is_reader_input_anonymized SMALLINT DEFAULT 0,
    UNIQUE (world_id, episode_type, episode_number)
);
