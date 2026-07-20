CREATE TABLE IF NOT EXISTS readers (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS worlds (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    premise TEXT NOT NULL,
    genre TEXT NOT NULL DEFAULT 'urban_mystery',
    world_rules TEXT NOT NULL,
    canonical_timeline TEXT,
    unresolved_global_questions TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(id, version)
);

CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL REFERENCES worlds(id),
    canonical_name TEXT NOT NULL,
    aliases TEXT,
    role TEXT NOT NULL,
    age_category TEXT NOT NULL DEFAULT 'adult',
    traits TEXT NOT NULL,
    goals TEXT,
    knowledge_state TEXT,
    relationships TEXT,
    location_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    first_canonical_episode TEXT,
    last_canonical_episode TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(world_id, id)
);

CREATE TABLE IF NOT EXISTS locations (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL REFERENCES worlds(id),
    name TEXT NOT NULL,
    physical_properties TEXT,
    access_rules TEXT,
    known_history TEXT,
    connected_locations TEXT,
    current_state TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(world_id, id)
);

CREATE TABLE IF NOT EXISTS clues (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL REFERENCES worlds(id),
    description TEXT NOT NULL,
    introduced_in_episode TEXT,
    resolved BOOLEAN NOT NULL DEFAULT 0 CHECK(resolved IN (0, 1)),
    resolution_episode TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(world_id, id)
);

CREATE TABLE IF NOT EXISTS canon_snapshots (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL REFERENCES worlds(id),
    version TEXT NOT NULL,
    episode_number INTEGER NOT NULL,
    accepted BOOLEAN NOT NULL DEFAULT 0 CHECK(accepted IN (0, 1)),
    world_state_json TEXT NOT NULL,
    character_states_json TEXT NOT NULL,
    location_states_json TEXT NOT NULL,
    clue_states_json TEXT NOT NULL,
    unresolved_threads_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(world_id, version),
    UNIQUE(world_id, episode_number)
);

CREATE TABLE IF NOT EXISTS canon_checkpoints (
    id TEXT PRIMARY KEY,
    canon_snapshot_id TEXT NOT NULL REFERENCES canon_snapshots(id),
    episode_number INTEGER NOT NULL,
    label TEXT NOT NULL,
    is_compatible_for_rejoin BOOLEAN NOT NULL DEFAULT 1 CHECK(is_compatible_for_rejoin IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL REFERENCES worlds(id),
    episode_type TEXT NOT NULL CHECK(episode_type IN ('canon', 'personal_branch')),
    episode_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    synopsis TEXT NOT NULL,
    canon_snapshot_id TEXT REFERENCES canon_snapshots(id),
    canon_checkpoint_id TEXT REFERENCES canon_checkpoints(id),
    prior_episode_id TEXT REFERENCES episodes(id),
    reader_id TEXT REFERENCES readers(id),
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
    UNIQUE(world_id, episode_type, episode_number)
);

CREATE TABLE IF NOT EXISTS reader_choices (
    id TEXT PRIMARY KEY,
    reader_id TEXT NOT NULL REFERENCES readers(id),
    canon_episode_id TEXT NOT NULL REFERENCES episodes(id),
    choice_text TEXT NOT NULL,
    comment TEXT,
    submitted_at TEXT NOT NULL,
    applied_to_branch_id TEXT REFERENCES episodes(id),
    applied_at TEXT,
    UNIQUE(reader_id, canon_episode_id, choice_text)
);

CREATE TABLE IF NOT EXISTS branches (
    id TEXT PRIMARY KEY,
    reader_id TEXT NOT NULL REFERENCES readers(id),
    canon_checkpoint_id TEXT NOT NULL REFERENCES canon_checkpoints(id),
    prior_episode_id TEXT NOT NULL REFERENCES episodes(id),
    branch_episode_id TEXT NOT NULL REFERENCES episodes(id),
    reader_choice_id TEXT NOT NULL REFERENCES reader_choices(id),
    divergence_state_json TEXT,
    branch_only_facts_json TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    rejoin_checkpoint_id TEXT REFERENCES canon_checkpoints(id),
    rejoin_explanation TEXT,
    rejoined_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(reader_id, canon_checkpoint_id, reader_choice_id)
);

CREATE TABLE IF NOT EXISTS generation_runs (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    advertised_model TEXT NOT NULL,
    cost_class TEXT NOT NULL DEFAULT 'free',
    prompt_version TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    latency_seconds REAL CHECK(latency_seconds IS NULL OR latency_seconds >= 0),
    success INTEGER NOT NULL DEFAULT 0 CHECK(success IN (0, 1)),
    validation_status TEXT,
    input_tokens INTEGER CHECK(input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK(output_tokens IS NULL OR output_tokens >= 0),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
    error_category TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pilot_evidence (
    id TEXT PRIMARY KEY,
    evidence_category TEXT NOT NULL,
    canon_episode_id TEXT REFERENCES episodes(id),
    branch_episode_id TEXT REFERENCES episodes(id),
    reader_id TEXT REFERENCES readers(id),
    evidence_data_json TEXT NOT NULL,
    privacy_safe BOOLEAN NOT NULL DEFAULT 1 CHECK(privacy_safe IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rejoin_requests (
    id TEXT PRIMARY KEY,
    branch_id TEXT NOT NULL REFERENCES branches(id),
    target_checkpoint_id TEXT NOT NULL REFERENCES canon_checkpoints(id),
    status TEXT NOT NULL DEFAULT 'pending',
    rejection_reason TEXT,
    unresolved_consequences_json TEXT,
    created_at TEXT NOT NULL
);
