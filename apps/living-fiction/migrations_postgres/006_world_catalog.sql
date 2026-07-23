-- World catalog: characters, locations, clues, and episode-number sequences.

CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL REFERENCES worlds (id),
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
    UNIQUE (world_id, id)
);

CREATE TABLE IF NOT EXISTS locations (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL REFERENCES worlds (id),
    name TEXT NOT NULL,
    physical_properties TEXT,
    access_rules TEXT,
    known_history TEXT,
    connected_locations TEXT,
    current_state TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (world_id, id)
);

CREATE TABLE IF NOT EXISTS clues (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL REFERENCES worlds (id),
    description TEXT NOT NULL,
    introduced_in_episode TEXT,
    resolved SMALLINT NOT NULL DEFAULT 0 CHECK (resolved IN (0, 1)),
    resolution_episode TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (world_id, id)
);

CREATE TABLE IF NOT EXISTS episode_number_sequences (
    world_id TEXT NOT NULL REFERENCES worlds (id) ON DELETE CASCADE,
    episode_type TEXT NOT NULL CHECK (episode_type IN ('canon', 'personal_branch')),
    next_episode_number INTEGER NOT NULL CHECK (next_episode_number >= 1),
    PRIMARY KEY (world_id, episode_type)
);
