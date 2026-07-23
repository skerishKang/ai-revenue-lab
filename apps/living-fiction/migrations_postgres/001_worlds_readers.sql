-- Living Fiction PostgreSQL schema: core aggregate roots.
--
-- Semantically equivalent to the final SQLite schema produced by migrations/.
-- Timestamps are TEXT (ISO-8601) because the application stores and compares
-- them as opaque strings; boolean-like flags are SMALLINT 0/1 because the
-- application stores integers and reads them back with bool(). Every statement
-- is idempotent (IF NOT EXISTS) so a fresh run builds the whole schema and a
-- re-run is a no-op.

CREATE TABLE IF NOT EXISTS worlds (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    premise TEXT NOT NULL,
    genre TEXT NOT NULL DEFAULT 'urban_mystery',
    world_rules TEXT NOT NULL,
    canonical_timeline TEXT,
    unresolved_global_questions TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (id, version)
);

CREATE TABLE IF NOT EXISTS readers (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    deleted_at TEXT
);
