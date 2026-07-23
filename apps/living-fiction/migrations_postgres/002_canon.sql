-- Canon snapshots and checkpoints (canon immutability + rejoin compatibility).

CREATE TABLE IF NOT EXISTS canon_snapshots (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL REFERENCES worlds (id),
    version TEXT NOT NULL,
    episode_number INTEGER NOT NULL,
    accepted SMALLINT NOT NULL DEFAULT 0 CHECK (accepted IN (0, 1)),
    world_state_json TEXT NOT NULL,
    character_states_json TEXT NOT NULL,
    location_states_json TEXT NOT NULL,
    clue_states_json TEXT NOT NULL,
    unresolved_threads_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (world_id, version),
    UNIQUE (world_id, episode_number)
);

CREATE TABLE IF NOT EXISTS canon_checkpoints (
    id TEXT PRIMARY KEY,
    canon_snapshot_id TEXT NOT NULL REFERENCES canon_snapshots (id),
    episode_number INTEGER NOT NULL,
    label TEXT NOT NULL,
    is_compatible_for_rejoin SMALLINT NOT NULL DEFAULT 1
        CHECK (is_compatible_for_rejoin IN (0, 1)),
    created_at TEXT NOT NULL
);
